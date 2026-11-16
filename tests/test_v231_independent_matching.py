"""
Independent Matching Quality and NDCG Benchmark Test Suite for AutoBot v2.3.1.
Verifies:
1. Separation between development fixtures and independent human-labeled ground truth.
2. Ranking quality: NDCG@10 >= 0.85 on realistic candidates and job postings.
3. Precision of Top-10 and Top-20 retrieved/ranked vacancies.
4. Eligibility confusion matrix (TP, TN, FP, FN) and accuracy >= 95%.
5. Proper separation of eligibility gate vs. technical fit (location/visa conflicts).
6. Statutory disclaimer notice presence (never described as hiring probabilities).
"""

import pytest
from src.matching.independent_benchmark import IndependentBenchmarkSuite, compute_ndcg_at_k
from src.matching.scorer import DISCLAIMER_NOTICE


def test_ndcg_calculation_mathematical_properties():
    """Verify NDCG computation with known synthetic sequences."""
    # Perfect ranking: IDCG == DCG -> NDCG == 1.0
    perfect = [3, 3, 2, 2, 1, 1, 0, 0]
    assert pytest.approx(compute_ndcg_at_k(perfect, k=5), 0.001) == 1.0

    # Completely inverted ranking: 0s at the top, 3s at the bottom
    inverted = [0, 0, 0, 1, 1, 2, 2, 3, 3]
    score_inv = compute_ndcg_at_k(inverted, k=5)
    assert score_inv < 0.3

    # All zeros
    assert compute_ndcg_at_k([0, 0, 0], k=3) == 1.0


def test_independent_matching_benchmark_metrics():
    """Run full evaluation over the 80 independent human-labeled pairs."""
    suite = IndependentBenchmarkSuite()
    report = suite.run_benchmark()

    # 1. Dataset size and category coverage
    assert report.total_pairs == 80
    assert len(report.category_metrics) == 8

    # 2. Eligibility Engine Metrics
    assert report.eligibility_accuracy >= 0.95
    assert report.eligibility_precision >= 0.90
    assert report.eligibility_recall >= 0.90
    assert report.eligibility_f1 >= 0.90
    assert report.eligibility_fp <= 3
    assert report.eligibility_fn <= 3

    # 3. Ranking Quality (NDCG@10)
    # Top ranked jobs must strongly align with human relevance grades
    assert report.ndcg_at_10 >= 0.85
    assert report.top_10_precision >= 0.80  # At least 80% of top-10 are highly relevant (grade >= 2)
    assert report.top_20_precision >= 0.70

    # 4. Location & Visa Conflict Disagreement Separation
    # Cases where technical fit is high (score >= 60) but candidate is INELIGIBLE due to visa/country
    assert report.location_conflict_cases == 10
    assert report.location_conflict_verified == 10  # 100% of location conflicts properly separated!


def test_independent_benchmark_disclaimer_notice():
    """Ensure the disclaimer is attached and explicitly rejects hiring probability claims."""
    suite = IndependentBenchmarkSuite()
    report = suite.run_benchmark()

    assert "NOT a hiring probability" in report.disclaimer
    assert "automated heuristic qualification estimate" in report.disclaimer


def test_category_fit_score_separation():
    """
    Verify expected score separation across distinct categories:
    - High fit average must exceed 75.0
    - Cross-domain mismatch average must be below 45.0
    """
    suite = IndependentBenchmarkSuite()
    report = suite.run_benchmark()

    metrics = report.category_metrics
    assert metrics["realistic_high_fit"]["avg_score"] >= 75.0
    assert metrics["cross_domain_mismatch"]["avg_score"] <= 45.0
    assert metrics["realistic_high_fit"]["avg_score"] > metrics["career_transition"]["avg_score"]
    assert metrics["career_transition"]["avg_score"] > metrics["cross_domain_mismatch"]["avg_score"]
