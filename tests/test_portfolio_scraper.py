"""Tests for portfolio scraper module."""

from unittest.mock import patch, MagicMock
import pytest
import requests

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.ingestion.portfolio_scraper import scrape_portfolio


def test_scrape_portfolio_empty_url():
    """Empty or None URL returns empty list without making HTTP requests."""
    assert scrape_portfolio("") == []
    assert scrape_portfolio(None) == []
    assert scrape_portfolio("   ") == []


def test_scrape_portfolio_malformed_url():
    """Malformed URLs with unclosed brackets or invalid IPv6 structures return [] without crashing."""
    assert scrape_portfolio("http://[invalid-ipv6") == []
    assert scrape_portfolio("http://[::1/path") == []
    assert scrape_portfolio("http://[") == []


def test_scrape_portfolio_network_error():
    """Network connection errors or timeouts must be isolated and return []."""
    with patch("src.ingestion.portfolio_scraper.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("DNS failure")
        chunks = scrape_portfolio("https://nonexistent-site-domain.io")
        assert chunks == []


def test_scrape_portfolio_html_sanitization_and_chunking():
    """Verify script/style/nav/footer stripping and semantic heading categorization."""
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Alex Rivera - Portfolio</title>
        <style>body { font-family: sans-serif; }</style>
        <script>console.log("tracking pixel");</script>
    </head>
    <body>
        <nav><a href="#about">About</a><a href="#projects">Projects</a></nav>
        <header><h1>Alex Rivera Portfolio</h1></header>

        <section id="about">
            <h2>About Me</h2>
            <p>I am a senior distributed systems engineer with deep expertise in cloud architectures and Python agent frameworks.</p>
        </section>

        <section id="projects">
            <h2>Featured Projects</h2>
            <p>AutoBot: An autonomous agent designed to streamline complex job search tasks using LangGraph and Playwright.</p>
            <p>CloudLake: A petabyte-scale data lake orchestrator deployed on Kubernetes.</p>
        </section>

        <section id="skills">
            <h2>Technical Skills</h2>
            <p>Python, Go, Docker, Kubernetes, AWS, FastAPI, Redis, Qdrant</p>
        </section>

        <footer>
            <p>&copy; 2024 Alex Rivera. All rights reserved.</p>
        </footer>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.text = sample_html
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    with patch("src.ingestion.portfolio_scraper.requests.get", return_value=mock_resp):
        chunks = scrape_portfolio("https://alexrivera.dev")

    assert len(chunks) >= 3

    # Ensure no script, style, nav, or footer text leaked into chunks
    combined_content = " ".join(c.content for c in chunks)
    assert "tracking pixel" not in combined_content
    assert "font-family" not in combined_content
    assert "All rights reserved" not in combined_content

    sections = {c.section for c in chunks}
    assert SectionType.SUMMARY in sections
    assert SectionType.PROJECTS in sections
    assert SectionType.SKILLS in sections

    for c in chunks:
        assert c.source == IngestionSource.PORTFOLIO
        assert c.metadata.get("url") == "https://alexrivera.dev"


def test_scrape_portfolio_paragraph_fallback():
    """When HTML lacks standard headings, paragraphs should fallback to SectionType.OTHER."""
    plain_html = """
    <html><body>
        <p>This is a portfolio statement without any explicit headings or structure.</p>
        <p>It describes various technical capabilities and past project delivery achievements.</p>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.text = plain_html
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    with patch("src.ingestion.portfolio_scraper.requests.get", return_value=mock_resp):
        chunks = scrape_portfolio("https://simple-site.com")

    assert len(chunks) >= 1
    for c in chunks:
        assert c.source == IngestionSource.PORTFOLIO
        assert c.section == SectionType.OTHER
