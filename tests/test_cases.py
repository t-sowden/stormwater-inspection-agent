"""Runs every case in tests/cases.json (same suite as the Verification tab).
Cases with "known_limitation" are accepted failures and show as xfail."""
import pytest

from agent.verify import run_all

RESULTS = run_all()


@pytest.mark.parametrize("r", RESULTS, ids=[r["id"] for r in RESULTS])
def test_case(r):
    if r["known_limitation"] and not r["passed"]:
        pytest.xfail(r["known_limitation"])
    assert r["passed"], f"{r['description']}\nexpected: {r['expected']}\nactual:   {r['actual']}"
