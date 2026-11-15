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

from src.storage.db import get_db_connection, init_db, DEFAULT_DB_PATH
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
    db_path: str = DEFAULT_DB_PATH,
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

            # Audit log
            conn.execute(
                """
                INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, created_at)
                VALUES (?, 'USER_REGISTER', 'users', ?, 'User registered successfully', ?)
                """,
                (user_id, str(user_id), now),
            )

            conn.commit()
            return True, user_id, "User registered successfully."
    except sqlite3.IntegrityError:
        return False, None, "A user with this email already exists."
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return False, None, str(e)


def authenticate_user(
    email: str,
    password: str,
    db_path: str = DEFAULT_DB_PATH,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticate a user by email and password.
    Returns (success, user_dict, message).
    """
    clean_email = email.strip().lower()
    init_db(db_path)

    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, is_active FROM users WHERE LOWER(email) = ?",
            (clean_email,),
        ).fetchone()

        if not row:
            return False, None, "Invalid email or password."

        if not row["is_active"]:
            return False, None, "User account is inactive."

        if not verify_password(password, row["password_hash"]):
            return False, None, "Invalid email or password."

        user_data = {
            "id": row["id"],
            "email": row["email"],
            "is_active": bool(row["is_active"]),
        }
        return True, user_data, "Authentication successful."


# In-memory and durable SQLite session token store
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}


def create_session(user_id: int, email: str, ttl_hours: int = 48, db_path: str = DEFAULT_DB_PATH) -> str:
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


def validate_session(token: Optional[str], db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Validate a session token against memory cache or SQLite table."""
    if not token:
        return None

    now = datetime.now()
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


def revoke_session(token: Optional[str], db_path: str = DEFAULT_DB_PATH) -> bool:
    """Revoke an active session token from memory and database."""
    revoked = False
    if token and token in _ACTIVE_SESSIONS:
        del _ACTIVE_SESSIONS[token]
        revoked = True

    if token:
        try:
            init_db(db_path)
            with get_db_connection(db_path) as conn:
                cur = conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
                conn.commit()
                if cur.rowcount > 0:
                    revoked = True
        except Exception as e:
            logger.debug(f"Error deleting session from db: {e}")

    return revoked
