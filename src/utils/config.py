"""
Config loader — reads config.yaml + .env into typed Pydantic settings.

Every module imports from here. Never read files directly.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into os.environ immediately on import
load_dotenv()


# ── Sub-models ────────────────────────────────────────────────────

class ProfileConfig(BaseModel):
    resume_path: str = "data/resume/resume.pdf"
    linkedin_url: str = ""
    portfolio_url: str = ""


class SearchConfig(BaseModel):
    keywords: List[str] = ["Software Engineer"]
    location: str = "India"
    remote: bool = True
    date_posted: str = "week"
    experience_level: List[str] = ["mid-senior"]
    job_type: List[str] = ["full-time"]
    under_10_applicants: bool = False
    easy_apply_only: bool = False


class AnswersConfig(BaseModel):
    years_of_experience: str = "3"
    expected_salary: str = ""
    notice_period: str = "30 days"
    willing_to_relocate: str = "Yes"
    work_authorization: str = "Yes"
    sponsorship_required: str = "No"
    cover_letter: str = ""


class ApplyConfig(BaseModel):
    easy_apply: bool = True
    external_apply: bool = True
    max_applications: int = 30
    skip_already_applied: bool = True
    min_match_score: float = 0.6
    answers: AnswersConfig = Field(default_factory=AnswersConfig)


class BlacklistConfig(BaseModel):
    companies: List[str] = []
    title_keywords: List[str] = []


class AgentConfig(BaseModel):
    max_retries: int = 3
    max_pages: int = 5
    delay_between_jobs: int = 5


class BrowserConfig(BaseModel):
    backend: str = "chromium"
    slow_mo: int = 50
    viewport_width: int = 1280
    viewport_height: int = 800
    executable_path: str = ""
    use_system_chrome: bool = True
    cookie_policy: str = "auto_accept"  # auto_accept, auto_reject, hide_banner


class AppConfig(BaseModel):
    """Full typed config parsed from config.yaml"""
    profile:   ProfileConfig   = Field(default_factory=ProfileConfig)
    search:    SearchConfig    = Field(default_factory=SearchConfig)
    apply:     ApplyConfig     = Field(default_factory=ApplyConfig)
    blacklist: BlacklistConfig = Field(default_factory=BlacklistConfig)
    agent:     AgentConfig     = Field(default_factory=AgentConfig)
    browser:   BrowserConfig   = Field(default_factory=BrowserConfig)


# ── Env Settings ─────────────────────────────────────────────────

class EnvSettings(BaseSettings):
    """Typed environment variables from .env"""

    # Candidate Public Links
    linkedin_profile_url: str = ""

    # LLM
    openai_api_key:       str = ""
    gemini_api_key:       str = ""
    anthropic_api_key:    str = ""
    anthropic_base_url:   str = ""
    groq_api_key:         str = ""
    groq_base_url:        str = "https://api.groq.com/openai/v1"
    groq_model:           str = "openai/gpt-oss-120b"
    llm_provider:         str = "openai"       # openai | gemini | anthropic | groq
    llm_model:            str = "gpt-4o"
    embeddings_provider:  str = "openai"       # openai | gemini | local
    embeddings_model:     str = "text-embedding-3-small"

    # Qdrant
    qdrant_url:        str = "http://localhost:6333"
    qdrant_collection: str = "autobot_profile"

    # Browser
    headless:                bool = False
    browser_backend:         str = "chromium"     # chromium | obscura
    browser_executable_path: str = ""
    use_system_chrome:       bool = True
    obscura_binary_path:     str = ""
    obscura_port:            int = 9222

    # Logging
    log_level:         str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


# ── Loaders ──────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_env() -> EnvSettings:
    """Return cached env settings."""
    return EnvSettings()


@lru_cache(maxsize=1)
def get_config(path: str = "config.yaml") -> AppConfig:
    """Load and return cached AppConfig from YAML."""
    p = Path(path)
    if not p.exists() and (PROJECT_ROOT / path).exists():
        p = PROJECT_ROOT / path
    with open(p, "r") as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw)
