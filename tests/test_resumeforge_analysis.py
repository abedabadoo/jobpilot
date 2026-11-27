from resumeforge.job_analysis import analyze_posting
from resumeforge.models import ModelSettings, Profile
from resumeforge.priorities import passages


def test_hiring_boilerplate_does_not_contaminate_posting_priorities():
    posting = """Information Systems Security Officer
Required Qualifications
Experience with security control assessments and incident response.
Please contact us for application accommodations.
Target Salary Range:
AWS skills vary by salary band.
Candidate AI Policy
Please contact us before using AI tools in the hiring process.
Preferred Qualifications
Familiarity with Python.
"""
    profile = Profile(
        name="Fictional Candidate",
        contact="candidate@example.invalid",
        skills=["Python", "AWS"],
        roles=[
            {
                "id": "role",
                "company": "Example",
                "title": "Security Engineer",
                "dates": "2022–2025",
                "bullets": [{"id": "response", "text": "Built incident response runbooks."}],
            },
        ],
    )
    text = " ".join(row.text for row in passages(posting))
    assert "salary" not in text.casefold()
    assert "policy" not in text.casefold()
    assert "contact us" not in text.casefold()
    rows = analyze_posting(profile, posting, [], ModelSettings(provider="none"))
    requirements = {row["term"].casefold(): row for row in rows}
    assert requirements["incident response"]["required"]
    assert requirements["python"]["required"] is False
    assert "aws" not in requirements
