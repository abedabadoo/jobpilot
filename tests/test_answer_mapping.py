from jobpilot.browser import _answer_for, _profile_values


def info(label, **extra):
    return {
        "label": label,
        "legend": "",
        "name": "",
        "id": "",
        "autocomplete": "",
        "placeholder": "",
        **extra,
    }


def test_preferred_name_and_residence_country_use_verified_contact():
    values = _profile_values(
        {"name": "Jordan Morgan", "first_name": "Jordan", "location": "Cincinnati, OH, USA"}
    )
    assert _answer_for(info("Preferred First Name*"), values, {})[0] == "Jordan"
    assert _answer_for(info("Country*"), values, {})[0] == "United States"
    assert _answer_for(info("Citizenship"), values, {})[0] is None


def test_canonical_authorization_requires_explicit_answer_and_correct_country():
    q = info("Are you legally authorized to work in the United States?*")
    assert _answer_for(q, {}, {})[0] is None
    assert _answer_for(q, {}, {"@work_authorized_us": "No"}) == ("No", True)
    assert (
        _answer_for(
            info("Are you legally authorized to work in Canada?"),
            {},
            {"@work_authorized_us": "Yes"},
        )[0]
        is None
    )


def test_exact_answer_overrides_canonical_preset():
    label = "Are you legally authorized to work in the United States?"
    assert _answer_for(info(label), {}, {"@work_authorized_us": "Yes", label: "No"}) == ("No", True)


def test_sponsorship_preset_only_us_job_context():
    q = info("Will you now or in the future require visa sponsorship?")
    assert _answer_for(q, {}, {"@requires_sponsorship_us": "No"})[0] is None
    assert _answer_for(q, {}, {"@requires_sponsorship_us": "No"}, {"location": "Remote - USA"}) == (
        "No",
        True,
    )


def test_privacy_preset_cannot_accept_marketing_or_terms():
    answers = {"@recruitment_privacy_consent": "Yes"}
    assert _answer_for(
        info(
            "I understand my application will be processed in accordance with the Candidate Privacy Policy."
        ),
        {},
        answers,
    ) == ("Yes", True)
    assert (
        _answer_for(info("I agree to the terms of service and Privacy Policy"), {}, answers)[0]
        is None
    )
    assert (
        _answer_for(info("I consent to marketing emails under the Privacy Policy"), {}, answers)[0]
        is None
    )


def test_work_authorization_does_not_answer_compound_sponsorship_question():
    q = info(
        "Do you live in the US and are you legally authorized to work now or in the future without employer sponsorship or transfer?"
    )
    assert (
        _answer_for(
            q,
            {},
            {"@work_authorized_us": "Yes", "@requires_sponsorship_us": "Yes"},
            {"location": "USA"},
        )[0]
        is None
    )


def test_combined_sponsorship_yes_cannot_establish_current_sponsorship_yes():
    q = info("Do you need employer sponsorship to work in the United States?")
    assert _answer_for(q, {}, {"@requires_sponsorship_us": "Yes"})[0] is None
    assert _answer_for(q, {}, {"@requires_sponsorship_us": "No"}) == ("No", True)
    combined = info(
        "Will you now or in the future require employer sponsorship to work in the United States?"
    )
    assert _answer_for(combined, {}, {"@requires_sponsorship_us": "Yes"}) == ("Yes", True)
