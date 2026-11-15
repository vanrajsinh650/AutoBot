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
    "uk": "united kingdom",
    "gb": "united kingdom",
    "great britain": "united kingdom",
    "ca": "canada",
    "de": "germany",
    "fr": "france",
    "au": "australia",
    "nl": "netherlands",
    "sg": "singapore",
}


def normalize_country(name: str) -> str:
    """Normalize country string."""
    clean = re.sub(r"[^a-zA-Z\s]", "", name.lower()).strip()
    return COUNTRY_SYNONYMS.get(clean, clean)


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

        if not eligible_countries:
            # No country constraints specified
            pass
        elif job_is_remote:
            # If candidate allows remote or country check on remote jobs
            if any("remote" in c for c in eligible_countries):
                pass
            else:
                # Check if remote is bounded to a specific country (e.g. 'Remote, US' or 'Remote (India)')
                matched_country = False
                for c in eligible_countries:
                    if c in job_location or normalize_country(job.country) == c:
                        matched_country = True
                        break
                if not matched_country and job_location and job_location != "remote":
                    # Remote for another country
                    # Check if another major country is mentioned
                    other_country_found = False
                    for other_code, other_name in COUNTRY_SYNONYMS.items():
                        if other_name not in eligible_countries and (other_name in job_location or f", {other_code}" in job_location):
                            other_country_found = True
                            mandatory_failures.append(
                                f"Country mismatch: Remote role is restricted to '{job.location}', which is outside candidate's eligible countries ({', '.join(eligible_countries)})."
                            )
                            break
                    if not other_country_found:
                        uncertainties.append(f"Remote role with location '{job.location}'; country eligibility requires candidate verification.")
        else:
            # On-site or hybrid role
            matched_country = False
            for c in eligible_countries:
                if c in job_location or normalize_country(job.country) == c:
                    matched_country = True
                    break

            if not matched_country:
                if not job_location:
                    uncertainties.append("Job location is not specified in the posting.")
                else:
                    mandatory_failures.append(
                        f"Location mismatch: Role is located in '{job.location}', which does not match candidate's eligible countries ({', '.join(eligible_countries)})."
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
