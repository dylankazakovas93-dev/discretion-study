"""Reproducibility: deterministic replay, ids, selection, locked schemas, hashes."""

from __future__ import annotations

import json
import os

import pytest

from discretion.recognizer.pipeline import (
    run_recognizer, candidate_ledger, ledger_hash,
)
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
WIN = dict(start="2025-07-07T13:00", end="2025-07-07T17:00")


def test_event_and_feature_schemas_present_and_valid():
    for path in ("schemas/event.schema.json", "schemas/feature.schema.json"):
        assert os.path.exists(path)
        with open(path) as fh:
            schema = json.load(fh)
        assert "properties" in schema


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_identical_rerun_produces_identical_ledger_hash():
    r1 = run_recognizer(**WIN)
    r2 = run_recognizer(**WIN)
    h1 = ledger_hash(candidate_ledger(r1))
    h2 = ledger_hash(candidate_ledger(r2))
    assert h1 == h2


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_deterministic_ids_and_ordering():
    r1 = run_recognizer(**WIN)
    r2 = run_recognizer(**WIN)
    l1 = candidate_ledger(r1)
    l2 = candidate_ledger(r2)
    assert [x["candidate_id"] for x in l1] == [x["candidate_id"] for x in l2]
    assert [x["episode_id"] for x in l1] == [x["episode_id"] for x in l2]
    assert [x["branch_id"] for x in l1] == [x["branch_id"] for x in l2]
    assert [x["qualification"] for x in l1] == [x["qualification"] for x in l2]


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_deterministic_example_selection():
    # first N candidates chronologically are identical across runs
    r1 = run_recognizer(**WIN)
    r2 = run_recognizer(**WIN)
    pick1 = [c.setup.id for c in sorted(r1["candidates"],
             key=lambda c: (c.setup.entry_seq, c.setup.id))[:10]]
    pick2 = [c.setup.id for c in sorted(r2["candidates"],
             key=lambda c: (c.setup.entry_seq, c.setup.id))[:10]]
    assert pick1 == pick2


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_qualification_independent_of_own_outcome():
    # a candidate's qualification uses only prior sessions; within a single
    # session (this window) there are no priors, so nothing qualifies regardless
    # of how its own outcome later resolves.
    r = run_recognizer(**WIN)
    quals = {c.qualification for c in r["candidates"]}
    assert quals == {"RECORDED_NOT_ACTIVATED"}
