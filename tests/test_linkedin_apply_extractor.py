import pytest
from src.browser.linkedin_apply_extractor import (
    decode_linkedin_apply_url,
    extract_company_apply_url_from_html,
)


def test_decode_external_apply_with_url_param():
    raw = (
        "https://www.linkedin.com/jobs/view/externalApply/123456789/"
        "?url=https%3A%2F%2Fjpmc.fa.oraclecloud.com%2FhcmUI%2FCandidateExperience%2Fen%2Fsites%2FCX_1001%2Fjob%2F210512345"
        "&urlHash=abc1234"
    )
    result = decode_linkedin_apply_url(raw)
    assert result == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210512345"


def test_decode_nested_encoded_url():
    raw = "https://www.linkedin.com/jobs/view/externalApply/999/?dest=https%253A%252F%252Fboards.greenhouse.io%252Fcompany%252Fjobs%252F123"
    result = decode_linkedin_apply_url(raw)
    assert result == "https://boards.greenhouse.io/company/jobs/123"


def test_decode_already_direct_external_url():
    raw = "https://jobs.lever.co/stripe/abc-def"
    result = decode_linkedin_apply_url(raw)
    assert result == "https://jobs.lever.co/stripe/abc-def"


def test_decode_plain_linkedin_job_view_returns_none():
    raw = "https://www.linkedin.com/jobs/view/software-engineer-at-google-4158913982"
    result = decode_linkedin_apply_url(raw)
    assert result is None


def test_extract_company_apply_url_from_voyager_html():
    html = '''
    <html>
      <body>
        <code id="bpr-guid-99123" style="display:none">
          <!-- {"data":{"$type":"com.linkedin.voyager.jobs.JobPosting","companyApplyUrl":"https:\\/\\/amazon.jobs\\/en\\/jobs\\/4490760961"}} -->
        </code>
      </body>
    </html>
    '''
    result = extract_company_apply_url_from_html(html)
    assert result == "https://amazon.jobs/en/jobs/4490760961"


def test_extract_company_apply_url_from_html_href():
    html = '''
    <div class="job-view">
      <a class="apply-button" href="https://www.linkedin.com/jobs/view/externalApply/4490103193/?url=https%3A%2F%2Fjpmc.fa.oraclecloud.com%2Fjob%2F12345">Apply ↗</a>
    </div>
    '''
    result = extract_company_apply_url_from_html(html)
    assert result == "https://jpmc.fa.oraclecloud.com/job/12345"


def test_extract_company_apply_url_from_json_ld():
    html = '''
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Software Engineer",
        "sameAs": "https://jobs.apple.com/en-us/details/20054321"
      }
    </script>
    '''
    result = extract_company_apply_url_from_html(html)
    assert result == "https://jobs.apple.com/en-us/details/20054321"


def test_decode_safety_redirect_url():
    raw = (
        "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fsynechron%2Ewd1%2Emyworkdayjobs%2Ecom"
        "%2FSynechronCareers%2Fjob%2FBengaluru---Bellandur-GTP%2FPython-Software-Engineer"
        "---Application-Maintenance--Debugging---Agile-Development_JR1044669%3Fsource%3DLinkedIn"
        "&urlhash=9w_c&mt=qcRN4kna"
    )
    result = decode_linkedin_apply_url(raw)
    expected = (
        "https://synechron.wd1.myworkdayjobs.com/SynechronCareers/job/Bengaluru---Bellandur-GTP/"
        "Python-Software-Engineer---Application-Maintenance--Debugging---Agile-Development_JR1044669?source=LinkedIn"
    )
    assert result == expected


def test_extract_safety_redirect_from_html():
    html = '''
    <div class="job-view">
      <a class="bsjlxl" href="https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fsynechron%2Ewd1%2Emyworkdayjobs%2Ecom%2FSynechronCareers%2Fjob%2F123%3Fsource%3DLinkedIn&urlhash=abc">Apply ↗</a>
    </div>
    '''
    result = extract_company_apply_url_from_html(html)
    assert result == "https://synechron.wd1.myworkdayjobs.com/SynechronCareers/job/123?source=LinkedIn"

