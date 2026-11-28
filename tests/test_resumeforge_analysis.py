from resumeforge.job_analysis import analyze_posting
from resumeforge.models import Candidate, ModelSettings, Profile
from resumeforge.priorities import passages
from resumeforge.skills import select_skills


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


def test_inferred_skills_omit_fragments_of_an_evidenced_product():
    profile = Profile(
        name="Fictional Candidate",
        contact="candidate@example.invalid",
        skills=["GitHub Actions"],
        roles=[
            {
                "id": "role",
                "company": "Example",
                "title": "Platform Engineer",
                "dates": "2022–2025",
                "bullets": [
                    {"id": "build", "text": "Operated release pipelines using GitHub Actions."}
                ],
            },
        ],
    )
    selected = [
        Candidate(
            id="original:build",
            role_id="role",
            slot_id="build",
            evidence_ids=["build"],
            text=profile.roles[0].bullets[0].text,
        ),
    ]
    skills = select_skills(profile, [], "Required: experience using GitHub Actions.", selected)
    assert skills == ["GitHub Actions"]

    posting = "Required: GitHub Actions for builds. Use GitHub for pull requests."
    proof = selected[0].model_copy(update={"text": "Managed pull requests using GitHub."})
    skills = select_skills(profile, [], posting, [*selected, proof])
    assert set(skills) == {"GitHub", "GitHub Actions"}
