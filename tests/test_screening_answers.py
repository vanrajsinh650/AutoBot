import pytest
from src.browser.groq_form_assistant import answer_question_with_groq

def test_micron_screening_questions_deterministic_answers():
    candidate = {
        "full_name": "Vanraj Solanki",
        "email": "vanrajsolanki2875@gmail.com",
        "phone": "+91-8320452875",
        "current_title": "Software & Automation Engineer",
        "expected_salary": "100000",
    }

    # 1. Relatives / Friends
    ans1 = answer_question_with_groq(
        "Do you have any friends/relatives presently employed by Micron?*",
        candidate_info=candidate,
    )
    assert ans1 == "No", f"Expected 'No', got '{ans1}'"

    # 2. Previous applications / former employee
    ans2 = answer_question_with_groq(
        "Have you applied on any previous occasions for employment in any capacity with Micron?*",
        candidate_info=candidate,
    )
    assert ans2 == "No", f"Expected 'No', got '{ans2}'"

    # 3. Employee referral
    ans3 = answer_question_with_groq(
        "Are you referred to this job by a Micron employee?*",
        candidate_info=candidate,
    )
    assert ans3 == "No", f"Expected 'No', got '{ans3}'"

    # 4. Termination / Resignation
    ans4 = answer_question_with_groq(
        "Have you ever been terminated or asked to resign by any former employer for the following reasons:*",
        candidate_info=candidate,
    )
    assert ans4 == "No", f"Expected 'No', got '{ans4}'"

    # 5. Salary
    ans5 = answer_question_with_groq(
        "Expected Monthly Basic Salary (exclude allowance & overtime pay):*",
        candidate_info=candidate,
    )
    assert ans5 == "100000", f"Expected '100000', got '{ans5}'"

    # 6. Title only when explicitly requested
    ans6 = answer_question_with_groq(
        "Current Job Title / Designation:*",
        candidate_info=candidate,
    )
    assert "Software" in ans6, f"Expected role title, got '{ans6}'"

    # 7. Authorization & Age
    assert answer_question_with_groq("Are you legally authorized to work in this location?", candidate_info=candidate) == "Yes"
    assert answer_question_with_groq("Are you at least 18 years of age?", candidate_info=candidate) == "Yes"
    assert answer_question_with_groq("Will you now or in the future require visa sponsorship?", candidate_info=candidate) == "No"
