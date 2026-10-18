import pytest

from jobpilot import core

SETTINGS = {
    "target_roles": ["Security Engineer", "Security Analyst", "GRC Analyst"],
    "location": "Cincinnati, OH",
    "remote": True,
    "min_fit": 0,
}
PROFILE = {
    "experience": [
        {"title": "Security Analyst", "start": "June 2022", "end": "December 2023"},
        {"title": "Security Engineer", "start": "January 2024", "end": "September 2026"},
    ]
}


def assess(title, description="", profile=PROFILE, settings=SETTINGS):
    assessment = getattr(core, "role_assessment", None)
    assert callable(assessment), "Role assessment must gate jobs independently of the fit score."
    return assessment({"title": title, "description": description}, profile, settings)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Security Sales Engineer",
        "Enterprise Security Sales Specialist",
        "Director, Security Channels (North America)",
        "Security Account Executive",
        "Sales Engineer",
        "Software Engineer",
        "Retail Compliance Sales Representative",
    ],
)
def test_commercial_or_unrelated_roles_are_excluded_even_with_zero_fit_threshold(title):
    status, note = assess(title, "AWS Python SOC 2 ISO 27001 cloud security engineering")
    assert status == "excluded"
    assert note


def test_exact_configured_commercial_role_intent_is_respected():
    status, _ = assess(
        "Security Sales Engineer",
        settings={**SETTINGS, "target_roles": ["Security Sales Engineer"]},
    )
    assert status == "eligible"


@pytest.mark.parametrize(
    "title",
    [
        "Senior Security Engineer",
        "Sr. Security Analyst",
        "Staff Security Engineer",
        "Principal Security Engineer",
    ],
)
def test_advanced_titles_alone_do_not_block_truthful_stretch_applications(title):
    assert assess(title)[0] == "eligible"


def test_exact_configured_director_role_is_not_blocked_by_title_alone():
    assert (
        assess(
            "Director of Security", settings={**SETTINGS, "target_roles": ["Director of Security"]}
        )[0]
        == "eligible"
    )


@pytest.mark.parametrize(
    "title",
    [
        "Security Engineer",
        "Cloud Security Engineer",
        "Information Security Analyst",
        "Security Analyst",
        "GRC Analyst",
        "Compliance Analyst",
        "Security Governance Risk & Compliance (GRC) Analyst",
    ],
)
def test_ordinary_security_and_compliance_roles_remain_available(title):
    assert assess(title)[0] == "eligible"


@pytest.mark.parametrize(
    "requirement",
    [
        "Minimum of 5+ years of information security, IT audit or IT Risk Management experience.",
        "At least 5 years of relevant experience are required.",
        "5+ years of experience in cloud security engineering.",
        "5-7 years of experience in information security.",
    ],
)
def test_explicit_experience_above_documented_career_span_is_a_fit_note(requirement):
    status, note = assess("Security Engineer", requirement)
    assert status == "eligible"
    assert "experience" in note.lower()


def test_supported_experience_requirement_remains_available():
    assert (
        assess("Security Engineer", "3+ years of experience in information security.")[0]
        == "eligible"
    )


def test_preferred_experience_does_not_become_a_mandatory_requirement():
    assert (
        assess("Security Engineer", "Preferred: 5+ years of experience in cloud security.")[0]
        == "eligible"
    )


def test_business_age_does_not_become_candidate_experience_requirement():
    assert (
        assess("Security Engineer", "Our company has over 20 years of experience serving clients.")[
            0
        ]
        == "eligible"
    )


def test_unknown_career_dates_do_not_block_or_claim_zero_experience():
    profile = {"experience": [{"title": "Security Engineer", "start": "unknown", "end": "unknown"}]}
    status, note = assess("Security Engineer", "At least 5 years of experience required.", profile)
    assert status == "eligible"
    assert "unknown" in note.lower() or "establish" in note.lower()
    assert "0 years" not in note


def test_overlapping_career_dates_are_not_counted_twice():
    profile = {
        "experience": [
            {"start": "January 2023", "end": "January 2024"},
            {"start": "January 2023", "end": "January 2024"},
        ]
    }
    status, note = assess("Security Engineer", "2+ years of experience required.", profile)
    assert status == "eligible"
    assert "career" in note.lower()


@pytest.mark.parametrize(
    "location",
    [
        "Illinois, USA, Remote; Texas, USA, Remote",
        "California, USA, Remote; Colorado, USA, Remote; Washington, USA, Remote",
        "Chicago, IL, USA, Remote; Austin, TX, USA, Remote",
        "Remote - USA (excluding Ohio)",
    ],
)
def test_explicit_remote_state_restrictions_excluding_ohio_block_automatic_application(location):
    status, note = core.eligibility({"location": location}, SETTINGS)
    assert status in ("excluded", "review")
    assert "ohio" in note.lower() or "state" in note.lower()


@pytest.mark.parametrize(
    "location",
    [
        "Ohio, USA, Remote; Texas, USA, Remote",
        "Columbus, OH, USA, Remote",
        "Remote - US",
        "Remote - USA; Headquarters: Boston, Massachusetts",
        "Cincinnati, OH, USA",
    ],
)
def test_eligible_ohio_or_unrestricted_remote_locations_still_pass(location):
    assert core.eligibility({"location": location}, SETTINGS)[0] == "eligible"


def test_washington_dc_remote_is_still_ambiguous_for_ohio_resident():
    assert (
        core.eligibility(
            {"location": "Washington, DC - Remote", "country": "USA", "is_remote": True}, SETTINGS
        )[0]
        == "review"
    )
