"""
Security, PII Sanitization, Credential Redaction, and Privacy Utilities for AutoBot v2.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Union

from src.storage.auth import revoke_all_user_sessions
from src.storage.db import get_db_connection, get_db_path, init_db, log_audit
from src.utils.logger import logger


SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|auth|authorization)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{6,})['\"]?"), r"\1=[REDACTED]"),
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"li_at=[^;\s]+"), "li_at=[REDACTED_COOKIE]"),
]

PII_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"), "[REDACTED_PHONE]"),
]


def redact_secrets(content: Union[str, Dict[str, Any], List[Any]]) -> Union[str, Dict[str, Any], List[Any]]:
    """Redact passwords, API keys, and authorization headers from strings or nested dictionaries."""
    if isinstance(content, str):
        result = content
        for pattern, repl in SECRET_PATTERNS:
            result = pattern.sub(repl, result)
        return result
    elif isinstance(content, dict):
        clean_dict = {}
        for k, v in content.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ["password", "secret", "api_key", "apikey", "token", "auth", "authorization", "bearer", "cookie", "li_at", "session"]):
                clean_dict[k] = "[REDACTED]"
            else:
                clean_dict[k] = redact_secrets(v)
        return clean_dict
    elif isinstance(content, list):
        return [redact_secrets(item) for item in content]
    return content


def sanitize_for_logs(data: Any, mask_pii: bool = True) -> Any:
    """Format data safely for SSE broadcasting and log writing without leaking PII or secrets."""
    redacted = redact_secrets(data)
    if not mask_pii:
        return redacted

    if isinstance(redacted, str):
        result = redacted
        for pattern, repl in PII_PATTERNS:
            result = pattern.sub(repl, result)
        return result
    elif isinstance(redacted, dict):
        clean_dict = {}
        for k, v in redacted.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in ["email", "phone", "full_name", "candidate_name", "address", "contact"]):
                clean_dict[k] = "[REDACTED_PII]"
            else:
                clean_dict[k] = sanitize_for_logs(v, mask_pii=True)
        return clean_dict
    elif isinstance(redacted, list):
        return [sanitize_for_logs(item, mask_pii=True) for item in redacted]
    return redacted


def delete_user_account_and_data(
    user_id: int,
    db_path: Optional[str] = None,
    user_storage_dir: Optional[Path] = None,
) -> bool:
    """
    Permanently delete all user profile, resume files, preferences, evaluations,
    and tracker history (privacy right to erasure).
    """
    init_db(db_path)
    now = datetime.now().isoformat()

    try:
        # Delete user files from disk
        if user_storage_dir is None:
            user_storage_dir = Path("data/users") / str(user_id)
        if user_storage_dir.exists():
            shutil.rmtree(user_storage_dir, ignore_errors=True)

        # Revoke all active sessions immediately from memory and storage
        revoke_all_user_sessions(user_id, db_path)

        # Cryptographically chained audit event before user record deletion
        log_audit(
            user_id=None,
            action="USER_DATA_DELETED",
            resource_type="users",
            resource_id=str(user_id),
            details="All candidate records erased per user request",
            db_path=db_path,
        )

        with get_db_connection(db_path) as conn:
            # Nullify audit log user references for any historical entries
            conn.execute("UPDATE audit_logs SET user_id = NULL WHERE user_id = ?", (user_id,))
            # Explicitly delete all tenant-scoped data in strict leaf-to-root dependency order
            conn.execute("DELETE FROM application_events WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM application_packs WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM match_evaluations WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM resume_evidence WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM resume_versions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM candidate_profiles WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM job_preferences WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()

        logger.info(f"[security]Completely purged all account and personal data for user_id={user_id}[/security]")
        return True
    except Exception as e:
        logger.error(f"Error purging user data: {e}")
        return False
