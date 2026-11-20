"""
Personalized Keyword Expansion and Search Engine for AutoBot v2.3.
Expands candidate technical skills and target roles into industry synonyms,
distinguishes employment types (internships vs full-time), and provides
transparent, explainable, and editable search query expansions.
"""

from dataclasses import dataclass, field
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from src.discovery.models import EmploymentType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.storage.db import (
    get_candidate_profile,
    get_db_connection,
    get_db_path,
    get_job_preferences,
    init_db,
)
from src.utils.logger import logger


# Curated, domain-specific skill and role taxonomy
SKILL_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "python": {
        "synonyms": ["python3", "py"],
        "related_frameworks": ["fastapi", "django", "flask", "pydantic", "sqlalchemy"],
        "related_roles": ["python developer", "backend engineer", "software engineer"],
        "domain": "programming_language",
    },
    "ai": {
        "synonyms": ["artificial intelligence", "genai", "generative ai", "foundation models"],
        "related_frameworks": ["langchain", "langgraph", "llamaindex", "transformers", "openai"],
        "related_roles": ["ai engineer", "ai developer", "applied ai engineer", "llm engineer"],
        "domain": "artificial_intelligence",
    },
    "machine learning": {
        "synonyms": ["ml", "deep learning", "dl"],
        "related_frameworks": ["pytorch", "tensorflow", "scikit-learn", "keras"],
        "related_roles": ["machine learning engineer", "ml engineer", "mlops engineer", "data scientist"],
        "domain": "artificial_intelligence",
    },
    "java": {
        "synonyms": ["java 17", "java 21", "jvm", "core java"],
        "related_frameworks": ["spring", "spring boot", "hibernate", "micronaut", "quarkus"],
        "related_roles": ["java developer", "backend engineer", "enterprise software engineer"],
        "domain": "programming_language",
    },
    "javascript": {
        "synonyms": ["js", "ecmascript"],
        "related_frameworks": ["react", "node.js", "express", "vue", "next.js"],
        "related_roles": ["frontend engineer", "full stack engineer", "web developer"],
        "domain": "web_development",
    },
    "typescript": {
        "synonyms": ["ts"],
        "related_frameworks": ["react", "next.js", "nest.js", "node.js", "remix"],
        "related_roles": ["frontend engineer", "full stack engineer", "software engineer"],
        "domain": "web_development",
    },
    "react": {
        "synonyms": ["react.js", "reactjs"],
        "related_frameworks": ["next.js", "redux", "tailwind", "zustand"],
        "related_roles": ["frontend engineer", "ui engineer", "react developer"],
        "domain": "web_development",
    },
    "cloud": {
        "synonyms": ["aws", "gcp", "azure", "cloud infrastructure"],
        "related_frameworks": ["terraform", "docker", "kubernetes", "helm"],
        "related_roles": ["devops engineer", "platform engineer", "sre", "cloud engineer"],
        "domain": "infrastructure",
    },
    "kubernetes": {
        "synonyms": ["k8s"],
        "related_frameworks": ["docker", "helm", "istio", "argocd", "terraform"],
        "related_roles": ["devops engineer", "sre", "platform engineer", "infrastructure engineer"],
        "domain": "infrastructure",
    },
    "data engineering": {
        "synonyms": ["etl", "data pipelines", "big data"],
        "related_frameworks": ["apache spark", "airflow", "snowflake", "dbt", "kafka", "sql"],
        "related_roles": ["data engineer", "analytics engineer", "big data developer"],
        "domain": "data",
    },
    "security": {
        "synonyms": ["infosec", "cybersecurity", "appsec"],
        "related_frameworks": ["iam", "oauth", "penetration testing", "owasp", "siem"],
        "related_roles": ["security engineer", "application security engineer", "cloud security engineer"],
        "domain": "security",
    },
}

ROLE_TAXONOMY: Dict[str, List[str]] = {
    "software engineer": ["software developer", "full stack engineer", "backend developer", "core engineer"],
    "backend engineer": ["backend developer", "systems engineer", "api engineer", "server engineer"],
    "frontend engineer": ["frontend developer", "ui engineer", "web engineer", "client engineer"],
    "ai engineer": ["applied ai engineer", "llm engineer", "machine learning engineer", "ai developer"],
    "data engineer": ["analytics engineer", "data platform engineer", "etl developer"],
    "devops engineer": ["site reliability engineer", "sre", "platform engineer", "infrastructure engineer"],
}


@dataclass
class KeywordExplanation:
    source_term: str
    expanded_term: str
    relation_type: str  # synonym, framework, related_role, employment_tier
    justification: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "source_term": self.source_term,
            "expanded_term": self.expanded_term,
            "relation_type": self.relation_type,
            "justification": self.justification,
        }


@dataclass
class ExpansionResult:
    user_id: int
    original_skills: List[str]
    target_roles: List[str]
    expanded_keywords: List[str]
    explanations: List[KeywordExplanation]
    employment_filters: List[str]
    workplace_filters: List[str]
    eligible_countries: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "original_skills": self.original_skills,
            "target_roles": self.target_roles,
            "expanded_keywords": self.expanded_keywords,
            "explanations": [e.to_dict() for e in self.explanations],
            "employment_filters": self.employment_filters,
            "workplace_filters": self.workplace_filters,
            "eligible_countries": self.eligible_countries,
        }


def expand_candidate_keywords(
    user_id: int,
    db_path: Optional[str] = None,
    manual_overrides: Optional[List[str]] = None,
) -> ExpansionResult:
    """
    Generate explainable keyword expansion for a tenant user based on their
    profile and job preferences.
    """
    prefs = get_job_preferences(user_id, db_path)
    profile = get_candidate_profile(user_id, db_path)

    primary_skills = [str(s).strip() for s in prefs.get("primary_skills", []) if str(s).strip()]
    secondary_skills = [str(s).strip() for s in prefs.get("secondary_skills", []) if str(s).strip()]
    target_roles = [str(r).strip() for r in prefs.get("target_roles", []) if str(r).strip()]

    # Supplement with candidate_profile technical skills if preferences empty
    if not primary_skills and profile and profile.get("technical_skills"):
        prof_skills = profile.get("technical_skills", [])
        if isinstance(prof_skills, list):
            primary_skills = [str(s).strip() for s in prof_skills[:10] if str(s).strip()]

    all_raw_skills = list(dict.fromkeys(primary_skills + secondary_skills))

    expanded_set: Set[str] = set()
    explanations: List[KeywordExplanation] = []

    # 1. Expand technical skills using taxonomy
    for skill in all_raw_skills:
        s_low = skill.lower().strip()
        expanded_set.add(s_low)

        # Check exact or partial match in taxonomy
        found_entry = None
        for tax_key, entry in SKILL_TAXONOMY.items():
            if s_low == tax_key or s_low in entry.get("synonyms", []):
                found_entry = (tax_key, entry)
                break

        if found_entry:
            tax_key, entry = found_entry
            for syn in entry.get("synonyms", []):
                if syn not in expanded_set:
                    expanded_set.add(syn)
                    explanations.append(
                        KeywordExplanation(
                            source_term=skill,
                            expanded_term=syn,
                            relation_type="synonym",
                            justification=f"Direct industry synonym or abbreviation for {skill}",
                        )
                    )
            for fw in entry.get("related_frameworks", []):
                if fw not in expanded_set:
                    expanded_set.add(fw)
                    explanations.append(
                        KeywordExplanation(
                            source_term=skill,
                            expanded_term=fw,
                            relation_type="framework",
                            justification=f"Commonly paired technical stack/tool with {skill}",
                        )
                    )
            for rr in entry.get("related_roles", []):
                if rr not in expanded_set:
                    expanded_set.add(rr)
                    explanations.append(
                        KeywordExplanation(
                            source_term=skill,
                            expanded_term=rr,
                            relation_type="related_role",
                            justification=f"Job title commonly requiring proficiency in {skill}",
                        )
                    )

    # 2. Expand target roles
    for role in target_roles:
        r_low = role.lower().strip()
        expanded_set.add(r_low)
        for tax_role, syns in ROLE_TAXONOMY.items():
            if tax_role in r_low or r_low in tax_role:
                for syn in syns:
                    if syn not in expanded_set:
                        expanded_set.add(syn)
                        explanations.append(
                            KeywordExplanation(
                                source_term=role,
                                expanded_term=syn,
                                relation_type="role_synonym",
                                justification=f"Equivalent occupational title for {role}",
                            )
                        )

    # 3. Employment type classification adjustments
    emp_types = [str(e).lower().strip() for e in prefs.get("employment_types", ["full-time"])]
    if any(e in ["intern", "internship"] for e in emp_types):
        intern_terms = ["intern", "internship", "co-op", "working student"]
        for term in intern_terms:
            if term not in expanded_set:
                expanded_set.add(term)
                explanations.append(
                    KeywordExplanation(
                        source_term="internship preference",
                        expanded_term=term,
                        relation_type="employment_tier",
                        justification="Explicitly requested internship / early-career vacancy tier",
                    )
                )

    # 4. Integrate manual overrides if candidate provided them
    if manual_overrides:
        for mo in manual_overrides:
            mo_clean = str(mo).lower().strip()
            if mo_clean and mo_clean not in expanded_set:
                expanded_set.add(mo_clean)
                explanations.append(
                    KeywordExplanation(
                        source_term="candidate_manual_override",
                        expanded_term=mo_clean,
                        relation_type="manual_override",
                        justification="Candidate explicitly added custom search keyword",
                    )
                )

    workplace_pref = str(prefs.get("work_arrangement", "remote")).lower().strip()
    workplace_filters = [workplace_pref]
    if workplace_pref == "remote":
        workplace_filters.append("hybrid")  # allow hybrid consideration

    # Prioritize: core target roles and primary skills first, then synonyms, then other expanded terms
    prioritized_keywords = []
    seen = set()
    for term in (manual_overrides or []) + target_roles + primary_skills:
        tc = term.lower().strip()
        if tc in expanded_set and tc not in seen:
            prioritized_keywords.append(tc)
            seen.add(tc)
    for term in sorted(list(expanded_set)):
        if term not in seen:
            prioritized_keywords.append(term)
            seen.add(term)

    return ExpansionResult(
        user_id=user_id,
        original_skills=all_raw_skills,
        target_roles=target_roles,
        expanded_keywords=prioritized_keywords,
        explanations=explanations,
        employment_filters=emp_types,
        workplace_filters=workplace_filters,
        eligible_countries=prefs.get("eligible_countries", []),
    )


def _build_regex_boundary_pattern(term: str) -> str:
    """Build regex pattern enforcing word boundaries at alphanumeric edges to prevent substring collisions."""
    clean = term.strip()
    escaped = re.escape(clean)
    start_b = r"\b" if re.match(r"^\w", clean) else ""
    end_b = r"\b" if re.match(r".*\w$", clean) else r"(?:\s|$|[^a-zA-Z0-9])"
    return f"{start_b}{escaped}{end_b}"


def search_personalized_jobs(
    user_id: int,
    db_path: Optional[str] = None,
    manual_keywords: Optional[List[str]] = None,
    status_filter: str = "active",
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Search jobs strictly scoped to candidate preferences, tenant isolation,
    and keyword expansion with word-boundary precision.
    """
    db_file = db_path or get_db_path()
    init_db(db_file)

    expansion = expand_candidate_keywords(user_id, db_file, manual_overrides=manual_keywords)
    prefs = get_job_preferences(user_id, db_file)

    with get_db_connection(db_file) as conn:
        # Build query
        query = "SELECT * FROM jobs WHERE 1=1"
        params: List[Any] = []

        # 1. Status filter (defaults to active, strictly suppresses expired and stale listings)
        if status_filter != "all":
            query += " AND status = ?"
            params.append(status_filter)

        # 2. Employment type filter (strictly separates internships, full-time, contract, part-time)
        if expansion.employment_filters:
            placeholders = ",".join("?" for _ in expansion.employment_filters)
            query += f" AND (employment_type IN ({placeholders}) OR employment_type = 'other')"
            params.extend(expansion.employment_filters)

        # 3. Country / Location eligibility filter (respects remote vs country restrictions)
        countries = [c.lower().strip() for c in expansion.eligible_countries if c.strip()]
        if countries:
            country_clauses = ["is_remote = 1", "country = ''"]
            for c in countries:
                country_clauses.append("LOWER(country) = ?")
                params.append(c)
            query += f" AND ({' OR '.join(country_clauses)})"

        # 4. Workplace filter
        if "remote" in expansion.workplace_filters:
            query += " AND (is_remote = 1 OR workplace_type IN ('remote', 'hybrid'))"

        # 5. Keywords matching using boundary-aware regex to prevent substring false positives
        if expansion.expanded_keywords:
            kw_clauses = []
            for kw in expansion.expanded_keywords[:15]:  # top 15 prioritized keywords
                pattern = _build_regex_boundary_pattern(kw)
                kw_clauses.append("(title REGEXP ? OR description REGEXP ?)")
                params.extend([pattern, pattern])
            if kw_clauses:
                query += f" AND ({' OR '.join(kw_clauses)})"

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        jobs = [dict(r) for r in rows]

    return {
        "user_id": user_id,
        "total_results": len(jobs),
        "expansion": expansion.to_dict(),
        "jobs": jobs,
    }


def resolve_search_keywords(
    user_provided: Optional[Union[str, List[str]]] = None,
    user_id: int = 1,
    max_keywords: int = 5,
    db_path: Optional[str] = None,
) -> Tuple[List[str], str]:
    """
    Resolve search keywords prioritizing:
      1. User-provided keywords (from UI input, CLI args, or API request payload).
      2. Deep resume analysis (analyzing candidate profile, primary skills, summary, and target roles).

    Returns:
      (keywords_list, origin_description)
      where origin_description is either 'user_provided' or 'deep_resume_analysis'.
    """
    # ── 1. Check User-Provided Keywords ──
    if user_provided:
        if isinstance(user_provided, str):
            parts = [p.strip() for p in re.split(r"[,;|\n]", user_provided) if p.strip()]
        elif isinstance(user_provided, (list, tuple, set)):
            parts = [str(p).strip() for p in user_provided if str(p).strip()]
        else:
            parts = []

        # Filter out empty or placeholder strings
        cleaned = [p for p in parts if p and p.lower() not in {"none", "null", "all"}]
        if cleaned:
            return cleaned[:max_keywords], "user_provided"

    # ── 2. Deep Resume & Profile Analysis ──
    try:
        profile = get_candidate_profile(user_id, db_path) or {}
    except Exception as e:
        logger.debug(f"Could not load candidate profile for keyword extraction: {e}")
        profile = {}

    try:
        prefs = get_job_preferences(user_id, db_path) or {}
    except Exception as e:
        logger.debug(f"Could not load job preferences for keyword extraction: {e}")
        prefs = {}

    # Gather raw technical skills from preferences & profile
    raw_skills: List[str] = []
    seen_skills: Set[str] = set()

    for s in (
        (prefs.get("primary_skills") or [])
        + (profile.get("primary_skills") or [])
        + (profile.get("technical_skills") or [])
    ):
        sc = str(s).strip()
        if sc and sc.lower() not in seen_skills:
            raw_skills.append(sc)
            seen_skills.add(sc.lower())

    summary = str(profile.get("summary") or "").lower()
    headline = str(profile.get("headline") or "").lower()
    target_roles = [str(r).strip() for r in (prefs.get("target_roles") or []) if str(r).strip()]

    # Infer candidate target roles and domains from summary, headline, or experience
    inferred_roles: List[str] = list(target_roles)
    role_signals: List[Tuple[str, str]] = [
        ("backend", "Backend Developer"),
        ("full stack", "Full Stack Developer"),
        ("frontend", "Frontend Developer"),
        ("ai engineer", "AI Engineer"),
        ("ai executive", "AI Engineer"),
        ("ai automation", "AI Automation Engineer"),
        ("machine learning", "Machine Learning Engineer"),
        ("python developer", "Python Developer"),
        ("software engineer", "Software Engineer"),
        ("data engineer", "Data Engineer"),
        ("devops", "DevOps Engineer"),
    ]

    for pattern, role_title in role_signals:
        if pattern in summary or pattern in headline:
            if role_title.lower() not in [r.lower() for r in inferred_roles]:
                inferred_roles.append(role_title)

    # Filter out senior or blacklisted roles from candidate target roles if any
    clean_inferred_roles: List[str] = []
    for r in inferred_roles:
        r_low = r.lower()
        if any(w in r_low for w in ["senior", "lead", "principal", "architect", "director", "staff", "vp"]):
            continue
        if r not in clean_inferred_roles:
            clean_inferred_roles.append(r)

    if not clean_inferred_roles:
        clean_inferred_roles = ["Software Engineer"]

    # Identify primary languages and key frameworks
    primary_tech: List[str] = []
    high_priority_tech = [
        "python", "fastapi", "django", "javascript", "typescript",
        "react", "node.js", "node", "go", "golang", "java", "c++", "sql"
    ]
    for t in high_priority_tech:
        for s in raw_skills:
            if t == s.lower():
                if s not in primary_tech:
                    primary_tech.append(s)
                break

    # Synthesize composite, high-precision search phrases
    composite_phrases: List[str] = []
    seen_phrases: Set[str] = set()

    def add_phrase(p: str):
        p_clean = p.strip()
        if p_clean and p_clean.lower() not in seen_phrases:
            composite_phrases.append(p_clean)
            seen_phrases.add(p_clean.lower())

    # Strategy A: Primary Language + Developer (e.g. 'Python Developer')
    if primary_tech:
        top_lang = primary_tech[0]
        add_phrase(f"{top_lang} Developer")

        # Strategy B: Target Roles combined with Primary Language (e.g. 'Software Engineer Python', 'Backend Developer Python')
        for r in clean_inferred_roles:
            if top_lang.lower() not in r.lower():
                add_phrase(f"{r} {top_lang}")
            else:
                add_phrase(r)

        # Strategy C: Core Frameworks (e.g. 'FastAPI Developer', 'Django Developer')
        for tech in primary_tech[1:4]:
            if tech.lower() not in {"git", "rest", "sql", "mysql", "sqlite"}:
                add_phrase(f"{tech} Developer")
    else:
        for r in clean_inferred_roles:
            add_phrase(r)

    # Strategy D: Raw clean target roles
    for r in clean_inferred_roles:
        add_phrase(r)

    # Strategy E: Fallback if everything is empty
    if not composite_phrases:
        composite_phrases = ["Python Developer", "Software Engineer", "Backend Developer"]

    return composite_phrases[:max_keywords], "deep_resume_analysis"

