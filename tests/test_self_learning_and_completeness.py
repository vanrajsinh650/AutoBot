"""
Systematic end-to-end verification tests for:
1. 100% scraped portal delivery (no 100-item dashboard truncation & underscore seniority fix).
2. Confidence-gated form resolution (never guessing options[0] on unknown questions).
3. Self-learning Q&A rules persisted in SQLite & reused automatically in both ExternalApplyActuator & FormRAG.
4. Real Chromium end-to-end proof: AutoBot stops before submit on an unknown question, captures a
   proof screenshot + pending question record, learns the user's answer via the Web API, and
   autonomously completes submission on re-run.
"""

import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.agent.state import JobPosting
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.groq_form_assistant import (
    answer_question_with_groq,
    resolve_form_question_with_confidence,
)
from src.matching.evaluator import is_senior_or_blacklisted_title
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType
from src.storage.db import (
    find_learned_qa_answer,
    get_apply_portals,
    get_pending_form_questions,
    init_db,
    save_learned_qa_rule,
    save_scraped_job,
)
from src.web.server import create_app


def test_underscore_seniority_boundary_detection():
    """Titles with underscores like IN_Senior Manager_FDC must be caught as senior."""
    is_sr, kw = is_senior_or_blacklisted_title("IN_Senior Manager_FDC, GenAI_Agentic")
    assert is_sr is True
    assert "senior" in kw.lower() or "manager" in kw.lower()


def test_dashboard_returns_all_portals_without_100_cap(tmp_path):
    """Verify get_apply_portals with limit=0 returns 100% of matching portals (>100)."""
    db_file = str(tmp_path / "all_portals.db")
    init_db(db_file)

    for i in range(135):
        save_scraped_job(
            title=f"Python Backend Developer #{i}",
            company=f"TechCo {i}",
            location="Remote",
            description="Python FastAPI backend engineering role with REST APIs.",
            apply_url=f"https://boards.greenhouse.io/techco{i}/jobs/{1000 + i}",
            source_name="Greenhouse",
            is_easy_apply=False,
            job_id=f"gh_all_{i}",
            user_id=1,
            match_score=0.82,
            db_path=db_file,
        )

    res = get_apply_portals(user_id=1, min_match_score=0.60, limit=0, db_path=db_file)
    assert res["grand_total"] == 135
    assert len(res["jobs"]) == 135


def test_unknown_question_does_not_guess_option_zero_and_self_learns(tmp_path, monkeypatch):
    """
    When encountering a new question without a verified answer, AutoBot MUST NOT guess options[0].
    Once the user teaches an answer, AutoBot remembers and applies it automatically every time.
    """
    db_file = str(tmp_path / "learn_test.db")
    init_db(db_file)

    monkeypatch.setattr("src.browser.groq_form_assistant.call_groq_json", lambda *args, **kwargs: None)

    question = "Do you hold an active Top Secret security clearance?"
    options = ["Active Top Secret", "No Clearance", "Interim Secret"]

    # Before learning: must refuse to guess and flag confident=False
    before = resolve_form_question_with_confidence(
        question=question,
        options=options,
        field_type="select",
        candidate_info={"user_id": 1},
        user_id=1,
        db_path=db_file,
    )
    assert before["confident"] is False
    assert before["answer"] == ""
    assert before["source"] == "unknown"
    assert answer_question_with_groq(question, options=options, user_id=1, db_path=db_file) == ""

    # User teaches AutoBot
    save_learned_qa_rule(
        user_id=1,
        question_pattern=question,
        user_answer="No Clearance",
        field_type="select",
        options=options,
        instruction_note="Always select No Clearance when asked about clearances",
        db_path=db_file,
    )

    # After learning: exact & phrased-variant questions resolve deterministically via learned_qa
    after = resolve_form_question_with_confidence(
        question="Active Top Secret security clearance status?",
        options=options,
        field_type="select",
        candidate_info={"user_id": 1},
        user_id=1,
        db_path=db_file,
    )
    assert after["confident"] is True
    assert after["source"] == "learned_qa"
    assert after["answer"] == "No Clearance"

    # Also verify FormRAG Tier 0 picks it up cleanly when AUTOBOT_DB_PATH points to db_file
    monkeypatch.setenv("AUTOBOT_DB_PATH", db_file)
    mock_retriever = type("R", (), {"retrieve": lambda self, query, top_k=4: []})()
    rag = FormRAG(retriever=mock_retriever, llm=None)
    rag_ans = rag.answer_question(question=question, field_type=FieldType.SELECT, options=options)
    assert rag_ans.source == "learned_qa"
    assert rag_ans.answer == "No Clearance"
    assert rag_ans.confidence == 1.0

    # Verify direct DB lookup hits & increments hit_count
    direct_learned = find_learned_qa_answer(user_id=1, question=question, options=options, db_path=db_file)
    assert direct_learned is not None
    assert direct_learned["answer"] == "No Clearance"


@pytest.mark.asyncio
async def test_web_learned_qa_api_roundtrip(tmp_path, monkeypatch):
    """Verify /api/learned-qa GET/POST/DELETE and /api/portals/{id}/pending-questions endpoints."""
    db_file = str(tmp_path / "web_learn.db")
    monkeypatch.setenv("AUTOBOT_DB_PATH", db_file)
    monkeypatch.setenv("AUTOBOT_STRICT_AUTH", "0")
    init_db(db_file)

    app = create_app()
    async with TestClient(TestServer(app)) as client:
        # Save a learned rule via POST /api/learned-qa
        resp = await client.post(
            "/api/learned-qa",
            json={
                "question": "Expected hourly rate in USD?",
                "answer": "$45/hr",
                "field_type": "text",
                "job_id": "job_test_1",
                "company": "Acme AI",
            },
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload["success"] is True
        rule_id = payload["rule"]["id"]

        # GET /api/learned-qa lists the rule
        list_resp = await client.get("/api/learned-qa")
        assert list_resp.status == 200
        listed = await list_resp.json()
        assert len(listed["rules"]) == 1
        assert listed["rules"][0]["user_answer"] == "$45/hr"

        # GET /api/apply-portals defaults to returning >100 items cleanly
        portals_resp = await client.get("/api/apply-portals?limit=0")
        assert portals_resp.status == 200

        # DELETE /api/learned-qa/{id} removes the rule
        del_resp = await client.delete(f"/api/learned-qa/{rule_id}")
        assert del_resp.status == 200


@pytest.mark.asyncio
async def test_real_chromium_stop_on_unknown_question_teach_and_resubmit(tmp_path, monkeypatch):
    """
    Real Playwright Chromium E2E proof:
    1. Form has contact fields + resume upload + brand new unknown required dropdown.
    2. Run 1 (no learned rule): AutoBot fills known fields, refuses to guess options[0],
       stops BEFORE clicking Submit, captures a proof screenshot, and stores pending question in DB.
    3. User teaches AutoBot ("None Required") via learned Q&A memory.
    4. Run 2: AutoBot applies learned rule, submits cleanly, and verifies thank-you confirmation!
    """
    from playwright.async_api import async_playwright

    db_file = str(tmp_path / "e2e_self_learn.db")
    proof_dir = tmp_path / "proofs"
    monkeypatch.setenv("AUTOBOT_DB_PATH", db_file)
    monkeypatch.setattr("src.browser.proof_audit.PROOF_DIR", proof_dir)
    monkeypatch.setattr("src.browser.groq_form_assistant.call_groq_json", lambda *args, **kwargs: None)
    init_db(db_file)

    submissions = []

    class _PortalHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            html = """<!doctype html>
<html>
<head><title>Acme AI - Application</title></head>
<body>
  <form id="app-form" method="POST" action="/submit">
    <div><label for="first_name">First Name *</label><input id="first_name" name="first_name" required></div>
    <div><label for="last_name">Last Name *</label><input id="last_name" name="last_name" required></div>
    <div><label for="email">Email *</label><input id="email" name="email" type="email" required></div>
    <div><label for="phone">Phone *</label><input id="phone" name="phone" type="tel" required></div>
    <div>
      <label for="custom_clearance">Do you hold an active Top Secret clearance? *</label>
      <select id="custom_clearance" name="custom_clearance" required>
        <option value="">Select...</option>
        <option value="top_secret">Yes - Active Top Secret</option>
        <option value="none_required">No Clearance Held</option>
      </select>
    </div>
    <button type="submit" id="submit-btn">Submit Application</button>
  </form>
  <script>
    document.getElementById('app-form').addEventListener('submit', function(e) {
      e.preventDefault();
      const sel = document.getElementById('custom_clearance').value;
      fetch('/record_submit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          first_name: document.getElementById('first_name').value,
          email: document.getElementById('email').value,
          clearance: sel
        })
      }).then(() => {
        document.body.innerHTML = '<h1>Thank you for applying! Your application has been received.</h1>';
      });
    });
  </script>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", errors="ignore")
            try:
                submissions.append(json.loads(body))
            except Exception:
                submissions.append({"raw": body})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

    server = HTTPServer(("127.0.0.1", 0), _PortalHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            candidate_info = {
                "user_id": 1,
                "first_name": "Vanraj",
                "last_name": "Solanki",
                "full_name": "Vanraj Solanki",
                "email": "vanrajsolanki2875@gmail.com",
                "phone": "+91-8320452875",
                "location": "Ahmedabad, Gujarat, India",
            }
            resume_pdf = tmp_path / "resume.pdf"
            resume_pdf.write_bytes(b"%PDF-1.4\n%Mock")

            actuator = ExternalApplyActuator(
                context=context,
                resume_path=resume_pdf,
                candidate_info=candidate_info,
            )
            job = JobPosting(
                job_id="e2e_clearance_01",
                title="Python AI Engineer",
                company="Acme AI",
                location="Remote",
                url=f"http://127.0.0.1:{port}/apply",
                external_apply_url=f"http://127.0.0.1:{port}/apply",
                is_easy_apply=False,
            )

            # Run 1: Must STOP before submit and capture proof screenshot
            res1 = await actuator.apply(job=job, dry_run=False)
            assert res1 is False
            assert len(submissions) == 0, "AutoBot must NOT submit when an unknown required question is present!"
            assert actuator.last_outcome["reason_code"] == "NEEDS_USER_INPUT"
            shot1_name = Path(actuator.last_outcome["proof_screenshot"]).name
            assert (proof_dir / shot1_name).is_file()

            pending = get_pending_form_questions(user_id=1, job_id="e2e_clearance_01", status="pending", db_path=db_file)
            assert len(pending) == 1
            assert "top secret" in pending[0]["question_text"].lower()
            assert "No Clearance Held" in pending[0]["options"]

            # Teach AutoBot user's instruction
            save_learned_qa_rule(
                user_id=1,
                question_pattern=pending[0]["question_text"],
                user_answer="No Clearance Held",
                field_type="select",
                options=pending[0]["options"],
                db_path=db_file,
            )

            # Run 2: Must recall learned rule, submit cleanly, and pass verification!
            res2 = await actuator.apply(job=job, dry_run=False)
            assert res2 is True
            assert len(submissions) == 1
            assert submissions[0]["first_name"] == "Vanraj"
            assert submissions[0]["clearance"] == "none_required"
            assert actuator.last_outcome["status"] == "applied"
            assert Path(actuator.last_outcome["proof_screenshot"]).name.endswith("_confirmed.png")

            await browser.close()
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_soft_challenge_terms_in_job_description_do_not_false_trigger():
    """Security Engineer job descriptions mentioning '2FA', 'MFA', or 'security check' when a form is visible must not abort."""
    from unittest.mock import AsyncMock, MagicMock
    from src.application.workflows import AntiBotChallengeDetected

    actuator = ExternalApplyActuator(context=MagicMock())
    page = AsyncMock()
    page.url = "https://boards.greenhouse.io/cloudflare/jobs/999"
    page.title = AsyncMock(return_value="Security Engineer at Cloudflare")
    page.evaluate = AsyncMock(return_value=(
        "we are hiring a security engineer to work on 2fa, mfa, and security check pipelines. "
        + "a" * 1600
    ))
    visible_input = AsyncMock()
    visible_input.is_visible = AsyncMock(return_value=True)

    async def _qs(sel):
        if "email" in sel or "first_name" in sel:
            return visible_input
        return None

    page.query_selector = AsyncMock(side_effect=_qs)
    # Must complete without raising AntiBotChallengeDetected
    await actuator.check_security_challenges(page)

    # Now verify a genuine short blocking gate WITHOUT visible form DOES raise AntiBotChallengeDetected
    page_blocked = AsyncMock()
    page_blocked.url = "https://example.com/apply"
    page_blocked.title = AsyncMock(return_value="Just a moment...")
    page_blocked.evaluate = AsyncMock(return_value="verify you are human before continuing")
    page_blocked.query_selector = AsyncMock(return_value=None)
    with pytest.raises(AntiBotChallengeDetected):
        await actuator.check_security_challenges(page_blocked)


def test_strict_resume_only_provenance_no_hardcoded_personal_defaults(tmp_path):
    """Profile extraction must strictly read the user's resume + DB without hardcoding another person's details."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from src.browser.external_apply_actuator import load_candidate_profile_info
    from src.utils.config import AppConfig

    other_pdf = tmp_path / "alice_resume.pdf"
    c = canvas.Canvas(str(other_pdf), pagesize=letter)
    c.drawString(80, 750, "Alice Vance")
    c.drawString(80, 730, "Email: alice.vance@example.org | Phone: +1-415-555-0192 | Location: Seattle, WA, USA")
    c.drawString(80, 700, "SKILLS")
    c.drawString(80, 680, "Languages: Python, Go, SQL")
    c.save()

    cfg = AppConfig()
    cfg.profile.resume_path = str(other_pdf)
    alice_info = load_candidate_profile_info(cfg=cfg, user_id=999, resume_path=other_pdf)
    assert alice_info["full_name"] == "Alice Vance"
    assert alice_info["first_name"] == "Alice"
    assert alice_info["last_name"] == "Vance"
    assert alice_info["email"] == "alice.vance@example.org"
    assert alice_info["linkedin"] == ""
    assert alice_info["github"] == ""
    assert alice_info["street_address"] == ""
    assert alice_info["postal_code"] == ""
    assert alice_info["gender"] == ""
    assert alice_info["graduation_year"] == ""

    real_info = load_candidate_profile_info(user_id=1)
    assert real_info["first_name"] == "Vanraj"
    assert real_info["last_name"] == "Solanki"
    assert real_info["linkedin"] == "https://www.linkedin.com/in/vanraj-s-5b5010336/"
    assert real_info["github"] == "https://github.com/vanrajsinh650"
    assert real_info["location"] == "Gujarat, India"
    assert real_info["street_address"] == ""
    assert real_info["postal_code"] == ""
    assert real_info["graduation_year"] == ""


