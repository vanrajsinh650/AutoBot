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


def test_eeoc_and_dropdown_options():
    # Without user-supplied/learned demographic answers, AutoBot MUST NOT fabricate gender/race/veteran/disability
    blank_candidate = {
        "full_name": "Vanraj Solanki",
        "expected_salary": "100000",
    }
    assert answer_question_with_groq("Gender", options=["Female", "Male", "Decline"], candidate_info=blank_candidate) == ""
    assert answer_question_with_groq("Race / Ethnicity", options=["Hispanic/Latino", "Asian (Not Hispanic or Latino)", "White", "Decline"], candidate_info=blank_candidate) == ""

    # With explicit user profile/taught values, exact matching applies cleanly
    candidate = {
        "full_name": "Vanraj Solanki",
        "expected_salary": "100000",
        "gender": "Male",
        "disability": "No",
        "veteran": "No",
        "race": "Asian",
    }
    # Gender
    assert answer_question_with_groq("Gender", options=["Female", "Male", "Decline"], candidate_info=candidate) == "Male"
    # Disability
    assert answer_question_with_groq("Voluntary Self-Identification of Disability", options=["Yes, I have a disability", "No, I don't have a disability", "I don't wish to answer"], candidate_info=candidate) == "No, I don't have a disability"
    # Veteran
    assert answer_question_with_groq("Veteran Status", options=["I am a protected veteran", "I am not a protected veteran", "Decline to identify"], candidate_info=candidate) == "I am not a protected veteran"
    # Race
    assert answer_question_with_groq("Race / Ethnicity", options=["Hispanic/Latino", "Asian (Not Hispanic or Latino)", "White", "Decline"], candidate_info=candidate) == "Asian (Not Hispanic or Latino)"
    # Referral source
    assert answer_question_with_groq("How did you hear about this opportunity?", options=["Company Website", "LinkedIn", "Referral", "Other"], candidate_info=candidate) == "LinkedIn"


def test_cloudflare_and_conditional_questions():
    candidate = {
        "full_name": "Vanraj Solanki",
        "first_name": "Vanraj",
        "last_name": "Solanki",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "country": "India",
        "linkedin": "https://linkedin.com/in/vanrajsinh",
        "github": "https://github.com/vanrajsinh650",
        "university": "Gokul Global University",
        "degree": "Bachelor of Computer Applications (BCA)",
        "major": "Computer Applications",
        "current_company": "DivineHindu",
    }

    # LinkedIn text box must return URL, never "No"
    assert answer_question_with_groq(
        "Would you like to include your LinkedIn profile, personal website or blog?",
        candidate_info=candidate,
    ) == "https://linkedin.com/in/vanrajsinh"

    # Conditional follow-up text question must return N/A, not job title
    assert answer_question_with_groq(
        'If you answered "Yes" to having a relative currently employed at Entrata, please share the name and your relationship to them.',
        candidate_info=candidate,
    ) == "N/A"

    # Multi-hub based question
    assert answer_question_with_groq(
        "Are you currently based in Singapore, Sydney, Tokyo, Seoul, or London?",
        options=[
            "I am based in Singapore",
            "I am based in Sydney",
            "I am based outside of these locations",
        ],
        candidate_info=candidate,
    ) == "I am based outside of these locations"

    # Combined based + relocation question
    assert answer_question_with_groq(
        "Are you currently based in Singapore or Sydney?",
        options=[
            "I am currently based in Singapore",
            "I am currently based in Sydney",
            "I am based outside of Singapore and Sydney, and would require relocation support",
            "I am based outside of Singapore and Sydney, and am not willing to relocate",
        ],
        candidate_info=candidate,
    ) == "I am based outside of Singapore and Sydney, and would require relocation support"

    # Willingness to relocate multi-choice
    assert answer_question_with_groq(
        "Do you currently live or are you willing to relocate to the job’s location?",
        options=[
            "I currently live in this job's location.",
            "I am willing to relocate to this job's location.",
            "I do not live and not willing to relocate to this job's location.",
        ],
        candidate_info=candidate,
    ) == "I am willing to relocate to this job's location."

    # Sponsorship with false-citizenship guard vs standard Yes/No
    assert answer_question_with_groq(
        "Do you now or will you in the future require immigration sponsorship to work at Cloudflare in Singapore?",
        options=["Yes", "No, I'm a Singapore Citizen.", "No, I'm a Permanent resident."],
        candidate_info=candidate,
    ) == "Yes"
    assert answer_question_with_groq(
        "Do you now or will you in the future require immigration sponsorship to work at Cloudflare?",
        options=["Yes", "No"],
        candidate_info=candidate,
    ) == "No"

    # Preferred names
    assert answer_question_with_groq("Preferred First Name*", candidate_info=candidate) == "Vanraj"
    assert answer_question_with_groq("Preferred Last Name*", candidate_info=candidate) == "Solanki"


def test_country_skill_graduation_and_date_rules():
    candidate = {
        "country": "India",
        "graduation_year": "2025",
        "years_of_experience": "1",
        "skills": ["Python", "FastAPI", "SQL", "Playwright", "Docker"],
    }
    assert answer_question_with_groq("Country*", options=["United States", "India", "United Kingdom"], candidate_info=candidate) == "India"
    assert answer_question_with_groq("Graduation Year*", candidate_info=candidate) == "2025"
    assert answer_question_with_groq("Do you have experience with Python?", options=["Yes", "No"], candidate_info=candidate) == "Yes"
    assert answer_question_with_groq("How many years of experience do you have with FastAPI?", field_type="number", candidate_info=candidate) == "1"
    date_ans = answer_question_with_groq("Earliest Start Date", field_type="date", candidate_info=candidate)
    assert len(date_ans) == 10 and date_ans[4] == "-" and date_ans[7] == "-"

