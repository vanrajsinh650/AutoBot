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


def answer_question_with_groq(
    question: str,
    options: Optional[List[str]] = None,
    field_type: str = "text",
    candidate_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Intelligently answer ANY form screening question, dropdown, or custom text input
    using Groq AI with the candidate's verified profile data.
    """
    candidate = candidate_info or {}
    q_lower = (question or "").lower()

    # 0a. Conditional follow-up text fields ("If you answered Yes...", "If yes, please...")
    # We default to negative on prior screening checks, so conditional detail boxes take N/A (not job title).
    if not options and any(
        p in q_lower for p in (
            "if you answered yes", "if you answered \"yes\"", "if you answered 'yes'",
            "if yes,", "if yes please", "if you selected yes", "if applicable, please",
            "if different than above", "please share the name and your relationship",
            "name used during your employment",
        )
    ):
        return "N/A"

    # 0b. Referral source ("How did you hear about...") - must check BEFORE LinkedIn URL matching
    if any(k in q_lower for k in ("how did you hear", "source of referral", "referral source", "where did you hear", "hear about")):
        if options:
            for o in options:
                if "linkedin" in o.lower():
                    return o
            for o in options:
                if any(s in o.lower() for s in ("job board", "career site", "company website", "online")):
                    return o
            return options[0]
        return "LinkedIn"

    # 0c. Candidate Social / Portfolio / Name / Education / Employer fields (BEFORE Yes/No patterns!)
    if "linkedin" in q_lower:
        if options:
            for o in options:
                if o.strip().lower().startswith("yes"):
                    return o
            return options[0]
        return candidate.get("linkedin", "https://linkedin.com/in/vanrajsinh")

    if "github" in q_lower:
        if not options:
            return candidate.get("github", "https://github.com/vanrajsinh650")

    if any(k in q_lower for k in ("personal website", "portfolio", "website or blog", "blog", "website")):
        if not options:
            return candidate.get("portfolio", "https://github.com/vanrajsinh650")

    if "preferred first" in q_lower:
        return candidate.get("first_name", "Vanraj")
    if "preferred last" in q_lower:
        return candidate.get("last_name", "Solanki")
    if any(k in q_lower for k in ("preferred name", "legal name")):
        return candidate.get("full_name", "Vanraj Solanki")

    if any(k in q_lower for k in ("school", "university", "college", "institution")):
        if not options:
            return candidate.get("university", "Gokul Global University")

    if any(k in q_lower for k in ("degree", "qualification")) and "years" not in q_lower:
        if options:
            for o in options:
                if any(d in o.lower() for d in ("bachelor", "bca", "b.sc", "undergraduate")):
                    return o
        else:
            return candidate.get("degree", "Bachelor of Computer Applications (BCA)")

    if any(k in q_lower for k in ("discipline", "major", "field of study")):
        if options:
            for o in options:
                if any(m in o.lower() for m in ("computer", "software", "information technology")):
                    return o
        else:
            return candidate.get("major", "Computer Applications")

    if any(k in q_lower for k in ("current company", "current employer", "present employer")):
        if not options:
            return candidate.get("current_company", "DivineHindu")

    # 0d. Geographic Location & Relocation checks ("Are you currently based in ...?", "willing to relocate")
    candidate_city = (candidate.get("city") or "Ahmedabad").lower()
    candidate_state = (candidate.get("state") or "Gujarat").lower()
    candidate_country = (candidate.get("country") or "India").lower()

    if any(k in q_lower for k in ("currently based in", "based in", "currently reside", "currently live", "live in")):
        if options:
            # First check if candidate's actual city/state/country is explicitly an option
            for o in options:
                o_low = o.lower()
                if any(loc in o_low for loc in (candidate_city, candidate_state, candidate_country) if loc):
                    return o
            # Otherwise look for "outside ... relocate / relocation support" or "willing to relocate"
            for o in options:
                o_low = o.lower()
                if ("relocat" in o_low or "support" in o_low) and ("willing" in o_low or "outside" in o_low or "require" in o_low) and "not willing" not in o_low and "do not live" not in o_low:
                    return o
            for o in options:
                o_low = o.lower()
                if any(out in o_low for out in ("outside", "not based", "neither", "other")) and "not willing" not in o_low:
                    return o
            # Binary Yes/No fallback based on whether candidate city/country is mentioned in question (skip if asking willingness to relocate)
            if "relocat" not in q_lower:
                cand_in_question = any(loc in q_lower for loc in (candidate_city, candidate_state, candidate_country) if loc)
                target_word = "yes" if cand_in_question else "no"
                for o in options:
                    if target_word in o.lower().split() or o.lower().strip().startswith(target_word):
                        return o

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
            # On sponsorship questions, never falsely claim foreign citizenship/PR when plain "No" is absent
            citizenship_tokens = ("citizen", "permanent resident", "green card", "national", "passport")
            # Pass 1: clean non-citizenship "No" options
            for o in options:
                o_low = o.lower()
                if any(n in o_low for n in ("no", "none", "neither", "false", "never", "not applicable", "n/a", "decline")):
                    if is_sponsorship_q and any(ct in o_low for ct in citizenship_tokens):
                        if candidate_country not in o_low:
                            continue
                    return o
            # Pass 2: if sponsorship options only have "Yes" vs false foreign citizenship, choose "Yes" truthfully
            if is_sponsorship_q:
                for o in options:
                    if o.strip().lower().startswith("yes"):
                        return o
            for o in options:
                o_low = o.lower()
                if any(n in o_low for n in ("no", "none", "neither", "false", "never", "not applicable", "n/a", "decline")):
                    return o
        return "No"

    # 2. Positive screening questions (Instant "Yes" - work auth, legal right, 18+, background consent, relocate)
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
                if "not willing" in o_low or "do not require relocation" in o_low and "already live" in o_low:
                    continue
                if any(y in o_low for y in ("yes", "authorized", "eligible", "agree", "consent", "willing")):
                    return o
        return "Yes"

    # 3. Notice period & Availability
    if any(k in q_lower for k in ("notice period", "availability", "how soon can you start", "available to start", "start date", "earliest start")):
        if options:
            for o in options:
                o_low = o.lower()
                if any(imm in o_low for imm in ("immediate", "immediately", "15", "1-2 weeks", "2 weeks", "less than 1 month")):
                    return o
            return options[0]
        return "Immediate"

    # 4. Salary / CTC / Compensation
    if any(k in q_lower for k in ("salary", "compensation", "ctc", "expected monthly", "expected annual", "expected pay", "basic salary")):
        expected_val = str(candidate.get("expected_salary") or "100000")
        if options:
            for o in options:
                if any(c in o.lower() for c in ("100,000", "100000", "10-15", "competitive", "negotiable")):
                    return o
            return options[0]
        return expected_val

    # 5. EEOC / Diversity & Inclusion (Gender, Disability, Veteran, Race, Referral Source)
    if any(k in q_lower for k in ("gender", "sex")) and not any(w in q_lower for w in ("sexual orientation",)):
        if options:
            for o in options:
                o_low = o.lower().strip()
                if "female" not in o_low and ("male" in o_low or "man" in o_low or any(g in o_low for g in ("decline", "prefer not"))):
                    return o
            return options[0]
        return "Male"

    if any(k in q_lower for k in ("disability", "disabled", "handicap")):
        if options:
            for o in options:
                if any(d in o.lower() for d in ("no, i don't have", "no disability", "do not have a disability", "no", "decline", "prefer not")):
                    return o
            return options[0]
        return "No"

    if any(k in q_lower for k in ("veteran", "military")):
        if options:
            for o in options:
                if any(v in o.lower() for v in ("not a protected veteran", "i am not a protected", "not a veteran", "no", "decline", "prefer not")):
                    return o
            return options[0]
        return "No"

    if any(k in q_lower for k in ("race", "ethnicity", "ethnic origin")):
        if options:
            for o in options:
                o_low = o.lower()
                if "american indian" in o_low:
                    continue
                if any(r in o_low for r in ("asian", "south asian")):
                    return o
            for o in options:
                if any(d in o.lower() for d in ("decline", "prefer not to say", "do not wish")):
                    return o
            return options[0]
        return "Asian"

    # 5c. Total years of work experience (non-skill-specific)
    if any(k in q_lower for k in ("years of experience", "years of relevant", "total years", "work experience")) and "with " not in q_lower:
        if not options:
            return str(candidate.get("years_of_experience") or "1")

    # 5d. Government ID / sensitive PII (PAN, SSN, Aadhaar, Passport) - never hallucinate
    if any(k in q_lower for k in ("pan number", "pan card", "aadhaar", "ssn", "social security", "passport number")):
        return ""

    # 5e. Strict URL input guard: never return non-URL prose for <input type="url">
    if field_type == "url":
        if any(k in q_lower for k in ("video", "loom", "youtube", "recording")):
            return ""
        return candidate.get("portfolio", "https://github.com/vanrajsinh650")

    # 5b. Pronouns & Relocation Referral moved above; handle Pronouns here
    if "pronoun" in q_lower:
        if options:
            for o in options:
                if "he/him" in o.lower():
                    return o
            return options[0]
        return "He/Him"

    # 6. Job Title / Current Role (ONLY when explicitly requested!)
    if any(k in q_lower for k in ("current title", "job title", "current role", "designation", "position title", "current position")):
        return candidate.get("current_title", "Software & AI Automation Engineer")

    # Use Groq LLM for domain-specific, complex, or unknown questions
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
        f"- Disability: No disability / Decline to state"
    )

    if options:
        prompt = (
            f"You are AutoBot Job Application Form Assistant.\n"
            f"Candidate Profile & Verified Answers:\n{candidate_summary}\n\n"
            f"Question: \"{question}\"\n"
            f"Options: {json.dumps(options)}\n\n"
            f"RULES:\n"
            f"1. Pick the SINGLE BEST matching option string from the options list that accurately represents the candidate.\n"
            f"2. For screening questions regarding relatives, former employment, referrals, termination, or misconduct, select the negative ('No' / 'None') option.\n"
            f"Output strictly a JSON object: {{\"best_option\": \"<exact string from options>\"}}"
        )
        res = call_groq_json(prompt, timeout=4.5)
        if res and res.get("best_option"):
            best = str(res["best_option"]).strip()
            # Verify it matches one of the options
            for opt in options:
                if opt.lower().strip() == best.lower().strip() or best.lower() in opt.lower():
                    return opt
            return best
        # Fallback to first non-empty option
        return options[0] if options else ""
    else:
        prompt = (
            f"You are AutoBot Job Application Form Assistant.\n"
            f"Candidate Profile & Verified Answers:\n{candidate_summary}\n\n"
            f"Form Question/Field Label: \"{question}\"\n"
            f"RULES:\n"
            f"1. If this is a Yes/No screening question (relatives, former employee, referral, termination, crime), answer 'No'.\n"
            f"2. NEVER output the candidate's job title or technical skills unless the field label explicitly asks for current job title or skills.\n"
            f"3. Provide only the exact, concise string to type into this input field.\n"
            f"Output strictly a JSON object: {{\"answer\": \"<value>\"}}"
        )
        res = call_groq_json(prompt, timeout=4.5)
        if res and res.get("answer") is not None:
            return str(res["answer"]).strip()

    return ""


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
