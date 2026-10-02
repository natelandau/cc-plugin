"""Read which hosts a shell clause reaches, and which hosts the user trusts.

protect-remote asks before every command that reaches a remote host. Hosts the
user lists in `trusted_remote_hosts` (global config only; see `lib.config`)
skip that prompt. This module supplies both halves of the decision: `resolve`
turns the configured patterns into a `TrustedHosts`, and `parse_clause` reads
the destination hosts out of one ssh, autossh, sftp, scp, or rsync launch.

The parser is deliberately narrow, and anything it cannot read with certainty
returns None so the caller keeps asking:

- a wrapper it cannot see through (`bash -c`, `sudo -u <user>`);
- a host spelled through a variable or command substitution;
- an option that runs a program on the local machine (`ProxyCommand`,
  `LocalCommand`, `scp -S`, `sftp -b`, an rsync `-e` that is not ssh, an
  `RSYNC_RSH` or `SSH_ASKPASS` in the environment), loads a library or an ssh
  config the command names (`-I`, `-F`, `Include`), or sends the connection
  somewhere other than the host as written (`HostName`, `CanonicalDomains`, a
  control socket from `-S` or `ControlPath`).

ssh reads options after the destination as well as before it, so those are
vetted too.

A wrong None costs one prompt; a wrong host would silence one.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Words that run the next word as the program. One followed by its own option
# (`sudo -u root ssh`) makes the program ambiguous, so the parse gives up.
_LAUNCHERS = frozenset({"sudo", "doas", "env", "command", "exec", "nice", "nohup", "time"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# A hostname, alias, or IP as written. Excludes `$`, backticks, and parentheses,
# so a host the shell has yet to expand never reads as a literal name.
_HOST = re.compile(r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*|[0-9A-Fa-f.%]*:[0-9A-Fa-f:.%]*)$")

# Short options that take a value, per tool, from each tool's man page.
_SSH_VALUE_FLAGS = frozenset("BbcDEeFIiJLlmOoPpQRSWw")
_SFTP_VALUE_FLAGS = frozenset("BbcDFiJloPRSsX")
_SCP_VALUE_FLAGS = frozenset("cDFiJloPSX")
_RSYNC_VALUE_FLAGS = frozenset("BefMT@")

# Short options that run a local program, load a caller-named ssh config or
# library, or reuse a control socket that may be connected to another host.
_SSH_REFUSED_FLAGS = frozenset("FIS")
_SFTP_REFUSED_FLAGS = frozenset("bDFS")
_SCP_REFUSED_FLAGS = frozenset("DFS")

# `-o` keys with the same effect, that connect somewhere other than the host
# as written, or that run a remote command the hook would not see as part of
# the clause.
_REFUSED_SSH_OPTIONS = frozenset(
    {
        "canonicaldomains",
        "controlpath",
        "hostname",
        "include",
        "knownhostscommand",
        "localcommand",
        "match",
        "permitlocalcommand",
        "pkcs11provider",
        "proxycommand",
        "remotecommand",
        "securitykeyprovider",
    }
)

# Environment variables that make rsync or ssh run a local program of the
# caller's choosing. Matched anywhere in the text, so an `export` in an
# earlier clause counts as much as a prefix assignment.
REFUSED_ENV = re.compile(r"\b(?:RSYNC_RSH|RSYNC_CONNECT_PROG|SSH_ASKPASS)\b")


@dataclass(frozen=True, slots=True)
class RemoteCall:
    """The hosts one clause reaches, plus the command ssh runs there.

    `remote_command` is the text after an ssh destination, so the caller can
    check whether a trusted host is being used as a hop to another one. It is
    empty for sftp, scp, rsync, and an interactive ssh session.
    """

    hosts: tuple[str, ...]
    remote_command: str = ""


@dataclass(frozen=True, slots=True)
class TrustedHosts:
    """The hosts the user lets protect-remote pass without a prompt."""

    patterns: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """Return whether any host is trusted, so an empty list skips all parsing."""
        return bool(self.patterns)

    def trusts(self, host: str) -> bool:
        """Return whether `host` matches a trusted name or glob, ignoring case."""
        name = host.lower()
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.patterns)


def _usable_pattern(raw: str) -> str | None:
    """Return `raw` as a host pattern, or None when it cannot name a host.

    A user part (`root@nas`) is dropped because the hook judges hosts, not
    accounts. A pattern with no literal character (`*`, `*.*`) would trust
    every machine, which is the same as disabling the hook, so it is refused.
    """
    host = raw.strip().rpartition("@")[2].lower()
    if not re.search(r"[a-z0-9]", host):
        return None
    return host


def resolve(configured: Sequence[str] = ()) -> TrustedHosts:
    """Resolve the trusted host patterns from the global config list."""
    return TrustedHosts(
        tuple(pattern for pattern in map(_usable_pattern, configured) if pattern is not None)
    )


def _host(raw: str) -> str | None:
    """Return `raw` as a lowercase host, or None when it is not a literal one."""
    host = raw.removeprefix("[").removesuffix("]")
    return host.lower() if host and _HOST.match(host) else None


def _uri_host(uri: str) -> str | None:
    """Return the host of a `scheme://[user@]host[:port][/path]` URI."""
    authority = uri.split("://", 1)[1].split("/", 1)[0].rpartition("@")[2]
    if authority.startswith("["):
        return _host(authority.partition("]")[0])
    return _host(authority.partition(":")[0])


def _endpoint_host(operand: str) -> tuple[bool, str | None]:
    """Classify a scp/sftp/rsync operand as local or remote.

    Returns `(False, None)` for a local path, `(True, host)` for a remote
    endpoint, and `(True, None)` for a remote endpoint whose host is not a
    literal name. A colon after a slash is part of a local path, the rule scp
    and rsync themselves apply.
    """
    if "://" in operand:
        return True, _uri_host(operand)
    if operand.startswith("["):
        bracketed, _, rest = operand.partition("]")
        return (True, _host(bracketed)) if rest.startswith(":") else (False, None)
    head, colon, _ = operand.partition(":")
    if not colon or not head or "/" in head:
        return False, None
    return True, _host(head.rpartition("@")[2])


def _walk_options(
    args: list[str], value_flags: frozenset[str], refused_flags: frozenset[str]
) -> int | None:
    """Skip a tool's leading options and return the index of its first operand.

    Returns None when an option is refused, a value flag has no value, or an
    `-o` names a refused ssh option.
    """
    walked = _skip_options(args, value_flags, refused_flags)
    return None if walked is None else walked[0]


def _skip_options(
    args: list[str], value_flags: frozenset[str], refused_flags: frozenset[str]
) -> tuple[int, bool] | None:
    """Return `_walk_options`' index paired with whether a `--` ended the options."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return i + 1, True
        if not arg.startswith("-") or arg == "-":
            return i, False
        for j, flag in enumerate(arg[1:], start=1):
            if flag in refused_flags:
                return None
            if flag not in value_flags:
                continue
            value = arg[j + 1 :]
            if not value:
                i += 1
                if i >= len(args):
                    return None
                value = args[i]
            if flag == "o" and re.split(r"[\s=]", value.strip(), maxsplit=1)[0].lower() in (
                _REFUSED_SSH_OPTIONS
            ):
                return None
            break
        i += 1
    return i, False


def _destination_host(destination: str, *, strip_path: bool) -> str | None:
    """Return the host of an ssh or sftp destination (`[user@]host`, URI, or sftp's `host:path`)."""
    if "://" in destination:
        return _uri_host(destination)
    if strip_path:
        destination = destination.partition(":")[0]
    return _host(destination.rpartition("@")[2])


def _parse_ssh(args: list[str], value_flags: frozenset[str]) -> RemoteCall | None:
    walked = _skip_options(args, value_flags, _SSH_REFUSED_FLAGS)
    if walked is None or walked[0] >= len(args):
        return None
    start, terminated = walked
    host = _destination_host(args[start], strip_path=False)
    if host is None:
        return None
    command_start = start + 1
    if not terminated:
        # ssh resumes option parsing after the destination unless `--` came first.
        rest = _walk_options(args[command_start:], value_flags, _SSH_REFUSED_FLAGS)
        if rest is None:
            return None
        command_start += rest
    return RemoteCall(hosts=(host,), remote_command=" ".join(args[command_start:]))


def _parse_sftp(args: list[str]) -> RemoteCall | None:
    start = _walk_options(args, _SFTP_VALUE_FLAGS, _SFTP_REFUSED_FLAGS)
    if start is None or start >= len(args):
        return None
    host = _destination_host(args[start], strip_path=True)
    return RemoteCall(hosts=(host,)) if host else None


def _hosts_from_operands(operands: list[str]) -> RemoteCall | None:
    """Collect the remote hosts among scp/rsync operands; None if any is unreadable."""
    hosts: dict[str, None] = {}
    for operand in operands:
        is_remote, host = _endpoint_host(operand)
        if not is_remote:
            continue
        if host is None:
            return None
        hosts[host] = None
    return RemoteCall(hosts=tuple(hosts)) if hosts else None


def _parse_scp(args: list[str]) -> RemoteCall | None:
    start = _walk_options(args, _SCP_VALUE_FLAGS, _SCP_REFUSED_FLAGS)
    if start is None:
        return None
    return _hosts_from_operands(args[start:])


def _rsh_is_plain_ssh(value: str) -> bool:
    """Return whether an rsync `-e`/`--rsh` value is ssh with no refused options."""
    try:
        words = shlex.split(value)
    except ValueError:
        return False
    if not words or PurePosixPath(words[0]).name != "ssh":
        return False
    return _walk_options(words[1:], _SSH_VALUE_FLAGS, _SSH_REFUSED_FLAGS) == len(words) - 1


def _rsync_option(args: list[str], i: int) -> tuple[str | None, int]:
    """Read the rsync option at `args[i]`, returning its remote shell (if any) and next index.

    Consumes the option's separate value when it takes one, so the value is
    never mistaken for an endpoint.
    """
    arg = args[i]
    if arg.startswith("--rsh="):
        return arg.removeprefix("--rsh="), i + 1
    if arg == "--rsh":
        return (args[i + 1] if i + 1 < len(args) else ""), i + 2
    if arg.startswith("--"):
        return None, i + 1
    for j, flag in enumerate(arg[1:], start=1):
        if flag not in _RSYNC_VALUE_FLAGS:
            continue
        value = arg[j + 1 :]
        if not value:
            i += 1
            value = args[i] if i < len(args) else ""
        return (value if flag == "e" else None), i + 1
    return None, i + 1


def _parse_rsync(args: list[str]) -> RemoteCall | None:
    """Read rsync's endpoints, skipping its options and vetting any remote shell.

    rsync has many long options; those with a separate value let that value
    read as an operand, which can only add a host to judge, never hide one.
    """
    operands: list[str] = []
    i = 0
    while i < len(args):
        if not args[i].startswith("-") or args[i] == "-":
            operands.append(args[i])
            i += 1
            continue
        rsh, i = _rsync_option(args, i)
        if rsh is not None and not _rsh_is_plain_ssh(rsh):
            return None
    return _hosts_from_operands(operands)


_PARSERS = {
    "ssh": lambda args: _parse_ssh(args, _SSH_VALUE_FLAGS),
    "autossh": lambda args: _parse_ssh(args, _SSH_VALUE_FLAGS | {"M"}),
    "sftp": _parse_sftp,
    "scp": _parse_scp,
    "rsync": _parse_rsync,
}


def parse_clause(clause: str) -> RemoteCall | None:
    """Return the hosts one shell clause reaches, or None when that cannot be read.

    Use on a single clause (split on `&&`, `;`, `|`), never a whole command:
    a later clause's operands would otherwise read as this tool's. None means
    the caller must treat the clause as reaching an untrusted host.
    """
    if REFUSED_ENV.search(clause):
        return None
    try:
        words = shlex.split(clause)
    except ValueError:
        return None
    while words and (_ASSIGNMENT.match(words[0]) or words[0] in _LAUNCHERS):
        words.pop(0)
    if not words:
        return None
    parser = _PARSERS.get(PurePosixPath(words[0]).name)
    return parser(words[1:]) if parser else None
