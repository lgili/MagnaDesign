"""Positioning module + AboutDialog + README invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

from pfc_inductor.positioning import (
    COMPETITORS,
    DIFFERENTIALS,
    PITCH,
    coverage_label,
    get_competitor,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_seven_differentials_protected():
    """The seven defended differentials must all exist in the module."""
    keys = {d.key for d in DIFFERENTIALS}
    expected = {
        "pfc_topology", "cost_model", "litz_optimizer",
        "multi_compare", "bh_loop", "polished_ux", "br_market",
    }
    assert keys == expected, (
        f"Missing or extra differentials. Found: {keys - expected}; "
        f"missing: {expected - keys}. ADR 0001 enumerates seven; this test "
        "is a guardrail."
    )


def test_every_differential_covers_every_competitor():
    comp_ids = {c.id for c in COMPETITORS}
    for diff in DIFFERENTIALS:
        missing = comp_ids - set(diff.coverage.keys())
        assert not missing, (
            f"Differential {diff.key!r} missing coverage for: {missing}"
        )


def test_coverage_values_are_known():
    valid = {"yes", "partial", "no", "na"}
    for d in DIFFERENTIALS:
        for cid, cov in d.coverage.items():
            assert cov in valid, (
                f"Invalid coverage value {cov!r} in {d.key} for {cid}"
            )


def test_coverage_label_returns_known_glyph():
    assert coverage_label("yes") == "✓"
    assert coverage_label("partial") == "≈"
    assert coverage_label("no") == "✗"
    assert coverage_label("na") == "—"


def test_get_competitor_lookup():
    c = get_competitor("femmt")
    assert "FEMMT" in c.name
    with pytest.raises(KeyError):
        get_competitor("does-not-exist")


def test_competitor_urls_are_https():
    for c in COMPETITORS:
        assert c.url.startswith("https://"), (
            f"Competitor {c.id} url must be https: got {c.url!r}"
        )


def test_pitch_is_present_and_short():
    assert PITCH
    assert len(PITCH) < 500


def test_positioning_doc_exists_and_mentions_each_competitor():
    """`docs/POSITIONING.md` is the human-readable mirror; every competitor
    short name must appear there too."""
    p = REPO_ROOT / "docs" / "POSITIONING.md"
    assert p.exists(), "docs/POSITIONING.md is required (ADR 0001)"
    text = p.read_text(encoding="utf-8")
    for c in COMPETITORS:
        assert c.short in text, (
            f"docs/POSITIONING.md must reference competitor {c.short!r}"
        )


def test_adr_exists():
    p = REPO_ROOT / "docs" / "adr" / "0001-positioning.md"
    assert p.exists(), "ADR 0001 must exist alongside POSITIONING.md"


def test_contributing_exists_with_scope_section():
    p = REPO_ROOT / "CONTRIBUTING.md"
    assert p.exists(), "CONTRIBUTING.md is required (ADR 0001)"
    text = p.read_text(encoding="utf-8")
    assert "Scope guardrails" in text or "scope guardrails" in text


def test_readme_pitch_precedes_install():
    """The differential pitch (in any of its accepted phrasings) must
    appear before the install instructions.

    The README has been through PT-BR and now EN editions; we accept
    either canonical phrasing so the test stays meaningful as the copy
    evolves.
    """
    p = REPO_ROOT / "README.md"
    text = p.read_text(encoding="utf-8")
    # Accept the original PT-BR header, an EN equivalent, or the
    # current "What is supported today" section as the differential
    # pitch entry point.
    pitch_candidates = (
        "Por que este projeto importa",
        "Why this project matters",
        "## What is supported today",
    )
    pitch_idx = -1
    for cand in pitch_candidates:
        pitch_idx = text.find(cand)
        if pitch_idx >= 0:
            break
    install_candidates = (
        "## Instalação",
        "## Setup rápido",
        "## Getting started",
        "### Install",
    )
    install_idx = -1
    for cand in install_candidates:
        idx = text.find(cand)
        if idx >= 0 and (install_idx < 0 or idx < install_idx):
            install_idx = idx
    assert pitch_idx >= 0, (
        "README must contain a differential-pitch section "
        f"(any of {pitch_candidates})"
    )
    assert install_idx >= 0, (
        f"README must have an install section (any of {install_candidates})"
    )
    assert pitch_idx < install_idx, (
        "README hero must come before installation"
    )


def test_readme_links_to_positioning():
    p = REPO_ROOT / "README.md"
    text = p.read_text(encoding="utf-8")
    # The reference may be relative (``docs/POSITIONING.md``) or in a
    # markdown link form. Accept either; just require the filename.
    assert "POSITIONING.md" in text, (
        "README must reference docs/POSITIONING.md somewhere"
    )
