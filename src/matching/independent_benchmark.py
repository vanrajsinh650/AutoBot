"""
Independent Matching Benchmark and Quality Evaluator for AutoBot v2.3.1.
Evaluates deterministic scoring, eligibility engine, NDCG@10 ranking quality,
and precision/recall on the independently human-labeled dataset.

Strictly preserves:
1. Deterministic Python scoring formula (0-100).
2. Clean separation between Eligibility (gate) and Fit Score (ranking).
3. Statutory disclaimer: Never describe match scores as hiring probabilities.
"""

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.evaluator import extract_requirements_heuristic
from src.matching.scorer import DISCLAIMER_NOTICE, DeterministicFitScorer, MatchBreakdown

INDEPENDENT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "benchmarks", "independent_eval_dataset.json"
)


@dataclass
class IndependentPairResult:
    pair_id: str
    category: str
    computed_eligibility: str
    expected_eligibility: str
    computed_score: float
    expected_relevance_grade: int
    expected_fit_tier: str
    is_location_conflict: bool
    eligibility_correct: bool
    disagreement_detected: bool
    score_breakdown: Dict[str, float]
    human_notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "category": self.category,
            "computed_eligibility": self.computed_eligibility,
            "expected_eligibility": self.expected_eligibility,
            "computed_score": self.computed_score,
            "expected_relevance_grade": self.expected_relevance_grade,
            "expected_fit_tier": self.expected_fit_tier,
            "is_location_conflict": self.is_location_conflict,
            "eligibility_correct": self.eligibility_correct,
            "disagreement_detected": self.disagreement_detected,
            "score_breakdown": self.score_breakdown,
            "human_notes": self.human_notes,
        }


@dataclass
class IndependentBenchmarkReport:
    total_pairs: int
    passed_pairs: int

    # Eligibility Metrics
    eligibility_tp: int
    eligibility_tn: int
    eligibility_fp: int
    eligibility_fn: int
    eligibility_accuracy: float
    eligibility_precision: float
    eligibility_recall: float
    eligibility_f1: float

    # Ranking & Quality Metrics
    ndcg_at_10: float
    top_10_precision: float
    top_20_precision: float

    # Disagreement & Location Conflict Separation
    location_conflict_cases: int
    location_conflict_verified: int

    # Categories breakdown
    category_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Disclaimer Notice
    disclaimer: str = DISCLAIMER_NOTICE
    pair_results: List[IndependentPairResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pairs": self.total_pairs,
            "passed_pairs": self.passed_pairs,
            "eligibility": {
                "tp": self.eligibility_tp,
                "tn": self.eligibility_tn,
                "fp": self.eligibility_fp,
                "fn": self.eligibility_fn,
                "accuracy": round(self.eligibility_accuracy, 4),
                "precision": round(self.eligibility_precision, 4),
                "recall": round(self.eligibility_recall, 4),
                "f1": round(self.eligibility_f1, 4),
            },
            "ranking": {
                "ndcg_at_10": round(self.ndcg_at_10, 4),
                "top_10_precision": round(self.top_10_precision, 4),
                "top_20_precision": round(self.top_20_precision, 4),
            },
            "location_conflicts": {
                "total": self.location_conflict_cases,
                "properly_separated": self.location_conflict_verified,
            },
            "category_metrics": self.category_metrics,
            "disclaimer": self.disclaimer,
            "sample_results": [r.to_dict() for r in self.pair_results[:8]],
        }


def compute_ndcg_at_k(actual_grades: List[int], k: int = 10) -> float:
    """
    Computes Normalized Discounted Cumulative Gain (NDCG) at rank k.
    Formula: DCG@k / IDCG@k
    where DCG@k = sum((2^rel - 1) / log2(i + 2))
    """
    if not actual_grades:
        return 0.0

    k_eff = min(k, len(actual_grades))

    # Calculate DCG@k
    dcg = 0.0
    for i in range(k_eff):
        rel = actual_grades[i]
        dcg += (math.pow(2, rel) - 1.0) / math.log2(i + 2)

    # Calculate Ideal DCG@k (IDCG@k)
    ideal_grades = sorted(actual_grades, reverse=True)
    idcg = 0.0
    for i in range(k_eff):
        rel = ideal_grades[i]
        idcg += (math.pow(2, rel) - 1.0) / math.log2(i + 2)

    if idcg <= 0.0:
        return 1.0 if dcg <= 0.0 else 0.0

    return dcg / idcg


class IndependentBenchmarkSuite:
    """
    Orchestrates independent evaluation over the human-labeled dataset.
    """

    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = dataset_path or INDEPENDENT_DATASET_PATH
        if not os.path.exists(self.dataset_path):
            raise FileNotFoundError(f"Independent benchmark dataset not found at '{self.dataset_path}'")
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)

    def run_benchmark(self) -> IndependentBenchmarkReport:
        pair_results: List[IndependentPairResult] = []

        # Eligibility confusion matrix
        tp = 0
        tn = 0
        fp = 0
        fn = 0

        loc_conflict_total = 0
        loc_conflict_verified = 0

        category_stats: Dict[str, Dict[str, Any]] = {}

        for item in self.dataset:
            pid = item["pair_id"]
            cat = item["category"]
            resume = item["resume"]
            prefs = item["preferences"]
            job_dict = item["job"]
            gt = item["ground_truth"]

            exp_elig = gt["expected_eligibility"]
            exp_grade = gt["expected_relevance_grade"]
            exp_tier = gt["expected_fit_tier"]
            is_loc_conflict = gt.get("is_location_conflict", False)

            # Build NormalizedJob
            raw_emp = job_dict.get("employment_type", "full-time")
            try:
                emp_type = EmploymentType(raw_emp)
            except ValueError:
                emp_type = EmploymentType.OTHER

            job = NormalizedJob(
                stable_id=job_dict["stable_id"],
                source_name="IndependentBenchmark",
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

            # 1. Eligibility Evaluation
            status, mandatory_failures, elig_expl = EligibilityEngine.evaluate(job, prefs)
            computed_elig = status.value.upper()

            # 2. Extract Requirements
            reqs = extract_requirements_heuristic(job.description)

            # 3. Deterministic Fit Score
            breakdown = DeterministicFitScorer.calculate_score(
                candidate_profile=resume,
                candidate_preferences=prefs,
                job_title=job.title,
                job_reqs=reqs,
            )
            score = breakdown.overall_score

            # Check Eligibility Truth
            is_elig_correct = (computed_elig == exp_elig.upper())
            if exp_elig.upper() == "ELIGIBLE":
                if computed_elig == "ELIGIBLE":
                    tp += 1
                else:
                    fn += 1
            else:
                if computed_elig == "INELIGIBLE":
                    tn += 1
                else:
                    fp += 1

            # Check Disagreement / Location Conflict Separation
            # (High technical fit >= 60, but correctly gated as INELIGIBLE)
            disagree_detected = (computed_elig == "INELIGIBLE" and score >= 60.0)
            if is_loc_conflict:
                loc_conflict_total += 1
                if computed_elig == "INELIGIBLE" and score >= 60.0:
                    loc_conflict_verified += 1

            result = IndependentPairResult(
                pair_id=pid,
                category=cat,
                computed_eligibility=computed_elig,
                expected_eligibility=exp_elig.upper(),
                computed_score=score,
                expected_relevance_grade=exp_grade,
                expected_fit_tier=exp_tier,
                is_location_conflict=is_loc_conflict,
                eligibility_correct=is_elig_correct,
                disagreement_detected=disagree_detected,
                score_breakdown={
                    "overall": score,
                    "required_skills": breakdown.required_skills_score,
                    "responsibilities": breakdown.responsibilities_score,
                    "target_role": breakdown.target_role_score,
                    "experience_edu": breakdown.experience_edu_score,
                    "preferred_skills": breakdown.preferred_skills_score,
                },
                human_notes=gt.get("human_notes", ""),
            )
            pair_results.append(result)

            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "correct_elig": 0, "avg_score": 0.0, "scores": []}
            category_stats[cat]["total"] += 1
            if is_elig_correct:
                category_stats[cat]["correct_elig"] += 1
            category_stats[cat]["scores"].append(score)

        # Finalize category averages
        for cat, stats in category_stats.items():
            scores = stats.pop("scores")
            stats["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0

        # Eligibility summary metrics
        total = len(pair_results)
        elig_acc = (tp + tn) / total if total > 0 else 0.0
        elig_prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        elig_rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        elig_f1 = (2 * elig_prec * elig_rec) / (elig_prec + elig_rec) if (elig_prec + elig_rec) > 0 else 0.0

        # Ranking & NDCG Evaluation:
        # Sort all pairs by computed fit score descending
        ranked_by_score = sorted(pair_results, key=lambda x: x.computed_score, reverse=True)
        ranked_grades = [r.expected_relevance_grade for r in ranked_by_score]

        ndcg_10 = compute_ndcg_at_k(ranked_grades, k=10)

        # Top-10 and Top-20 Precision (grade >= 2 is relevant)
        top_10 = ranked_grades[:10]
        top_10_prec = sum(1 for g in top_10 if g >= 2) / 10.0 if len(top_10) == 10 else 0.0

        top_20 = ranked_grades[:20]
        top_20_prec = sum(1 for g in top_20 if g >= 2) / 20.0 if len(top_20) == 20 else 0.0

        passed_count = sum(1 for r in pair_results if r.eligibility_correct)

        return IndependentBenchmarkReport(
            total_pairs=total,
            passed_pairs=passed_count,
            eligibility_tp=tp,
            eligibility_tn=tn,
            eligibility_fp=fp,
            eligibility_fn=fn,
            eligibility_accuracy=elig_acc,
            eligibility_precision=elig_prec,
            eligibility_recall=elig_rec,
            eligibility_f1=elig_f1,
            ndcg_at_10=ndcg_10,
            top_10_precision=top_10_prec,
            top_20_precision=top_20_prec,
            location_conflict_cases=loc_conflict_total,
            location_conflict_verified=loc_conflict_verified,
            category_metrics=category_stats,
            pair_results=pair_results,
        )
