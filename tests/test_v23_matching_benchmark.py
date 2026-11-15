"""
Matching Evaluation Benchmark Test Suite for AutoBot v2.3.
Verifies the deterministic 5-component scoring formula across the curated 60-pair benchmark dataset:
- 100% mathematical reproducibility
- Alias and abbreviation recognition
- Negation handling
- Mandatory requirement failures
- Misleading description mitigation
- Disagreement identification (where technical fit is high but eligibility is INELIGIBLE)
- Fit score disclaimer presence
"""

import pytest
from src.matching.benchmark import MatchingBenchmarkSuite
from src.matching.scorer import DISCLAIMER_NOTICE


def test_matching_benchmark_dataset_metrics():
    """Verify that all 60 benchmark pairs pass evaluation criteria."""
    suite = MatchingBenchmarkSuite()
    report = suite.run_benchmark()

    assert report.total_pairs == 60
    assert report.passed_pairs == 60
    assert report.failed_pairs == 0
    assert report.reproducibility_rate == 100.0
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.disagreement_cases >= 15  # At least 15 clear disagreement cases

    # Category checks
    for cat in [
        "exact_match",
        "abbreviations_and_aliases",
        "negations_and_not_required",
        "mandatory_requirements_mismatch",
        "misleading_job_descriptions",
        "eligibility_fit_disagreement",
    ]:
        assert cat in report.category_scores
        assert report.category_scores[cat]["passed"] == report.category_scores[cat]["total"]


def test_fit_score_disclaimer_notice():
    """Verify that the disclaimer is never missing and never presents fit score as hiring probability."""
    assert "NOT a hiring probability" in DISCLAIMER_NOTICE
    assert "automated heuristic qualification estimate" in DISCLAIMER_NOTICE


def test_disagreement_between_eligibility_and_fit():
    """
    Ensure the system identifies cases where candidate has high technical fit
    but is strictly ineligible due to country or employment tier constraints.
    """
    suite = MatchingBenchmarkSuite()
    report = suite.run_benchmark()

    disagreements = [p for p in report.pair_results if p.disagreement_detected]
    assert len(disagreements) >= 15

    for d in disagreements:
        assert d.computed_eligibility.lower() == "ineligible"
        assert d.computed_score >= 60.0
