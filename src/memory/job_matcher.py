"""
Job Match Evaluator (Semantic Matching & Scoring Engine).

Educational Concept:
An agentic job bot should not blindly apply to every job returned by search.
Blind applying burns rate limits, risks account flags, and yields low conversion.

JobMatcher implements an automated qualification gate:
1. Candidate Grounding:
   Extracts key technical requirements from the job description and performs
   multi-aspect vector search across candidate skills and experience in Qdrant.
2. Structured LLM Evaluation:
   Prompts the model with a strict evaluation rubric (skills alignment,
   seniority calibration, domain experience) and demands a structured JSON verdict.
3. Resilient Fallback:
   If the LLM is unavailable, computes a mathematical score using the mean cosine
   similarity of top retrieved chunks combined with lexical keyword overlap.
4. Decision Threshold:
   Compares the composite match score against `min_match_score` (configured in
   config.yaml, e.g. 0.6) to drive the LangGraph state machine branch (should_apply).
"""

import json
import re
from typing import List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.memory.models import JobMatchEvaluation, RetrievedChunk
from src.memory.retriever import ProfileRetriever
from src.utils.config import get_config
from src.utils.llm_factory import get_llm
from src.utils.logger import logger


class JobMatcher:
    """
    Evaluates job postings against the candidate's profile stored in Qdrant vector memory.
    """

    def __init__(
        self,
        retriever: ProfileRetriever,
        llm: Optional[BaseChatModel] = None,
        min_match_score: Optional[float] = None,
    ):
        self.retriever = retriever
        self.llm = llm
        if min_match_score is not None:
            self.min_match_score = float(min_match_score)
        else:
            try:
                self.min_match_score = float(get_config().apply.min_match_score)
            except Exception:
                self.min_match_score = 0.60

    def _get_llm(self) -> Optional[BaseChatModel]:
        """Lazy loader for LLM model."""
        if self.llm is not None:
            return self.llm
        try:
            self.llm = get_llm(temperature=0.0)
            return self.llm
        except Exception as e:
            logger.debug(f"LLM not initialized in JobMatcher: {e}")
            return None

    def evaluate_job(
        self,
        job_title: str,
        company: str,
        job_description: str,
    ) -> JobMatchEvaluation:
        """
        Evaluate candidate fit for a job posting.

        Args:
            job_title: The title of the role (e.g. "Senior Python Engineer").
            company: Hiring organization name.
            job_description: Raw job description text with requirements and responsibilities.

        Returns:
            JobMatchEvaluation with match_score (0.0 to 1.0) and boolean is_match.
        """
        desc_clean = job_description.strip()
        if not desc_clean:
            # If no description provided, evaluate purely on job title
            desc_clean = f"Role: {job_title} at {company}"

        # 1. Retrieve relevant candidate profile evidence
        # Query combining title and top 300 chars of description
        search_query = f"{job_title}\n{desc_clean[:400]}"
        evidence = self.retriever.retrieve(query=search_query, top_k=6)

        llm_model = self._get_llm()

        # 2. Try LLM Structured Evaluation
        if llm_model and evidence:
            try:
                evaluation = self._llm_evaluate(
                    llm=llm_model,
                    job_title=job_title,
                    company=company,
                    job_description=desc_clean,
                    evidence=evidence,
                )
                if evaluation:
                    logger.info(
                        f"[matcher]🎯 Match score for {job_title} @ {company}: "
                        f"{evaluation.match_score:.2f} (Match: {evaluation.is_match})[/matcher]"
                    )
                    return evaluation
            except Exception as e:
                logger.warning(f"LLM job evaluation failed ({e}); falling back to vector heuristics.")

        # 3. Fallback Heuristic Evaluation
        fallback_eval = self._heuristic_evaluate(
            job_title=job_title,
            company=company,
            job_description=desc_clean,
            evidence=evidence,
        )
        logger.info(
            f"[matcher]🎯 Heuristic match score for {job_title} @ {company}: "
            f"{fallback_eval.match_score:.2f} (Match: {fallback_eval.is_match})[/matcher]"
        )
        return fallback_eval

    def _llm_evaluate(
        self,
        llm: BaseChatModel,
        job_title: str,
        company: str,
        job_description: str,
        evidence: List[RetrievedChunk],
    ) -> Optional[JobMatchEvaluation]:
        """Prompt LLM to evaluate match score and extract structured assessment."""
        evidence_str = "\n\n".join(
            f"[{c.source.value.upper()} | {c.section.value.upper()}]:\n{c.content}"
            for c in evidence
        )

        system_prompt = (
            "You are an expert technical recruiter evaluating candidate fit for a job posting.\n"
            "Evaluate the match between the candidate's profile and the job description.\n"
            "Score on a scale of 0.0 to 1.0 based on:\n"
            "- Tech stack and primary tools match (40%)\n"
            "- Seniority and experience depth (30%)\n"
            "- Domain relevance and responsibilities (30%)\n\n"
            "You MUST output ONLY a valid JSON object with these exact keys:\n"
            "{\n"
            '  "match_score": float (between 0.0 and 1.0),\n'
            '  "matching_skills": ["skill1", "skill2"],\n'
            '  "missing_skills": ["skill3"],\n'
            '  "summary_reason": "concise 1-2 sentence justification",\n'
            '  "relevant_experiences": ["company or project highlight"]\n'
            "}"
        )

        user_prompt = (
            f"JOB TITLE: {job_title}\n"
            f"COMPANY: {company}\n"
            f"JOB DESCRIPTION:\n{job_description[:2500]}\n\n"
            f"CANDIDATE PROFILE EVIDENCE:\n{evidence_str}\n\n"
            "JSON ASSESSMENT:"
        )

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        raw_content = str(response.content).strip()

        # Extract JSON from code fences if present
        json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if not json_match:
            return None

        parsed = json.loads(json_match.group(0))
        score = float(parsed.get("match_score", 0.5))
        # Clamp score between 0.0 and 1.0
        score = max(0.0, min(1.0, score))

        is_match = score >= self.min_match_score

        return JobMatchEvaluation(
            job_title=job_title,
            company=company,
            match_score=round(score, 2),
            is_match=is_match,
            matching_skills=list(parsed.get("matching_skills", [])),
            missing_skills=list(parsed.get("missing_skills", [])),
            summary_reason=str(parsed.get("summary_reason", "")),
            relevant_experiences=list(parsed.get("relevant_experiences", [])),
        )

    def _heuristic_evaluate(
        self,
        job_title: str,
        company: str,
        job_description: str,
        evidence: List[RetrievedChunk],
    ) -> JobMatchEvaluation:
        """Mathematical fallback score derived from vector cosine similarities and lexical overlap."""
        if not evidence:
            return JobMatchEvaluation(
                job_title=job_title,
                company=company,
                match_score=0.30,
                is_match=False,
                summary_reason="No matching candidate profile data found in vector database.",
            )

        # 1. Base score from top chunk cosine similarities
        scores = [c.score for c in evidence if c.score > 0.0]
        if scores:
            avg_similarity = sum(scores) / len(scores)
        else:
            avg_similarity = 0.50

        # 2. Extract technical keywords from job title
        title_words = set(re.findall(r"\b[A-Za-z]{3,}\b", job_title.lower()))
        combined_profile_text = " ".join(c.content.lower() for c in evidence)

        matched_title_keywords = [
            w for w in title_words
            if w in combined_profile_text and w not in ("and", "the", "for", "with")
        ]

        title_overlap_ratio = len(matched_title_keywords) / max(len(title_words), 1)

        # Composite score
        composite_score = (avg_similarity * 0.70) + (title_overlap_ratio * 0.30)
        composite_score = max(0.0, min(1.0, composite_score))

        is_match = composite_score >= self.min_match_score

        return JobMatchEvaluation(
            job_title=job_title,
            company=company,
            match_score=round(composite_score, 2),
            is_match=is_match,
            matching_skills=matched_title_keywords,
            missing_skills=[],
            summary_reason=(
                f"Heuristic evaluation: Vector similarity {avg_similarity:.2f} "
                f"with {len(matched_title_keywords)} title keywords matched."
            ),
            relevant_experiences=[c.content[:80] + "..." for c in evidence[:2]],
        )
