"""Runs every case in tests/cases.json (same suite as the Verification tab)."""
import pytest

from agent.verify import run_all

RESULTS = run_all()


@pytest.mark.parametrize("r", RESULTS, ids=[r["id"] for r in RESULTS])
def test_case(r):
    assert r["passed"], f"{r['description']}\nexpected: {r['expected']}\nactual:   {r['actual']}"
