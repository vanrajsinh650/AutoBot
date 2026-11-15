"""
User Authentication, Password Hashing, and Secure Session Management.
"""

from datetime import datetime, timedelta
import hashlib
import hmac
import os
import secrets
import sqlite3
from typing import Any, Dict, Optional, Tuple

from src.storage.db import get_db_connection, init_db, get_db_path, log_audit
from src.utils.logger import logger


PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a unique cryptographic salt."""
    salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${pw_hash.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against stored salt$hash using constant-time comparison."""
    try:
        parts = hashed.split("$")
        if len(parts) != 2:
            return False
        salt = bytes.fromhex(parts[0])
        expected_hash = bytes.fromhex(parts[1])
        candidate_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(candidate_hash, expected_hash)
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


def create_user(
    email: str,
    password: str,
    db_path: Optional[str] = None,
) -> Tuple[bool, Optional[int], str]:
    """
    Register a new user account.
    Returns (success, user_id, message).
    """
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email or len(clean_email) < 5:
        return False, None, "Invalid email address format."
    if len(password) < 6:
        return False, None, "Password must be at least 6 characters."

    db_path = db_path or get_db_path()
    init_db(db_path)
    now = datetime.now().isoformat()
    hashed = hash_password(password)

    try:
        with get_db_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO users (email, password_hash, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (clean_email, hashed, now, now),
            )
            user_id = cur.lastrowid

            # Create empty candidate_profile and job_preferences for the new user
            conn.execute(
                """
                INSERT OR IGNORE INTO candidate_profiles (
                    user_id, full_name, email, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, clean_email.split("@")[0].title(), clean_email, now, now),
            )

            conn.execute(
                """
                INSERT OR IGNORE INTO job_preferences (
                    user_id, created_at, updated_at
                ) VALUES (?, ?, ?)
                """,
                (user_id, now, now),
            )

            conn.commit()

        # Audit log with cryptographic hash chain
        log_audit(
            user_id=user_id,
            action="USER_REGISTER",
            resource_type="users",
            resource_id=str(user_id),
            details="User registered successfully",
            db_path=db_path,
        )
        return True, user_id, "User registered successfully."
    except sqlite3.IntegrityError:
        return False, None, "A user with this email already exists."
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return False, None, str(e)


# Brute-force protection tracking
_FAILED_LOGIN_ATTEMPTS: Dict[str, List[datetime]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 minutes


def is_rate_limited(key: str) -> Tuple[bool, int]:
    """Check if key (e.g. email) has exceeded max failed attempts within lockout window."""
    now = datetime.now()
    attempts = _FAILED_LOGIN_ATTEMPTS.get(key, [])
    recent_attempts = [t for t in attempts if (now - t).total_seconds() < LOCKOUT_SECONDS]
    _FAILED_LOGIN_ATTEMPTS[key] = recent_attempts

    if len(recent_attempts) >= MAX_FAILED_ATTEMPTS:
        oldest = recent_attempts[0]
        remaining = int(LOCKOUT_SECONDS - (now - oldest).total_seconds())
        return True, max(1, remaining)
    return False, 0


def record_failed_attempt(key: str) -> None:
    """Record a failed login attempt timestamp."""
    now = datetime.now()
    if key not in _FAILED_LOGIN_ATTEMPTS:
        _FAILED_LOGIN_ATTEMPTS[key] = []
    _FAILED_LOGIN_ATTEMPTS[key].append(now)


def clear_failed_attempts(key: str) -> None:
    """Clear failed login attempts after successful authentication."""
    _FAILED_LOGIN_ATTEMPTS.pop(key, None)


def reset_all_login_attempts() -> None:
    """Reset attempt trackers across all keys (for tests)."""
    _FAILED_LOGIN_ATTEMPTS.clear()


def authenticate_user(
    email: str,
    password: str,
    client_ip: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user by email and password with brute-force rate-limiting.
    Returns (success, user_dict, message).
    """
    clean_email = email.strip().lower()
    if not clean_email:
        return False, None, "Email address is required."

    # Check brute-force lockout
    locked, remaining_sec = is_rate_limited(clean_email)
    if locked:
        logger.warning(f"Brute-force lockout triggered for '{clean_email}': {remaining_sec}s remaining.")
        return False, None, f"Too many failed login attempts. Account temporarily locked for {remaining_sec} seconds."

    db_path = db_path or get_db_path()
    init_db(db_path)

    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, is_active FROM users WHERE LOWER(email) = ?",
            (clean_email,),
        ).fetchone()

        if not row:
            record_failed_attempt(clean_email)
            return False, None, "Invalid email or password."

        if not row["is_active"]:
            return False, None, "User account is inactive."

        if not verify_password(password, row["password_hash"]):
            record_failed_attempt(clean_email)
            return False, None, "Invalid email or password."

        # Successful authentication: clear lockout history
        clear_failed_attempts(clean_email)

        user_data = {
            "id": row["id"],
            "email": row["email"],
            "is_active": bool(row["is_active"]),
        }
        return True, user_data, "Authentication successful."


# In-memory and durable SQLite session token store
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}


def create_session(user_id: int, email: str, ttl_hours: int = 48, db_path: Optional[str] = None) -> str:
    """Generate and record a secure session token both in-memory and in SQLite."""
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = now + timedelta(hours=ttl_hours)
    session_data = {
        "user_id": user_id,
        "email": email,
        "expires_at": expires_at,
    }
    _ACTIVE_SESSIONS[token] = session_data

    try:
        db_path = db_path or get_db_path()
        init_db(db_path)
        with get_db_connection(db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO user_sessions (token, user_id, email, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, user_id, email, expires_at.isoformat(), now.isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not persist session token to database: {e}")

    return token


def validate_session(token: Optional[str], db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Validate a session token against memory cache or SQLite table."""
    if not token:
        return None

    now = datetime.now()
    db_path = db_path or get_db_path()
    if token in _ACTIVE_SESSIONS:
        session = _ACTIVE_SESSIONS[token]
        if now > session["expires_at"]:
            _ACTIVE_SESSIONS.pop(token, None)
            revoke_session(token, db_path=db_path)
            return None
        return session

    # Check durable database for sessions surviving restarts
    try:
        init_db(db_path)
        with get_db_connection(db_path) as conn:
            row = conn.execute(
                "SELECT user_id, email, expires_at FROM user_sessions WHERE token = ?",
                (token,),
            ).fetchone()
            if not row:
                return None

            expires_at = datetime.fromisoformat(row["expires_at"])
            if now > expires_at:
                conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
                conn.commit()
                return None

            session = {
                "user_id": row["user_id"],
                "email": row["email"],
                "expires_at": expires_at,
            }
            _ACTIVE_SESSIONS[token] = session
            return session
    except Exception as e:
        logger.debug(f"Error checking persistent session: {e}")
        return None


def revoke_session(token: Optional[str], db_path: Optional[str] = None) -> bool:
    """Revoke an active session token from memory and database."""
    revoked = False
    if token and token in _ACTIVE_SESSIONS:
        del _ACTIVE_SESSIONS[token]
        revoked = True

    if token:
        try:
            db_path = db_path or get_db_path()
            init_db(db_path)
            with get_db_connection(db_path) as conn:
                cur = conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
                conn.commit()
                if cur.rowcount > 0:
                    revoked = True
        except Exception as e:
            logger.debug(f"Error deleting session from db: {e}")

    return revoked


def revoke_all_user_sessions(user_id: int, db_path: Optional[str] = None) -> bool:
    """Revoke all active sessions for a user from in-memory cache and persistent database."""
    # 1. Clear from in-memory cache
    tokens_to_remove = [t for t, s in _ACTIVE_SESSIONS.items() if s.get("user_id") == user_id]
    for t in tokens_to_remove:
        _ACTIVE_SESSIONS.pop(t, None)

    # 2. Clear from SQLite
    try:
        db_path = db_path or get_db_path()
        init_db(db_path)
        with get_db_connection(db_path) as conn:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
        return True
    except Exception as e:
        logger.debug(f"Error deleting user sessions: {e}")
        return False
