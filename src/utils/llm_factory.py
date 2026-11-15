"""
LLM Factory — returns a LangChain chat model based on env config.
Swap providers without touching any other code.

Usage:
    from src.utils.llm_factory import get_llm, get_embeddings
    llm = get_llm()
    embeddings = get_embeddings()
"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional
from urllib.parse import urlparse

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

from src.utils.config import get_env
from src.utils.logger import logger


class LocalDenseEmbeddings(Embeddings):
    """
    Deterministic, offline dense embeddings using token hashing and L2 normalization.
    Provides immediate local vector retrieval without external API keys or heavy weights.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _hash_token(self, token: str) -> int:
        return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dim

    def embed_query(self, text: str) -> List[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = text.lower().split()
        if not tokens:
            return vec.tolist()
        for tok in tokens:
            idx = self._hash_token(tok)
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]


def validate_gateway_url(url: str) -> str:
    """
    Ensure AI gateway connects strictly to loopback or uses TLS/HTTPS for remote endpoints.
    Protects candidate PII and resumes from cleartext transport exposure.
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    is_loopback = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    if parsed.scheme == "http" and not is_loopback:
        raise ValueError(
            f"Insecure gateway URL '{url}'. Remote AI gateway connections must use HTTPS to protect candidate PII."
        )
    return url


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Return a LangChain chat model based on LLM_PROVIDER env var.
    Defaults to OpenAI GPT-4o, supports Gemini and Anthropic (Orbit gateway).
    """
    env = get_env()
    provider = env.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        logger.info(f"[agent]🤖 LLM: OpenAI {env.llm_model}[/agent]")
        return ChatOpenAI(
            model=env.llm_model,
            temperature=temperature,
            api_key=env.openai_api_key,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        logger.info(f"[agent]🤖 LLM: Gemini {env.llm_model}[/agent]")
        return ChatGoogleGenerativeAI(
            model=env.llm_model,
            temperature=temperature,
            google_api_key=env.gemini_api_key,
        )

    elif provider in ("anthropic", "claude"):
        from langchain_anthropic import ChatAnthropic

        class OrbitCleanChatAnthropic(ChatAnthropic):
            """ChatAnthropic wrapper stripping Orbit proxy telemetry banners."""

            def _clean_msg(self, msg):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    msg.content = re.sub(
                        r"^>\s*🪐\s*\*\*Engine:\*\*.*?\n\n", "", msg.content, flags=re.DOTALL
                    ).strip()
                return msg

            def _generate(self, *args, **kwargs):
                res = super()._generate(*args, **kwargs)
                for gen in res.generations:
                    self._clean_msg(gen.message)
                    if hasattr(gen, "text"):
                        gen.text = re.sub(
                            r"^>\s*🪐\s*\*\*Engine:\*\*.*?\n\n", "", gen.text, flags=re.DOTALL
                        ).strip()
                return res

            async def _agenerate(self, *args, **kwargs):
                res = await super()._agenerate(*args, **kwargs)
                for gen in res.generations:
                    self._clean_msg(gen.message)
                    if hasattr(gen, "text"):
                        gen.text = re.sub(
                            r"^>\s*🪐\s*\*\*Engine:\*\*.*?\n\n", "", gen.text, flags=re.DOTALL
                        ).strip()
                return res

        raw_url = env.anthropic_base_url or "http://localhost:4981"
        base_url = validate_gateway_url(raw_url)
        api_key = env.anthropic_api_key or "orbit-sk-local"
        model_name = env.llm_model if env.llm_model and "gpt" not in env.llm_model else "claude-sonnet-4-6"

        logger.info(f"[agent]🤖 LLM: Anthropic {model_name} (gateway={base_url})[/agent]")
        return OrbitCleanChatAnthropic(
            model_name=model_name,
            temperature=temperature,
            anthropic_api_key=api_key,
            anthropic_api_url=base_url,
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider}'. "
            "Set LLM_PROVIDER=openai, LLM_PROVIDER=gemini, or LLM_PROVIDER=anthropic in .env"
        )


def get_embeddings() -> Embeddings:
    """
    Return a LangChain embeddings model based on EMBEDDINGS_PROVIDER env var.
    Supports OpenAI, Gemini, and local offline embeddings.
    """
    env = get_env()
    provider = env.embeddings_provider.lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        logger.info(f"[agent]📐 Embeddings: OpenAI {env.embeddings_model}[/agent]")
        return OpenAIEmbeddings(
            model=env.embeddings_model,
            api_key=env.openai_api_key,
        )

    elif provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        logger.info(f"[agent]📐 Embeddings: Gemini {env.embeddings_model}[/agent]")
        return GoogleGenerativeAIEmbeddings(
            model=env.embeddings_model,
            google_api_key=env.gemini_api_key,
        )

    elif provider in ("local", "offline", "fastembed"):
        logger.info(f"[agent]📐 Embeddings: Local Dense 384d (offline)[/agent]")
        return LocalDenseEmbeddings(dim=384)

    else:
        raise ValueError(
            f"Unknown EMBEDDINGS_PROVIDER='{provider}'. "
            "Set EMBEDDINGS_PROVIDER=openai, gemini, or local in .env"
        )
