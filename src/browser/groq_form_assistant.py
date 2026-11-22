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
        return None

    base_url = os.environ.get("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL).rstrip("/")
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    endpoint = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "AutoBot/2.0 (FormAssistant)",
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
