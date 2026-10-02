"""Unit tests for hooks/lib/remote_hosts.py: trusted-host matching and host parsing.

Exercises `resolve()` over the configured patterns, including the entries that
must trust nothing, then `parse_clause()` across the ssh, sftp, scp, and rsync
launch shapes it must read and the ones it must refuse. Every command here is
a string handed to the parser; nothing is executed.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def remote_hosts(hooks_dir: Path) -> ModuleType:
    """Import lib.remote_hosts with the hooks dir importable."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.remote_hosts")
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize(
    ("patterns", "host", "trusted"),
    [
        (("nas",), "nas", True),
        (("NAS",), "nas", True),
        (("nas",), "NAS", True),
        (("nas",), "nas2", False),
        (("*.lan",), "box.lan", True),
        (("*.lan",), "lan", False),
        (("*.lan",), "box.lan.example.com", False),
        (("root@nas",), "nas", True),
        ((" nas ",), "nas", True),
        ((), "nas", False),
    ],
)
def test_trusts(
    remote_hosts: ModuleType, patterns: tuple[str, ...], host: str, *, trusted: bool
) -> None:
    """Verify hosts match configured names and globs case-insensitively."""
    assert remote_hosts.resolve(patterns).trusts(host) is trusted


@pytest.mark.parametrize("entry", ["", "   ", "*", "**", "?", "*.*", "user@", "@"])
def test_entries_that_would_trust_everything_or_nothing_are_dropped(
    remote_hosts: ModuleType, entry: str
) -> None:
    """Verify a blank or all-wildcard entry trusts no host.

    A bare `*` would silence the prompt for every machine, which is the same as
    disabling the hook, so it is refused rather than honored.
    """
    trusted = remote_hosts.resolve((entry,))
    assert not trusted
    assert not trusted.trusts("anything")


def test_bad_entry_leaves_neighbors_intact(remote_hosts: ModuleType) -> None:
    """Verify one unusable entry does not void the rest of the list."""
    trusted = remote_hosts.resolve(("*", "nas"))
    assert trusted.trusts("nas")
    assert not trusted.trusts("other")


@pytest.mark.parametrize(
    ("clause", "hosts", "remote_command"),
    [
        # ssh and its option forms
        ("ssh nas", ("nas",), ""),
        ("ssh user@nas", ("nas",), ""),
        ("ssh -p 2222 user@nas uptime", ("nas",), "uptime"),
        ("ssh -p2222 nas", ("nas",), ""),
        ("ssh -i ~/.ssh/key -o StrictHostKeyChecking=no nas", ("nas",), ""),
        ("ssh -tt nas 'ls -la'", ("nas",), "ls -la"),
        ("ssh -At nas", ("nas",), ""),
        ("ssh -J jump nas", ("nas",), ""),
        ("ssh -- nas", ("nas",), ""),
        ("ssh ssh://user@nas:2222", ("nas",), ""),
        ("ssh nas systemctl status nginx", ("nas",), "systemctl status nginx"),
        ("ssh NAS", ("nas",), ""),
        ("ssh nas -t top", ("nas",), "top"),
        ("ssh nas -- ls -la", ("nas",), "ls -la"),
        ("ssh -- nas -o x", ("nas",), "-o x"),
        # launchers and prefixes ahead of the tool
        ("sudo ssh nas", ("nas",), ""),
        ("env FOO=1 ssh nas", ("nas",), ""),
        ("FOO=1 ssh nas", ("nas",), ""),
        ("/usr/bin/ssh nas", ("nas",), ""),
        ("  ssh nas  ", ("nas",), ""),
        ("autossh -M 0 nas", ("nas",), ""),
        # sftp
        ("sftp user@nas", ("nas",), ""),
        ("sftp nas:/srv/data", ("nas",), ""),
        ("sftp -P 2222 nas", ("nas",), ""),
        ("sftp sftp://user@nas:22/srv", ("nas",), ""),
        # scp
        ("scp file.txt nas:/tmp/", ("nas",), ""),
        ("scp -r nas:src ./dst", ("nas",), ""),
        ("scp -P 22 -i key f user@nas:/x", ("nas",), ""),
        ("scp a:src b:dst", ("a", "b"), ""),
        ("scp ./odd:name nas:/x", ("nas",), ""),
        ("scp f scp://user@nas:22/srv", ("nas",), ""),
        ("scp f [fe80::1]:/x", ("fe80::1",), ""),
        # rsync
        ("rsync -av src/ nas:/dst/", ("nas",), ""),
        ("rsync -av user@nas:src ./dst", ("nas",), ""),
        ("rsync -av nas::module ./dst", ("nas",), ""),
        ("rsync rsync://nas/module ./dst", ("nas",), ""),
        ("rsync rsync://user@nas:873/module ./dst", ("nas",), ""),
        ("rsync -avze ssh src/ nas:/dst/", ("nas",), ""),
        ("rsync -e 'ssh -p 2222' src/ nas:/dst", ("nas",), ""),
        ("rsync --rsh=ssh src nas:/dst", ("nas",), ""),
        ("rsync --rsh 'ssh -i key' src nas:/dst", ("nas",), ""),
        ("rsync -av --delete src/ nas:/dst/", ("nas",), ""),
        ("rsync -av [::1]:/x ./", ("::1",), ""),
    ],
)
def test_parse_clause_reads_destination(
    remote_hosts: ModuleType, clause: str, hosts: tuple[str, ...], remote_command: str
) -> None:
    """Verify the destination host is read from each supported launch shape."""
    call = remote_hosts.parse_clause(clause)
    assert call is not None, clause
    assert call.hosts == hosts
    assert call.remote_command == remote_command


@pytest.mark.parametrize(
    "clause",
    [
        # not a remote launch at all, or one the parser cannot see into
        "echo ssh nas",
        "bash -c 'ssh nas'",
        "ansible all -m ping",
        "ssh-copy-id nas",
        # no destination to judge
        "ssh",
        "ssh -p 22",
        "ssh -",
        "ssh .",
        "scp a b",
        "rsync -av src/ dst/",
        "rsync -e ssh src/ dst/",
        # a launcher whose own flags hide which word is the program
        "sudo -u root ssh nas",
        # a local program run on the user's behalf
        "scp -S /tmp/wrapper f nas:/x",
        "rsync -e 'nc relay 22' src nas:/dst",
        "rsync --rsh='/tmp/wrapper' src nas:/dst",
        "ssh -o ProxyCommand='nc relay 22' nas",
        "ssh -oProxyCommand=nc nas",
        "ssh -o LocalCommand=touch nas",
        "ssh -o 'ProxyCommand nc relay 22' nas",
        "ssh -F /tmp/ssh_config nas",
        "scp -o ProxyCommand=nc f nas:/x",
        "sftp -S /tmp/wrapper nas",
        "sftp -D /tmp/server nas",
        "ssh -I /tmp/pkcs11.so nas",
        "ssh -o PKCS11Provider=/tmp/p.so nas",
        "ssh -o SecurityKeyProvider=/tmp/sk.so nas",
        "RSYNC_RSH=/tmp/wrapper rsync src nas:/dst",
        "env RSYNC_CONNECT_PROG='nc relay 873' rsync rsync://nas/m ./",
        "SSH_ASKPASS=/tmp/x SSH_ASKPASS_REQUIRE=force ssh nas",
        # options after the destination, which ssh still parses
        "ssh nas -oProxyCommand=nc uptime",
        "ssh nas -F /tmp/ssh_config uptime",
        "ssh nas -o HostName=prod uptime",
        # an option that connects somewhere other than the host as written
        "ssh -o HostName=prod nas",
        "ssh -oCanonicalDomains=prod.example -oCanonicalizeHostname=yes nas",
        "scp -o HostName=prod f nas:/x",
        "ssh -S /tmp/ctl nas",
        "ssh -o ControlPath=/tmp/ctl nas",
        # a destination that hides the real host
        "ssh $HOST",
        "ssh `pick-host`",
        "scp f $(pick-host):/x",
        # unbalanced quoting
        "ssh nas 'unterminated",
    ],
)
def test_parse_clause_refuses(remote_hosts: ModuleType, clause: str) -> None:
    """Verify an unreadable or unsafe launch yields None, so the caller keeps asking."""
    assert remote_hosts.parse_clause(clause) is None
