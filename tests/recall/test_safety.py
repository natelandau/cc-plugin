"""Verify the shared secret-scrub redacts token- and key:value-shaped secrets."""

from __future__ import annotations

from recall.safety import REDACTED, scrub  # ty: ignore[unresolved-import]


def test_scrub_redacts_aws_key_and_reports_change() -> None:
    # Given text containing an AWS access key id
    text = "use AKIAIOSFODNN7EXAMPLE here"
    # When scrubbed
    out, changed = scrub(text)
    # Then the token is replaced and the change is reported
    assert "AKIA" not in out
    assert REDACTED in out
    assert changed is True


def test_scrub_preserves_label_redacts_value() -> None:
    # Given a key:value secret
    text = "api_key = 'abcdefghijklmnopqrstuvwxyz0123'"
    # When scrubbed
    out, changed = scrub(text)
    # Then the label remains and only the value is redacted
    assert out.startswith("api_key = '")
    assert REDACTED in out
    assert changed is True


def test_scrub_clean_text_unchanged() -> None:
    # Given text with no secrets
    text = "just a normal learning about how the parser works"
    # When scrubbed
    out, changed = scrub(text)
    # Then nothing changes
    assert out == text
    assert changed is False
