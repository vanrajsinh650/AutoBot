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

    # 0c. Candidate Social / Portfolio / Name / Education / Employer fields (BEFORE Yes/No patterns!)
    if "linkedin" in q_lower:
        if options:
            for o in options:
                if o.strip().lower().startswith("yes"):
                    return _ok(o, reason="LinkedIn profile confirmation")
            return _need_user("Unclear LinkedIn dropdown options")
        return _ok(candidate.get("linkedin", "https://linkedin.com/in/vanrajsinh"), reason="Profile LinkedIn URL")

    if "github" in q_lower:
        if not options:
            return _ok(candidate.get("github", "https://github.com/vanrajsinh650"), reason="Profile GitHub URL")

    if any(k in q_lower for k in ("personal website", "portfolio", "website or blog", "blog", "website")):
        if not options:
            return _ok(candidate.get("portfolio", "https://github.com/vanrajsinh650"), reason="Profile portfolio URL")

    if "preferred first" in q_lower:
        return _ok(candidate.get("first_name", "Vanraj"), reason="Profile first name")
    if "preferred last" in q_lower:
        return _ok(candidate.get("last_name", "Solanki"), reason="Profile last name")
    if any(k in q_lower for k in ("preferred name", "legal name")):
        return _ok(candidate.get("full_name", "Vanraj Solanki"), reason="Profile full name")

    if any(k in q_lower for k in ("school", "university", "college", "institution")):
        if not options:
            return _ok(candidate.get("university", "Gokul Global University"), reason="Profile university")

    if any(k in q_lower for k in ("degree", "qualification")) and "years" not in q_lower:
        if options:
            for o in options:
                if any(d in o.lower() for d in ("bachelor", "bca", "b.sc", "undergraduate")):
                    return _ok(o, reason="Profile degree")
        else:
            return _ok(candidate.get("degree", "Bachelor of Computer Applications (BCA)"), reason="Profile degree")

    if any(k in q_lower for k in ("discipline", "major", "field of study")):
        if options:
            for o in options:
                if any(m in o.lower() for m in ("computer", "software", "information technology")):
                    return _ok(o, reason="Profile major")
        else:
            return _ok(candidate.get("major", "Computer Applications"), reason="Profile major")

    if any(k in q_lower for k in ("current company", "current employer", "present employer")):
        if not options:
            return _ok(candidate.get("current_company", "DivineHindu"), reason="Profile current company")

    # 0d. Geographic Location & Relocation checks ("Are you currently based in ...?", "willing to relocate")
    candidate_city = (candidate.get("city") or "Ahmedabad").lower()
    candidate_state = (candidate.get("state") or "Gujarat").lower()
    candidate_country = (candidate.get("country") or "India").lower()

    if any(k in q_lower for k in ("currently based in", "based in", "currently reside", "currently live", "live in")):
        if options:
            for o in options:
                o_low = o.lower()
                if any(loc in o_low for loc in (candidate_city, candidate_state, candidate_country) if loc):
                    return _ok(o, reason="Location matches candidate residence")
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
        if options:
            for o in options:
                o_low = o.lower()
                if any(imm in o_low for imm in ("immediate", "immediately", "15", "1-2 weeks", "2 weeks", "less than 1 month")):
                    return _ok(o, src="config", reason="Configured notice period")
            return _need_user(f"No matching availability option for notice period in: {options}")
        return _ok(str(candidate.get("notice_period") or "Immediate"), src="config", reason="Configured notice period")

    # 4. Salary / CTC / Compensation
    if any(k in q_lower for k in ("salary", "compensation", "ctc", "expected monthly", "expected annual", "expected pay", "basic salary")):
        expected_val = str(candidate.get("expected_salary") or "").strip()
        if not expected_val:
            return _need_user("Expected compensation question has no configured salary preference")
        if options:
            for o in options:
                if any(c in o.lower() for c in ("100,000", "100000", "10-15", "competitive", "negotiable", expected_val.lower())):
                    return _ok(o, src="config", reason="Configured salary expectation")
            return _need_user(f"Salary dropdown options {options} did not match configured '{expected_val}'")
        return _ok(expected_val, src="config", reason="Configured salary expectation")

    # 5. EEOC / Diversity & Inclusion
    if any(k in q_lower for k in ("gender", "sex")) and "sexual orientation" not in q_lower:
        if options:
            for o in options:
                o_low = o.lower().strip()
                if "female" not in o_low and ("male" in o_low or "man" in o_low or any(g in o_low for g in ("decline", "prefer not"))):
                    return _ok(o, reason="EEOC gender")
            return _need_user("Unrecognized gender dropdown options")
        return _ok("Male", reason="Profile gender")

    if any(k in q_lower for k in ("disability", "disabled", "handicap")):
        if options:
            for o in options:
                if any(d in o.lower() for d in ("no, i don't have", "no disability", "do not have a disability", "no", "decline", "prefer not")):
                    return _ok(o, reason="EEOC disability")
            return _need_user("Unrecognized disability dropdown options")
        return _ok("No", reason="EEOC disability")

    if any(k in q_lower for k in ("veteran", "military")):
        if options:
            for o in options:
                if any(v in o.lower() for v in ("not a protected veteran", "i am not a protected", "not a veteran", "no", "decline", "prefer not")):
                    return _ok(o, reason="EEOC veteran")
            return _need_user("Unrecognized veteran dropdown options")
        return _ok("No", reason="EEOC veteran")

    if any(k in q_lower for k in ("race", "ethnicity", "ethnic origin")):
        if options:
            for o in options:
                o_low = o.lower()
                if "american indian" in o_low:
                    continue
                if any(r in o_low for r in ("asian", "south asian")):
                    return _ok(o, reason="EEOC race")
            for o in options:
                if any(d in o.lower() for d in ("decline", "prefer not to say", "do not wish")):
                    return _ok(o, reason="EEOC decline")
            return _need_user("Unrecognized race/ethnicity dropdown options")
        return _ok("Asian", reason="EEOC race")

    # 5b. Country dropdowns / inputs ("Country", "Country of residence")
    if any(k in q_lower for k in ("country", "country of residence", "location (country)")) and "dial" not in q_lower and "code" not in q_lower:
        cand_country = str(candidate.get("country") or "India").strip()
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
        if not options:
            return _ok(str(candidate.get("graduation_year") or "2025"), reason="Profile graduation year")

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
        yoe = str(candidate.get("years_of_experience") or "1")
        if options:
            if any(o.strip().lower().startswith("yes") for o in options):
                return _ok(next(o for o in options if o.strip().lower().startswith("yes")), src="profile", reason=f"Verified skill '{matched_skill}' in profile")
            for o in options:
                if yoe in o or "1-2" in o.lower() or "1+" in o.lower() or "less than 2" in o.lower():
                    return _ok(o, src="profile", reason=f"Verified years with '{matched_skill}'")
        else:
            if "years" in q_lower or "how many" in q_lower or field_type == "number":
                return _ok(yoe, src="profile", reason=f"Verified years with '{matched_skill}'")
            return _ok("Yes", src="profile", reason=f"Verified skill '{matched_skill}' in profile")

    # 5e. Total years of work experience (non-skill-specific)
    if any(k in q_lower for k in ("years of experience", "years of relevant", "total years", "work experience")) and "with " not in q_lower:
        if not options:
            return _ok(str(candidate.get("years_of_experience") or "1"), src="config", reason="Configured years of experience")

    # 5f. Government ID / sensitive PII (PAN, SSN, Aadhaar, Passport) - NEVER hallucinate; pause for user
    if any(k in q_lower for k in ("pan number", "pan card", "aadhaar", "ssn", "social security", "passport number", "driver's license", "drivers license")):
        return _need_user("Sensitive government ID / PII requires explicit candidate input")

    # 5g. Strict URL input guard: never return non-URL prose for <input type="url">
    if field_type == "url":
        if any(k in q_lower for k in ("video", "loom", "youtube", "recording")):
            return _need_user("Custom video/recording URL must be provided by candidate")
        return _ok(candidate.get("portfolio", "https://github.com/vanrajsinh650"), reason="Profile portfolio URL")

    # 5h. Pronouns
    if "pronoun" in q_lower:
        if options:
            for o in options:
                if "he/him" in o.lower():
                    return _ok(o, reason="Profile pronouns")
            for o in options:
                if any(d in o.lower() for d in ("decline", "prefer not")):
                    return _ok(o, reason="Decline pronouns")
            return _need_user("Unrecognized pronoun options")
        return _ok("He/Him", reason="Profile pronouns")

    # 6. Job Title / Current Role (ONLY when explicitly requested!)
    if any(k in q_lower for k in ("current title", "job title", "current role", "designation", "position title", "current position")):
        return _ok(candidate.get("current_title", "Software & AI Automation Engineer"), reason="Profile current job title")

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

    candidate_summary = (
        f"Candidate Full Name: {candidate.get('full_name', 'Vanraj Solanki')}\n"
        f"Candidate Email: {candidate.get('email', 'vanrajsolanki2875@gmail.com')}\n"
        f"Candidate Phone: {candidate.get('phone', '+91-8320452875')}\n"
        f"Candidate Location: {candidate.get('location', 'Ahmedabad, Gujarat, India')}\n"
        f"LinkedIn: {candidate.get('linkedin', 'https://linkedin.com/in/vanrajsinh')}\n"
        f"GitHub: {candidate.get('github', 'https://github.com/vanrajsinh650')}\n"
        f"Current Company: {candidate.get('current_company', 'DivineHindu')}\n"
        f"Current Job Title: {candidate.get('current_title', 'AI Executive Intern / Software & Automation Engineer')}\n"
        f"Years of Experience: {candidate.get('years_of_experience', '1+')} years in Python backend systems, AI agents, and automation\n"
        f"Education: {candidate.get('degree', 'Bachelor of Computer Applications (BCA)')} at {candidate.get('university', 'Gokul Global University')}\n"
        f"Notice Period: {candidate.get('notice_period', 'Immediate')}\n"
        f"Work Authorization: Authorized in India; willing to relocate internationally if supported\n"
        f"Screening Defaults:\n"
        f"- Friends or relatives employed at company: No\n"
        f"- Previously applied or former employee: No\n"
        f"- Referred by employee: No\n"
        f"- Terminated or asked to resign: No\n"
        f"- Criminal convictions / record: No\n"
        f"- Conflict of interest / non-compete: No\n"
        f"- Veteran: Not a protected veteran\n"
        f"- Disability: No disability / Decline to state\n"
        f"{learned_ctx}"
    )

    if options:
        prompt = (
            f"You are AutoBot Job Application Form Assistant.\n"
            f"Candidate Profile & Verified Answers:\n{candidate_summary}\n\n"
            f"Question: \"{question}\"\n"
            f"Options: {json.dumps(options)}\n\n"
            f"RULES:\n"
            f"1. Pick the SINGLE BEST matching option string from the options list ONLY if it is clearly supported by Candidate Profile or User-Taught Rules.\n"
            f"2. If this is a NEW / ambiguous / legal / compensation / clearance / certification / personal question where the candidate's true answer is unknown or confidence < 0.75, set \"needs_user_input\": true and DO NOT GUESS.\n"
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

        prompt = (
            f"You are AutoBot Form Field Mapper.\n"
            f"Candidate profile to fill into the job application:\n"
            f"- first_name: {candidate_info.get('first_name', 'Vanraj')}\n"
            f"- last_name: {candidate_info.get('last_name', 'Solanki')}\n"
            f"- email: {candidate_info.get('email', 'vanrajsolanki2875@gmail.com')}\n"
            f"- phone: {candidate_info.get('phone', '+91-8320452875')}\n"
            f"- location: {candidate_info.get('location', 'India')}\n"
            f"- work_authorization: 'Yes'\n"
            f"- sponsorship_required: 'No'\n\n"
            f"Here are the unfilled form inputs found on the webpage:\n"
            f"{json.dumps(unfilled_inputs, indent=2)}\n\n"
            f"Map each input to the exact value to fill.\n"
            f"Output ONLY a JSON object:\n"
            f'{{"mappings": [{{"id": "<id or name>", "field_type": "<firstName|lastName|fullName|email|phone|location|workAuth|sponsorship|unknown>", "fill_value": "<value>"}}]}}'
        )

        res = call_groq_json(prompt, timeout=5.0)
        if res and isinstance(res.get("mappings"), list):
            return res["mappings"]
    except Exception as ex:
        logger.debug(f"[groq-form-assistant] Map fields error: {ex}")

    return []
