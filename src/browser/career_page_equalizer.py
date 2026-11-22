"""
AutoBot Career Page Requisition Equalizer.

Solves the generic career hub problem:
When companies provide or resolve to a general directory path like `/careers/`,
`/jobs/`, or `/openings/` containing dozens of postings, this module
automatically pinpoints and equalizes the exact job requisition matching what
was found on LinkedIn (title, location, keywords, requisition ID).

Multi-Tier Equalizer Architecture:
- Tier 1: Instant deterministic fuzzy token & requisition ID matching (0ms).
- Tier 2: Groq High-Throughput LPU LLM inference (free, ~200-300ms) with structured JSON output.
- Live Tab Navigation: Directs the Playwright tab directly to the matched requisition.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from src.utils.logger import logger


DEFAULT_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DEFAULT_GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Synonyms for title token normalization
TITLE_SYNONYMS: Dict[str, str] = {
    "sr": "senior",
    "snr": "senior",
    "jr": "junior",
    "dev": "developer",
    "eng": "engineer",
    "mgr": "manager",
    "dir": "director",
    "vp": "vice president",
    "tech": "technical",
    "swe": "software engineer",
    "sde": "software development engineer",
    "qa": "quality assurance",
    "fullstack": "full stack",
    "frontend": "front end",
    "backend": "back end",
}

GENERIC_DIRECTORY_PATTERNS: List[str] = [
    r"^/careers/?$",
    r"^/career/?$",
    r"^/jobs/?$",
    r"^/job/?$",
    r"^/en/careers/?$",
    r"^/en-us/careers/?$",
    r"^/openings/?$",
    r"^/current-openings/?$",
    r"^/opportunities/?$",
    r"^/join-us/?$",
    r"^/work-with-us/?$",
]

EXCLUDED_HREF_PATTERNS: List[str] = [
    r"javascript:",
    r"mailto:",
    r"tel:",
    r"#",
    r"/privacy",
    r"/terms",
    r"/cookie",
    r"/about",
    r"/contact",
    r"/login",
    r"/signin",
    r"/signup",
    r"/register",
    r"/blog",
    r"/press",
    r"/news",
    r"/investor",
    r"/leadership",
    r"/support",
    r"/faq",
]


def is_generic_career_hub_url(url: str) -> bool:
    """Check if a URL represents a generic career directory rather than a specific requisition."""
    if not url or not isinstance(url, str):
        return False
    parsed = urllib.parse.urlparse(url.strip())
    path = parsed.path.rstrip("/")
    if not path or path == "":
        return True
    for pat in GENERIC_DIRECTORY_PATTERNS:
        if re.search(pat, path, re.IGNORECASE):
            # If there is no specific query with a job ID, it's a generic hub
            if not parsed.query or not any(k in parsed.query.lower() for k in ("jobid", "req", "jid", "id=")):
                return True
    return False


def normalize_tokens(text: str) -> set[str]:
    """Tokenize and normalize text, expanding common role abbreviations."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    normalized = set()
    for w in words:
        normalized.add(TITLE_SYNONYMS.get(w, w))
    return normalized


def extract_candidate_links_from_html(html: str, base_url: str = "") -> List[Dict[str, str]]:
    """
    Parse HTML to extract outbound or intra-site job links with link text and context snippets.
    Filters out navigation, policy, and social links.
    """
    if not html:
        return []

    candidates: List[Dict[str, str]] = []
    seen_urls: set[str] = set()

    # Find anchor tags: <a ... href="..." ...>text</a>
    anchor_regex = re.compile(
        r'<a\s+[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in anchor_regex.finditer(html):
        href = match.group(1).strip()
        raw_text = re.sub(r"<[^>]+>", " ", match.group(2)).strip()
        raw_text = re.sub(r"\s+", " ", raw_text)

        if not href or href.startswith("#") or any(re.search(p, href, re.IGNORECASE) for p in EXCLUDED_HREF_PATTERNS):
            continue

        full_url = urllib.parse.urljoin(base_url, href) if base_url else href
        parsed = urllib.parse.urlparse(full_url)
        if not parsed.scheme or not parsed.netloc:
            continue

        if full_url in seen_urls:
            continue

        # Look for job-like markers in href or text
        href_lower = href.lower()
        is_job_like = any(
            marker in href_lower
            for marker in (
                "/job/", "/jobs/", "/career/", "/careers/", "/position/", "/positions/",
                "/openings/", "/opening/", "req", "requisition", "gh_jid", "jobid",
                "lever.co", "myworkdayjobs.com", "greenhouse.io", "smartrecruiters", "ashbyhq"
            )
        ) or any(
            kw in raw_text.lower()
            for kw in (
                "engineer", "developer", "architect", "manager", "lead", "designer",
                "analyst", "consultant", "specialist", "intern", "associate", "officer"
            )
        )

        if not is_job_like:
            continue

        seen_urls.add(full_url)
        candidates.append({
            "url": full_url,
            "title": raw_text or href.split("/")[-1].replace("-", " ").title(),
            "snippet": raw_text,
        })

    return candidates


def fuzzy_match_candidate(
    target_title: str,
    candidates: List[Dict[str, str]],
    req_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """
    Tier-1 Fast deterministic matcher (0ms).
    Computes token overlap, requisition ID match, and location compatibility.
    """
    if not target_title or not candidates:
        return None

    target_tokens = normalize_tokens(target_title)
    if not target_tokens:
        return None

    best_match: Optional[Dict[str, str]] = None
    best_score = 0.0
    second_best_score = 0.0

    for cand in candidates:
        cand_url = cand.get("url", "")
        cand_text = f"{cand.get('title', '')} {cand.get('snippet', '')} {cand_url}"
        cand_tokens = normalize_tokens(cand_text)

        # 1. Exact Requisition ID match is immediate winner
        if req_id and req_id.lower() in cand_text.lower():
            return cand

        # 2. Token overlap score
        intersection = target_tokens.intersection(cand_tokens)
        score = len(intersection) / float(len(target_tokens))

        # Check location bonus
        if location and normalize_tokens(location).intersection(cand_tokens):
            score += 0.15

        if score > best_score:
            second_best_score = best_score
            best_score = score
            best_match = cand
        elif score > second_best_score:
            second_best_score = score

    # Strict confidence floor and margin of victory for Tier 1
    if best_score >= 0.75 and (best_score - second_best_score >= 0.15 or best_score >= 0.90):
        return best_match

    return None


def llm_match_candidate_groq(
    target_job: Dict[str, str],
    candidates: List[Dict[str, str]],
    groq_api_key: Optional[str] = None,
    groq_model: Optional[str] = None,
    groq_base_url: Optional[str] = None,
    timeout: float = 8.0,
) -> Optional[Dict[str, str]]:
    """
    Tier-2 Groq High-Throughput LPU LLM Requisition Matcher.
    Uses free Groq inference to pick the exact requisition link from candidate links.
    """
    api_key = (
        groq_api_key
        or os.environ.get("GROQ_API_KEY")
        or DEFAULT_GROQ_API_KEY
    )
    if not api_key or not candidates:
        return None

    model = groq_model or os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL
    base_url = (groq_base_url or os.environ.get("GROQ_BASE_URL") or DEFAULT_GROQ_BASE_URL).rstrip("/")

    # Cap candidates to top 25 to fit within token limits and optimize inference speed
    limited_candidates = candidates[:25]
    candidate_summary = []
    url_map = {}
    for idx, c in enumerate(limited_candidates, 1):
        u = c["url"]
        t = c.get("title", "")
        url_map[u] = c
        candidate_summary.append(f"{idx}. URL: {u} | Title: {t}")

    prompt = (
        f"You are AutoBot Career Requisition Equalizer.\n"
        f"We found a job on LinkedIn, but the company's website is a multi-job career directory.\n"
        f"Target Job From LinkedIn:\n"
        f"- Title: {target_job.get('title', '')}\n"
        f"- Company: {target_job.get('company', '')}\n"
        f"- Location: {target_job.get('location', '')}\n"
        f"- Description/Keywords: {target_job.get('keywords', '')}\n\n"
        f"Candidate Job Links Found on Career Directory:\n"
        + "\n".join(candidate_summary)
        + "\n\nSelect the EXACT matching job link that corresponds to the target job.\n"
        f"Output ONLY a valid JSON object matching this schema:\n"
        f'{{"matched_url": "<exact url from candidate list or empty string>", "confidence": <float between 0.0 and 1.0>, "reason": "<brief justification>"}}'
    )

    endpoint = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "AutoBot/2.0 (CareerEqualizer)",
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
            result = json.loads(content)

            matched_url = (result.get("matched_url") or "").strip()
            confidence = float(result.get("confidence") or 0.0)
            reason = result.get("reason", "")

            logger.info(
                f"[browser]Groq Equalizer Match: url='{matched_url}', conf={confidence:.2f}, reason='{reason}'"
            )

            if matched_url and confidence >= 0.5:
                # Find the candidate matching this URL
                if matched_url in url_map:
                    return url_map[matched_url]
                for u, c in url_map.items():
                    if matched_url.lower() in u.lower() or u.lower() in matched_url.lower():
                        return c
    except Exception as ex:
        logger.warning(f"[browser]Groq LLM Requisition Equalizer call failed: {ex}")

    return None


async def equalize_career_hub_url(
    page: Any,
    target_title: str,
    company: str = "",
    location: str = "",
    current_url: Optional[str] = None,
    groq_api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Live Browser Requisition Equalizer.
    If the current tab is on a multi-job directory or generic career page,
    extracts candidate links, runs Tier 1 fuzzy match or Tier 2 Groq LLM,
    and automatically navigates the tab directly to the specific job requisition.

    Returns:
        The matched requisition URL if navigated successfully, or None if no equalization needed/found.
    """
    try:
        page_url = current_url or getattr(page, "url", "") or ""
        # 1. Quick check: Is this page a generic career directory?
        if not is_generic_career_hub_url(page_url):
            # Check if page has multiple job postings
            pass

        # 2. Extract job links directly from page DOM
        links_data = await page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const results = [];
            const seen = new Set();
            for (const a of anchors) {
                const href = a.href;
                if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:')) continue;
                if (seen.has(href)) continue;
                seen.add(href);

                const text = (a.innerText || a.textContent || '').trim();
                const parentText = (a.parentElement ? (a.parentElement.innerText || '') : '').slice(0, 200).trim();
                results.push({
                    url: href,
                    title: text,
                    snippet: parentText
                });
            }
            return results;
        }""")

        if not links_data or len(links_data) == 0:
            return None

        # Filter candidate links
        filtered_candidates = []
        for c in links_data:
            u_lower = c["url"].lower()
            t_lower = c["title"].lower()
            if any(re.search(p, u_lower) for p in EXCLUDED_HREF_PATTERNS):
                continue
            if any(marker in u_lower for marker in ("/job/", "/jobs/", "/career/", "/careers/", "/position/", "/openings/", "req", "lever.co", "myworkdayjobs.com", "greenhouse.io")) or any(kw in t_lower for kw in ("engineer", "developer", "lead", "manager", "architect", "analyst")):
                filtered_candidates.append(c)

        if not filtered_candidates:
            return None

        # 3. Tier 1: Fast rule / fuzzy match
        matched = fuzzy_match_candidate(target_title, filtered_candidates, location=location)

        # 4. Tier 2: Groq LLM Equalizer if Tier 1 is ambiguous or multiple candidates
        if not matched and len(filtered_candidates) > 1:
            target_job = {
                "title": target_title,
                "company": company,
                "location": location,
            }
            matched = llm_match_candidate_groq(target_job, filtered_candidates, groq_api_key=groq_api_key)

        if matched and matched.get("url"):
            target_req_url = matched["url"]
            if target_req_url != page_url:
                logger.info(
                    f"[browser]🎯 Career Equalizer pinpointed exact job requisition: {target_req_url} "
                    f"for '{target_title}' @ '{company}'"
                )
                await page.goto(target_req_url, wait_until="domcontentloaded", timeout=25000)
                
                # Dismiss cookie banners on the new requisition page
                from src.browser.cookie_handler import dismiss_cookie_banners
                await dismiss_cookie_banners(page)
                return target_req_url
    except Exception as ex:
        logger.warning(f"[browser]Career Page Equalizer encounter: {ex}")

    return None


def resolve_career_hub_requisition_offline(
    hub_url: str,
    target_title: str,
    company: str = "",
    location: str = "",
    groq_api_key: Optional[str] = None,
    timeout: float = 4.0,
) -> Optional[str]:
    """
    Offline/HTTP-based Requisition Equalizer.
    Fetches the career hub HTML, extracts candidates, and resolves the exact requisition URL
    without requiring an active browser tab.
    """
    if not hub_url or not target_title:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        req = urllib.request.Request(hub_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            candidates = extract_candidate_links_from_html(html, base_url=hub_url)
            if not candidates:
                return None

            # Tier 1: Fuzzy match
            match = fuzzy_match_candidate(target_title, candidates, location=location)
            if match:
                return match["url"]

            # Tier 2: Groq LLM Match
            if len(candidates) > 1:
                target_job = {
                    "title": target_title,
                    "company": company,
                    "location": location,
                }
                llm_match = llm_match_candidate_groq(target_job, candidates, groq_api_key=groq_api_key)
                if llm_match:
                    return llm_match["url"]
    except Exception as ex:
        logger.debug(f"Offline requisition equalizer failed for {hub_url}: {ex}")

    return None
