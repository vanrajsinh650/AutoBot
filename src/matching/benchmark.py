"""
Matching Quality and Evaluation Benchmark Harness for AutoBot v2.3.
Evaluates deterministic 0–100 scoring, alias normalization, negation handling,
mandatory requirement failures, and eligibility disagreements against the curated benchmark dataset.
"""

from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.evaluator import extract_requirements_heuristic
from src.matching.scorer import DISCLAIMER_NOTICE, DeterministicFitScorer, MatchBreakdown


BENCHMARK_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "benchmarks", "matching_eval_dataset.json"
)


@dataclass
class PairResult:
    pair_id: str
    category: str
    computed_eligibility: str
    expected_eligibility: str
    computed_score: float
    expected_score_range: Tuple[float, float]
    disagreement_detected: bool
    reproducible: bool
    passed: bool
    diagnostic: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "category": self.category,
            "computed_eligibility": self.computed_eligibility,
            "expected_eligibility": self.expected_eligibility,
            "computed_score": self.computed_score,
            "expected_score_range": list(self.expected_score_range),
            "disagreement_detected": self.disagreement_detected,
            "reproducible": self.reproducible,
            "passed": self.passed,
            "diagnostic": self.diagnostic,
        }


@dataclass
class BenchmarkReport:
    total_pairs: int
    passed_pairs: int
    failed_pairs: int
    false_positives: int
    false_negatives: int
    disagreement_cases: int
    reproducibility_rate: float
    category_scores: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    disclaimer: str = DISCLAIMER_NOTICE
    pair_results: List[PairResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pairs": self.total_pairs,
            "passed_pairs": self.passed_pairs,
            "failed_pairs": self.failed_pairs,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "disagreement_cases": self.disagreement_cases,
            "reproducibility_rate": self.reproducibility_rate,
            "category_scores": self.category_scores,
            "disclaimer": self.disclaimer,
            "results_sample": [p.to_dict() for p in self.pair_results[:10]],
        }


class MatchingBenchmarkSuite:
    """
    Executes automated evaluation over the curated 60-pair dataset.
    """

    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = dataset_path or BENCHMARK_DATASET_PATH
        if not os.path.exists(self.dataset_path):
            raise FileNotFoundError(f"Benchmark dataset not found at '{self.dataset_path}'")
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)

    def run_benchmark(self) -> BenchmarkReport:
        """Run all test pairs through deterministic scoring and eligibility engine."""
        pair_results: List[PairResult] = []
        category_stats: Dict[str, Dict[str, int]] = {}

        false_positives = 0
        false_negatives = 0
        disagreement_count = 0
        reproducible_count = 0

        for item in self.dataset:
            pid = item["pair_id"]
            cat = item["category"]
            resume = item["resume"]
            prefs = item["preferences"]
            job_dict = item["job"]
            exp_elig = item["expected_eligibility"]
            exp_min, exp_max = item["expected_score_range"]
            exp_disagree = item.get("expected_disagreement", False)

            # Build NormalizedJob
            raw_emp = job_dict.get("employment_type", "full-time")
            try:
                emp_type = EmploymentType(raw_emp)
            except ValueError:
                emp_type = EmploymentType.OTHER

            job = NormalizedJob(
                stable_id=job_dict["stable_id"],
                source_name="Benchmark",
                source_type=SourceType.MANUAL,
                title=job_dict["title"],
                company=job_dict["company"],
                description=job_dict["description"],
                employment_type=emp_type,
                location=job_dict.get("location", ""),
                country=job_dict.get("country", ""),
                is_remote=job_dict.get("is_remote", False),
                publication_date="2026-01-01T00:00:00",
                application_url="https://example.com/job",
                raw_data=job_dict,
            )

            # 1. Eligibility evaluation
            status, mandatory_failures, elig_expl = EligibilityEngine.evaluate(job, prefs)
            computed_elig = status.value

            # 2. Extract requirements (deterministic heuristics)
            reqs = extract_requirements_heuristic(job.description)

            # 3. Deterministic Python scoring run 1
            breakdown1 = DeterministicFitScorer.calculate_score(
                candidate_profile=resume,
                candidate_preferences=prefs,
                job_title=job.title,
                job_reqs=reqs,
            )
            score1 = breakdown1.overall_score

            # 4. Deterministic Python scoring run 2 (test mathematical consistency)
            breakdown2 = DeterministicFitScorer.calculate_score(
                candidate_profile=resume,
                candidate_preferences=prefs,
                job_title=job.title,
                job_reqs=reqs,
            )
            score2 = breakdown2.overall_score

            is_reproducible = abs(score1 - score2) < 1e-6
            if is_reproducible:
                reproducible_count += 1

            # Check score within expected range (allowing 5-point tolerance on boundaries)
            score_in_range = (exp_min - 5.0) <= score1 <= (exp_max + 5.0)
            exp_elig_clean = exp_elig.lower().strip()
            computed_elig_clean = computed_elig.lower().strip()
            elig_matches = (computed_elig_clean == exp_elig_clean)

            # Check Disagreement (e.g. High technical fit >= 60, but INELIGIBLE)
            is_disagreement = (computed_elig_clean == "ineligible" and score1 >= 60.0)
            if is_disagreement:
                disagreement_count += 1

            # Detect False Positives and False Negatives
            # False Positive: Should have failed eligibility or had low score (<50), but got high score and eligible
            is_fp = (exp_elig_clean == "ineligible" and computed_elig_clean == "eligible") or (exp_max < 50.0 and score1 >= 65.0)
            if is_fp:
                false_positives += 1

            # False Negative: Should have been eligible and high score (>=70), but got low score or marked ineligible
            is_fn = (exp_elig_clean == "eligible" and computed_elig_clean == "ineligible") or (exp_min >= 70.0 and score1 < 50.0)
            if is_fn:
                false_negatives += 1

            passed = (not is_fp) and (not is_fn) and is_reproducible
            if cat == "eligibility_fit_disagreement":
                passed = is_disagreement and is_reproducible

            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "passed": 0}
            category_stats[cat]["total"] += 1
            if passed:
                category_stats[cat]["passed"] += 1

            diag = (
                f"Score={score1:.1f} (exp [{exp_min}, {exp_max}]), "
                f"Elig={computed_elig} (exp {exp_elig}), "
                f"Disagreement={is_disagreement}"
            )

            pair_results.append(
                PairResult(
                    pair_id=pid,
                    category=cat,
                    computed_eligibility=computed_elig,
                    expected_eligibility=exp_elig,
                    computed_score=score1,
                    expected_score_range=(exp_min, exp_max),
                    disagreement_detected=is_disagreement,
                    reproducible=is_reproducible,
                    passed=passed,
                    diagnostic=diag,
                )
            )

        total = len(self.dataset)
        passed_count = sum(1 for p in pair_results if p.passed)

        return BenchmarkReport(
            total_pairs=total,
            passed_pairs=passed_count,
            failed_pairs=total - passed_count,
            false_positives=false_positives,
            false_negatives=false_negatives,
            disagreement_cases=disagreement_count,
            reproducibility_rate=round(reproducible_count / max(1, total) * 100.0, 2),
            category_scores=category_stats,
            pair_results=pair_results,
        )
