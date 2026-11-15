"""
Tests for AutoBot v2 Multi-Tenant Foundations and Isolation.
"""

from pathlib import Path
import pytest

from src.storage.auth import authenticate_user, create_session, create_user, hash_password, validate_session, verify_password
from src.storage.db import (
    get_candidate_profile,
    get_job_preferences,
    get_resume_evidence,
    get_resume_versions,
    get_stats,
    init_db,
    is_already_applied,
    save_application,
    save_candidate_profile,
    save_job_preferences,
    save_resume_evidence,
    save_resume_version,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_tenant.db"
    init_db(str(db_file))
    return str(db_file)


def test_user_registration_and_auth(temp_db):
    """Test user registration, password hashing, and authentication."""
    ok, u1_id, msg = create_user("alice@example.com", "Password123!", db_path=temp_db)
    assert ok is True
    assert u1_id is not None

    # Duplicate registration must fail
    dup_ok, _, _ = create_user("alice@example.com", "DifferentPw!", db_path=temp_db)
    assert dup_ok is False

    # Password auth
    auth_ok, u1_data, _ = authenticate_user("alice@example.com", "Password123!", db_path=temp_db)
    assert auth_ok is True
    assert u1_data["id"] == u1_id
    assert u1_data["email"] == "alice@example.com"

    # Wrong password
    bad_auth, _, _ = authenticate_user("alice@example.com", "WrongPassword", db_path=temp_db)
    assert bad_auth is False


def test_secure_password_hashing():
    """Verify PBKDF2-HMAC-SHA256 salted hash and constant-time verify."""
    hashed = hash_password("SecretKey99")
    assert "$" in hashed
    assert verify_password("SecretKey99", hashed) is True
    assert verify_password("secretkey99", hashed) is False
    assert verify_password("Wrong", hashed) is False


def test_session_token_lifecycle():
    """Test session creation, validation, and revocation."""
    token = create_session(user_id=42, email="bob@test.com", ttl_hours=24)
    assert isinstance(token, str) and len(token) > 20

    session = validate_session(token)
    assert session is not None
    assert session["user_id"] == 42
    assert session["email"] == "bob@test.com"

    # Invalid token
    assert validate_session("non_existent_token") is None


def test_tenant_isolation_candidate_profile(temp_db):
    """Verify profiles are strictly partitioned by tenant ID."""
    ok1, u1, _ = create_user("user1@test.com", "pass123", db_path=temp_db)
    ok2, u2, _ = create_user("user2@test.com", "pass456", db_path=temp_db)

    # Save profile for User 1
    save_candidate_profile(
        user_id=u1,
        profile={
            "full_name": "User One",
            "technical_skills": ["Python", "Docker"],
            "headline": "Lead Python Engineer",
        },
        db_path=temp_db,
    )

    # Save profile for User 2
    save_candidate_profile(
        user_id=u2,
        profile={
            "full_name": "User Two",
            "technical_skills": ["Rust", "Wasm"],
            "headline": "Systems Specialist",
        },
        db_path=temp_db,
    )

    # Retrieve and assert isolation
    p1 = get_candidate_profile(u1, db_path=temp_db)
    p2 = get_candidate_profile(u2, db_path=temp_db)

    assert p1["full_name"] == "User One"
    assert "Python" in p1["technical_skills"]
    assert "Rust" not in p1["technical_skills"]

    assert p2["full_name"] == "User Two"
    assert "Rust" in p2["technical_skills"]
    assert "Python" not in p2["technical_skills"]


def test_tenant_isolation_resume_versions_and_evidence(temp_db):
    """Verify resume versions and evidence are completely private per user."""
    _, u1, _ = create_user("u1@resumes.com", "pass123", db_path=temp_db)
    _, u2, _ = create_user("u2@resumes.com", "pass456", db_path=temp_db)

    v1_id = save_resume_version(
        user_id=u1,
        version_name="u1_cv.pdf",
        file_path="/data/u1.pdf",
        file_hash="hash1",
        parsed_data={"skills": ["Go"]},
        db_path=temp_db,
    )

    save_resume_evidence(
        user_id=u1,
        resume_version_id=v1_id,
        section="skills",
        content="Go, Kubernetes",
        metadata={"page": "1"},
        db_path=temp_db,
    )

    # User 2 should have NO resume versions or evidence
    u2_versions = get_resume_versions(user_id=u2, db_path=temp_db)
    u2_evidence = get_resume_evidence(user_id=u2, db_path=temp_db)
    assert len(u2_versions) == 0
    assert len(u2_evidence) == 0

    # User 1 should have their record
    u1_versions = get_resume_versions(user_id=u1, db_path=temp_db)
    assert len(u1_versions) == 1
    assert u1_versions[0]["version_name"] == "u1_cv.pdf"


def test_tenant_isolation_applications_and_stats(temp_db):
    """Verify application tracking is scoped per user."""
    _, u1, _ = create_user("u1@apps.com", "pass123", db_path=temp_db)
    _, u2, _ = create_user("u2@apps.com", "pass456", db_path=temp_db)

    save_application(
        job_id="job_common_101",
        job_title="Backend Dev",
        company="TechCorp",
        location="Remote",
        apply_type="external",
        match_score=0.9,
        status="applied",
        url="https://example.com/job1",
        db_path=temp_db,
        user_id=u1,
    )

    # u1 applied
    assert is_already_applied("job_common_101", db_path=temp_db, user_id=u1) is True
    # u2 has NOT applied
    assert is_already_applied("job_common_101", db_path=temp_db, user_id=u2) is False

    stats_u1 = get_stats(db_path=temp_db, user_id=u1)
    stats_u2 = get_stats(db_path=temp_db, user_id=u2)
    assert stats_u1["applied"] == 1
    assert stats_u2["applied"] == 0
