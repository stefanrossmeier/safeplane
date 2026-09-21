from collections import Counter
from pathlib import Path

from safeplane_routing_advisor.runner import load_suite

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_corpus_shape() -> None:
    suite = load_suite(ROOT / "data" / "corpus.v1.json")
    assert suite.metadata.status == "frozen"
    assert len(suite.cases) == 420
    assert Counter(case.expected_route for case in suite.cases) == {
        "chat": 120,
        "assistant": 120,
        "developer": 120,
        "unclear": 60,
    }
    assert Counter(case.split for case in suite.cases) == {
        "calibration": 315,
        "holdout": 105,
    }


def test_corpus_has_hard_families() -> None:
    suite = load_suite(ROOT / "data" / "corpus.v1.json")
    families = Counter(case.family for case in suite.cases)
    assert families["minimal_pair"] == 90
    assert families["route_spoofing"] >= 20
    assert families["missing_repository_profile"] == 10
    assert families["cross_workflow"] == 10
    assert families["missing_artifact"] == 15
