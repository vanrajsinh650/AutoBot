"""
Comprehensive Job Fit Evaluator for AutoBot v2.
Extracts requirements via LLM/heuristics, evaluates eligibility,
computes deterministic scores in Python, and records tenant-isolated evaluations.
"""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

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
        import os
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("AUTOBOT_OFFLINE") == "1":
            return None
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


DEFAULT_BLACKLIST_KEYWORDS = [
    "senior",
    "sr.",
    "sr",
    "lead",
    "principal",
    "staff",
    "director",
    "vp",
    "avp",
    "head of",
    "head",
    "architect",
    "manager",
    "mgr",
    "chief",
    "ii",
    "iii",
    "iv",
    "v",
    "sde 2",
    "sde-2",
    "sde ii",
    "sde-ii",
    "sde 3",
    "sde-3",
    "sde iii",
    "sde-iii",
    "sde2",
    "sde3",
    "level 2",
    "level ii",
    "l4",
    "l5",
    "l6",
    "3+ years",
    "4+ years",
    "5+ years",
    "6+ years",
    "7+ years",
    "8+ years",
    "10+ years",
    "15+ years",
]

SENIOR_REGEX_PATTERNS = [
    r"\b(senior|sr\.?|lead|principal|staff|director|vp|avp|head of|head|architect|manager|mgr|chief)\b",
    r"\b(ii|iii|iv|v)\b",
    r"\b(l[3-6]|level\s*[2-6]|sde[- ]?[2-4]|sde[2-4]|swe[- ]?[2-4])\b",
    r"\b(engineer|developer|sde|swe|consultant|analyst)\s*[-_]?\s*(2|3|4)\b",
    r"\b([3-9]|1[0-9])\+\s*(years?|yrs?|y)\b",
    r"\b([3-9]|1[0-9])\s*[-–to]+\s*([0-9]+)\s*(years?|yrs?|y)\b",
]


def is_senior_or_blacklisted_title(
    title: str, blacklist_keywords: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Check if a job title contains senior-level keywords, level indicators (II/III/IV/L4/SDE2),
    or user-configured blacklisted terms.
    Uses regex word boundaries for accurate matching without false positives.
    """
    if not title:
        return False, ""
    title_lower = title.lower()

    # 1. Structural regex detection for senior/level indicators
    for pat in SENIOR_REGEX_PATTERNS:
        match = re.search(pat, title_lower)
        if match:
            return True, match.group(0)

    # 2. Check explicit configured blacklist keywords
    keywords = blacklist_keywords
    if keywords is None:
        try:
            from src.utils.config import get_config
            keywords = get_config().blacklist.title_keywords
        except Exception:
            keywords = DEFAULT_BLACKLIST_KEYWORDS

    for kw in (keywords or DEFAULT_BLACKLIST_KEYWORDS):
        clean_kw = kw.strip().lower()
        if not clean_kw:
            continue
        if clean_kw.isalnum():
            if re.search(rf"\b{re.escape(clean_kw)}\b", title_lower):
                return True, kw
        else:
            if clean_kw in title_lower:
                return True, kw
    return False, ""


MAJOR_FOREIGN_TECH_STACKS = {
    "Java / Spring": [r"\bjava\b", r"\bspring\b", r"\bspring ?boot\b", r"\bhibernate\b", r"\bj2ee\b", r"\bjvm\b"],
    ".NET / C#": [r"\b\.net\b", r"(?:\bdotnet\b|\.net(?!\w))", r"(?:\bcsharp\b|\bc#(?!\w))", r"\basp\.net\b", r"\bblazor\b", r"\bwpf\b"],
    "C++": [r"(?:\bcpp\b|\bc\+\+(?!\w))"],
    "PHP": [r"\bphp\b", r"\blaravel\b", r"\bsymfony\b", r"\bcodeigniter\b"],
    "Ruby": [r"\bruby\b", r"\brails\b", r"\bruby on rails\b"],
    "Golang": [r"\bgolang\b", r"\bgo developer\b", r"\bgo engineer\b"],
    "Rust": [r"\brust developer\b", r"\brust engineer\b"],
    "iOS / Swift": [r"\bswift\b", r"\bios developer\b", r"\bswiftui\b"],
    "Android / Kotlin": [r"\bkotlin\b", r"\bandroid developer\b"],
    "Angular": [r"\bangular\b", r"\bangularjs\b"],
    "Salesforce": [r"\bsalesforce\b", r"\bapex\b"],
    "SAP": [r"\bsap\b", r"\babap\b"],
    "Mainframe / COBOL": [r"\bcobol\b", r"\bmainframe\b"],
}


def check_resume_technology_alignment(
    title: str,
    description: str = "",
    candidate_skills: Optional[List[str]] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Ensure the job strictly aligns with technologies explicitly present in the candidate's resume.
    1. If the job requires a foreign tech stack (e.g. Java, .NET, C#, PHP, C++) that the
       candidate does NOT have in their resume, reject it.
    2. If the title is generic (e.g. 'Software Engineer', 'Backend Developer') without explicit tech in title,
       the description MUST explicitly require at least one primary skill from candidate's resume
       (e.g. Python, FastAPI, Django, AI, Playwright, React, etc.). Otherwise, reject it.
    """
    if candidate_skills is None:
        try:
            from src.storage.db import get_candidate_profile, get_job_preferences
            prof = get_candidate_profile(user_id, db_path) or {}
            prefs = get_job_preferences(user_id, db_path) or {}
            candidate_skills = [
                s.lower().strip()
                for s in (
                    (prof.get("technical_skills") or [])
                    + (prof.get("primary_skills") or [])
                    + (prefs.get("primary_skills") or [])
                )
                if s and str(s).strip()
            ]
        except Exception:
            candidate_skills = []

    if not candidate_skills:
        candidate_skills = ["python", "fastapi", "django", "playwright", "rest", "sql", "redis", "typescript", "javascript", "ai"]

    candidate_skills_lower = [s.lower().strip() for s in candidate_skills]
    t_low = (title or "").lower()
    d_low = (description or "").lower()

    # 1. Foreign Tech Stack Rejection
    for stack_name, patterns in MAJOR_FOREIGN_TECH_STACKS.items():
        has_skill_in_resume = any(
            any(re.search(pat, s) for pat in patterns)
            for s in candidate_skills_lower
        )
        if not has_skill_in_resume:
            if any(re.search(pat, t_low) for pat in patterns):
                return False, f"Incompatible tech stack: Job requires {stack_name}, which is not in candidate resume"
            candidate_primary = [s for s in candidate_skills_lower if s in {"python", "fastapi", "django", "playwright", "ai", "react", "typescript", "javascript", "golang", "rust"}]
            if any(re.search(pat, d_low) for pat in patterns):
                has_any_primary = any(re.search(r"\b" + re.escape(p) + r"\b", d_low) for p in candidate_primary)
                if not has_any_primary:
                    return False, f"Incompatible tech stack: Job description requires {stack_name}, not in candidate resume"

    # 2. Generic Title Positive Match Requirement
    generic_titles = {"software engineer", "backend developer", "full stack developer", "software developer", "developer", "engineer", "systems engineer", "cloud developer"}
    clean_title = re.sub(r"[^a-z\s]", "", t_low).strip()
    if clean_title in generic_titles:
        candidate_primary = [s for s in candidate_skills_lower if s in {"python", "fastapi", "django", "playwright", "ai", "react", "typescript", "javascript", "node", "redis", "sql", "postgres", "docker", "selenium"}]
        has_primary = any(
            re.search(r"\b" + re.escape(p) + r"\b", d_low) or re.search(r"\b" + re.escape(p) + r"\b", t_low)
            for p in candidate_primary
        )
        if not has_primary:
            return False, "Generic role without any candidate resume skills (Python, FastAPI, AI, etc.) in job details"

    return True, "Aligned with candidate resume"


def is_job_matching_resume(
    title: str,
    description: str = "",
    candidate_skills: Optional[List[str]] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Master gate: combines seniority check and technology alignment with the candidate's resume.
    """
    is_senior, senior_kw = is_senior_or_blacklisted_title(title)
    if is_senior:
        return False, f"Seniority conflict: '{senior_kw}'"

    return check_resume_technology_alignment(
        title=title,
        description=description,
        candidate_skills=candidate_skills,
        user_id=user_id,
        db_path=db_path,
    )


def evaluate_scraped_job_fit(
    title: str,
    company: str,
    description: str,
    user_id: int = 1,
    db_path: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    preferences: Optional[Dict[str, Any]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Lightweight, fast, deterministic evaluation of any scraped job against the
    candidate's parsed resume and preferences.
    """
    # 1. Seniority / Blacklist check
    is_senior, kw = is_senior_or_blacklisted_title(title)
    if is_senior:
        return {
            "match_score": 0.0,
            "match_percentage": 0,
            "is_senior": True,
            "eligibility_status": "ineligible_seniority",
            "matched_requirements": [],
            "missing_requirements": [f"Seniority conflict: Title contains '{kw}'"],
            "explanation": f"Rejected by blacklist / seniority filter: '{title}' contains '{kw}'",
        }

    # 1.5 Technology Alignment Check
    is_aligned, align_reason = check_resume_technology_alignment(
        title=title,
        description=description,
        user_id=user_id,
        db_path=db_path,
    )
    if not is_aligned:
        return {
            "match_score": 0.0,
            "match_percentage": 0,
            "is_senior": False,
            "eligibility_status": "ineligible_tech_mismatch",
            "matched_requirements": [],
            "missing_requirements": [align_reason],
            "explanation": f"Rejected: {align_reason}",
        }

    # 2. Candidate profile & preferences (use preloaded if provided)
    if profile is None:
        profile = get_candidate_profile(user_id, db_path) or {
            "full_name": "Candidate",
            "technical_skills": [],
            "experience": [],
            "education": [],
        }
    if preferences is None:
        preferences = get_job_preferences(user_id, db_path)
    if evidence is None:
        evidence = get_resume_evidence(user_id, None, db_path)

    # 3. Requirement extraction (heuristics for fast, offline, reliable scoring)
    reqs = extract_requirements_heuristic(description or f"{title} at {company}")

    # 4. Deterministic score calculation
    breakdown = DeterministicFitScorer.calculate_score(
        candidate_profile=profile,
        candidate_preferences=preferences,
        job_title=title,
        job_reqs=reqs,
        resume_evidence=evidence,
    )

    score_fraction = round(max(0.0, min(1.0, breakdown.overall_score / 100.0)), 2)

    return {
        "match_score": score_fraction,
        "match_percentage": int(round(breakdown.overall_score)),
        "is_senior": False,
        "eligibility_status": "eligible",
        "matched_requirements": breakdown.matched_requirements,
        "missing_requirements": breakdown.missing_requirements,
        "explanation": breakdown.explanation,
    }
