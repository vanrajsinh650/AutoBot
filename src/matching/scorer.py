"""
Deterministic 0–100 Resume Fit Scorer for AutoBot v2.
Calculates objective match scores purely in Python:
- Required skill coverage: 35%
- Responsibilities: 25%
- Target role alignment: 15%
- Experience and education: 15%
- Preferred skills: 10%

Never fabricates candidate experience or credentials.
Never presents score as real ATS score or hiring probability.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple


DISCLAIMER_NOTICE = (
    "NOTICE: This deterministic Fit Score is an automated heuristic qualification estimate "
    "calculated by AutoBot to assist the candidate in triaging job applications. "
    "It is NOT a hiring probability, candidate ranking guarantee, or proprietary ATS score."
)


SKILL_ALIASES: Dict[str, str] = {
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "kubernetes": "kubernetes",
    "py": "python",
    "python": "python",
    "python3": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "go": "golang",
    "golang": "golang",
    "react": "react",
    "reactjs": "react",
    "react.js": "react",
    "node": "nodejs",
    "nodejs": "nodejs",
    "node.js": "nodejs",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "aws": "amazon web services",
    "amazon web services": "amazon web services",
    "gcp": "google cloud",
    "google cloud": "google cloud",
    "google cloud platform": "google cloud",
    "tf": "terraform",
    "terraform": "terraform",
    "docker": "docker",
    "ci/cd": "cicd",
    "cicd": "cicd",
}


def normalize_skill(skill: str) -> str:
    """Normalize skill name to standard canonical identifier."""
    clean = skill.lower().strip()
    return SKILL_ALIASES.get(clean, clean)


@dataclass
class JobRequirementsExtracted:
    """Requirements extracted from job description (via LLM or heuristics)."""
    required_skills: List[str] = field(default_factory=list)
    preferred_skills: List[str] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)
    min_years_experience: float = 0.0
    required_degree: str = ""


@dataclass
class MatchBreakdown:
    overall_score: float
    required_skills_score: float
    responsibilities_score: float
    target_role_score: float
    experience_edu_score: float
    preferred_skills_score: float
    matched_requirements: List[str]
    missing_requirements: List[str]
    evidence_references: List[Dict[str, Any]]
    explanation: str


class DeterministicFitScorer:
    """
    Computes exact, transparent fit scores using Python arithmetic.
    """

    WEIGHT_REQUIRED_SKILLS = 0.35
    WEIGHT_RESPONSIBILITIES = 0.25
    WEIGHT_TARGET_ROLE = 0.15
    WEIGHT_EXPERIENCE_EDU = 0.15
    WEIGHT_PREFERRED_SKILLS = 0.10

    @staticmethod
    def _skill_matches(target_skill: str, candidate_skill: str) -> bool:
        """
        Check if a candidate skill matches a required/preferred skill.
        Supports canonical skill aliases (e.g. k8s <-> kubernetes, postgres <-> postgresql),
        exact matches, and word-boundary substring matches.
        Prevents single letters (e.g. 'C', 'R') from matching arbitrary words (e.g. 'Docker', 'React').
        """
        ts = target_skill.lower().strip()
        cs = candidate_skill.lower().strip()
        if ts == cs:
            return True

        # Check canonical aliases
        norm_ts = normalize_skill(ts)
        norm_cs = normalize_skill(cs)
        if norm_ts == norm_cs:
            return True

        if len(cs) <= 2 or len(ts) <= 2:
            return ts == cs
        # Word boundary matching
        pattern = r"\b" + re.escape(cs) + r"\b"
        if re.search(pattern, ts):
            return True
        pattern_rev = r"\b" + re.escape(ts) + r"\b"
        if re.search(pattern_rev, cs):
            return True
        return False

    @classmethod
    def calculate_score(
        cls,
        candidate_profile: Dict[str, Any],
        candidate_preferences: Dict[str, Any],
        job_title: str,
        job_reqs: JobRequirementsExtracted,
        resume_evidence: Optional[List[Dict[str, Any]]] = None,
    ) -> MatchBreakdown:
        """
        Calculate deterministic composite score (0.0 to 100.0).
        """
        matched_requirements: List[str] = []
        missing_requirements: List[str] = []
        evidence_references: List[Dict[str, Any]] = []

        # Candidate skills
        candidate_skills_raw = (
            candidate_profile.get("technical_skills", [])
            + candidate_profile.get("primary_skills", [])
            + candidate_profile.get("secondary_skills", [])
        )
        candidate_skills_set = {s.lower().strip() for s in candidate_skills_raw if s.strip()}
        candidate_skills_list = list(candidate_skills_set)

        # ── 1. Required Skill Coverage (35%) ─────────────────────────
        required_skills = [s.strip() for s in job_reqs.required_skills if s.strip()]
        if required_skills:
            matched_req = []
            missing_req = []
            for skill in required_skills:
                if any(cls._skill_matches(skill, cs) for cs in candidate_skills_set):
                    matched_req.append(skill)
                    matched_requirements.append(f"Required Skill: {skill}")
                else:
                    missing_req.append(skill)
                    missing_requirements.append(f"Missing Required Skill: {skill}")

            req_ratio = len(matched_req) / len(required_skills)
            required_skills_score = round(req_ratio * 100.0, 2)
        else:
            # Check overlap between candidate skills and job title / responsibilities
            job_context = f"{job_title} {' '.join(job_reqs.responsibilities)}".lower()
            overlap_count = 0
            for cs in candidate_skills_set:
                if len(cs) <= 2:
                    if re.search(r"\b" + re.escape(cs) + r"\b", job_context):
                        overlap_count += 1
                elif cs in job_context:
                    overlap_count += 1

            if candidate_skills_set and overlap_count > 0:
                required_skills_score = round(min(1.0, overlap_count / max(1, len(candidate_skills_list[:5]))) * 100.0, 2)
            elif candidate_skills_set and overlap_count == 0:
                required_skills_score = 10.0
                missing_requirements.append("No technical skill overlap found with job description")
            else:
                required_skills_score = 30.0

        # ── 2. Responsibilities Alignment (25%) ───────────────────────
        responsibilities = [r.strip() for r in job_reqs.responsibilities if r.strip()]
        candidate_exp_texts = []
        for exp in candidate_profile.get("experience", []):
            if isinstance(exp, dict):
                candidate_exp_texts.extend(exp.get("bullets", []))
                candidate_exp_texts.append(exp.get("role", ""))
                candidate_exp_texts.append(exp.get("company", ""))
            elif isinstance(exp, str):
                candidate_exp_texts.append(exp)

        exp_corpus = " ".join(candidate_exp_texts).lower()

        if responsibilities and exp_corpus:
            resp_matched = 0
            for resp in responsibilities:
                # Find key verb/noun words in responsibility
                words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", resp.lower()) if w not in {"with", "that", "this", "from", "have", "will"}]
                if words:
                    overlap = sum(1 for w in words if w in exp_corpus)
                    if overlap / len(words) >= 0.35:
                        resp_matched += 1
                        matched_requirements.append(f"Responsibility Experience: {resp[:60]}...")
                    else:
                        missing_requirements.append(f"Uncovered Responsibility: {resp[:60]}...")
            resp_ratio = resp_matched / len(responsibilities)
            responsibilities_score = round(resp_ratio * 100.0, 2)
        elif not responsibilities:
            responsibilities_score = 80.0 if exp_corpus else 40.0
        else:
            responsibilities_score = 30.0

        # ── 3. Target Role Alignment (15%) ───────────────────────────
        target_roles = [r.lower().strip() for r in candidate_preferences.get("target_roles", []) if r.strip()]
        if not target_roles:
            target_roles = [candidate_profile.get("headline", "").lower().strip() or "software engineer"]

        job_title_clean = job_title.lower().strip()
        job_tokens = set(re.findall(r"\b[a-z]{3,}\b", job_title_clean))

        best_role_overlap = 0.0
        for target in target_roles:
            target_tokens = set(re.findall(r"\b[a-z]{3,}\b", target))
            if not target_tokens:
                continue
            common = job_tokens.intersection(target_tokens)
            overlap = len(common) / len(target_tokens)
            if overlap > best_role_overlap:
                best_role_overlap = overlap

        target_role_score = round(min(1.0, best_role_overlap * 1.2) * 100.0, 2)
        if target_role_score >= 60.0:
            matched_requirements.append(f"Role Title Alignment: '{job_title}' aligns with candidate target roles")
        else:
            missing_requirements.append(f"Role Title Variance: '{job_title}' differs from target roles ({', '.join(target_roles)})")

        # ── 4. Experience & Education (15%) ───────────────────────────
        # Estimate candidate years of experience from experience records
        candidate_years = 0.0
        for exp in candidate_profile.get("experience", []):
            candidate_years += 1.5  # average default per documented role
        if candidate_years == 0 and candidate_profile.get("headline"):
            candidate_years = 2.0

        required_years = job_reqs.min_years_experience
        if required_years > 0:
            if candidate_years >= required_years:
                exp_score = 100.0
                matched_requirements.append(f"Experience Level: {candidate_years:.1f} yrs exceeds required {required_years:.1f} yrs")
            else:
                ratio = candidate_years / required_years
                exp_score = max(30.0, ratio * 100.0)
                missing_requirements.append(f"Experience Gap: Candidate ~{candidate_years:.1f} yrs vs required {required_years:.1f} yrs")
        else:
            exp_score = 90.0

        # Degree check
        edu_list = candidate_profile.get("education", [])
        if job_reqs.required_degree and edu_list:
            matched_requirements.append(f"Education: Candidate holds degrees ({len(edu_list)} records on file)")
            edu_score = 100.0
        elif not job_reqs.required_degree:
            edu_score = 90.0
        else:
            edu_score = 60.0

        experience_edu_score = round((exp_score * 0.6) + (edu_score * 0.4), 2)

        # ── 5. Preferred Skills (10%) ─────────────────────────────────
        pref_skills = [s.strip() for s in job_reqs.preferred_skills if s.strip()]
        if pref_skills:
            matched_pref = []
            for ps in pref_skills:
                if any(cls._skill_matches(ps, cs) for cs in candidate_skills_set):
                    matched_pref.append(ps)
                    matched_requirements.append(f"Preferred Skill Match: {ps}")
                else:
                    missing_requirements.append(f"Missing Preferred Skill: {ps}")
            pref_ratio = len(matched_pref) / len(pref_skills)
            preferred_skills_score = round(pref_ratio * 100.0, 2)
        else:
            preferred_skills_score = 80.0

        # ── Composite Overall Score (0–100) ───────────────────────────
        overall = (
            (required_skills_score * cls.WEIGHT_REQUIRED_SKILLS)
            + (responsibilities_score * cls.WEIGHT_RESPONSIBILITIES)
            + (target_role_score * cls.WEIGHT_TARGET_ROLE)
            + (experience_edu_score * cls.WEIGHT_EXPERIENCE_EDU)
            + (preferred_skills_score * cls.WEIGHT_PREFERRED_SKILLS)
        )
        overall_score = round(max(0.0, min(100.0, overall)), 2)

        # Generate evidence references from actual profile chunks
        if resume_evidence:
            for ev in resume_evidence[:4]:
                evidence_references.append({
                    "section": ev.get("section", ""),
                    "excerpt": ev.get("content", "")[:120],
                })
        else:
            # Generate from candidate profile sections
            for exp in candidate_profile.get("experience", [])[:2]:
                if isinstance(exp, dict) and exp.get("role"):
                    evidence_references.append({
                        "section": "experience",
                        "excerpt": f"{exp.get('role')} at {exp.get('company')}",
                    })

        explanation = (
            f"Overall Resume Fit Score: {overall_score:.1f}/100. "
            f"Required Skills: {required_skills_score:.1f}% (weight 35%), "
            f"Responsibilities: {responsibilities_score:.1f}% (weight 25%), "
            f"Target Role: {target_role_score:.1f}% (weight 15%), "
            f"Experience & Edu: {experience_edu_score:.1f}% (weight 15%), "
            f"Preferred Skills: {preferred_skills_score:.1f}% (weight 10%)."
        )

        return MatchBreakdown(
            overall_score=overall_score,
            required_skills_score=required_skills_score,
            responsibilities_score=responsibilities_score,
            target_role_score=target_role_score,
            experience_edu_score=experience_edu_score,
            preferred_skills_score=preferred_skills_score,
            matched_requirements=matched_requirements,
            missing_requirements=missing_requirements,
            evidence_references=evidence_references,
            explanation=explanation,
        )
