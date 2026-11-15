"""
Tests for AutoBot v2 Security, PII Sanitization, and Privacy Erasure.
"""

from pathlib import Path
import pytest

from src.storage.auth import create_user
from src.storage.db import (
    get_candidate_profile,
    get_resume_versions,
    init_db,
    save_candidate_profile,
    save_resume_version,
)
from src.utils.security import (
    delete_user_account_and_data,
    redact_secrets,
    sanitize_for_logs,
)
from src.web.server import create_app


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_sec.db"
    init_db(str(db_file))
    return str(db_file)


def test_credential_and_secret_redaction():
    """Verify secrets and API keys are redacted from text and dictionaries."""
    sample_text = "Initialized with API_KEY=sk-abcdef1234567890123456 and password='SuperSecretPassword!'"
    redacted_text = redact_secrets(sample_text)
    assert "sk-" not in redacted_text
    assert "SuperSecretPassword!" not in redacted_text
    assert "[REDACTED" in redacted_text

    sample_dict = {
        "status": "ok",
        "api_key": "sk-secret1234567890123456",
        "nested": {"password": "mypassword123", "normal": "valid_value"},
    }
    redacted_dict = redact_secrets(sample_dict)
    assert redacted_dict["api_key"] == "[REDACTED]"
    assert redacted_dict["nested"]["password"] == "[REDACTED]"
    assert redacted_dict["nested"]["normal"] == "valid_value"


def test_pii_sanitization_for_logs():
    """Verify candidate email, phone numbers, and PII are masked in log/SSE broadcasts."""
    log_payload = {
        "event": "applicant_created",
        "email": "candidate@example.com",
        "phone": "+1 (555) 234-5678",
        "message": "Candidate candidate@example.com applied successfully.",
    }

    sanitized = sanitize_for_logs(log_payload, mask_pii=True)
    assert "candidate@example.com" not in str(sanitized)
    assert "+1 (555) 234-5678" not in str(sanitized)
    assert "[REDACTED_EMAIL]" in sanitized["message"] or "[REDACTED_PII]" in str(sanitized)


def test_gdpr_right_to_erasure_account_purge(temp_db, tmp_path):
    """Verify delete_user_account_and_data erases all candidate profile, resumes, and history."""
    _, u_id, _ = create_user("purge_me@example.com", "pass123", db_path=temp_db)

    # Save profile
    save_candidate_profile(
        user_id=u_id,
        profile={"full_name": "Ephemeral Candidate", "headline": "DevOps"},
        db_path=temp_db,
    )

    # Save resume file on disk
    user_dir = tmp_path / "users" / str(u_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    resume_file = user_dir / "resume.pdf"
    resume_file.write_bytes(b"dummy pdf bytes")

    save_resume_version(
        user_id=u_id,
        version_name="resume.pdf",
        file_path=str(resume_file),
        file_hash="hash99",
        parsed_data={},
        db_path=temp_db,
    )

    assert get_candidate_profile(u_id, db_path=temp_db) is not None
    assert resume_file.exists() is True

    # Execute permanent erasure
    ok = delete_user_account_and_data(user_id=u_id, db_path=temp_db, user_storage_dir=user_dir)
    assert ok is True

    # Assert profile erased from SQLite
    assert get_candidate_profile(u_id, db_path=temp_db) is None
    assert len(get_resume_versions(u_id, db_path=temp_db)) == 0

    # Assert files purged from disk
    assert resume_file.exists() is False
    assert user_dir.exists() is False


def test_no_linkedin_credentials_required():
    """Verify system does not require or collect LinkedIn passwords or session cookies in v2."""
    from src.discovery.adapters.manual import ManualJobAdapter
    adapter = ManualJobAdapter()
    job = adapter.import_job(
        title="Software Engineer",
        company="Acme Corp",
        description="Python role",
        application_url="https://www.linkedin.com/jobs/view/123456",
    )
    # No credentials needed or accepted
    assert job.company == "Acme Corp"
    assert "password" not in job.raw_data
    assert "cookie" not in job.raw_data
