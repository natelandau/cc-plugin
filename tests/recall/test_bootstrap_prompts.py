"""Guard the bootstrap prompts' safety-critical invariants."""

from __future__ import annotations

from pathlib import Path

PROMPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "plugins"
    / "natelandau-recall"
    / "hooks"
    / "prompts"
)


def test_extract_prompt_forbids_writes_and_marks_untrusted() -> None:
    text = (PROMPTS / "bootstrap-extract.md").read_text(encoding="utf-8")
    assert "UNTRUSTED" in text
    assert "do not write" in text.lower() or "write nothing" in text.lower()
    assert "json" in text.lower()


def test_merge_prompt_marks_untrusted_and_no_write() -> None:
    text = (PROMPTS / "bootstrap-merge.md").read_text(encoding="utf-8")
    # Given the merge prompt file
    # When reading the prompt
    # Then it marks untrusted data and forbids writes
    assert "UNTRUSTED" in text
    assert "do not write" in text.lower() or "without writing" in text.lower()
    # And output key names are present (must match Bootstrap.apply consumer)
    assert "processed_session_ids" in text
    assert '"filename"' in text
    assert '"content"' in text
    assert "json" in text.lower()


def test_no_em_dashes_in_prompts() -> None:
    for name in ("bootstrap-extract.md", "bootstrap-merge.md"):
        assert "—" not in (PROMPTS / name).read_text(encoding="utf-8")
