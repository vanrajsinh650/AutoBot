"""
Comprehensive Job Fit Evaluator for AutoBot v2.
Extracts requirements via LLM/heuristics, evaluates eligibility,
computes deterministic scores in Python, and records tenant-isolated evaluations.
"""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.discovery.models import NormalizedJob
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.scorer import (
    DISCLAIMER_NOTICE,
    DeterministicFitScorer,
    JobRequirementsExtracted,
    MatchBreakdown,
)
from src.storage.db import (
    get_candidate_profile,
    get_db_connection,
    get_db_path,
    get_job_preferences,
    get_resume_evidence,
    init_db,
)
from src.utils.llm_factory import get_llm
from src.utils.logger import logger


COMMON_TECH_KEYWORDS = [
    "Python", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Java", "C++", "C#",
    "SQL", "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Elasticsearch", "Qdrant",
    "FastAPI", "Flask", "Django", "React", "Next.js", "Vue", "Node.js", "Express",
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "Terraform", "CI/CD", "Git",
    "REST", "GraphQL", "gRPC", "Kafka", "RabbitMQ", "Linux", "Microservices"
]


def extract_requirements_heuristic(description: str) -> JobRequirementsExtracted:
    """Extract job requirements using deterministic text heuristics."""
    desc_lower = f" {description.lower()} "
    found_skills = []
    for skill in COMMON_TECH_KEYWORDS:
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, desc_lower):
            # Negation guard: Check for phrases like "no python", "without java", "not required", "strictly not used"
            neg_pattern = (
                rf"\b(?:no|not|without|never|avoid|strictly no)\b[^.\n]{{0,35}}\b{re.escape(skill.lower())}\b|"
                rf"\b{re.escape(skill.lower())}\b[^.\n]{{0,35}}\b(?:not required|not needed|not used|never used|strictly not used|not accepted|prohibited)\b"
            )
            if re.search(neg_pattern, desc_lower):
                continue
            found_skills.append(skill)

    # Years of experience heuristic (e.g. '3+ years', '5 years of experience')
    exp_matches = re.findall(r"(\d+)\+?\s*years?(?:\s+of)?\s+experience", desc_lower)
    min_years = float(exp_matches[0]) if exp_matches else 0.0

    # Extract lines looking like responsibilities
    resp_lines = []
    for line in description.splitlines():
        clean = line.strip().lstrip("-•* ")
        if clean and any(clean.lower().startswith(v) for v in ["build", "design", "develop", "lead", "collaborate", "architect", "maintain", "scale"]):
            resp_lines.append(clean)

    req_skills = found_skills[:8]
    pref_skills = found_skills[8:]

    return JobRequirementsExtracted(
        required_skills=req_skills,
        preferred_skills=pref_skills,
        responsibilities=resp_lines[:6],
        min_years_experience=min_years,
        required_degree="bachelor" if "bachelor" in desc_lower or "degree" in desc_lower else "",
    )


def extract_requirements_llm(
    description: str,
    llm: BaseChatModel,
) -> JobRequirementsExtracted:
    """Use LLM solely to parse requirements from raw text into structured schema."""
    prompt = (
        "Analyze the following job description and extract requirements into JSON with fields:\n"
        "- required_skills: list of mandatory technical skills\n"
        "- preferred_skills: list of nice-to-have skills\n"
        "- responsibilities: list of key job duties (max 6)\n"
        "- min_years_experience: number of minimum years required (float, 0 if not specified)\n"
        "- required_degree: string if a degree is required, else empty string\n\n"
        f"Job Description:\n{description[:3000]}\n\n"
        "Return ONLY a JSON object."
    )
    try:
        response = llm.invoke([
            SystemMessage(content="You are an expert ATS requirement extractor. Extract requirements accurately without fabricating anything. Return JSON only."),
            HumanMessage(content=prompt),
        ])
        content_str = response.content if isinstance(response.content, str) else str(response.content)
        clean_json = re.sub(r"^```(?:json)?\s*", "", content_str.strip())
        clean_json = re.sub(r"\s*```$", "", clean_json)
        data = json.loads(clean_json)

        return JobRequirementsExtracted(
            required_skills=[str(s) for s in data.get("required_skills", [])],
            preferred_skills=[str(s) for s in data.get("preferred_skills", [])],
            responsibilities=[str(r) for r in data.get("responsibilities", [])],
            min_years_experience=float(data.get("min_years_experience", 0.0)),
            required_degree=str(data.get("required_degree", "")),
        )
    except Exception as e:
        logger.debug(f"LLM requirement extraction fallback to heuristics: {e}")
        return extract_requirements_heuristic(description)


class JobFitEvaluator:
    """
    Evaluates jobs for a specific tenant and stores full diagnostic records.
    """

    def __init__(self, db_path: Optional[str] = None, llm: Optional[BaseChatModel] = None):
        self.db_path = db_path or get_db_path()
        self._llm = llm

    def _get_llm(self) -> Optional[BaseChatModel]:
        if self._llm is not None:
            return self._llm
        try:
            self._llm = get_llm(temperature=0.0)
            return self._llm
        except Exception:
            return None

    def evaluate_job(
        self,
        user_id: int,
        job: NormalizedJob,
        resume_version_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Perform complete evaluation:
        1. Check eligibility (employment type & country).
        2. Extract requirements (LLM or heuristic).
        3. Deterministically compute 0–100 Resume Fit Score in Python.
        4. Persist to match_evaluations table with user_id.
        """
        init_db(self.db_path)

        profile = get_candidate_profile(user_id, self.db_path) or {
            "full_name": "Candidate",
            "technical_skills": [],
            "experience": [],
            "education": [],
        }
        preferences = get_job_preferences(user_id, self.db_path)
        evidence = get_resume_evidence(user_id, resume_version_id, self.db_path)

        # 1. Eligibility Check
        status, mandatory_failures, elig_explanation = EligibilityEngine.evaluate(job, preferences)

        # 2. Requirement Extraction (LLM used only for extraction)
        llm_model = self._get_llm()
        if llm_model:
            reqs = extract_requirements_llm(job.description, llm_model)
        else:
            reqs = extract_requirements_heuristic(job.description)

        # 3. Deterministic Python Scoring
        breakdown = DeterministicFitScorer.calculate_score(
            candidate_profile=profile,
            candidate_preferences=preferences,
            job_title=job.title,
            job_reqs=reqs,
            resume_evidence=evidence,
        )

        full_explanation = f"{elig_explanation} {breakdown.explanation} {DISCLAIMER_NOTICE}"

        # 4. Save to match_evaluations
        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            # Find job internal ID in SQLite or insert job if not present
            job_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (job.stable_id,)).fetchone()
            if not job_row:
                emp_type = job.employment_type.value if hasattr(job.employment_type, "value") else str(job.employment_type)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs (
                        stable_id, source_name, title, company, description,
                        employment_type, location, country, is_remote, salary_info,
                        publication_date, application_url, raw_data, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        job.stable_id,
                        job.source_name,
                        job.title,
                        job.company,
                        job.description,
                        emp_type,
                        job.location or "",
                        getattr(job, "country", "") or "",
                        1 if job.is_remote else 0,
                        job.salary_info or "",
                        job.publication_date or "",
                        job.application_url or "",
                        job.fingerprint or job.stable_id,
                        now,
                    ),
                )
                conn.commit()
                job_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (job.stable_id,)).fetchone()
            job_internal_id = job_row["id"] if job_row else 1

            cur = conn.execute(
                """
                INSERT INTO match_evaluations (
                    user_id, job_id, resume_version_id, eligibility_status, overall_score,
                    required_skills_score, responsibilities_score, target_role_score,
                    experience_edu_score, preferred_skills_score, matched_requirements,
                    missing_requirements, evidence_references, mandatory_failures,
                    explanation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    job_internal_id,
                    resume_version_id,
                    status.value,
                    breakdown.overall_score,
                    breakdown.required_skills_score,
                    breakdown.responsibilities_score,
                    breakdown.target_role_score,
                    breakdown.experience_edu_score,
                    breakdown.preferred_skills_score,
                    json.dumps(breakdown.matched_requirements),
                    json.dumps(breakdown.missing_requirements),
                    json.dumps(breakdown.evidence_references),
                    json.dumps(mandatory_failures),
                    full_explanation,
                    now,
                ),
            )
            eval_id = cur.lastrowid
            conn.commit()

        return {
            "id": eval_id,
            "user_id": user_id,
            "job_stable_id": job.stable_id,
            "job_title": job.title,
            "company": job.company,
            "eligibility_status": status.value,
            "overall_score": breakdown.overall_score,
            "required_skills_score": breakdown.required_skills_score,
            "responsibilities_score": breakdown.responsibilities_score,
            "target_role_score": breakdown.target_role_score,
            "experience_edu_score": breakdown.experience_edu_score,
            "preferred_skills_score": breakdown.preferred_skills_score,
            "matched_requirements": breakdown.matched_requirements,
            "missing_requirements": breakdown.missing_requirements,
            "evidence_references": breakdown.evidence_references,
            "mandatory_failures": mandatory_failures,
            "explanation": full_explanation,
            "disclaimer": DISCLAIMER_NOTICE,
        }
