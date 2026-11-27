"""
Structured Resume Parser and Extractor for AutoBot v2.
Extracts contact info, technical skills, experience, projects, education,
certifications, and achievements from parsed resume chunks or text.
"""

from datetime import datetime
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.ingestion.models import DocumentChunk, SectionType
from src.utils.logger import logger


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
URL_REGEX = re.compile(r"https?://[^\s]+|(?:linkedin\.com/in/|github\.com/)[^\s]+")


COMMON_TECH_SKILLS = [
    "Python", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Java", "C++", "C#",
    "SQL", "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Elasticsearch", "Qdrant",
    "FastAPI", "Flask", "Django", "Django REST Framework", "REST APIs", "React", "Next.js", "Vue", "Node.js", "Express",
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "Terraform", "CI/CD", "Git", "GitHub", "GitHub Actions",
    "REST", "GraphQL", "gRPC", "Kafka", "RabbitMQ", "Celery", "Pandas", "NumPy", "PyTorch",
    "TensorFlow", "LangChain", "LangGraph", "LlamaIndex", "OpenAI", "LLMs", "AI Agents", "MCP", "RAG", "OCR",
    "Playwright", "Selenium", "BeautifulSoup", "Firebase", "n8n", "Streamlit", "OpenPyXL", "WeasyPrint", "Tesseract",
    "Shopify API", "KwikShip API", "HTML", "CSS", "TailwindCSS", "Linux", "Bash", "Shell", "Microservices", "TDD"
]


def extract_contact_info(text: str, extra_links: Optional[List[str]] = None) -> Dict[str, str]:
    """Extract candidate name, email, phone, location, and profile URLs strictly from resume text & links."""
    combined_sources = [text] + list(extra_links or [])
    combined_blob = "\n".join(s for s in combined_sources if s)

    emails = EMAIL_REGEX.findall(combined_blob)
    if not emails and extra_links:
        for lnk in extra_links:
            if lnk.lower().startswith("mailto:"):
                addr = lnk[7:].strip()
                if "@" in addr:
                    emails.append(addr)
                    break
    phones = PHONE_REGEX.findall(text)

    linkedin = ""
    github = ""
    portfolio = ""

    for src in combined_sources:
        for line in src.splitlines():
            if not linkedin and "linkedin.com/in/" in line.lower():
                m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?", line, re.IGNORECASE)
                if m:
                    url = m.group(0)
                    linkedin = url if url.startswith("http") else f"https://{url}"
            if not github and "github.com/" in line.lower():
                m = re.search(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+)/?(?:\s|$)", line, re.IGNORECASE)
                if m:
                    url = m.group(0).strip()
                    github = url if url.startswith("http") else f"https://{url}"

    # Extract location from contact header segments without hardcoding
    extracted_location = ""
    for line in text.splitlines():
        loc_m = re.search(r"(?:location|address|city)\s*:\s*([^|\n⋄•·]+)", line, re.IGNORECASE)
        if loc_m:
            extracted_location = loc_m.group(1).strip()
            break
    if not extracted_location:
        for line in text.splitlines():
            for seg in re.split(r"[|⋄•·]", line):
                s = seg.strip()
                if not s or "@" in s or "http" in s.lower() or any(ch.isdigit() for ch in s):
                    continue
                if "," in s and len(s) <= 50 and "linkedin" not in s.lower() and "github" not in s.lower():
                    extracted_location = s
                    break
            if extracted_location:
                break

    # Extract candidate name: first clean non-contact-detail line before sections
    candidate_name = ""
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if "@" in clean or "http" in clean or any(char.isdigit() for char in clean if char not in " -+()"):
            continue
        if len(clean.split()) in (2, 3, 4) and len(clean) < 40:
            candidate_name = clean.title() if clean.isupper() else clean
            break

    return {
        "full_name": candidate_name,
        "email": emails[0] if emails else "",
        "phone": phones[0] if phones else "",
        "linkedin_url": linkedin,
        "github_url": github,
        "portfolio_url": portfolio,
        "location": extracted_location,
    }


def extract_skills_heuristic(text: str) -> List[str]:
    """Extract recognized skills from text without hallucination."""
    found = set()
    text_lower = f" {text.lower()} "
    for skill in COMMON_TECH_SKILLS:
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, text_lower):
            found.add(skill)
    return sorted(list(found))


def parse_structured_profile(
    chunks: List[DocumentChunk],
    llm: Optional[BaseChatModel] = None,
) -> Dict[str, Any]:
    """
    Synthesize structured candidate data from document chunks.
    Combines rule-based extraction with optional LLM normalization.
    """
    sections: Dict[str, List[str]] = {}
    extra_links: List[str] = []
    for c in chunks:
        sec = c.section.value
        sections.setdefault(sec, []).append(c.content)
        raw_hl = (c.metadata or {}).get("hyperlinks", "")
        if isinstance(raw_hl, str) and raw_hl:
            for u in raw_hl.split("||"):
                u = u.strip()
                if u and u not in extra_links:
                    extra_links.append(u)

    contact_text = "\n".join(sections.get("contact", []) + sections.get("summary", []))
    contact = extract_contact_info(contact_text, extra_links=extra_links)

    skills_text = "\n".join(sections.get("skills", []) + sections.get("summary", []))
    tech_skills = extract_skills_heuristic(skills_text)
    if not tech_skills:
        # Check all chunks
        all_text = "\n".join(c.content for c in chunks)
        tech_skills = extract_skills_heuristic(all_text)

    # Parse experience blocks
    experiences: List[Dict[str, Any]] = []
    for exp_chunk in sections.get("experience", []):
        lines = [l.strip() for l in exp_chunk.splitlines() if l.strip()]
        if not lines:
            continue
        header = lines[0]
        bullets = lines[1:] if len(lines) > 1 else [header]
        role = header
        company = ""
        if "|" in header:
            parts = [p.strip() for p in header.split("|")]
            role = parts[0]
            company = parts[1] if len(parts) > 1 else ""
        elif " at " in header:
            parts = header.split(" at ")
            role = parts[0].strip()
            company = parts[1].strip()
        experiences.append({
            "role": role,
            "company": company,
            "bullets": bullets,
            "raw_text": exp_chunk,
        })

    # Parse projects
    projects: List[Dict[str, Any]] = []
    for proj_chunk in sections.get("projects", []):
        lines = [l.strip() for l in proj_chunk.splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0]
        desc = " ".join(lines[1:]) if len(lines) > 1 else title
        projects.append({
            "title": title,
            "description": desc,
            "technologies": extract_skills_heuristic(proj_chunk),
        })

    # Parse education
    education: List[Dict[str, Any]] = []
    for edu_chunk in sections.get("education", []):
        lines = [l.strip() for l in edu_chunk.splitlines() if l.strip()]
        if lines:
            education.append({
                "institution": lines[0],
                "details": lines[1:] if len(lines) > 1 else [],
                "raw_text": edu_chunk,
            })

    # Parse certifications
    certifications: List[Dict[str, Any]] = []
    for cert_chunk in sections.get("certifications", []):
        for line in cert_chunk.splitlines():
            clean = line.strip().lstrip("-•* ")
            if clean and len(clean) > 3:
                certifications.append({"name": clean})

    # Parse achievements & honors
    achievements: List[Dict[str, Any]] = []
    achievement_candidates = sections.get("achievements", []) + sections.get("awards", []) + sections.get("honors", [])
    for ach_chunk in achievement_candidates:
        for line in ach_chunk.splitlines():
            clean = line.strip().lstrip("-•* ")
            if clean and len(clean) > 4:
                achievements.append({"title": clean, "description": clean})

    # If no explicit achievement sections, search other chunks for honors/awards/achievements
    if not achievements:
        for chunk in chunks:
            if chunk.section.value in ("experience", "education", "other"):
                for line in chunk.content.splitlines():
                    clean = line.strip().lstrip("-•* ")
                    lower = clean.lower()
                    if any(kw in lower for kw in ["awarded", "1st place", "winner", "hackathon", "patent", "scholarship", "honors", "fellowship", "dean's list"]):
                        if len(clean) > 10:
                            achievements.append({"title": clean[:80], "description": clean})

    # Summary
    summary = "\n".join(sections.get("summary", []))
    if not summary and experiences:
        summary = f"Experienced professional with background in {', '.join(tech_skills[:5])}."

    # If LLM is available, optionally refine extraction
    if llm:
        try:
            prompt = (
                "Extract structured resume information from the following text into JSON with keys: "
                "full_name, email, phone, headline, summary, technical_skills (list), "
                "experience (list of {role, company, bullets}), projects (list of {title, description, technologies}), "
                "education (list of {institution, details}), certifications (list of {name}), "
                "achievements (list of {title, description}).\n\n"
                f"Resume Content:\n{contact_text}\n{skills_text}\n"
                "Return ONLY valid JSON."
            )
            response = llm.invoke([
                SystemMessage(content="You are a strict resume parser. Return only JSON without conversational text."),
                HumanMessage(content=prompt),
            ])
            content_str = response.content if isinstance(response.content, str) else str(response.content)
            # Remove markdown backticks if present
            clean_json = re.sub(r"^```(?:json)?\s*", "", content_str.strip())
            clean_json = re.sub(r"\s*```$", "", clean_json)
            llm_data = json.loads(clean_json)
            if isinstance(llm_data, dict):
                if llm_data.get("full_name"):
                    contact["full_name"] = str(llm_data["full_name"])
                if llm_data.get("email"):
                    contact["email"] = str(llm_data["email"])
                if llm_data.get("phone"):
                    contact["phone"] = str(llm_data["phone"])
                if llm_data.get("headline"):
                    contact["headline"] = str(llm_data["headline"])
                if llm_data.get("summary"):
                    summary = str(llm_data["summary"])
                if isinstance(llm_data.get("technical_skills"), list) and llm_data["technical_skills"]:
                    tech_skills = sorted(list(set(tech_skills + [str(s) for s in llm_data["technical_skills"]])))
                if isinstance(llm_data.get("achievements"), list) and llm_data["achievements"]:
                    achievements = [
                        {"title": str(a.get("title", a)), "description": str(a.get("description", a))}
                        if isinstance(a, dict) else {"title": str(a), "description": str(a)}
                        for a in llm_data["achievements"]
                    ]
        except Exception as e:
            logger.debug(f"LLM structured resume parsing fallback to heuristics: {e}")

    # Build primary vs secondary skills without assuming skills are target roles
    primary_skills = tech_skills[:8]
    secondary_skills = tech_skills[8:]

    from src.matching.eligibility import resolve_job_country
    candidate_country = resolve_job_country(contact.get("location", "")) or ""

    return {
        "full_name": contact.get("full_name") or "",
        "email": contact.get("email") or "",
        "phone": contact.get("phone") or "",
        "location": contact.get("location") or "",
        "country": candidate_country,
        "headline": contact.get("headline") or (f"{experiences[0]['role']}" if experiences else ""),
        "summary": summary,
        "technical_skills": tech_skills,
        "primary_skills": primary_skills,
        "secondary_skills": secondary_skills,
        "experience": experiences,
        "projects": projects,
        "education": education,
        "certifications": certifications,
        "achievements": achievements,
        "contact_info": contact,
        "linkedin_url": contact.get("linkedin_url") or "",
        "portfolio_url": contact.get("portfolio_url") or "",
        "github_url": contact.get("github_url") or "",
        "resume_text": "\n\n".join(c.content for c in chunks),
    }
