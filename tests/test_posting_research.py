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
