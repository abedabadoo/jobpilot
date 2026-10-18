import json

import pytest
from playwright.sync_api import sync_playwright

from jobpilot.browser import _fill_fields


@pytest.fixture
def page():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        yield pg
        b.close()


def test_react_style_country_select_commits_option_and_ignores_proxy(page):
    page.set_content("""<form><label for="country">Country*</label><div class="select">
    <div class="select__control"><input id="country" type="text" role="combobox" aria-required="true" aria-controls="countries" onclick="document.querySelector('#countries').hidden=false">
    <span class="select__single-value"></span><input required aria-hidden="true" tabindex="-1" style="position:absolute;width:1px;height:1px;opacity:0" id="proxy"></div>
    <div role="listbox" id="countries" hidden><div role="option" onclick="document.querySelector('.select__single-value').textContent='United States';document.querySelector('#country').value='';document.querySelector('#proxy').value='US';this.parentNode.hidden=true">United States</div></div></div></form>""")
    unknown = _fill_fields(
        page.locator("form"), {"name": "Jordan", "location": "Cincinnati, OH, USA"}, {}, {}
    )
    assert unknown == [], unknown
    assert page.locator(".select__single-value").inner_text() == "United States"
    assert page.locator("#proxy").input_value() == "US"


def test_phone_country_flag_proves_us_but_dial_code_alone_does_not(page):
    from jobpilot.browser import _FIELD_INFO, _approved_current_value

    page.set_content("""<label for="country">Country*</label><div class="select"><div class="select__control">
    <div class="select__single-value"><div class="iti__flag iti__us"></div><span>+1</span></div>
    <input id="country" role="combobox" aria-required="true"></div></div>""")
    field = page.locator("#country")
    assert _approved_current_value(field.evaluate(_FIELD_INFO), "United States", False)
    page.locator(".iti__flag").evaluate('el=>el.className="iti__flag iti__ca"')
    assert not _approved_current_value(field.evaluate(_FIELD_INFO), "United States", False)


def test_custom_eligibility_select_uses_only_explicit_saved_answer(page):
    page.set_content("""<form><label for="auth">Are you legally authorized to work in the United States?*</label><div class="select"><div class="select__control">
    <input id="auth" type="text" role="combobox" aria-required="true" onclick="document.querySelector('#opts').hidden=false"><span class="select__single-value"></span></div>
    <div id="opts" role="listbox" hidden><div role="option" onclick="document.querySelector('.select__single-value').textContent='No';document.querySelector('#auth').value='';this.parentNode.hidden=true">No</div></div></div></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {}, {})
    assert unknown
    unknown = _fill_fields(page.locator("form"), {}, {"@work_authorized_us": "No"}, {})
    assert unknown == [], unknown
    assert page.locator(".select__single-value").inner_text() == "No"


def test_phone_formatter_does_not_invalidate_verified_number(page):
    page.set_content(
        """<form><label>Phone*<input type="tel" name="phone" aria-required="true" oninput="this.value=this.value.replace(/[^0-9]/g,'').replace(/^1(?=.{10}$)/,'')"></label></form>"""
    )
    unknown = _fill_fields(page.locator("form"), {"phone": "+1 (202) 555-0142"}, {}, {})
    assert unknown == [], unknown
    assert page.locator("input").input_value() == "2025550142"


def test_workable_resume_uses_semantic_file_label(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><span id="resume-heading">Resume</span>
    <label for="random-file">Choose file</label>
    <input id="random-file" type="file" required data-ui="resume"
      aria-labelledby="resume-heading upload-description">
    <span id="upload-description">Choose file or drag and drop here</span></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {}, {"resume_pdf": str(resume)})
    assert unknown == [], unknown
    assert page.locator("input").evaluate("el=>el.files[0].name") == "resume.pdf"


def test_generic_required_attachment_is_not_guessed_as_resume(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content('<form><label>Choose file<input type="file" required></label></form>')
    unknown = _fill_fields(page.locator("form"), {}, {}, {"resume_pdf": str(resume)})
    assert unknown
    assert page.locator("input").evaluate("el=>el.files.length") == 0


def test_workable_radio_label_selects_covered_native_input(page):
    page.set_default_timeout(250)
    page.set_content("""<form><span id="q">Are you legally authorized to work in the United States?</span>
    <fieldset role="radiogroup" aria-labelledby="q">
    <label style="display:block"><input style="pointer-events:none;opacity:0;position:absolute" name="auth" type="radio" value="true" required>YES</label>
    <label style="display:block"><input style="pointer-events:none;opacity:0;position:absolute" name="auth" type="radio" value="false" required>NO</label>
    </fieldset></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {"@work_authorized_us": "Yes"}, {})
    assert unknown == [], unknown
    assert page.locator("input[value=true]").is_checked()
    assert not page.locator("input[value=false]").is_checked()


def test_workable_upload_waits_for_remote_attachment_completion(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><div data-role="dropzone"><label>Resume
    <input type="file" data-ui="resume" required onchange="
      document.querySelector('#pending').hidden=false;
      setTimeout(()=>{document.querySelector('#pending').hidden=true;
        document.querySelector('#done').hidden=false;document.querySelector('button[type=submit]').disabled=false},400)"></label>
    <button id="pending" data-action="abort" hidden>Cancel uploading resume.pdf</button>
    <div id="done" hidden><a data-action="view" href="https://example.com/resume.pdf">View file</a>
    <span data-id="filename">resume.pdf</span></div></div>
    <button type="submit" disabled>Submit application</button></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {}, {"resume_pdf": str(resume)})
    assert unknown == [], unknown
    assert page.locator("[data-action=view]").is_visible()
    assert page.locator("button[type=submit]").is_enabled()


def test_workable_upload_remount_keeps_remote_completion_requirement(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><div data-role="dropzone"><label>Resume
    <input id="old-file" type="file" data-ui="resume" required onchange="this.id='new-file';
      setTimeout(()=>{document.querySelector('#done').hidden=false},350)"></label>
    <div id="done" hidden><a data-action="view" href="https://example.com/resume.pdf">View file</a>
    <span data-id="filename">resume.pdf</span></div></div></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {}, {"resume_pdf": str(resume)})
    assert unknown == [], unknown
    assert page.locator("[data-action=view]").is_visible()


def test_workable_upload_failure_blocks_submission(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><div data-role="dropzone"><label>Resume
    <input type="file" data-ui="resume" required onchange="document.querySelector('#error').hidden=false"></label>
    <div id="error" hidden role="alert" aria-live="assertive">Upload failed</div></div></form>""")
    unknown = _fill_fields(page.locator("form"), {}, {}, {"resume_pdf": str(resume)})
    assert any("upload" in x.lower() for x in unknown), unknown


def test_upload_rerender_is_followed_by_fresh_contact_and_radio_controls(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><label>Resume<input type="file" name="resume" required
      onchange="document.querySelector('#name-old').id='name-new';document.querySelector('#name-new').value='';
        document.querySelector('#auth-old').id='auth-new';document.querySelector('#auth-new').checked=false"></label>
    <label>Full name<input id="name-old" required></label>
    <fieldset><legend>Are you legally authorized to work in the United States?</legend>
      <label>Yes<input id="auth-old" type="radio" name="auth" value="yes" required></label>
      <label>No<input type="radio" name="auth" value="no" required></label></fieldset></form>""")
    unknown = _fill_fields(
        page.locator("form"),
        {"name": "Jordan"},
        {"@work_authorized_us": "Yes"},
        {"resume_pdf": str(resume)},
    )
    assert unknown == [], unknown
    assert page.locator("#name-new").input_value() == "Jordan"
    assert page.locator("#auth-new").is_checked()


def test_contact_updates_can_change_radio_and_group_ids(page):
    page.set_content("""<form><label>Full name<input name="name" required oninput="
      document.querySelector('input[type=radio]').id='new-radio';document.querySelector('[role=radiogroup]').id='new-group'"></label>
    <fieldset role="radiogroup" id="old-group"><legend>Are you legally authorized to work in the United States?</legend>
      <label>Yes<input id="old-radio" type="radio" name="auth" value="yes" required></label>
      <label>No<input type="radio" name="auth" value="no" required></label></fieldset></form>""")
    unknown = _fill_fields(
        page.locator("form"), {"name": "Jordan"}, {"@work_authorized_us": "Yes"}, {}
    )
    assert unknown == [], unknown


def test_lever_location_requires_and_commits_the_exact_offered_city(page):
    page.set_content("""<form><label>Current location<input class="location-input" name="location" required
      onkeydown="if(event.key==='End')document.querySelector('.dropdown-results').hidden=false"
      onblur="if(!document.querySelector('#selected-location').value)this.value=''"></label>
    <input type="hidden" id="selected-location" name="selectedLocation">
    <div class="dropdown-results" hidden>
    <div class="dropdown-location" onclick="document.querySelector('input[name=location]').value=this.textContent;document.querySelector('#selected-location').value=JSON.stringify({name:this.textContent});this.parentElement.hidden=true">Cincinnati, IL, USA</div>
    <div class="dropdown-location" onclick="document.querySelector('input[name=location]').value=this.textContent;document.querySelector('#selected-location').value=JSON.stringify({name:this.textContent});this.parentElement.hidden=true">Cincinnati, OH, USA</div></div></form>""")
    unknown = _fill_fields(page.locator("form"), {"location": "Cincinnati, OH, USA"}, {}, {})
    assert unknown == [], unknown
    assert page.locator("input[name=location]").input_value() == "Cincinnati, OH, USA"
    assert (
        json.loads(page.locator("#selected-location").input_value())["name"]
        == "Cincinnati, OH, USA"
    )


def test_lever_location_is_not_guessed_when_only_wrong_city_is_offered(page):
    page.set_content("""<form><label>Current location<input class="location-input" name="location" required></label>
    <input type="hidden" id="selected-location" name="selectedLocation">
    <div class="dropdown-results"><div class="dropdown-location">Cincinnati, IL, USA</div></div></form>""")
    unknown = _fill_fields(page.locator("form"), {"location": "Cincinnati, OH, USA"}, {}, {})
    assert unknown
    assert page.locator("#selected-location").input_value() == ""


def test_lever_resume_parser_finishes_before_contact_and_company_validation(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    page.set_content("""<form><label>Resume<input type="file" id="resume-upload-input" name="resume" onchange="
      document.querySelector('.resume-upload-working').hidden=false;
      setTimeout(()=>{document.querySelector('input[name=name]').value='Wrong parsed name';
      document.querySelector('input[name=org]').value='Former employer';
      document.querySelector('.resume-upload-working').hidden=true;
      document.querySelector('.resume-upload-success').hidden=false},200)"></label>
    <div class="resume-upload-working" hidden>Analyzing resume</div>
    <div class="resume-upload-success" hidden>Success</div>
    <label>Full name<input name="name" required></label>
    <label>Current company<input name="org"></label></form>""")
    unknown = _fill_fields(
        page.locator("form"), {"name": "Jordan"}, {}, {"resume_pdf": str(resume)}
    )
    assert unknown == [], unknown
    assert page.locator("input[name=name]").input_value() == "Jordan"
    assert page.locator("input[name=org]").input_value() == ""
    assert page.locator(".resume-upload-success").is_visible()


def test_lever_location_helper_is_excluded_from_the_question_label(page):
    from jobpilot.browser import _FIELD_INFO

    page.set_content("""<label>Current location<input class="location-input" name="location">
    <div class="dropdown-container" style="display:none">No location found. Try entering a different location Loading</div></label>""")
    assert page.locator("input").evaluate(_FIELD_INFO)["label"] == "Current location"


def test_browser_timezone_metadata_is_not_a_hidden_applicant_answer(page):
    page.set_content("""<form><label>Full name<input name="name" required>
    <input type="hidden" name="timezone" value="America/New_York"></label></form>""")
    assert _fill_fields(page.locator("form"), {"name": "Jordan"}, {}, {}) == []


def test_country_option_after_large_hidden_phone_list_and_external_proxy(page):
    hidden = "".join(f'<div role="option">Unused country {x}</div>' for x in range(250))
    page.set_content(
        """<form><div hidden>"""
        + hidden
        + """</div>
    <label for="country">Country*</label><div class="select-shell"><div><div class="select__control">
    <input id="country" type="text" role="combobox" aria-required="true" onclick="document.querySelector('#opts').hidden=false"><span class="select__single-value"></span></div></div>
    <input required aria-hidden="true" tabindex="-1" style="position:absolute;width:1px;height:1px;opacity:0">
    <div id="opts" role="listbox" hidden><div role="option" onclick="document.querySelector('.select__single-value').textContent='United States';document.querySelector('#country').value='';document.querySelector('input[aria-hidden]').value='US';this.parentNode.hidden=true">United States+1</div></div></div></form>"""
    )
    unknown = _fill_fields(page.locator("form"), {"location": "Cincinnati, OH, USA"}, {}, {})
    assert unknown == [], unknown
