"""
Tests for AutoBot v2.1 Phase 4: Data Security, File Validation, Tamper-Evident Audit Logs,
Database File Permissions, and AI Gateway Binding.
"""

from io import BytesIO
import os
from pathlib import Path
import sqlite3
import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from src.storage.auth import create_user
from src.storage.db import (
    AUDIT_GENESIS_HASH,
    backup_database,
    get_db_connection,
    init_db,
    log_audit,
    verify_audit_log_tamper_evidence,
)
from src.utils.llm_factory import validate_gateway_url
from src.utils.security import redact_secrets, sanitize_for_logs
from src.web.server import create_app


@pytest_asyncio.fixture
async def client():
    """Create test client with isolated test database."""
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    try:
        yield c
    finally:
        await c.close()


def test_tamper_evident_audit_log_hash_chain(tmp_path):
    """Verify that audit_logs maintains a cryptographic SHA-256 chain and detects tampering."""
    db_file = str(tmp_path / "tamper_test.db")
    init_db(db_file)

    # Create users first to satisfy foreign key integrity
    ok_a, u1, _ = create_user("alice_audit@example.com", "SecretPass123!", db_path=db_file)
    ok_b, u2, _ = create_user("bob_audit@example.com", "SecretPass123!", db_path=db_file)
    assert ok_a and ok_b

    # 1. Log three events
    hash1 = log_audit(user_id=u1, action="login", resource_type="auth", db_path=db_file)
    hash2 = log_audit(user_id=u1, action="upload_resume", resource_type="resume", details={"filename": "doc.pdf"}, db_path=db_file)
    hash3 = log_audit(user_id=u2, action="prepare_pack", resource_type="pack", resource_id="42", db_path=db_file)

    assert hash1 and len(hash1) == 64
    assert hash2 and len(hash2) == 64
    assert hash3 and len(hash3) == 64

    # 2. Verify pristine chain
    is_valid, violations = verify_audit_log_tamper_evidence(db_file)
    assert is_valid is True
    assert len(violations) == 0

    # 3. Tamper with upload_resume details directly in SQLite
    with get_db_connection(db_file) as conn:
        conn.execute("UPDATE audit_logs SET details = '{\"filename\": \"hacked.pdf\"}' WHERE action = 'upload_resume'")
        conn.commit()

    # 4. Chain integrity check must now fail closed
    is_valid_after_tamper, violations = verify_audit_log_tamper_evidence(db_file)
    assert is_valid_after_tamper is False
    assert len(violations) > 0


def test_atomic_database_backup_and_permissions(tmp_path):
    """Verify atomic database online backup with strict 0700/0600 permissions."""
    src_db = str(tmp_path / "prod.db")
    init_db(src_db)

    # Insert test record via create_user
    ok, uid, _ = create_user("test@example.com", "Pass123456!", db_path=src_db)
    assert ok is True

    backup_dir = tmp_path / "secure_backups"
    backup_file = backup_database(db_path=src_db, backup_dir=backup_dir)

    assert backup_file.exists()
    assert backup_file.is_file()

    # Verify backup directory permissions (0700)
    dir_mode = oct(backup_dir.stat().st_mode & 0o777)
    assert dir_mode == "0o700"

    # Verify backup file permissions (0600)
    file_mode = oct(backup_file.stat().st_mode & 0o777)
    assert file_mode == "0o600"

    # Verify backup is a valid SQLite DB with intact data
    with sqlite3.connect(str(backup_file)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT email FROM users WHERE email = 'test@example.com'").fetchone()
        assert row is not None
        assert row["email"] == "test@example.com"


def test_secret_and_pii_redaction():
    """Verify that sensitive secrets and candidate PII are masked in text and nested dicts."""
    raw_payload = {
        "user_email": "candidate@securecloud.org",
        "phone_number": "+1 (555) 234-5678",
        "candidate_name": "Jane Doe",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
        "authorization": "Bearer CZeWm75FJeVbrNmeSaR81I-H4-zIzvrbeCDj37iLlpg",
        "session": "secret_session_token_12345",
        "nested": {
            "api_key": "sk-123456789012345678901234",
            "password": "supersecretpassword123",
            "notes": "Contact candidate@securecloud.org or call 555-234-5678",
        },
    }

    sanitized = sanitize_for_logs(raw_payload)

    # Secrets masked
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["session"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"

    # PII masked
    assert sanitized["user_email"] == "[REDACTED_PII]"
    assert sanitized["phone_number"] == "[REDACTED_PII]"
    assert sanitized["candidate_name"] == "[REDACTED_PII]"
    assert "[REDACTED_EMAIL]" in sanitized["nested"]["notes"]
    assert "[REDACTED_PHONE]" in sanitized["nested"]["notes"]


def test_orbit_gateway_binding_validation():
    """Verify AI gateway rejects unencrypted remote HTTP endpoints."""
    # Loopback endpoints are permitted
    assert validate_gateway_url("http://localhost:4981") == "http://localhost:4981"
    assert validate_gateway_url("http://127.0.0.1:4981") == "http://127.0.0.1:4981"
    assert validate_gateway_url("http://localhost:8000") == "http://localhost:8000"

    # Remote endpoints must use HTTPS
    assert validate_gateway_url("https://ai.company.internal/v1") == "https://ai.company.internal/v1"

    # Cleartext remote HTTP must be rejected
    with pytest.raises(ValueError, match="Insecure gateway URL"):
        validate_gateway_url("http://remote-proxy.com/api")


@pytest.mark.asyncio
async def test_upload_magic_bytes_validation(client: TestClient):
    """Verify resume uploads reject fake extensions with invalid magic bytes."""
    # Register a user
    reg = await client.post("/api/auth/register", json={"email": "alice_data@example.com", "password": "Passw0rdSecure!123"})
    token = (await reg.json())["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fake PDF (contains plain text / shell script instead of %PDF)
    data_bad = FormData()
    data_bad.add_field("file", b"#!/bin/bash\nrm -rf /", filename="malicious.pdf", content_type="application/pdf")
    resp_bad = await client.post("/api/upload", data=data_bad, headers=headers)
    assert resp_bad.status == 400
    err = await resp_bad.json()
    assert "missing %PDF" in err["error"]

    # 2. Valid PDF magic bytes
    data_good = FormData()
    data_good.add_field("file", b"%PDF-1.5 test content", filename="valid.pdf", content_type="application/pdf")
    resp_good = await client.post("/api/upload", data=data_good, headers=headers)
    assert resp_good.status == 200
    res = await resp_good.json()
    assert res["success"] is True

    # 3. Verify saved resume file permissions
    saved_file = Path(res["path"])
    assert saved_file.exists()
    file_mode = oct(saved_file.stat().st_mode & 0o777)
    assert file_mode == "0o600"
