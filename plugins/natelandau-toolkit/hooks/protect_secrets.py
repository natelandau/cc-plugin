#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: blocks reads, edits, and exfiltration of sensitive files.

For Read/Edit/Write the file_path is matched against a list of sensitive
file regexes (`.env`, SSH keys, AWS credentials, PEM/key files, etc.).
For Bash the command is matched against a list of risky patterns
(`cat .env`, env dumps, `scp` of secrets, deletion of credentials, etc.).
Allowlisted templates like `.env.example` always pass through.

Three escalating thresholds gate which rules apply:

- `critical` -- only the highest-impact rules (private keys, .env, AWS).
- `high` (default) -- adds secrets files, env dumps, exfiltration patterns.
- `strict` -- adds dotfiles that may contain credentials (`.gitconfig`,
  `database.yaml`, `known_hosts`).

Override the level with the `CLAUDE_PROTECT_SECRETS_LEVEL` env var.

Ported from karanb192/claude-code-hooks `protect-secrets.js`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}
DEFAULT_LEVEL = "high"
LEVEL_ENV_VAR = "CLAUDE_PROTECT_SECRETS_LEVEL"

# Maps a tool name to the verb used in the user-facing block message.
ACTION_VERBS: dict[str, str] = {
    "Read": "read",
    "Edit": "modify",
    "Write": "write to",
    "Bash": "execute",
}

# Templates and example files that are always safe. Tested against both
# file paths (Read/Edit/Write) and the entire bash command string. The
# string-end anchors mean a bash command like `cat .env.example` is
# allowlisted but `cat .env.example .env` is not, so the second file is
# still checked by the sensitive-file rules.
ALLOWLIST: tuple[str, ...] = (
    r"\.env\.example$",
    r"\.env\.sample$",
    r"\.env\.template$",
    r"\.env\.schema$",
    r"\.env\.defaults$",
    r"(?:^|/)env\.example$",
    r"(?:^|/)example\.env$",
)


@dataclass(frozen=True, slots=True)
class Rule:
    """Pattern-matched secrets rule.

    `level` gates whether the rule fires at the active threshold.
    `pattern` is a regex tested via `re.search` with `re.IGNORECASE`.
    `id` is a stable slug shown in the block message; users can grep it
    out of CI logs or paste it back as feedback when refining rules.
    `reason` is the human-facing explanation appended to the block.
    """

    level: str
    id: str
    pattern: str
    reason: str


# === RULE DEFINITIONS ===
#
# To add a rule, append a Rule(...) to the appropriate tuple below.
# First match wins; iteration is in declaration order. Rules whose
# `level` is above the active threshold are skipped.
#
# `# fmt: off` keeps the tables column-aligned so the rules read as a
# scannable matrix. When adding a rule whose id or pattern is longer than
# the current column, widen every row in that table to match.

# fmt: off
# Sensitive file rules: matched against file_path of Read/Edit/Write.
SENSITIVE_FILES: tuple[Rule, ...] = (
    # CRITICAL
    Rule("critical", "env-file",             r"(?:^|/)\.env(?:\.[^/]*)?$",                          ".env file contains secrets"),
    Rule("critical", "envrc",                r"(?:^|/)\.envrc$",                                    ".envrc (direnv) contains secrets"),
    Rule("critical", "ssh-private-key",      r"(?:^|/)\.ssh/id_[^/]+$",                             "SSH private key"),
    Rule("critical", "ssh-private-key-bare", r"(?:^|/)(id_rsa|id_ed25519|id_ecdsa|id_dsa)$",        "SSH private key"),
    Rule("critical", "ssh-authorized",       r"(?:^|/)\.ssh/authorized_keys$",                      "SSH authorized_keys"),
    Rule("critical", "aws-credentials",      r"(?:^|/)\.aws/credentials$",                          "AWS credentials file"),
    Rule("critical", "aws-config",           r"(?:^|/)\.aws/config$",                               "AWS config may contain secrets"),
    Rule("critical", "kube-config",          r"(?:^|/)\.kube/config$",                              "Kubernetes config contains credentials"),
    Rule("critical", "pem-key",              r"\.pem$",                                             "PEM key file"),
    Rule("critical", "key-file",             r"\.key$",                                             "Key file"),
    Rule("critical", "p12-key",              r"\.(p12|pfx)$",                                       "PKCS12 key file"),
    # HIGH
    Rule("high",     "credentials-json",     r"(?:^|/)credentials\.json$",                          "Credentials file"),
    Rule("high",     "secrets-file",         r"(?:^|/)(secrets?|credentials?)\.(json|ya?ml|toml)$", "Secrets configuration file"),
    Rule("high",     "service-account",      r"service[_-]?account.*\.json$",                       "GCP service account key"),
    Rule("high",     "gcloud-creds",         r"(?:^|/)\.config/gcloud/.*(credentials|tokens)",      "GCloud credentials"),
    Rule("high",     "azure-creds",          r"(?:^|/)\.azure/(credentials|accessTokens)",          "Azure credentials"),
    Rule("high",     "docker-config",        r"(?:^|/)\.docker/config\.json$",                      "Docker config may contain registry auth"),
    Rule("high",     "netrc",                r"(?:^|/)\.netrc$",                                    ".netrc contains credentials"),
    Rule("high",     "npmrc",                r"(?:^|/)\.npmrc$",                                    ".npmrc may contain auth tokens"),
    Rule("high",     "pypirc",               r"(?:^|/)\.pypirc$",                                   ".pypirc contains PyPI credentials"),
    Rule("high",     "gem-creds",            r"(?:^|/)\.gem/credentials$",                          "RubyGems credentials"),
    Rule("high",     "vault-token",          r"(?:^|/)(\.vault-token|vault-token)$",                "Vault token file"),
    Rule("high",     "keystore",             r"\.(keystore|jks)$",                                  "Java keystore"),
    Rule("high",     "htpasswd",             r"(?:^|/)\.?htpasswd$",                                "htpasswd contains hashed passwords"),
    Rule("high",     "pgpass",               r"(?:^|/)\.pgpass$",                                   "PostgreSQL password file"),
    Rule("high",     "my-cnf",               r"(?:^|/)\.my\.cnf$",                                  "MySQL config may contain password"),
    # STRICT
    Rule("strict",   "database-config",      r"(?:^|/)(?:config/)?database\.(json|ya?ml)$",         "Database config may contain passwords"),
    Rule("strict",   "ssh-known-hosts",      r"(?:^|/)\.ssh/known_hosts$",                          "SSH known_hosts reveals infrastructure"),
    Rule("strict",   "gitconfig",            r"(?:^|/)\.gitconfig$",                                ".gitconfig may contain credentials"),
    Rule("strict",   "curlrc",               r"(?:^|/)\.curlrc$",                                   ".curlrc may contain auth"),
)

# Bash command rules: matched against the full command string.
BASH_PATTERNS: tuple[Rule, ...] = (
    # CRITICAL: direct reads of secret files.
    Rule("critical", "cat-env",           r"\b(cat|less|head|tail|more|bat|view)\s+[^|;]*\.env\b", "Reading .env file exposes secrets"),
    Rule("critical", "cat-ssh-key",       r"\b(cat|less|head|tail|more|bat)\s+[^|;]*(id_rsa|id_ed25519|id_ecdsa|id_dsa|\.pem|\.key)\b", "Reading private key"),
    Rule("critical", "cat-aws-creds",     r"\b(cat|less|head|tail|more)\s+[^|;]*\.aws/credentials", "Reading AWS credentials"),
    # HIGH: environment exposure.
    Rule("high",     "env-dump",          r"\bprintenv\b|(?:^|[;&|]\s*)env\s*(?:$|[;&|])", "Environment dump may expose secrets"),
    Rule("high",     "echo-secret-var",   r"\becho\b[^;|&]*\$\{?[A-Za-z_]*(?:SECRET|KEY|TOKEN|PASSWORD|PASSW|CREDENTIAL|API_KEY|AUTH|PRIVATE)[A-Za-z_]*\}?", "Echoing secret variable"),
    Rule("high",     "printf-secret-var", r"\bprintf\b[^;|&]*\$\{?[A-Za-z_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY|AUTH|PRIVATE)[A-Za-z_]*\}?", "Printing secret variable"),
    Rule("high",     "cat-secrets-file",  r"\b(cat|less|head|tail|more)\s+[^|;]*(credentials?|secrets?)\.(json|ya?ml|toml)", "Reading secrets file"),
    Rule("high",     "cat-netrc",         r"\b(cat|less|head|tail|more)\s+[^|;]*\.netrc", "Reading .netrc credentials"),
    Rule("high",     "source-env",        r"\bsource\s+[^|;]*\.env\b|(?:^|[;&|]\s*)\.\s+[^|;]*\.env\b", "Sourcing .env loads secrets"),
    Rule("high",     "export-cat-env",    r"export\s+.*\$\(cat\s+[^)]*\.env", "Exporting secrets from .env"),
    # HIGH: exfiltration.
    Rule("high",     "curl-upload-env",   r"\bcurl\b[^;|&]*(-d\s*@|-F\s*[^=]+=@|--data[^=]*=@)[^;|&]*(\.env|credentials|secrets|id_rsa|\.pem|\.key)", "Uploading secrets via curl"),
    Rule("high",     "curl-post-secrets", r"\bcurl\b[^;|&]*-X\s*POST[^;|&]*(\.env|credentials|secrets)", "POSTing secrets via curl"),
    Rule("high",     "wget-post-secrets", r"\bwget\b[^;|&]*--post-file[^;|&]*(\.env|credentials|secrets)", "POSTing secrets via wget"),
    Rule("high",     "scp-secrets",       r"\bscp\b[^;|&]*(\.env|credentials|secrets|id_rsa|\.pem|\.key)[^;|&]+:", "Copying secrets via scp"),
    Rule("high",     "rsync-secrets",     r"\brsync\b[^;|&]*(\.env|credentials|secrets|id_rsa)[^;|&]+:", "Syncing secrets via rsync"),
    Rule("high",     "nc-secrets",        r"\bnc\b[^;|&]*<[^;|&]*(\.env|credentials|secrets|id_rsa)", "Exfiltrating secrets via netcat"),
    # HIGH: copy/move/delete of secret files.
    Rule("high",     "cp-env",            r"\bcp\b[^;|&]*\.env\b", "Copying .env file"),
    Rule("high",     "cp-ssh-key",        r"\bcp\b[^;|&]*(id_rsa|id_ed25519|\.pem|\.key)\b", "Copying private key"),
    Rule("high",     "mv-env",            r"\bmv\b[^;|&]*\.env\b", "Moving .env file"),
    Rule("high",     "rm-ssh-key",        r"\brm\b[^;|&]*(id_rsa|id_ed25519|id_ecdsa|authorized_keys)", "Deleting SSH key"),
    Rule("high",     "rm-env",            r"\brm\b.*\.env\b", "Deleting .env file"),
    Rule("high",     "rm-aws-creds",      r"\brm\b[^;|&]*\.aws/credentials", "Deleting AWS credentials"),
    Rule("high",     "truncate-secrets",  r"\btruncate\b.*\.(env|pem|key)\b|(?:^|[;&|]\s*)>\s*\.env\b", "Truncating secrets file"),
    # HIGH: process environ + indirect access.
    Rule("high",     "proc-environ",      r"/proc/[^/]*/environ", "Reading process environment"),
    Rule("high",     "xargs-cat-env",     r"xargs.*cat|\.env.*xargs", "Reading .env via xargs"),
    Rule("high",     "find-exec-cat-env", r"find\b.*\.env.*-exec|find\b.*-exec.*(cat|less)", "Finding and reading .env files"),
    # STRICT
    Rule("strict",   "grep-password",     r"\bgrep\b[^|;]*(-r|--recursive)[^|;]*(password|secret|api.?key|token|credential)", "Grep for secrets may expose them"),
    Rule("strict",   "base64-secrets",    r"\bbase64\b[^|;]*(\.env|credentials|secrets|id_rsa|\.pem)", "Base64 encoding secrets"),
)
# fmt: on


def _active_threshold() -> int:
    """Return the numeric threshold from the env var, falling back to default."""
    raw = os.environ.get(LEVEL_ENV_VAR, DEFAULT_LEVEL).lower()
    return LEVELS.get(raw, LEVELS[DEFAULT_LEVEL])


def _is_allowlisted(text: str) -> bool:
    """Check if the input matches any safe-template pattern."""
    return any(re.search(p, text, re.IGNORECASE) for p in ALLOWLIST)


def _first_match(text: str, rules: tuple[Rule, ...], threshold: int) -> Rule | None:
    """Return the first rule firing at or below the active threshold."""
    for rule in rules:
        if LEVELS[rule.level] > threshold:
            continue
        if re.search(rule.pattern, text, re.IGNORECASE):
            return rule
    return None


def _block(rule: Rule, action: str) -> None:
    """Print BLOCKED message to stderr and exit 2."""
    print(  # noqa: T201
        f"BLOCKED [{rule.id}]: Cannot {action}: {rule.reason}",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    """Entry point for the PreToolUse hook."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name: str = data.get("tool_name", "")
    tool_input: dict = data.get("tool_input") or {}
    threshold = _active_threshold()

    if tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if not file_path or _is_allowlisted(file_path):
            sys.exit(0)
        rule = _first_match(file_path, SENSITIVE_FILES, threshold)
        if rule:
            _block(rule, ACTION_VERBS[tool_name])
        sys.exit(0)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not command or _is_allowlisted(command):
            sys.exit(0)
        rule = _first_match(command, BASH_PATTERNS, threshold)
        if rule:
            _block(rule, ACTION_VERBS["Bash"])

    sys.exit(0)


if __name__ == "__main__":
    main()
