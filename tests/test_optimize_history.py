"""Smoke tests for ``pfc_inductor.optimize.history``.

The history layer is best-effort persistence — the optimizer must
continue to function whether or not the disk is writable or the
JSON files are valid. The tests below pin that contract:

- Empty / missing files return ``[]`` rather than raising.
- ``record_pick`` dedupes on the (mat, core, wire) triple and caps
  the list at 5.
- ``record_run`` caps the list at 10.
- ``format_relative_age`` is forgiving of garbage input.

All disk writes are sandboxed to a per-test temp dir via
``monkeypatch.setenv``-style redirection of the platformdirs
resolver. The store helpers re-resolve the directory on every call,
so a per-test patch is sufficient.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pfc_inductor.optimize import history


@pytest.fixture(autouse=True)
def _sandbox_history_dir(monkeypatch, tmp_path: Path):
    """Redirect ``platformdirs.user_data_dir`` into a tmp dir for the
    duration of each test. Otherwise the tests would pollute the
    real user-data directory and could interfere with each other.
    """

    def _fake_dir(*_args, **_kwargs) -> str:
        return str(tmp_path)

    monkeypatch.setattr(history, "user_data_dir", _fake_dir)
    yield


# ─── Recent picks ──────────────────────────────────────────────────


def test_recent_picks_returns_empty_when_no_file():
    assert history.recent_picks() == []


def test_record_pick_round_trips():
    history.record_pick("M1", "C1", "W1", "M1 · C1 · W1")
    picks = history.recent_picks()
    assert len(picks) == 1
    assert picks[0]["material_id"] == "M1"
    assert picks[0]["core_id"] == "C1"
    assert picks[0]["wire_id"] == "W1"
    assert picks[0]["label"] == "M1 · C1 · W1"


def test_record_pick_dedupes_on_triple():
    """Re-applying the same triple should move it to the top, not
    accumulate duplicates."""
    history.record_pick("M1", "C1", "W1", "first")
    history.record_pick("M2", "C2", "W2", "second")
    history.record_pick("M1", "C1", "W1", "first-again")
    picks = history.recent_picks()
    assert len(picks) == 2
    # Most recently applied triple is now at the top with the new label.
    assert picks[0]["material_id"] == "M1"
    assert picks[0]["label"] == "first-again"
    assert picks[1]["material_id"] == "M2"


def test_record_pick_caps_list_at_max():
    for i in range(history.MAX_RECENT_PICKS + 3):
        history.record_pick(f"M{i}", f"C{i}", f"W{i}", f"label-{i}")
    picks = history.recent_picks()
    assert len(picks) == history.MAX_RECENT_PICKS
    # Newest first — the last 5 recorded should be present, oldest dropped.
    assert picks[0]["material_id"] == f"M{history.MAX_RECENT_PICKS + 2}"


# ─── Run history ───────────────────────────────────────────────────


def test_recent_runs_returns_empty_when_no_file():
    assert history.recent_runs() == []


def test_record_run_round_trips():
    history.record_run(
        n_combinations=1_000,
        n_feasible=750,
        objective="score",
        top_pick={
            "material_id": "M1",
            "core_id": "C1",
            "wire_id": "W1",
            "label": "M1 · C1 · W1",
        },
        filter_summary="3m × 28c × 1k_w",
    )
    runs = history.recent_runs()
    assert len(runs) == 1
    assert runs[0]["n_combinations"] == 1_000
    assert runs[0]["n_feasible"] == 750
    assert runs[0]["objective"] == "score"
    assert runs[0]["filter_summary"] == "3m × 28c × 1k_w"
    assert runs[0]["top_pick"]["material_id"] == "M1"


def test_record_run_caps_list_at_max():
    for i in range(history.MAX_RUN_HISTORY + 5):
        history.record_run(
            n_combinations=i,
            n_feasible=i,
            objective="loss",
        )
    runs = history.recent_runs()
    assert len(runs) == history.MAX_RUN_HISTORY
    # The newest (highest i) should be on top.
    assert runs[0]["n_combinations"] == history.MAX_RUN_HISTORY + 4


def test_record_run_handles_missing_top_pick():
    """``top_pick=None`` is allowed — the engineer may have run a
    sweep with zero feasible designs."""
    history.record_run(
        n_combinations=42,
        n_feasible=0,
        objective="loss",
        top_pick=None,
    )
    runs = history.recent_runs()
    assert len(runs) == 1
    assert runs[0]["top_pick"] is None


# ─── format_relative_age ───────────────────────────────────────────


def test_format_relative_age_returns_just_now_for_recent():
    from datetime import datetime, timezone

    iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    assert history.format_relative_age(iso) == "just now"


def test_format_relative_age_handles_garbage_input():
    assert history.format_relative_age("not-a-date") == "not-a-date"
    assert history.format_relative_age("") == ""


# ─── Robustness: corrupt files ─────────────────────────────────────


def test_corrupt_json_returns_empty(tmp_path: Path):
    (tmp_path / "optimizer_recent_picks.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "optimizer_run_history.json").write_text("[1, 2, 3", encoding="utf-8")
    assert history.recent_picks() == []
    assert history.recent_runs() == []


def test_wrong_type_in_json_returns_empty(tmp_path: Path):
    # A dict instead of a list — old format that should be ignored,
    # not promoted to a single dict entry.
    (tmp_path / "optimizer_recent_picks.json").write_text(
        '{"foo": "bar"}', encoding="utf-8"
    )
    assert history.recent_picks() == []
