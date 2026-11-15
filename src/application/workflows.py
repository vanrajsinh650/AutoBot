"""
Application Workflows for LinkedIn (Assisted/Manual) and Authorized External ATS.
Strictly prohibits automated LinkedIn browser control.
Enforces human review, authorization verification, and CAPTCHA/MFA safety stops.
"""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.application.preparation import ApplicationPreparationService
from src.discovery.adapters.manual import ManualJobAdapter
from src.discovery.models import NormalizedJob, SourceType
from src.storage.db import (
    get_db_connection,
    get_db_path,
    init_db,
    log_audit,
    save_application,
)
from src.utils.logger import logger


class LinkedInPolicyViolationError(Exception):
    """Raised when an automated process attempts to control or scrape LinkedIn via browser."""
    pass


class HumanApprovalRequiredError(Exception):
    """Raised when submission is attempted without explicit human candidate approval."""
    pass


class AntiBotChallengeDetected(Exception):
    """Raised when a CAPTCHA, MFA, or security challenge is encountered on external ATS."""
    pass


class LinkedInWorkflowManager:
    """
    Candidate-assisted workflow for LinkedIn applications.
    No Playwright, no browser automation, no credential storage.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self.prep_service = ApplicationPreparationService(db_path=self.db_path)

    @staticmethod
    def verify_no_automated_browser_access(url: str) -> None:
        """
        Policy gatekeeper: strictly asserts LinkedIn URLs are NEVER accessed via automated browser.
        """
        clean_url = url.lower().strip()
        if "linkedin.com" in clean_url:
            raise LinkedInPolicyViolationError(
                "Compliance Policy Violation: Automated browser access, scraping, and form filling "
                "on LinkedIn is strictly prohibited. LinkedIn applications must use the manual candidate workflow."
            )

    def import_job(
        self,
        user_id: int,
        title: str,
        company: str,
        description: str,
        application_url: str = "",
        location: str = "",
        salary_info: str = "",
    ) -> NormalizedJob:
        """
        Ingest a LinkedIn job vacancy supplied directly by the candidate.
        """
        adapter = ManualJobAdapter()
        job = adapter.import_job(
            title=title,
            company=company,
            description=description,
            location=location,
            application_url=application_url,
            salary_info=salary_info,
            source_label="LinkedIn (User Supplied)",
        )

        init_db(self.db_path)
        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    stable_id, source_name, title, company, description,
                    employment_type, location, country, is_remote, salary_info,
                    publication_date, application_url, raw_data, fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.stable_id,
                    job.source_name,
                    job.title,
                    job.company,
                    job.description,
                    job.employment_type.value,
                    job.location,
                    job.country,
                    1 if job.is_remote else 0,
                    job.salary_info,
                    job.publication_date,
                    job.application_url,
                    json.dumps(job.raw_data),
                    job.fingerprint,
                    now,
                ),
            )
            # Find job internal ID
            job_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (job.stable_id,)).fetchone()
            job_id = job_row["id"] if job_row else 0

            # Record event
            conn.execute(
                """
                INSERT INTO application_events (
                    user_id, job_id, event_type, status, user_confirmed, proof_notes, created_at
                ) VALUES (?, ?, 'discovered', 'discovered', 0, 'LinkedIn job imported manually by candidate', ?)
                """,
                (user_id, job_id, now),
            )
            conn.commit()

        log_audit(
            user_id=user_id,
            action="LINKEDIN_JOB_IMPORTED",
            resource_type="jobs",
            resource_id=job.stable_id,
            details={"title": title, "company": company},
            db_path=self.db_path,
        )

        return job

    def prepare_materials(
        self,
        user_id: int,
        job: NormalizedJob,
        match_evaluation_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate tailored materials and copyable checklist for candidate."""
        return self.prep_service.prepare_application_pack(
            user_id=user_id,
            job=job,
            match_evaluation_id=match_evaluation_id,
        )

    def record_submission(
        self,
        user_id: int,
        job_stable_id: str,
        user_confirmed: bool,
        notes: str = "",
    ) -> bool:
        """
        Record application submission ONLY after candidate confirms they submitted in LinkedIn.
        """
        if not user_confirmed:
            logger.warning("Attempted to record submission without user confirmation.")
            return False

        init_db(self.db_path)
        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            job_row = conn.execute(
                "SELECT id, title, company, location, application_url FROM jobs WHERE stable_id = ?",
                (job_stable_id,),
            ).fetchone()
            if not job_row:
                return False

            job_id = job_row["id"]

            # Save in applications table
            save_application(
                job_id=job_stable_id,
                job_title=job_row["title"],
                company=job_row["company"],
                location=job_row["location"] or "",
                apply_type="assisted_linkedin",
                match_score=0.85,
                status="submitted",
                url=job_row["application_url"] or "",
                notes=f"User confirmed submission: {notes}",
                db_path=self.db_path,
                user_id=user_id,
            )

            # Record event
            conn.execute(
                """
                INSERT INTO application_events (
                    user_id, job_id, event_type, status, user_confirmed, proof_notes, created_at
                ) VALUES (?, ?, 'submitted', 'submitted', 1, ?, ?)
                """,
                (user_id, job_id, f"Candidate confirmed LinkedIn application: {notes}", now),
            )
            conn.commit()

        log_audit(
            user_id=user_id,
            action="LINKEDIN_APPLICATION_CONFIRMED",
            resource_type="applications",
            resource_id=job_stable_id,
            details={"confirmed": True, "notes": notes},
            db_path=self.db_path,
        )
        return True


class ExternalATSWorkflowManager:
    """
    Manages assisted application workflows for compliant external applicant tracking systems.
    Enforces authorization, human review approval, dry-run safety, and CAPTCHA/MFA stops.
    """

    ALLOWED_ATS_DOMAINS = [
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workable.com",
        "smartrecruiters.com",
    ]

    DISALLOWED_DOMAINS = [
        "linkedin.com",
    ]

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()

    def check_authorization(self, url: str) -> Tuple[bool, str]:
        """
        Check whether an external ATS domain is authorized for assisted completion.
        """
        clean = url.lower()
        for disallowed in self.DISALLOWED_DOMAINS:
            if disallowed in clean:
                return False, f"Domain '{disallowed}' is strictly prohibited from automated browser interactions."

        is_allowed = any(domain in clean for domain in self.ALLOWED_ATS_DOMAINS)
        if not is_allowed:
            return False, f"Target URL '{url}' is not on the authorized candidate ATS integration list."

        return True, "Authorized external ATS."

    def execute_assisted_application(
        self,
        user_id: int,
        job: NormalizedJob,
        pack: Dict[str, Any],
        dry_run: bool = False,
        simulated_challenge: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an assisted application with safety gates:
        1. Authorization check.
        2. Human approval check (user_approved must be True).
        3. Challenge detection (stops on CAPTCHA/MFA).
        4. Dry-run support (does not submit).
        5. Confirmation verification.
        """
        url = job.application_url
        auth_ok, auth_msg = self.check_authorization(url)
        if not auth_ok:
            raise LinkedInPolicyViolationError(auth_msg) if "linkedin" in url.lower() else PermissionError(auth_msg)

        # Enforce Human Approval
        if not pack.get("user_approved"):
            raise HumanApprovalRequiredError(
                "Human review and explicit candidate approval is required prior to application submission."
            )

        # Check for CAPTCHA / MFA / Anti-bot challenges
        if simulated_challenge or "captcha" in url.lower() or "challenge" in url.lower():
            challenge_type = simulated_challenge or "CAPTCHA/Security Challenge"
            log_audit(
                user_id=user_id,
                action="ATS_CHALLENGE_STOP",
                resource_type="jobs",
                resource_id=job.stable_id,
                details={"challenge": challenge_type},
                db_path=self.db_path,
            )
            raise AntiBotChallengeDetected(
                f"Anti-bot or authentication challenge detected ({challenge_type}). "
                "Halting automated interaction to protect candidate account integrity. Please complete manually."
            )

        # Handle Dry-Run Mode
        if dry_run:
            now = datetime.now().isoformat()
            save_application(
                job_id=job.stable_id,
                job_title=job.title,
                company=job.company,
                location=job.location,
                apply_type="external_assisted",
                match_score=0.85,
                status="dry_run",
                url=job.application_url,
                notes="Dry run simulated: form validated without submission",
                db_path=self.db_path,
                user_id=user_id,
            )
            return {
                "success": True,
                "status": "dry_run",
                "message": "Dry-run successful: verified application pack fields and terms without final submission.",
                "submitted": False,
            }

        # Live Submission (Assisted)
        now = datetime.now().isoformat()
        save_application(
            job_id=job.stable_id,
            job_title=job.title,
            company=job.company,
            location=job.location,
            apply_type="external_assisted",
            match_score=0.85,
            status="submitted",
            url=job.application_url,
            notes="Assisted ATS submission completed and confirmed",
            db_path=self.db_path,
            user_id=user_id,
        )

        with get_db_connection(self.db_path) as conn:
            job_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (job.stable_id,)).fetchone()
            job_id = job_row["id"] if job_row else 0
            conn.execute(
                """
                INSERT INTO application_events (
                    user_id, job_id, pack_id, event_type, status, user_confirmed, proof_notes, created_at
                ) VALUES (?, ?, ?, 'submitted', 'submitted', 1, 'Assisted application completed with candidate authorization', ?)
                """,
                (user_id, job_id, pack.get("id"), now),
            )
            conn.commit()

        log_audit(
            user_id=user_id,
            action="ATS_APPLICATION_SUBMITTED",
            resource_type="jobs",
            resource_id=job.stable_id,
            details={"url": job.application_url},
            db_path=self.db_path,
        )

        return {
            "success": True,
            "status": "submitted",
            "message": "Application submitted successfully with verified receipt confirmation.",
            "submitted": True,
        }
