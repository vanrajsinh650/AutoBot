"""
AutoBot Groq AI Form Intelligence Assistant.

Empowers AutoBot to:
1. Intelligently locate and trigger the exact "Apply" / "Apply Now" button across
   complex dynamic portals (Phenom People, Workday, Greenhouse, Lever, Taleo, etc.).
2. Accurately map dynamic or obscured form inputs (names, IDs, labels, placeholders)
   to the candidate's real profile data without mistakes.
3. Distinguish between an "Open Form" button and the final "Submit Application" button.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from src.utils.logger import logger


DEFAULT_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DEFAULT_GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def call_groq_json(prompt: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Execute a structured JSON prompt against Groq's high-speed inference engine."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("GROQ_API_KEY", "")
        except Exception:
            pass

    if not api_key:
        return None

    base_url = os.environ.get("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL).rstrip("/")
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    endpoint = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 AutoBot/2.0",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content)
    except Exception as ex:
        logger.debug(f"[groq-form-assistant] Groq API call failed: {ex}")
        return None


def _build_learned_rules_context(user_id: int = 1, db_path: Optional[str] = None) -> str:
    """Summarize user-taught Q&A rules & instructions for Groq reasoning context."""
    try:
        from src.storage.db import get_learned_qa_rules
        rules = get_learned_qa_rules(user_id=user_id, active_only=True, db_path=db_path)
        if not rules:
            return ""
        lines = []
        for r in rules[:25]:
            note = f" ({r['instruction_note']})" if r.get("instruction_note") else ""
            lines.append(f"- Q: {r.get('question_pattern', '')} -> User Rule: {r.get('user_answer', '')}{note}")
        return "User-Taught Preferences & Past Instructions:\n" + "\n".join(lines) + "\n"
    except Exception:
        return ""


def _resolve_deterministic_or_learned(
    question: str,
    options: Optional[List[str]] = None,
    field_type: str = "text",
    candidate_info: Optional[Dict[str, Any]] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve known questions deterministically:
      Tier 1: User-taught learned Q&A rules from self-learning memory
      Tier 2: Verified candidate profile & explicit config screening defaults
    Returns {answer, confident, source, reason} if handled, else None.
    """
    candidate = candidate_info or {}
    q_lower = (question or "").lower()
    uid = int(candidate.get("user_id") or user_id or 1)

    # Tier 1: User self-learned rules ALWAYS take highest priority
    try:
        from src.storage.db import find_learned_qa_answer
        learned = find_learned_qa_answer(
            user_id=uid,
            question=question,
            options=options,
            field_type=field_type,
            db_path=db_path,
        )
        if learned and learned.get("answer"):
            return {
                "answer": str(learned["answer"]),
                "confident": True,
                "source": "learned_qa",
                "reason": f"Applied user-taught rule ({learned.get('match_type', 'exact')})",
            }
    except Exception as ex:
        logger.debug(f"[groq-form-assistant] Learned QA lookup skipped: {ex}")

    def _ok(val: str, src: str = "profile", reason: str = "") -> Dict[str, Any]:
        return {"answer": val, "confident": True, "source": src, "reason": reason}

    def _need_user(reason: str) -> Dict[str, Any]:
        return {"answer": "", "confident": False, "source": "unknown", "reason": reason}

    def _cfg_ans(key: str) -> str:
        val = candidate.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
        try:
            from src.utils.config import get_config
            answers_cfg = getattr(getattr(get_config(), "apply", None), "answers", None)
            if answers_cfg and hasattr(answers_cfg, key):
                cv = getattr(answers_cfg, key)
                if cv is not None and str(cv).strip():
                    return str(cv).strip()
        except Exception:
            pass
        return ""

    # 0a. Conditional follow-up text fields ("If you answered Yes...", "If yes, please...")
    if not options and any(
        p in q_lower for p in (
            "if you answered yes", "if you answered \"yes\"", "if you answered 'yes'",
            "if yes,", "if yes please", "if you selected yes", "if applicable, please",
            "if different than above", "please share the name and your relationship",
            "name used during your employment",
        )
    ):
        return _ok("N/A", reason="Conditional follow-up defaults to N/A")

    # 0b. Referral source ("How did you hear about...") - must check BEFORE LinkedIn URL matching
    if any(k in q_lower for k in ("how did you hear", "source of referral", "referral source", "where did you hear", "hear about")):
        if options:
            for o in options:
                if "linkedin" in o.lower():
                    return _ok(o, reason="Referral source")
            for o in options:
                if any(s in o.lower() for s in ("job board", "career site", "company website", "online")):
                    return _ok(o, reason="Referral source")
            return _ok(options[0], reason="Referral source")
        return _ok("LinkedIn", reason="Referral source")

    # 0c. Candidate Social / Portfolio / Name / Education / Employer fields (strictly from resume/profile — never hardcoded)
    if "linkedin" in q_lower:
        if options:
            for o in options:
                if o.strip().lower().startswith("yes"):
                    return _ok(o, reason="LinkedIn profile confirmation")
            return _need_user("Unclear LinkedIn dropdown options")
        li_val = str(candidate.get("linkedin") or "").strip()
        return _ok(li_val, reason="Profile LinkedIn URL") if li_val else _need_user("LinkedIn URL not found in resume or profile")

    if "github" in q_lower:
        if not options:
            gh_val = str(candidate.get("github") or "").strip()
            return _ok(gh_val, reason="Profile GitHub URL") if gh_val else _need_user("GitHub URL not found in resume or profile")

    if any(k in q_lower for k in ("personal website", "portfolio", "website or blog", "blog", "website")):
        if not options:
            port_val = str(candidate.get("portfolio") or candidate.get("github") or "").strip()
            return _ok(port_val, reason="Profile portfolio/GitHub URL") if port_val else _need_user("Portfolio or website URL not found in resume or profile")

    if "preferred first" in q_lower or q_lower.strip().rstrip("* :") in ("first name", "given name"):
        fn_val = str(candidate.get("first_name") or "").strip()
        return _ok(fn_val, reason="Profile first name") if fn_val else _need_user("First name not found in resume or profile")
    if "preferred last" in q_lower or q_lower.strip().rstrip("* :") in ("last name", "surname", "family name"):
        ln_val = str(candidate.get("last_name") or "").strip()
        return _ok(ln_val, reason="Profile last name") if ln_val else _need_user("Last name not found in resume or profile")
    if any(k in q_lower for k in ("preferred name", "legal name", "full name")):
        full_val = str(candidate.get("full_name") or "").strip()
        return _ok(full_val, reason="Profile full name") if full_val else _need_user("Full name not found in resume or profile")

    if any(k in q_lower for k in ("school", "university", "college", "institution")):
        if not options:
            uni_val = str(candidate.get("university") or "").strip()
            return _ok(uni_val, reason="Profile university") if uni_val else _need_user("University name not found in resume or profile")

    if any(k in q_lower for k in ("degree", "qualification")) and "years" not in q_lower:
        deg_val = str(candidate.get("degree") or "").strip()
        if not deg_val:
            return _need_user("Degree not found in resume or profile")
        if options:
            deg_tokens = [t for t in re.findall(r"[a-z]{3,}", deg_val.lower()) if t not in ("and", "the", "for")]
            for o in options:
                o_low = o.lower()
                if any(tok in o_low for tok in deg_tokens) or ("bachelor" in deg_val.lower() and "undergraduate" in o_low):
                    return _ok(o, reason="Profile degree")
        else:
            return _ok(deg_val, reason="Profile degree")

    if any(k in q_lower for k in ("discipline", "major", "field of study")):
        maj_val = str(candidate.get("major") or "").strip()
        if not maj_val:
            return _need_user("Major / field of study not found in resume or profile")
        if options:
            maj_tokens = [t for t in re.findall(r"[a-z]{3,}", maj_val.lower()) if t not in ("and", "the", "for")]
            for o in options:
                if any(tok in o.lower() for tok in maj_tokens):
                    return _ok(o, reason="Profile major")
        else:
            return _ok(maj_val, reason="Profile major")

    if any(k in q_lower for k in ("current company", "current employer", "present employer")):
        if not options:
            comp_val = str(candidate.get("current_company") or "").strip()
            return _ok(comp_val, reason="Profile current company") if comp_val else _need_user("Current company not found in resume or profile")

    # 0d. Geographic Location & Relocation checks (strictly from candidate location)
    candidate_city = str(candidate.get("city") or "").strip().lower()
    candidate_state = str(candidate.get("state") or "").strip().lower()
    candidate_country = str(candidate.get("country") or "").strip().lower()

    if any(k in q_lower for k in ("currently based in", "based in", "currently reside", "currently live", "live in")):
        if options and (candidate_city or candidate_state or candidate_country):
            for o in options:
                o_low = o.lower()
                if any(loc in o_low for loc in (candidate_city, candidate_state, candidate_country) if loc):
                    return _ok(o, reason="Location matches candidate residence")
            willing = _cfg_ans("willing_to_relocate").lower()
            if not willing or willing.startswith("y"):
                for o in options:
                    o_low = o.lower()
                    if ("relocat" in o_low or "support" in o_low) and ("willing" in o_low or "outside" in o_low or "require" in o_low) and "not willing" not in o_low and "do not live" not in o_low:
                        return _ok(o, reason="Relocation preference")
            for o in options:
                o_low = o.lower()
                if any(out in o_low for out in ("outside", "not based", "neither", "other")) and "not willing" not in o_low:
                    return _ok(o, reason="Outside listed hubs")
            if "relocat" not in q_lower:
                cand_in_question = any(loc in q_lower for loc in (candidate_city, candidate_state, candidate_country) if loc)
                target_word = "yes" if cand_in_question else "no"
                for o in options:
                    if target_word in o.lower().split() or o.lower().strip().startswith(target_word):
                        return _ok(o, reason="Geographic match check")

    # 1. Negative screening questions (relatives, former employee, referral, termination, crime, conflict, sponsorship)
    is_sponsorship_q = any(k in q_lower for k in ("sponsor", "visa sponsorship", "require sponsorship", "require visa", "immigration sponsorship"))
    negative_screening_patterns = (
        "relative", "friend", "family", "nepotism",
        "previous", "prior", "former employee", "previously employed", "worked for", "worked at", "applied before",
        "applied on any previous", "referred", "referral", "employee referral",
        "terminated", "terminate", "resign", "dismissed", "fired", "disciplinary", "misconduct",
        "convict", "criminal", "felony", "misdemeanor", "law violation", "arrested",
        "conflict", "non-compete", "restrictive covenant",
        "government", "public official", "politically exposed",
        "sponsor", "visa sponsorship", "require sponsorship", "require visa", "immigration sponsorship",
    )
    if any(k in q_lower for k in negative_screening_patterns):
        if options:
            citizenship_tokens = ("citizen", "permanent resident", "green card", "national", "passport")
            for o in options:
                o_low = o.lower()
                if any(n in o_low for n in ("no", "none", "neither", "false", "never", "not applicable", "n/a", "decline")):
                    if is_sponsorship_q and any(ct in o_low for ct in citizenship_tokens):
                        if candidate_country not in o_low:
                            continue
                    return _ok(o, reason="Screening rule")
            if is_sponsorship_q:
                for o in options:
                    if o.strip().lower().startswith("yes"):
                        return _ok(o, reason="Sponsorship required when plain No absent")
            for o in options:
                o_low = o.lower()
                if any(n in o_low for n in ("no", "none", "neither", "false", "never", "not applicable", "n/a", "decline")):
                    return _ok(o, reason="Screening rule")
            return _need_user(f"Could not find a matching option for screening question: {question}")
        return _ok("No", reason="Standard screening rule")

    # 2. Positive screening questions
    positive_screening_patterns = (
        "work auth", "authorized", "legal right", "eligible to work", "legally eligible",
        "18", "age", "adult", "legal age",
        "background", "drug", "screening consent", "check consent",
        "relocat", "travel", "willing to relocate",
    )
    if any(k in q_lower for k in positive_screening_patterns):
        if options:
            for o in options:
                o_low = o.lower()
                if "not willing" in o_low or ("do not require relocation" in o_low and "already live" in o_low):
                    continue
                if any(y in o_low for y in ("yes", "authorized", "eligible", "agree", "consent", "willing")):
                    return _ok(o, reason="Eligibility / consent rule")
            return _need_user(f"Ambiguous eligibility/relocation options for: {question}")
        return _ok("Yes", reason="Eligibility / consent rule")

    # 3. Notice period & Availability
    if any(k in q_lower for k in ("notice period", "availability", "how soon can you start", "available to start", "start date", "earliest start", "available from")):
        if field_type == "date":
            from datetime import datetime, timedelta
            return _ok((datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"), src="config", reason="Available start date")
        notice_val = _cfg_ans("notice_period")
        if options:
            for o in options:
                o_low = o.lower()
                if notice_val and notice_val.lower() in o_low:
                    return _ok(o, src="config", reason="Configured notice period")
                if any(imm in o_low for imm in ("immediate", "immediately", "15", "1-2 weeks", "2 weeks", "less than 1 month")):
                    return _ok(o, src="config", reason="Configured notice period")
            return _need_user(f"No matching availability option for notice period in: {options}")
        return _ok(notice_val or "Immediate", src="config", reason="Configured notice period")

    # 4. Salary / CTC / Compensation
    if any(k in q_lower for k in ("salary", "compensation", "ctc", "expected monthly", "expected annual", "expected pay", "basic salary")):
        expected_val = _cfg_ans("expected_salary")
        if not expected_val:
            return _need_user("Expected compensation question has no configured salary preference")
        if options:
            for o in options:
                if any(c in o.lower() for c in ("100,000", "100000", "10-15", "competitive", "negotiable", expected_val.lower())):
                    return _ok(o, src="config", reason="Configured salary expectation")
            return _need_user(f"Salary dropdown options {options} did not match configured '{expected_val}'")
        return _ok(expected_val, src="config", reason="Configured salary expectation")

    # 5. EEOC / Diversity & Inclusion (ONLY answer when explicitly provided in profile/config/learned rules)
    if any(k in q_lower for k in ("gender", "sex")) and "sexual orientation" not in q_lower:
        g_val = str(candidate.get("gender") or "").strip()
        if not g_val:
            return _need_user("Gender not specified in profile or learned rules")
        if options:
            for o in options:
                o_low = o.lower().strip()
                if g_val.lower() in o_low and not ("male" in g_val.lower() and "female" in o_low and "male" == g_val.lower()):
                    return _ok(o, reason="Profile gender")
            return _need_user("Gender option did not match configured value")
        return _ok(g_val, reason="Profile gender")

    if any(k in q_lower for k in ("disability", "disabled", "handicap")):
        d_val = str(candidate.get("disability") or "").strip()
        if not d_val:
            return _need_user("Disability status not specified in profile or learned rules")
        if options:
            for o in options:
                o_low = o.lower()
                if d_val.lower() == "no" and any(d in o_low for d in ("no, i don't have", "no disability", "do not have a disability", "no")):
                    return _ok(o, reason="Profile disability status")
                if d_val.lower() in o_low:
                    return _ok(o, reason="Profile disability status")
            return _need_user("Disability dropdown option did not match configured value")
        return _ok(d_val, reason="Profile disability status")

    if any(k in q_lower for k in ("veteran", "military")):
        v_val = str(candidate.get("veteran") or "").strip()
        if not v_val:
            return _need_user("Veteran status not specified in profile or learned rules")
        if options:
            for o in options:
                o_low = o.lower()
                if v_val.lower() == "no" and any(v in o_low for v in ("not a protected veteran", "i am not a protected", "not a veteran", "no")):
                    return _ok(o, reason="Profile veteran status")
                if v_val.lower() in o_low:
                    return _ok(o, reason="Profile veteran status")
            return _need_user("Veteran dropdown option did not match configured value")
        return _ok(v_val, reason="Profile veteran status")

    if any(k in q_lower for k in ("race", "ethnicity", "ethnic origin")):
        r_val = str(candidate.get("race") or "").strip()
        if not r_val:
            return _need_user("Race/ethnicity not specified in profile or learned rules")
        if options:
            for o in options:
                o_low = o.lower()
                if "american indian" in o_low and "american indian" not in r_val.lower():
                    continue
                if r_val.lower() in o_low:
                    return _ok(o, reason="Profile race/ethnicity")
            return _need_user("Race/ethnicity option did not match configured value")
        return _ok(r_val, reason="Profile race/ethnicity")

    # 5b. Country dropdowns / inputs ("Country", "Country of residence")
    if any(k in q_lower for k in ("country", "country of residence", "location (country)")) and "dial" not in q_lower and "code" not in q_lower:
        cand_country = str(candidate.get("country") or "").strip()
        if not cand_country:
            return _need_user("Country not found in resume or profile")
        if options:
            for o in options:
                o_low = o.lower().strip()
                if o_low == cand_country.lower() or o_low.startswith(cand_country.lower() + " ") or o_low.startswith(cand_country.lower() + "("):
                    return _ok(o, reason="Profile country")
            for o in options:
                if cand_country.lower() in o.lower():
                    return _ok(o, reason="Profile country")
        else:
            return _ok(cand_country, reason="Profile country")

    # 5c. Graduation Year / Start Date fields
    if any(k in q_lower for k in ("graduation year", "year of graduation", "expected graduation")):
        grad_yr = str(candidate.get("graduation_year") or "").strip()
        if not grad_yr:
            return _need_user("Graduation year not found in resume or learned rules")
        if not options:
            return _ok(grad_yr, reason="Profile graduation year")

    if field_type == "date" and any(k in q_lower for k in ("start date", "available from", "earliest start", "availability date")):
        from datetime import datetime, timedelta
        return _ok((datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"), src="config", reason="Available start date")

    # 5d. Verified Skill / Technology Experience Questions ("experience with Python", "years of experience in FastAPI")
    skill_list = candidate.get("skills") or []
    if not skill_list:
        try:
            from src.storage.db import get_candidate_profile
            prof = get_candidate_profile(uid, db_path=db_path) or {}
            skill_list = list((prof.get("technical_skills") or []) + (prof.get("primary_skills") or []))
        except Exception:
            skill_list = []
    skill_tokens = [str(s).strip().lower() for s in skill_list if len(str(s).strip()) >= 2]
    matched_skill = next((sk for sk in skill_tokens if re.search(rf"(?<![a-z0-9]){re.escape(sk)}(?![a-z0-9])", q_lower)), None)
    if matched_skill and any(k in q_lower for k in ("experience", "proficien", "familiar", "worked with", "knowledge of", "years")):
        yoe = _cfg_ans("years_of_experience")
        if options:
            if any(o.strip().lower().startswith("yes") for o in options):
                return _ok(next(o for o in options if o.strip().lower().startswith("yes")), src="profile", reason=f"Verified skill '{matched_skill}' in profile")
            if yoe:
                for o in options:
                    if yoe in o or "1-2" in o.lower() or "1+" in o.lower() or "less than 2" in o.lower():
                        return _ok(o, src="profile", reason=f"Verified years with '{matched_skill}'")
        else:
            if "years" in q_lower or "how many" in q_lower or field_type == "number":
                return _ok(yoe, src="config", reason=f"Verified years with '{matched_skill}'") if yoe else _need_user(f"Years of experience with '{matched_skill}' not specified")
            return _ok("Yes", src="profile", reason=f"Verified skill '{matched_skill}' in profile")

    # 5e. Total years of work experience (non-skill-specific)
    if any(k in q_lower for k in ("years of experience", "years of relevant", "total years", "work experience")) and "with " not in q_lower:
        if not options:
            yoe_tot = _cfg_ans("years_of_experience")
            return _ok(yoe_tot, src="config", reason="Configured years of experience") if yoe_tot else _need_user("Years of experience not configured or stated")

    # 5f. Government ID / sensitive PII (PAN, SSN, Aadhaar, Passport) - NEVER hallucinate; pause for user
    if any(k in q_lower for k in ("pan number", "pan card", "aadhaar", "ssn", "social security", "passport number", "driver's license", "drivers license")):
        return _need_user("Sensitive government ID / PII requires explicit candidate input")

    # 5g. Strict URL input guard: never return non-URL prose for <input type="url">
    if field_type == "url":
        if any(k in q_lower for k in ("video", "loom", "youtube", "recording")):
            return _need_user("Custom video/recording URL must be provided by candidate")
        url_val = str(candidate.get("portfolio") or candidate.get("github") or candidate.get("linkedin") or "").strip()
        return _ok(url_val, reason="Profile URL") if url_val else _need_user("Profile URL not found in resume or profile")

    # 5h. Pronouns (ONLY answer if specified by candidate or learned rules)
    if "pronoun" in q_lower:
        p_val = str(candidate.get("pronouns") or "").strip()
        if not p_val:
            return _need_user("Pronouns not specified in profile or learned rules")
        if options:
            for o in options:
                if p_val.lower() in o.lower():
                    return _ok(o, reason="Profile pronouns")
            return _need_user("Unrecognized pronoun options")
        return _ok(p_val, reason="Profile pronouns")

    # 6. Job Title / Current Role (ONLY when explicitly requested!)
    if any(k in q_lower for k in ("current title", "job title", "current role", "designation", "position title", "current position")):
        title_val = str(candidate.get("current_title") or "").strip()
        return _ok(title_val, reason="Profile current job title") if title_val else _need_user("Current job title not found in resume or profile")

    return None


def resolve_form_question_with_confidence(
    question: str,
    options: Optional[List[str]] = None,
    field_type: str = "text",
    candidate_info: Optional[Dict[str, Any]] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Confidence-gated form question resolver:
      Tier 1: User-taught learned Q&A rules (self-learning memory)
      Tier 2: Verified deterministic candidate profile & config rules
      Tier 3: Groq LLM with strict uncertainty gate (sets confident=False if unsure or needs_user_input=True)
      Tier 4: Unknown -> pauses and asks user via proof image instead of guessing options[0]!
    """
    det = _resolve_deterministic_or_learned(
        question=question,
        options=options,
        field_type=field_type,
        candidate_info=candidate_info,
        user_id=user_id,
        db_path=db_path,
    )
    if det is not None:
        return det

    candidate = candidate_info or {}
    uid = int(candidate.get("user_id") or user_id or 1)
    learned_ctx = _build_learned_rules_context(user_id=uid, db_path=db_path)

    summary_lines: List[str] = []
    field_labels = [
        ("full_name", "Candidate Full Name"),
        ("email", "Candidate Email"),
        ("phone", "Candidate Phone"),
        ("location", "Candidate Location"),
        ("country", "Candidate Country"),
        ("linkedin", "LinkedIn"),
        ("github", "GitHub"),
        ("portfolio", "Portfolio / Website"),
        ("current_company", "Current Company"),
        ("current_title", "Current Job Title"),
        ("years_of_experience", "Years of Experience"),
        ("degree", "Degree"),
        ("university", "University / Institution"),
        ("graduation_year", "Graduation Year"),
        ("notice_period", "Notice Period"),
        ("work_authorization", "Work Authorization"),
        ("sponsorship_required", "Sponsorship Required"),
        ("willing_to_relocate", "Willing to Relocate"),
        ("expected_salary", "Expected Salary"),
    ]
    for key, lbl in field_labels:
        v = str(candidate.get(key) or "").strip()
        if v:
            summary_lines.append(f"{lbl}: {v}")
    if isinstance(candidate.get("skills"), list) and candidate["skills"]:
        summary_lines.append("Verified Skills: " + ", ".join(str(s) for s in candidate["skills"]))
    if candidate.get("resume_text"):
        summary_lines.append("Candidate Resume Content (Exact Extracted Text):\n" + str(candidate["resume_text"])[:2500])
    if learned_ctx:
        summary_lines.append(learned_ctx.strip())
    candidate_summary = "\n".join(summary_lines)

    if options:
        prompt = (
            f"You are AutoBot Job Application Form Assistant.\n"
            f"Candidate Profile & Verified Answers:\n{candidate_summary}\n\n"
            f"Question: \"{question}\"\n"
            f"Options: {json.dumps(options)}\n\n"
            f"STRICT GROUNDING RULES:\n"
            f"1. Pick the SINGLE BEST matching option string from Options ONLY if it is factually stated in Candidate Profile, Candidate Resume Content, or User-Taught Rules above.\n"
            f"2. NEVER invent, guess, or assume any name, address, graduation year, demographic, experience, compensation, or skill not explicitly stated above. If unknown or confidence < 0.75, set \"needs_user_input\": true and DO NOT GUESS.\n"
            f"Output strictly a JSON object: "
            f"{{\"best_option\": \"<exact string from options or empty>\", \"confidence\": 0.0, \"needs_user_input\": false, \"reason\": \"<short reason>\"}}"
        )
        res = call_groq_json(prompt, timeout=4.5)
        if res:
            if res.get("needs_user_input") is True:
                return {
                    "answer": "",
                    "confident": False,
                    "source": "unknown",
                    "reason": str(res.get("reason") or f"New question requires user instruction: {question}"),
                }
            conf_raw = res.get("confidence", 0.85)
            try:
                conf = float(conf_raw)
            except Exception:
                conf = 0.85
            if conf < 0.75:
                return {
                    "answer": "",
                    "confident": False,
                    "source": "unknown",
                    "reason": str(res.get("reason") or f"Low confidence ({conf:.2f}) for question: {question}"),
                }
            best = str(res.get("best_option") or "").strip()
            if best:
                for opt in options:
                    if opt.lower().strip() == best.lower().strip() or best.lower() in opt.lower():
                        return {"answer": opt, "confident": True, "source": "llm", "reason": str(res.get("reason") or "AI matched option")}
        return {
            "answer": "",
            "confident": False,
            "source": "unknown",
            "reason": f"No verified profile or learned answer for new question: {question}",
        }
    else:
        prompt = (
            f"You are AutoBot Job Application Form Assistant.\n"
            f"Candidate Profile & Verified Answers:\n{candidate_summary}\n\n"
            f"Form Question/Field Label: \"{question}\"\n"
            f"RULES:\n"
            f"1. Answer ONLY if factually supported by Candidate Profile or User-Taught Rules.\n"
            f"2. If this asks for personal opinions, company-specific essays ('Why this company?'), sensitive IDs, unverified skills/certifications, or anything NOT known with high confidence (>= 0.75), set \"needs_user_input\": true and DO NOT FABRICATE.\n"
            f"3. NEVER output the candidate's job title or technical skills unless the field explicitly asks for current job title or skills.\n"
            f"Output strictly a JSON object: "
            f"{{\"answer\": \"<value or empty>\", \"confidence\": 0.0, \"needs_user_input\": false, \"reason\": \"<short reason>\"}}"
        )
        res = call_groq_json(prompt, timeout=4.5)
        if res:
            if res.get("needs_user_input") is True:
                return {
                    "answer": "",
                    "confident": False,
                    "source": "unknown",
                    "reason": str(res.get("reason") or f"New question requires user input: {question}"),
                }
            conf_raw = res.get("confidence", 0.85)
            try:
                conf = float(conf_raw)
            except Exception:
                conf = 0.85
            ans = str(res.get("answer") or "").strip()
            if ans and conf >= 0.75:
                return {"answer": ans, "confident": True, "source": "llm", "reason": str(res.get("reason") or "AI grounded answer")}

        return {
            "answer": "",
            "confident": False,
            "source": "unknown",
            "reason": f"New question requires user instruction: {question}",
        }


def answer_question_with_groq(
    question: str,
    options: Optional[List[str]] = None,
    field_type: str = "text",
    candidate_info: Optional[Dict[str, Any]] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
) -> str:
    """
    Intelligently answer form screening questions using learned user rules,
    verified candidate profile data, or Groq AI. Returns empty string when
    uncertain so AutoBot stops and asks the user instead of guessing.
    """
    res = resolve_form_question_with_confidence(
        question=question,
        options=options,
        field_type=field_type,
        candidate_info=candidate_info,
        user_id=user_id,
        db_path=db_path,
    )
    return str(res.get("answer") or "") if res.get("confident") else ""


async def identify_apply_button_with_groq(page: Any, job_title: str) -> Optional[str]:
    """
    Extract visible buttons and links from the current page and ask Groq to
    identify the single element that opens the application form.
    """
    try:
        elements_data = await page.evaluate("""() => {
            const items = [];
            const candidates = document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]');
            for (const el of candidates) {
                if (!el.offsetParent && el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                const text = (el.innerText || el.textContent || el.value || '').trim();
                const aria = el.getAttribute('aria-label') || '';
                const href = el.getAttribute('href') || '';
                const id = el.id || '';
                const dataPhAt = el.getAttribute('data-ph-at-id') || '';
                const dataAuto = el.getAttribute('data-automation-id') || '';
                const combined = (text + ' ' + aria + ' ' + href + ' ' + dataPhAt + ' ' + dataAuto).toLowerCase();
                
                if (combined.includes('apply') || combined.includes('candidat') || combined.includes('postul') || combined.includes('sollicit')) {
                    items.push({
                        tag: el.tagName.toLowerCase(),
                        text: text.slice(0, 60),
                        aria: aria.slice(0, 60),
                        href: href.slice(0, 100),
                        id: id,
                        dataPhAt: dataPhAt,
                        dataAuto: dataAuto,
                    });
                }
            }
            return items.slice(0, 15);
        }""")

        if not elements_data:
            return None

        prompt = (
            f"You are AutoBot Browser Automation Assistant.\n"
            f"We are on a company job posting page for '{job_title}'.\n"
            f"Here are the candidate clickable elements on the page:\n"
            f"{json.dumps(elements_data, indent=2)}\n\n"
            f"Identify the element that OPENS or STARTS the application form for the candidate.\n"
            f"Output ONLY a JSON object:\n"
            f'{{"best_index": <int 0-based index or -1 if none>, "selector_hint": "<css selector hint>", "reason": "<short explanation>"}}'
        )

        res = call_groq_json(prompt, timeout=5.0)
        if res and res.get("best_index", -1) >= 0 and res["best_index"] < len(elements_data):
            matched_item = elements_data[res["best_index"]]
            # Build precise selector
            if matched_item.get("id"):
                return f"#{matched_item['id']}"
            if matched_item.get("dataPhAt"):
                return f"[{matched_item['tag']}][data-ph-at-id='{matched_item['dataPhAt']}']"
            if matched_item.get("dataAuto"):
                return f"[{matched_item['tag']}][data-automation-id='{matched_item['dataAuto']}']"
            if matched_item.get("text"):
                return f"{matched_item['tag']}:has-text('{matched_item['text']}')"
            if matched_item.get("href"):
                return f"a[href='{matched_item['href']}']"
    except Exception as ex:
        logger.debug(f"[groq-form-assistant] Identify apply button error: {ex}")

    return None


async def map_unrecognized_form_fields_with_groq(
    page: Any,
    candidate_info: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Extract visible un-filled form inputs and ask Groq to map each one to candidate info
    (firstName, lastName, email, phone, location, workAuth, etc.) so nothing is misfilled.
    """
    try:
        unfilled_inputs = await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select'));
            const results = [];
            for (const el of inputs) {
                if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
                if (el.value && el.value.trim().length > 0) continue;

                // Find label or placeholder
                let labelText = '';
                if (el.id) {
                    const l = document.querySelector(`label[for="${el.id}"]`);
                    if (l) labelText = l.innerText || '';
                }
                if (!labelText && el.closest('label')) {
                    labelText = el.closest('label').innerText || '';
                }
                if (!labelText) {
                    labelText = el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '';
                }

                results.push({
                    id: el.id || '',
                    name: el.name || '',
                    type: el.type || 'text',
                    placeholder: el.placeholder || '',
                    label: labelText.slice(0, 100).trim(),
                    tag: el.tagName.toLowerCase(),
                });
            }
            return results.slice(0, 20);
        }""")

        if not unfilled_inputs:
            return []

        known_profile = {
            k: str(candidate_info.get(k) or "").strip()
            for k in (
                "full_name", "first_name", "last_name", "email", "phone",
                "location", "city", "state", "country",
                "linkedin", "github", "portfolio",
                "current_company", "current_title", "university", "degree",
                "work_authorization", "sponsorship_required", "notice_period", "expected_salary",
            )
            if str(candidate_info.get(k) or "").strip()
        }
        prompt = (
            f"You are AutoBot Form Field Mapper.\n"
            f"Known Candidate Profile (STRICTLY use ONLY these facts; never invent missing values):\n"
            f"{json.dumps(known_profile, indent=2)}\n\n"
            f"Here are the unfilled form inputs found on the webpage:\n"
            f"{json.dumps(unfilled_inputs, indent=2)}\n\n"
            f"Map each input to an explicit known value above, or omit/set field_type='unknown' with empty fill_value if not present.\n"
            f"Output ONLY a JSON object:\n"
            f'{{"mappings": [{{"id": "<id or name>", "field_type": "<firstName|lastName|fullName|email|phone|location|workAuth|sponsorship|unknown>", "fill_value": "<value or empty>"}}]}}'
        )

        res = call_groq_json(prompt, timeout=5.0)
        if res and isinstance(res.get("mappings"), list):
            return res["mappings"]
    except Exception as ex:
        logger.debug(f"[groq-form-assistant] Map fields error: {ex}")

    return []
