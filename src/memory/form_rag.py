"""
Form Question Answering (Screening Questions RAG Engine).

Educational Concept:
Automated job applications require answering hundreds of unique, unpredictable
screening questions (e.g. "Describe your backend microservices experience",
"How many years have you used Docker?", "Are you legally authorized to work?").

A naive bot relies on hardcoded string templates which break easily.
FormRAG implements a 3-tier hierarchical resolution pipeline:
1. Tier 1: Authoritative Config Overrides
   Deterministic answers for legal/compliance questions (citizenship, salary,
   notice period) that must never hallucinate.
2. Tier 2: Grounded Semantic RAG
   Retrieves factual evidence from the candidate's vector profile in Qdrant,
   prompts the LLM with strict output schemas (number, exact dropdown option, etc.).
3. Tier 3: Heuristic Fallback
   Graceful degradation if the LLM or network is unavailable, ensuring the application
   flow does not crash.
"""

import re
from typing import Any, Dict, List, Optional, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.memory.models import FieldType, FormAnswer, FormQuestion, RetrievedChunk
from src.memory.retriever import ProfileRetriever
from src.utils.config import AnswersConfig, get_config
from src.utils.llm_factory import get_llm
from src.utils.logger import logger


_UNSET = object()


class FormRAG:
    """
    RAG-powered form answering agent for LinkedIn Easy Apply and external forms.
    """

    def __init__(
        self,
        retriever: ProfileRetriever,
        llm: Any = _UNSET,
        config_answers: Optional[Union[Dict[str, Any], AnswersConfig]] = None,
    ):
        self.retriever = retriever
        self._llm = None if llm is _UNSET else llm
        self._lazy_load = (llm is _UNSET)
        if config_answers is None:
            try:
                self.config_answers = get_config().apply.answers.model_dump()
            except Exception:
                self.config_answers = {}
        elif isinstance(config_answers, AnswersConfig):
            self.config_answers = config_answers.model_dump()
        else:
            self.config_answers = dict(config_answers)

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
            self._llm = get_llm(temperature=0.0)
            return self._llm
        except Exception as e:
            logger.debug(f"LLM not initialized: {e}")
            return None

    def answer_question(
        self,
        question: Union[str, FormQuestion],
        field_type: FieldType = FieldType.TEXT,
        options: Optional[List[str]] = None,
        required: bool = True,
    ) -> FormAnswer:
        """
        Produce a grounded answer for an application form question.

        Args:
            question: Question string or FormQuestion instance.
            field_type: FieldType enum (text, number, select, radio, checkbox).
            options: Allowed values for select/radio fields.
            required: Whether the question is mandatory.

        Returns:
            FormAnswer instance containing the formatted text, confidence, and evidence.
        """
        # 1. Normalize parameters
        if isinstance(question, FormQuestion):
            q_text = question.question
            f_type = question.field_type
            opts = question.options or options
        else:
            q_text = question
            f_type = field_type
            opts = options

        q_clean = q_text.strip()
        if not q_clean:
            return FormAnswer(
                question=q_text,
                answer="",
                confidence=0.0,
                source="fallback",
            )

        # ── Tier 1: Config overrides ──────────────────────────────────
        config_override = self._check_config_overrides(q_clean, f_type, opts)
        if config_override is not None:
            logger.info(
                f"[form]✓ Config override for '{q_clean[:40]}...': {config_override}[/form]"
            )
            return FormAnswer(
                question=q_clean,
                answer=config_override,
                confidence=1.0,
                source="config_override",
            )

        # ── Tier 2: RAG Retrieval from Qdrant ─────────────────────────
        evidence = self.retriever.retrieve(query=q_clean, top_k=4)

        llm_model = self._get_llm()
        if llm_model and evidence:
            try:
                llm_answer = self._generate_llm_answer(
                    llm=llm_model,
                    question=q_clean,
                    field_type=f_type,
                    options=opts,
                    evidence=evidence,
                )
                if llm_answer:
                    # Post-process answer based on field_type constraints
                    formatted_answer = self._format_answer_for_field(
                        llm_answer, f_type, opts
                    )
                    logger.info(
                        f"[form]✓ RAG answer for '{q_clean[:40]}...': {formatted_answer}[/form]"
                    )
                    return FormAnswer(
                        question=q_clean,
                        answer=formatted_answer,
                        confidence=0.88,
                        source="rag_llm",
                        evidence_chunks=evidence,
                    )
            except Exception as e:
                logger.warning(f"RAG LLM question answering failed: {e}")

        # ── Tier 3: Heuristic fallback ────────────────────────────────
        fallback_val = self._fallback_answer(q_clean, f_type, opts)
        logger.info(
            f"[form]⚠ Heuristic fallback for '{q_clean[:40]}...': {fallback_val}[/form]"
        )
        return FormAnswer(
            question=q_clean,
            answer=fallback_val,
            confidence=0.5,
            source="fallback",
            evidence_chunks=evidence,
        )

    def _check_config_overrides(
        self,
        question: str,
        field_type: FieldType,
        options: Optional[List[str]],
    ) -> Optional[str]:
        """Check if question matches deterministic answer rules in config."""
        q_lower = question.lower()
        answers = self.config_answers

        keyword_map = {
            ("year", "experience"): "years_of_experience",
            ("years", "experience"): "years_of_experience",
            ("salary", "expect"): "expected_salary",
            ("expected", "ctc"): "expected_salary",
            ("notice", "period"): "notice_period",
            ("relocat",): "willing_to_relocate",
            ("authorized", "work"): "work_authorization",
            ("legally", "authorized"): "work_authorization",
            ("visa", "sponsor"): "sponsorship_required",
            ("require", "sponsorship"): "sponsorship_required",
        }

        for keywords, key in keyword_map.items():
            if all(kw in q_lower for kw in keywords) and key in answers:
                # Disambiguation: Questions asking "experience with <Tool>" or "experience in <Stack>"
                # are skill-specific, so they should be answered via RAG rather than candidate's total YOE.
                if key == "years_of_experience":
                    if any(term in q_lower for term in ("with ", "in ", "using ", "on ")):
                        continue

                val = str(answers.get(key, "")).strip()
                if val:
                    return self._format_answer_for_field(val, field_type, options)

        return None

    def _generate_llm_answer(
        self,
        llm: BaseChatModel,
        question: str,
        field_type: FieldType,
        options: Optional[List[str]],
        evidence: List[RetrievedChunk],
    ) -> str:
        """Prompt LLM with retrieved context and strict output schemas."""
        context_text = "\n\n".join(
            f"[{c.source.value.upper()} | {c.section.value.upper()}]:\n{c.content}"
            for c in evidence
        )

        options_clause = ""
        if options and field_type in (FieldType.SELECT, FieldType.RADIO):
            options_clause = (
                f"\nAllowed options (YOU MUST PICK EXACTLY ONE OF THESE):\n"
                + "\n".join(f"- {opt}" for opt in options)
            )

        system_prompt = (
            "You are an AI assistant representing a candidate on a job application form.\n"
            "Answer the question truthfully and concisely based solely on the provided candidate profile.\n"
            "Rules:\n"
            "1. Output ONLY the final answer value. Do not include prefixes like 'Answer:', conversational text, or explanations.\n"
            "2. If field_type is 'number', return ONLY digits (or decimal). If the candidate lacks experience in this skill, return 0.\n"
            "3. If allowed options are given, choose the best matching option EXACTLY as listed.\n"
            "4. For yes/no questions, answer 'Yes' or 'No'.\n"
            "5. If field_type is 'textarea' or 'text', keep the answer professional, compelling, and under 100 words."
        )

        user_prompt = (
            f"CANDIDATE PROFILE EVIDENCE:\n{context_text}\n\n"
            f"QUESTION: {question}\n"
            f"FIELD TYPE: {field_type.value}"
            f"{options_clause}\n\n"
            f"ANSWER:"
        )

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        raw_text = str(response.content).strip()

        # Clean any accidental conversational prefixes
        for prefix in ("Answer:", "ANSWER:", "Response:", "Result:"):
            if raw_text.startswith(prefix):
                raw_text = raw_text[len(prefix):].strip()

        return raw_text

    def _format_answer_for_field(
        self,
        raw_answer: str,
        field_type: FieldType,
        options: Optional[List[str]],
    ) -> str:
        """Format and constrain raw answer to adhere strictly to HTML input specifications."""
        answer = raw_answer.strip()

        if field_type == FieldType.NUMBER:
            # Extract first numeric sequence (integer or float)
            match = re.search(r"[-+]?\d*\.?\d+", answer)
            if match:
                return match.group(0)
            return "0"

        if field_type in (FieldType.SELECT, FieldType.RADIO) and options:
            return self._match_best_option(answer, options)

        if field_type == FieldType.CHECKBOX:
            lower = answer.lower()
            if any(term in lower for term in ("yes", "true", "1", "agree", "accept")):
                return "Yes"
            return "No"

        return answer

    @staticmethod
    def _match_best_option(answer: str, options: List[str]) -> str:
        """Find the best matching option from a dropdown/radio list."""
        if not options:
            return answer

        ans_lower = answer.lower().strip()

        # 1. Exact match
        for opt in options:
            if opt.lower().strip() == ans_lower:
                return opt

        # 2. Substring match
        for opt in options:
            opt_lower = opt.lower().strip()
            if ans_lower in opt_lower or opt_lower in ans_lower:
                return opt

        # 3. Boolean heuristics (Yes/No)
        if ans_lower in ("yes", "true", "1"):
            for opt in options:
                if "yes" in opt.lower():
                    return opt
        if ans_lower in ("no", "false", "0"):
            for opt in options:
                if "no" in opt.lower():
                    return opt

        # 4. Fallback to first non-empty option
        return options[0]

    def _fallback_answer(
        self,
        question: str,
        field_type: FieldType,
        options: Optional[List[str]],
    ) -> str:
        """Deterministic heuristic fallback when neither config nor LLM can provide an answer."""
        q_lower = question.lower()

        if field_type == FieldType.NUMBER:
            if "year" in q_lower or "experience" in q_lower:
                return self.config_answers.get("years_of_experience", "3")
            if "salary" in q_lower or "ctc" in q_lower:
                return "1000000"
            return "1"

        if field_type in (FieldType.SELECT, FieldType.RADIO) and options:
            if any(kw in q_lower for kw in ("authorized", "legally", "relocat", "willing")):
                for opt in options:
                    if "yes" in opt.lower():
                        return opt
            if any(kw in q_lower for kw in ("sponsor", "visa")):
                for opt in options:
                    if "no" in opt.lower():
                        return opt
            return options[0]

        if any(term in q_lower for term in ("are you", "do you", "can you", "authorized", "willing")):
            return "Yes"

        return "Yes"
