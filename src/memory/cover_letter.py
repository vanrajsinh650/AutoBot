"""
Personalized Cover Letter Generator (Grounded Profile Synthesis).

Educational Concept:
Automated cover letters typically fall into two failure modes:
1. Pure Hallucination: The LLM invents companies and metrics the candidate never achieved.
2. Generic Spam: A static, repetitive template that ignores the company's actual stack.

CoverLetterGenerator solves this by grounding generation in vector memory:
1. Target Retrieval:
   Retrieves the candidate's top projects and accomplishments matching the target
   role's specific technical challenges.
2. Strict Grounding Constraint:
   The LLM prompt strictly forbids fabricating facts, metrics, or years. It only
   synthesizes verified achievements present in the retrieved context.
3. Fallback Template Engine:
   If the LLM is unconfigured or unavailable, substitutes role/company metadata
   into the candidate's approved template from `config.yaml`.
"""

from typing import List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.memory.models import CoverLetter, RetrievedChunk
from src.memory.retriever import ProfileRetriever
from src.utils.config import get_config
from src.utils.llm_factory import get_llm
from src.utils.logger import logger


_UNSET = object()


class CoverLetterGenerator:
    """
    Synthesizes tailored, truthful cover letters grounded in Qdrant profile evidence.
    """

    def __init__(
        self,
        retriever: ProfileRetriever,
        llm: Optional[BaseChatModel] = _UNSET,
        default_template: Optional[str] = None,
    ):
        self.retriever = retriever
        self._llm = None if llm is _UNSET else llm
        self._lazy_load = (llm is _UNSET)
        if default_template is not None:
            self.default_template = default_template
        else:
            try:
                self.default_template = get_config().apply.answers.cover_letter
            except Exception:
                self.default_template = ""

    @property
    def llm(self) -> Optional[BaseChatModel]:
        return self._llm

    @llm.setter
    def llm(self, value: Optional[BaseChatModel]) -> None:
        self._llm = value
        self._lazy_load = False

    def _get_llm(self) -> Optional[BaseChatModel]:
        """Lazy loader for LLM model."""
        if not self._lazy_load:
            return self._llm
        if self._llm is not None:
            return self._llm
        try:
            self._llm = get_llm(temperature=0.2)
            return self._llm
        except Exception as e:
            logger.debug(f"LLM not initialized in CoverLetterGenerator: {e}")
            return None

    def generate(
        self,
        job_title: str,
        company: str,
        job_description: str,
        recipient: str = "Hiring Team",
    ) -> CoverLetter:
        """
        Generate a personalized, truthful cover letter for a job opportunity.

        Args:
            job_title: Title of target position.
            company: Organization name.
            job_description: Job requirements and overview.
            recipient: Addressee (defaults to "Hiring Team").

        Returns:
            CoverLetter instance.
        """
        # 1. Retrieve top project and experience chunks relevant to the job requirements
        evidence = self.retriever.retrieve(
            query=f"{job_title} {job_description[:300]}",
            top_k=5,
        )

        llm_model = self._get_llm()

        # 2. Try LLM Generation
        if llm_model and evidence:
            try:
                content = self._llm_generate(
                    llm=llm_model,
                    job_title=job_title,
                    company=company,
                    job_description=job_description,
                    evidence=evidence,
                    recipient=recipient,
                )
                if content:
                    logger.info(
                        f"[cover]✓ Generated tailored cover letter for {job_title} @ {company}[/cover]"
                    )
                    return CoverLetter(
                        recipient=recipient,
                        company=company,
                        role=job_title,
                        content=content,
                        highlighted_skills=[c.section.value for c in evidence[:3]],
                    )
            except Exception as e:
                logger.warning(
                    f"LLM cover letter generation failed ({e}); falling back to template."
                )

        # 3. Fallback to Template
        fallback_letter = self._template_generate(
            job_title=job_title,
            company=company,
            recipient=recipient,
        )
        logger.info(
            f"[cover]✓ Using template cover letter for {job_title} @ {company}[/cover]"
        )
        return CoverLetter(
            recipient=recipient,
            company=company,
            role=job_title,
            content=fallback_letter,
            highlighted_skills=[],
        )

    def _llm_generate(
        self,
        llm: BaseChatModel,
        job_title: str,
        company: str,
        job_description: str,
        evidence: List[RetrievedChunk],
        recipient: str,
    ) -> str:
        """Prompt LLM to write a concise, grounded cover letter."""
        evidence_text = "\n\n".join(
            f"[{c.source.value.upper()} | {c.section.value.upper()}]:\n{c.content}"
            for c in evidence
        )

        system_prompt = (
            "You are a professional software engineer crafting a concise, persuasive cover letter.\n"
            "Rules:\n"
            "1. Length: 150 to 220 words (2-3 short, impactful paragraphs).\n"
            "2. Grounding: You MUST ONLY reference technical skills, projects, and experiences found in the candidate evidence. NEVER invent metrics, years of experience, or unmentioned technologies.\n"
            "3. Tone: Direct, energetic, professional, confident without exaggeration.\n"
            "4. Structure:\n"
            "   - Opening: Enthusiastic application for the specific role at the company.\n"
            "   - Body: 1-2 concrete accomplishments from the profile directly solving the job's needs.\n"
            "   - Closing: Brief statement of value and invitation to interview."
        )

        user_prompt = (
            f"RECIPIENT: {recipient}\n"
            f"ROLE: {job_title}\n"
            f"COMPANY: {company}\n"
            f"JOB REQUIREMENTS:\n{job_description[:1500]}\n\n"
            f"VERIFIED CANDIDATE PROFILE EVIDENCE:\n{evidence_text}\n\n"
            "COVER LETTER:"
        )

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        return str(response.content).strip()

    def _template_generate(
        self,
        job_title: str,
        company: str,
        recipient: str,
    ) -> str:
        """Fill in default cover letter template with role and company variables."""
        if self.default_template.strip():
            template = self.default_template
            template = template.replace("{role}", job_title)
            template = template.replace("{company}", company)
            template = template.replace("{recipient}", recipient)
            return template.strip()

        # Sensible clean default if no template in config
        return (
            f"Dear {recipient},\n\n"
            f"I am writing to express my enthusiasm for the {job_title} position at {company}. "
            "With a strong foundation in modern software development and engineering best practices, "
            "I have built scalable backend systems, APIs, and robust architectures that drive business results.\n\n"
            f"My technical background and proactive problem-solving approach align closely with what {company} "
            "is looking for. I am eager to bring my experience to your engineering team and contribute "
            "meaningfully to your goals.\n\n"
            "Thank you for your time and consideration. I look forward to speaking with you.\n\n"
            "Best regards,\nCandidate"
        )
