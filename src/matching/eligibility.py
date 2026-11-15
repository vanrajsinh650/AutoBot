"""
Eligibility Rules Engine for AutoBot v2.
Evaluates employment type and country/location eligibility into:
- 'eligible'
- 'uncertain'
- 'ineligible'
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple

from src.discovery.models import EmploymentType, NormalizedJob


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    UNCERTAIN = "uncertain"
    INELIGIBLE = "ineligible"


COUNTRY_SYNONYMS = {
    "us": "united states",
    "usa": "united states",
    "united states of america": "united states",
    "in": "india",
    "ind": "india",
    "uk": "united kingdom",
    "gb": "united kingdom",
    "great britain": "united kingdom",
    "ca": "canada",
    "de": "germany",
    "fr": "france",
    "au": "australia",
    "nl": "netherlands",
    "sg": "singapore",
    "jp": "japan",
    "ch": "switzerland",
    "se": "sweden",
    "ie": "ireland",
}

US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"
}

MAJOR_CITIES_BY_COUNTRY = {
    "united states": {
        "san francisco", "sf", "bay area", "new york", "nyc", "seattle", "austin",
        "boston", "los angeles", "chicago", "denver", "atlanta", "sunnyvale",
        "mountain view", "palo alto", "san jose", "cupertino", "redmond", "cambridge",
    },
    "united kingdom": {
        "london", "manchester", "birmingham", "edinburgh", "glasgow", "bristol",
        "cambridge", "oxford", "leeds",
    },
    "india": {
        "bengaluru", "bangalore", "mumbai", "delhi", "new delhi", "noida", "gurgaon",
        "gurugram", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "karnataka",
    },
    "canada": {
        "toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo",
    },
    "germany": {
        "berlin", "munich", "frankfurt", "hamburg", "cologne",
    },
}


def normalize_country(name: str) -> str:
    """Normalize country string."""
    clean = re.sub(r"[^a-zA-Z\s]", "", name.lower()).strip()
    return COUNTRY_SYNONYMS.get(clean, clean)


def resolve_job_country(location: str, explicit_country: str = "") -> Optional[str]:
    """
    Infer standardized country from explicit country and location string.
    Handles US states (e.g. ', CA', ', NY'), country abbreviations, and tech hubs.
    """
    if explicit_country:
        norm = normalize_country(explicit_country)
        if norm in COUNTRY_SYNONYMS.values():
            return norm

    loc_lower = location.lower().strip()
    if not loc_lower or loc_lower in ("remote", "anywhere", "worldwide"):
        return None

    # Check for direct country names
    for code, full in COUNTRY_SYNONYMS.items():
        if re.search(rf"\b{re.escape(full)}\b", loc_lower):
            return full
        if re.search(rf"\b{re.escape(code)}\b", loc_lower) and code not in ("in", "ca", "de"):
            return full

    # Check US state code patterns e.g. ", CA", "San Francisco, CA"
    m = re.search(r",\s*([a-z]{2})\b", loc_lower)
    if m and m.group(1) in US_STATE_CODES:
        return "united states"

    # Check city names
    for country, cities in MAJOR_CITIES_BY_COUNTRY.items():
        for city in cities:
            if re.search(rf"\b{re.escape(city)}\b", loc_lower):
                return country

    norm = normalize_country(location)
    if norm in COUNTRY_SYNONYMS.values():
        return norm

    return None


class EligibilityEngine:
    """
    Evaluates candidate preferences against a job vacancy.
    """

    @classmethod
    def evaluate(
        cls,
        job: NormalizedJob,
        preferences: Dict[str, Any],
    ) -> Tuple[EligibilityStatus, List[str], str]:
        """
        Evaluate candidate eligibility for a job.
        
        Returns:
            (status, mandatory_failures, explanation)
        """
        mandatory_failures: List[str] = []
        uncertainties: List[str] = []

        # 1. Employment Type Check
        desired_types = [t.lower() for t in preferences.get("employment_types", ["full-time"])]
        job_type = job.employment_type.value.lower()

        # If user wants ONLY internship and job is full-time
        if "internship" in desired_types and "full-time" not in desired_types:
            if job_type != "internship":
                mandatory_failures.append(
                    f"Employment type mismatch: candidate preferences specify 'internship only', but role is '{job_type}'."
                )

        # If user wants ONLY full-time and job is internship
        if "full-time" in desired_types and "internship" not in desired_types:
            if job_type == "internship":
                mandatory_failures.append(
                    "Employment type mismatch: candidate preferences specify 'full-time only', but role is an 'internship'."
                )

        # 2. Location & Country Check
        eligible_countries = [
            normalize_country(c)
            for c in preferences.get("eligible_countries", [])
            if c.strip()
        ]

        job_location = job.location.strip().lower()
        job_is_remote = job.is_remote or "remote" in job_location
        resolved_country = resolve_job_country(job.location, job.country)

        if not eligible_countries:
            # No country constraints specified
            pass
        elif job_is_remote:
            if any("remote" in c for c in eligible_countries):
                pass
            elif resolved_country:
                if resolved_country not in eligible_countries:
                    mandatory_failures.append(
                        f"Country mismatch: Remote role is restricted to '{job.location}' ({resolved_country.title()}), which is outside candidate's eligible countries ({', '.join(c.title() for c in eligible_countries)})."
                    )
            elif job_location and job_location not in ("remote", "anywhere", "worldwide"):
                uncertainties.append(f"Remote role with location '{job.location}'; country eligibility requires candidate verification.")
        else:
            # On-site or hybrid role
            if resolved_country:
                if resolved_country not in eligible_countries:
                    mandatory_failures.append(
                        f"Location mismatch: Role is located in '{job.location}' ({resolved_country.title()}), which does not match candidate's eligible countries ({', '.join(c.title() for c in eligible_countries)})."
                    )
            elif not job_location:
                uncertainties.append("Job location is not specified in the posting.")
            else:
                uncertainties.append(
                    f"Job location '{job.location}' could not be definitively matched to eligible countries ({', '.join(c.title() for c in eligible_countries)}). Requires candidate review."
                )

        # 3. Minimum Salary Check (if both provided)
        min_salary = float(preferences.get("min_salary", 0.0))
        if min_salary > 0 and job.salary_info:
            # Basic numeric extraction if possible
            salary_digits = re.findall(r"\d+[\d,]*", job.salary_info)
            # Not a mandatory failure unless exact parsed ceiling is lower, keep as uncertainty
            pass

        # Verdict
        if mandatory_failures:
            explanation = "Ineligible: " + " ".join(mandatory_failures)
            return EligibilityStatus.INELIGIBLE, mandatory_failures, explanation
        elif uncertainties:
            explanation = "Uncertain eligibility: " + " ".join(uncertainties)
            return EligibilityStatus.UNCERTAIN, [], explanation
        else:
            explanation = "Eligible: Meets employment type and country requirements."
            return EligibilityStatus.ELIGIBLE, [], explanation
