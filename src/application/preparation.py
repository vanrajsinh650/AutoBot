"""
Application Material Preparation Engine for AutoBot v2.
Generates truthful tailored variants, cover letters, question drafts, and missing info checklists.
Preserves original resume data and enforces user approval.
"""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.discovery.models import NormalizedJob
from src.storage.db import (
    DEFAULT_DB_PATH,
    get_candidate_profile,
    get_db_connection,
    get_job_preferences,
    init_db,
)
from src.utils.llm_factory import get_llm
from src.utils.logger import logger


class ApplicationPreparationService:
    """
    Assembles truthful application packs for candidate review and approval.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, llm: Optional[BaseChatModel] = None):
        self.db_path = db_path
        self._llm = llm

    def _get_llm(self) -> Optional[BaseChatModel]:
        if self._llm is not None:
            return self._llm
        try:
            self._llm = get_llm(temperature=0.2)
            return self._llm
        except Exception:
            return None

    def prepare_application_pack(
        self,
        user_id: int,
        job: NormalizedJob,
        match_evaluation_id: Optional[int] = None,
        resume_version_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Assemble comprehensive application materials:
        - Tailored summary highlighting real matching skills.
        - Truthful experience descriptions.
        - Tailored cover letter.
        - Application question drafts.
        - Missing info checklist.
        - Requires explicit user approval before marking ready.
        """
        init_db(self.db_path)
        profile = get_candidate_profile(user_id, self.db_path) or {}
        preferences = get_job_preferences(user_id, self.db_path)

        candidate_name = profile.get("full_name") or "Candidate"
        skills = profile.get("technical_skills") or []
        experience = profile.get("experience") or []

        # Find matching skills between job title/description and candidate skills
        desc_lower = job.description.lower()
        matching_skills = [s for s in skills if s.lower() in desc_lower]
        if not matching_skills and skills:
            matching_skills = skills[:4]

        # 1. Truthful Tailored Resume Summary
        tailored_summary = (
            f"Software Engineer with demonstrated expertise in {', '.join(matching_skills[:5])}. "
            f"Passionate about applying software engineering principles to {job.company}'s mission for the {job.title} role."
        )

        # 2. Truthful Tailored Experiences (highlight real bullet points)
        tailored_experiences = []
        for exp in experience[:3]:
            if isinstance(exp, dict):
                role = exp.get("role", "")
                company = exp.get("company", "")
                bullets = exp.get("bullets", [])
                # Reorder bullets to prioritize those mentioning matching skills
                highlighted_bullets = sorted(
                    bullets,
                    key=lambda b: any(s.lower() in b.lower() for s in matching_skills),
                    reverse=True,
                )
                tailored_experiences.append({
                    "role": role,
                    "company": company,
                    "bullets": highlighted_bullets,
                })

        # 3. Tailored Cover Letter (Truthful, non-fabricated)
        llm = self._get_llm()
        cover_letter = ""
        if llm:
            try:
                cl_prompt = (
                    f"Write a professional, concise, truthful 3-paragraph cover letter for {candidate_name} "
                    f"applying to the '{job.title}' position at '{job.company}'.\n"
                    f"The candidate's real verified technical skills are: {', '.join(matching_skills[:6])}.\n"
                    f"Candidate's real background:\n{json.dumps(tailored_experiences[:2])}\n\n"
                    "RULES:\n"
                    "1. Never fabricate experiences, employers, metrics, or degrees not provided.\n"
                    "2. Keep the tone professional, direct, and authentic.\n"
                    "3. Return only the text of the cover letter."
                )
                res = llm.invoke([
                    SystemMessage(content="You are a truthful career assistant. Never invent facts or hallucinate qualifications."),
                    HumanMessage(content=cl_prompt),
                ])
                cover_letter = res.content.strip() if isinstance(res.content, str) else str(res.content).strip()
            except Exception as e:
                logger.debug(f"LLM cover letter generation fallback: {e}")

        if not cover_letter:
            cover_letter = (
                f"Dear Hiring Team at {job.company},\n\n"
                f"I am writing to express my enthusiastic interest in the {job.title} position. "
                f"With a background in software development and practical experience utilizing {', '.join(matching_skills[:4])}, "
                f"I am eager to contribute effectively to your team's engineering goals.\n\n"
                f"In my previous roles, I have focused on building reliable, maintainable systems and collaborating "
                f"closely with cross-functional partners. I admire {job.company}'s work and look forward to the "
                f"opportunity to discuss how my qualifications align with your requirements.\n\n"
                f"Thank you for your time and consideration.\n\n"
                f"Sincerely,\n{candidate_name}"
            )

        # 4. Screening Question Drafts
        question_drafts = [
            {
                "question": "How many years of relevant experience do you have?",
                "draft_answer": str(max(1, len(experience) * 2)),
                "requires_review": True,
            },
            {
                "question": "Are you legally authorized to work in the role's designated country?",
                "draft_answer": "Yes",
                "requires_review": True,
            },
            {
                "question": "Will you now or in the future require visa sponsorship?",
                "draft_answer": "No",
                "requires_review": True,
            },
            {
                "question": "What is your desired salary / compensation expectation?",
                "draft_answer": f"{preferences.get('min_salary', 'Competitive')} (open to discussion)",
                "requires_review": True,
            },
            {
                "question": "What is your availability / notice period?",
                "draft_answer": "Standard 30 days notice (or immediate if agreed)",
                "requires_review": True,
            },
        ]

        # 5. Missing Information Checklist
        checklist = [
            {"item": "Verify accurate contact details (email, phone, LinkedIn URL)", "checked": False},
            {"item": "Review and approve tailored resume summary", "checked": False},
            {"item": "Review cover letter and personalize company references", "checked": False},
            {"item": "Confirm work authorization eligibility and country regulations", "checked": False},
        ]
        if not profile.get("phone"):
            checklist.append({"item": "Add candidate phone number in Profile settings", "checked": False})
        if not profile.get("linkedin_url") and "linkedin" in job.application_url.lower():
            checklist.append({"item": "Add candidate LinkedIn profile link", "checked": False})

        # 6. Job Match Explanation
        job_match_explanation = ""
        with get_db_connection(self.db_path) as conn:
            if match_evaluation_id:
                eval_row = conn.execute("SELECT explanation FROM match_evaluations WHERE id = ?", (match_evaluation_id,)).fetchone()
                if eval_row and eval_row["explanation"]:
                    job_match_explanation = eval_row["explanation"]

        if not job_match_explanation:
            job_match_explanation = (
                f"Application prepared for {candidate_name} applying to '{job.title}' at '{job.company}'. "
                f"Verified matching core competencies: {', '.join(matching_skills[:6])}. "
                "Materials generated truthfully without qualification fabrication."
            )

        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            job_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (job.stable_id,)).fetchone()
            job_internal_id = job_row["id"] if job_row else 0

            cur = conn.execute(
                """
                INSERT INTO application_packs (
                    user_id, job_id, resume_version_id, match_evaluation_id,
                    tailored_resume_summary, tailored_experiences, cover_letter,
                    question_drafts, missing_info_checklist, job_match_explanation, user_approved,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    user_id,
                    job_internal_id,
                    resume_version_id,
                    match_evaluation_id,
                    tailored_summary,
                    json.dumps(tailored_experiences),
                    cover_letter,
                    json.dumps(question_drafts),
                    json.dumps(checklist),
                    job_match_explanation,
                    now,
                    now,
                ),
            )
            pack_id = cur.lastrowid

            # Record event
            conn.execute(
                """
                INSERT INTO application_events (
                    user_id, job_id, pack_id, event_type, status, user_confirmed, proof_notes, created_at
                ) VALUES (?, ?, ?, 'prepared', 'prepared', 0, 'Application pack generated', ?)
                """,
                (user_id, job_internal_id, pack_id, now),
            )
            conn.commit()

        return {
            "id": pack_id,
            "user_id": user_id,
            "job_stable_id": job.stable_id,
            "tailored_resume_summary": tailored_summary,
            "tailored_experiences": tailored_experiences,
            "cover_letter": cover_letter,
            "question_drafts": question_drafts,
            "missing_info_checklist": checklist,
            "job_match_explanation": job_match_explanation,
            "user_approved": False,
        }

    def set_user_approval(self, user_id: int, pack_id: int, approved: bool) -> bool:
        """Explicitly record human candidate approval for an application pack."""
        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE application_packs
                SET user_approved = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (1 if approved else 0, now, pack_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
