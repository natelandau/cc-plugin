#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: block system-destructive bash commands.

Block catastrophic and high-risk shell operations that are largely
irreversible:

- Mass deletion of home, root, or system directories
  (`rm -rf ~`, `rm -rf /etc`).
- Disk wipes (`dd of=/dev/sda`, `mkfs.ext4 /dev/sda`,
  `diskutil eraseDisk`).
- Fork bombs and init/kernel-panic triggers (`kill -9 1`,
  `pkill -9 init`, `> /proc/sysrq-trigger`).
- Piping remote scripts to a shell (`curl ... | sh`).
- World-writable permissions (`chmod 777`).
- Docker volume deletion and prune ops.
- macOS system-integrity ops (`csrutil disable`, `nvram -c`,
  `tmutil delete`).
- Cloud / IaC catastrophes with explicit auto-confirm flags
  (`terraform destroy --auto-approve`, `aws s3 rb --force`,
  `gcloud ... delete --quiet`, `gh repo delete --yes`).
- `sudo rm`, `crontab -r`.

Three escalating thresholds gate which rules apply:

- `critical` -- only catastrophic, unrecoverable ops.
- `high` (default) -- adds significant-risk ops (`curl|sh`,
  `chmod 777`, docker volume rm).
- `strict` -- adds cautionary ops (`sudo rm`, docker prune,
  `crontab -r`).

Override the level with `CLAUDE_PROTECT_SYSTEM_LEVEL`.

Secret reads and git destructive ops are intentionally not duplicated
here; see `protect_secrets.py` and `enforce_branch_protection.py`.

Adapted from karanb192/claude-code-hooks `block-dangerous-commands.js`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}
DEFAULT_LEVEL = "high"
LEVEL_ENV_VAR = "CLAUDE_PROTECT_SYSTEM_LEVEL"


@dataclass(frozen=True, slots=True)
class Rule:
    """Pattern-matched system-destruction rule.

    `level` gates whether the rule fires at the active threshold.
    `pattern` is a regex tested via `re.search` with `re.IGNORECASE`.
    `id` is a stable slug shown in the block message; users can grep
    it out of CI logs or paste it back as feedback when refining rules.
    `reason` is the human-facing explanation appended to the block.
    """

    level: str
    id: str
    pattern: str
    reason: str


# === RULE DEFINITIONS ===
#
# To add a rule, append a Rule(...) to the tuple below. First match
# wins; iteration is in declaration order. Rules whose `level` is
# above the active threshold are skipped.
#
# `# fmt: off` keeps the table column-aligned so the rules read as a
# scannable matrix. When adding a rule whose id or pattern is longer
# than the current column, widen every row to match.

# fmt: off
# Bash command rules: matched against the full command string.
BASH_PATTERNS: tuple[Rule, ...] = (
    # CRITICAL: catastrophic and largely unrecoverable.
    Rule("critical", "rm-home",             r"\brm\b\s+(?:-\S+\s+)*[\"']?~/?[\"']?(?:\s|$|[;&|])",                                   "rm targeting home directory"),
    Rule("critical", "rm-home-var",         r"\brm\b\s+(?:-\S+\s+)*[\"']?\$HOME/?[\"']?(?:\s|$|[;&|])",                              "rm targeting $HOME"),
    Rule("critical", "rm-home-trailing",    r"\brm\b\s+\S.*\s[\"']?(?:~/?|\$HOME/?)[\"']?(?:\s*$|[;&|])",                            "rm with trailing ~ or $HOME"),
    Rule("critical", "rm-root",             r"\brm\b\s+(?:-\S+\s+)+/(?:\*|\s|$|[;&|])",                                              "rm targeting root filesystem"),
    Rule("critical", "rm-system",           r"\brm\b\s+(?:-\S+\s+)*/(?:etc|usr|var|bin|sbin|lib|boot|dev|proc|sys)(?:/|\s|$|[;&|])", "rm targeting system directory"),
    Rule("critical", "rm-cwd",              r"\brm\b\s+(?:-\S+\s+)*(?:\./?|\*|\./\*)(?:\s|$|[;&|])",                                 "rm of '.' or '*' wipes CWD contents"),
    Rule("critical", "dd-disk",             r"\bdd\b[^;|&]+\bof=/dev/(?:sd[a-z]|nvme\d+n\d+|hd[a-z]|vd[a-z]|xvd[a-z])",              "dd writing to disk device"),
    Rule("critical", "mkfs-disk",           r"\bmkfs(?:\.\w+)?\b[^;|&]+/dev/(?:sd[a-z]|nvme\d+n\d+|hd[a-z]|vd[a-z])",                "mkfs formatting disk device"),
    Rule("critical", "fork-bomb",           r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:[^}]*&[^}]*\}",                                         "fork bomb"),
    Rule("critical", "kill-init",           r"\bkill\b\s+(?:-\S+\s+)*1(?:\s|$|[;&|])",                                               "kill signal to PID 1 panics init"),
    Rule("critical", "kill-all",            r"\bkill\b\s+-\S+(?:\s+\S+)*\s+-1(?:\s|$|[;&|])",                                        "kill -1 signals every process"),
    Rule("critical", "pkill-init",          r"\b(?:pkill|killall)\b[^;|&]*\b(?:init|systemd|launchd)(?:\s|$|[;&|])",                 "killing init/systemd/launchd crashes the system"),
    Rule("critical", "sysrq-trigger",       r">\s*/proc/sysrq-trigger",                                                              "writing to sysrq-trigger crashes the kernel"),
    Rule("critical", "csrutil-disable",     r"\bcsrutil\s+(?:disable|clear)\b",                                                      "csrutil disable turns off macOS SIP"),
    Rule("critical", "nvram-clear",         r"\bnvram\b[^;|&]*\s-c\b",                                                               "nvram -c clears macOS NVRAM"),
    Rule("critical", "tmutil-delete",       r"\btmutil\s+(?:delete|deletelocalsnapshots)\b",                                         "tmutil destroys Time Machine snapshots"),
    Rule("critical", "diskutil-erase",      r"\bdiskutil\s+(?:eraseDisk|eraseVolume|zeroDisk|secureErase)\b",                        "diskutil erase wipes the disk"),
    # HIGH: significant, hard-to-reverse damage.
    Rule("high",     "curl-pipe-sh",        r"\b(?:curl|wget)\b[^;&]*\|\s*(?:sudo\s+)?(?:bash|zsh|sh)\b",                            "piping remote script to shell (RCE risk)"),
    Rule("high",     "chmod-world",         r"\bchmod\b[^;|&]*\b0?777\b",                                                            "chmod 777 grants world write"),
    Rule("high",     "docker-vol-rm",       r"\bdocker\s+volume\s+(?:rm|prune)\b",                                                   "docker volume deletion loses data"),
    Rule("high",     "terraform-destroy",   r"\bterraform\s+destroy\b[^;|&]*--?auto-approve\b",                                      "terraform destroy --auto-approve tears down infra"),
    Rule("high",     "aws-s3-rb-force",     r"\baws\s+s3\s+rb\b[^;|&]*--force\b",                                                    "aws s3 rb --force recursively deletes bucket"),
    Rule("high",     "aws-s3-rm-recursive", r"\baws\s+s3\s+rm\b(?=[^;|&]*--recursive)(?=[^;|&]*s3://)",                              "aws s3 rm --recursive wipes bucket contents"),
    Rule("high",     "gcloud-delete-quiet", r"\bgcloud\b[^;|&]*\bdelete\b[^;|&]*(?:-q\b|--quiet\b)",                                 "gcloud delete --quiet bypasses confirmation"),
    Rule("high",     "gh-repo-delete",      r"\bgh\s+repo\s+delete\b[^;|&]*--yes\b",                                                 "gh repo delete --yes destroys the repository"),
    # STRICT: cautionary, often legitimate.
    Rule("strict",   "sudo-rm",             r"\bsudo\b[^;|&]*\brm\b",                                                                "sudo rm has elevated privileges"),
    Rule("strict",   "docker-prune",        r"\bdocker\s+(?:system|image|container|builder)\s+prune\b",                              "docker prune removes images/containers"),
    Rule("strict",   "crontab-r",           r"\bcrontab\b[^;|&]*\s-\S*r(?:\s|$|[;&|])",                                              "crontab -r removes all cron jobs"),
)
# fmt: on


def _active_threshold() -> int:
    """Return the numeric threshold from the env var, falling back to default."""
    raw = os.environ.get(LEVEL_ENV_VAR, DEFAULT_LEVEL).lower()
    return LEVELS.get(raw, LEVELS[DEFAULT_LEVEL])


def _first_match(text: str, rules: tuple[Rule, ...], threshold: int) -> Rule | None:
    """Return the first rule firing at or below the active threshold."""
    for rule in rules:
        if LEVELS[rule.level] > threshold:
            continue
        if re.search(rule.pattern, text, re.IGNORECASE):
            return rule
    return None


def _block(rule: Rule) -> None:
    """Print BLOCKED message to stderr and exit 2."""
    print(  # noqa: T201
        f"BLOCKED [{rule.id}]: Cannot execute: {rule.reason}",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    """Entry point for the PreToolUse hook."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command: str = (data.get("tool_input") or {}).get("command", "")
    if not command:
        sys.exit(0)

    rule = _first_match(command, BASH_PATTERNS, _active_threshold())
    if rule:
        _block(rule)
    sys.exit(0)


if __name__ == "__main__":
    main()
