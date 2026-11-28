import json

import pytest
import requests

from jobpilot import collectors, posting_research


def test_alert_tracking_is_removed_and_greenhouse_uses_the_exact_requisition(monkeypatch):
    url = "https://job-boards.greenhouse.io/acme/jobs/123"

    def get(endpoint):
        assert endpoint.startswith("https://boards-api.greenhouse.io/v1/boards/acme/jobs/123?")
        return json.dumps(
            {
                "id": 123,
                "title": "Security Engineer",
                "company_name": "Acme",
                "location": {"name": "Cincinnati, OH"},
                "content": "<h2>Responsibilities</h2><p>Design production controls.</p>"
                "<h2>Required skills</h2><p>Use Python to automate security evidence collection.</p>",
            }
        ), endpoint

    monkeypatch.setattr(collectors, "_get_public", get)
    result = posting_research.research_posting(
        {"url": url + "?email_id=private-tracking-id&utm_source=mail"}
    )
    assert result["posting_source"] == "greenhouse"
    assert result["url"] == url
    assert "Responsibilities\nDesign" in result["description"]
    assert result["requisition_id"] == "123"


def test_official_missing_posting_is_closed(monkeypatch):
    def get(url):
        response = requests.Response()
        response.url = url
        response.status_code = 410
        response.raise_for_status()

    monkeypatch.setattr(collectors, "_get_public", get)
    with pytest.raises(posting_research.PostingClosed):
        posting_research.research_posting({"url": "https://job-boards.greenhouse.io/acme/jobs/123"})


@pytest.mark.parametrize("canonical_id,closed", [("123", False), ("999", False), ("123", True)])
def test_public_linkedin_markup_requires_the_same_job(monkeypatch, canonical_id, closed):
    alert = {"url": "https://www.linkedin.com/comm/jobs/view/platform-engineer-123/?trk=email"}
    description = "Build AWS infrastructure and GitHub Actions, maintain release monitoring, and own incident response."
    status = '<span class="closed-job">No longer accepting applications</span>' if closed else ""
    page = f"""
    <link rel="canonical" href="https://www.linkedin.com/jobs/view/platform-engineer-{canonical_id}">
    <main>
      <h1 class="top-card-layout__title">Platform Engineer</h1>
      <a class="topcard__org-name-link">Signal Orchard Studio</a>
      <span class="topcard__flavor--bullet">Cincinnati, OH</span>
      {status}
      <section class="description__text"><div class="show-more-less-html__markup">
        <p>{description}</p>
      </div></section>
    </main>
    """
    monkeypatch.setattr(collectors, "validate_public_url", lambda url: url)
    monkeypatch.setattr(collectors, "_get_public", lambda url: (page, url))
    if closed:
        with pytest.raises(posting_research.PostingClosed):
            posting_research.research_posting(alert)
    elif canonical_id != "123":
        with pytest.raises(ValueError, match="did not provide a full job posting"):
            posting_research.research_posting(alert)
    else:
        posting = posting_research.research_posting(alert)
        assert posting["description"] == description
        assert posting["company"] == "Signal Orchard Studio"
        assert posting["location"] == "Cincinnati, OH"
        assert posting["url"] == "https://www.linkedin.com/jobs/view/123/"


def test_employer_job_posting_microdata_can_supply_company_and_location(monkeypatch):
    url = "https://careers.example.com/job/cincinnati-platform-engineer/123/"
    page = """
    <div itemscope itemtype="http://schema.org/JobPosting">
      <meta itemprop="hiringOrganization" content="Signal Orchard Studio">
      <span itemprop="title">Platform Engineer</span>
      <span itemprop="jobLocation"><span itemprop="address">
        <meta itemprop="addressLocality" content="Cincinnati">
        <meta itemprop="addressRegion" content="OH">
        <meta itemprop="addressCountry" content="US">
      </span></span>
      <span itemprop="description"><p>Build AWS infrastructure and GitHub Actions.</p>
        <p>Maintain release monitoring and own production incident response.</p></span>
    </div>
    """
    monkeypatch.setattr(collectors, "validate_public_url", lambda url: url)
    monkeypatch.setattr(collectors, "_get_public", lambda url: (page, url))
    posting = posting_research.research_posting({"url": url})
    assert posting["company"] == "Signal Orchard Studio"
    assert posting["location"] == "Cincinnati, OH, US"
    assert "GitHub Actions.\nMaintain" in posting["description"]
