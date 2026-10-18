"""Isolated Playwright sessions and conservative known-answer form automation.

A final click is attempted once. Only a new explicit employer receipt can
produce confirmed status; uncertain outcomes are never retried here.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from .collectors import validate_public_url

_session_lock = threading.Lock()
_login_threads: dict[str, threading.Thread] = {}
_RECEIPT = re.compile(
    r"(?:your application (?:has been |was |is )?(?:successfully )?(?:submitted|received|sent)|"
    r"application (?:successfully )?(?:submitted|received)|"
    r"thank you for (?:applying|your application)|"
    r"we (?:have )?received your application|successfully applied)",
    re.I,
)
_FINAL = re.compile(
    r"^(?:submit(?: application)?|send application|apply(?: now)?|complete application)$", re.I
)
_NEXT = re.compile(r"^(?:next|continue|review(?: your application)?|save and continue)$", re.I)


def login_in_progress():
    return any(thread.is_alive() for thread in list(_login_threads.values()))


def open_browser_tab(url):
    """Hand a public application URL to the user's regular browser session."""
    try:
        url = validate_public_url(url)
        if os.name == "nt":
            os.startfile(url)
        elif not webbrowser.open_new_tab(url):
            raise OSError("The default browser did not accept the tab request")
    except Exception as exc:
        return {
            "status": "error",
            "note": f"Could not open your default browser: {type(exc).__name__}: {str(exc)[:200]}",
        }
    return {
        "status": "opened",
        "mode": "default_browser",
        "receipt_tracking": "manual",
        "url": url,
        "note": "Opened in your default browser, using its existing saved sessions. Finish the application there, then record the employer receipt in JobPilot.",
    }


def _fixture(settings):
    return bool(settings.get("_fixture_mode") and os.environ.get("PYTEST_CURRENT_TEST"))


def _data_dir(settings):
    path = Path(settings.get("data_dir") or Path(__file__).resolve().parents[1] / "data").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _platform(url, source=""):
    host = (urlsplit(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host == "indeed.com" or host.endswith(".indeed.com"):
        return "indeed"
    return "employer"


def _guard_context(context, fixture):
    checked = {}

    def handle(route):
        target = route.request.url
        try:
            parts = urlsplit(target)
            if parts.scheme in ("data", "blob"):
                route.continue_()
                return
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin not in checked:
                validate_public_url(origin, allow_fixture=fixture)
                checked[origin] = True
            route.continue_()
        except Exception:
            route.abort("blockedbyclient")

    context.route("**/*", handle)


def _launch(playwright, settings, platform, headless):
    profile = _data_dir(settings) / "browser_profiles" / platform
    context = playwright.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        accept_downloads=False,
        args=["--disable-extensions"],
    )
    context.set_default_timeout(3000)
    context.set_default_navigation_timeout(25000)
    _guard_context(context, _fixture(settings))
    return context


def _normal(value):
    return re.sub(r"[\W_]+", " ", str("" if value is None else value).lower()).strip()


def _profile_values(profile):
    contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
    merged = {**profile, **contact}
    full = str(merged.get("full_name") or merged.get("name") or "")
    first = str(merged.get("first_name") or (full.split()[0] if full else ""))
    last = str(merged.get("last_name") or (" ".join(full.split()[1:]) if full else ""))
    location = str(merged.get("location", ""))
    country = (
        "United States"
        if re.search(r"(?:\bUSA\b|\bUnited States\b|,\s*US\s*$)", location, re.I)
        else str(merged.get("country", ""))
    )
    return {
        "full name": full,
        "name": full,
        "your name": full,
        "first name": first,
        "given name": first,
        "firstname": first,
        "preferred first name": str(merged.get("preferred_first_name") or first),
        "preferred name": str(merged.get("preferred_first_name") or first),
        "last name": last,
        "family name": last,
        "lastname": last,
        "email": str(merged.get("email", "")),
        "email address": str(merged.get("email", "")),
        "phone": str(merged.get("phone") or merged.get("phone_full") or ""),
        "phone number": str(merged.get("phone") or merged.get("phone_full") or ""),
        "mobile phone": str(merged.get("phone") or merged.get("phone_full") or ""),
        "location": location,
        "current location": location,
        "country": country,
        "country of residence": country,
        "city": location.split(",")[0].strip(),
        "linkedin": str(merged.get("linkedin_url") or merged.get("linkedin") or ""),
        "linkedin profile": str(merged.get("linkedin_url") or merged.get("linkedin") or ""),
        "linkedin url": str(merged.get("linkedin_url") or merged.get("linkedin") or ""),
        "website": str(merged.get("portfolio_url") or merged.get("website") or ""),
        "portfolio": str(merged.get("portfolio_url") or merged.get("website") or ""),
    }


_FIELD_INFO = r"""el => {
 const labelText = label => {
   const copy = label.cloneNode(true);
   copy.querySelectorAll('input,select,textarea,button,.dropdown-container,[hidden],[aria-hidden="true"]').forEach(x => x.remove());
   return copy.textContent.trim();
 };
 const labels = el.labels ? Array.from(el.labels).map(labelText) : [];
 let text = labels.join(' ') || el.getAttribute('aria-label') || '';
 const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
 const labelledText = ids.map(id => document.getElementById(id)?.innerText || '').join(' ');
 if (!text && ids.length) text = labelledText;
 if (!text && el.closest('label')) text = labelText(el.closest('label'));
 const group = el.closest('fieldset,[role="radiogroup"],.form-group');
 const legend = group?.querySelector('legend')?.innerText || '';
 const groupIds = (group?.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
 const question = legend || group?.getAttribute('aria-label') ||
   groupIds.map(id => document.getElementById(id)?.innerText || '').join(' ');
 const role = el.getAttribute('role') || '';
 const selectControl = el.closest('.select__control,[class$="-control"]');
 const selectRoot = selectControl?.parentElement || el.closest('.select');
 const selectShell = el.closest('.select-shell,.select') || selectControl;
 const selectedLabels = role === 'combobox' && selectRoot ? Array.from(selectRoot.querySelectorAll('[class*="single-value"],[class*="singleValue"],[class*="multi-value__label"]')).map(x=>/country/i.test(text) && x.querySelector('.iti__flag.iti__us') && x.textContent.trim()==='+1' ? 'United States' : x.textContent.trim()).filter(Boolean) : [];
 const selectProxy = el.getAttribute('aria-hidden') === 'true' && el.required && !el.name && !!selectShell?.querySelector('[role="combobox"]');
 const phoneSearch = el.type === 'search' && !el.name && /^iti-.*search-input$/.test(el.id);
 const visible = x => !!x && !!(x.getBoundingClientRect().width || x.getBoundingClientRect().height);
 const dropzone = el.type === 'file' ? el.closest('[data-role="dropzone"]') : null;
 const remoteAttached = dropzone && visible(dropzone.querySelector('[data-action="view"]')) &&
   visible(dropzone.querySelector('[data-id="filename"]')) &&
   !visible(dropzone.querySelector('[data-action="abort"]')) &&
   !visible(dropzone.querySelector('[role="alert"][aria-live="assertive"]'));
 const leverLocation = el.matches('input.location-input[name="location"]') &&
   !!el.form?.querySelector('input[name="selectedLocation"]');
 let selectedLocation = '';
 if (leverLocation) {try {selectedLocation=JSON.parse(el.form.querySelector('input[name="selectedLocation"]').value)?.name || '';}catch{}}
 return {label: text, labelled_text: labelledText, data_ui: el.getAttribute('data-ui') || '',
   legend, name: el.name || '', id: el.id || '',
   role, select_proxy: selectProxy, helper: phoneSearch, selected_labels: selectedLabels,
   lever_location: leverLocation, selected_location: selectedLocation,
   multiple: !!el.multiple || !!selectRoot?.querySelector('[class*="multi-value"]'),
   question, checked: !!el.checked, option_value: el.value || '',
   selected_label: el.tagName === 'SELECT' ? el.selectedOptions?.[0]?.label || '' : '',
   radio_group: el.name ? `${Array.from(document.forms).indexOf(el.form)}:${el.name}` :
     `unnamed:${Array.from(document.querySelectorAll('input[type="radio"]')).indexOf(el)}`,
   placeholder: el.getAttribute('placeholder') || '',
   autocomplete: el.getAttribute('autocomplete') || '', tag: el.tagName.toLowerCase(),
   type: el.type || el.getAttribute('role') || '',
   required: !!el.required || el.getAttribute('aria-required') === 'true' ||
     group?.getAttribute('aria-required') === 'true',
   disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
   value: selectedLabels.length ? selectedLabels.join('; ') : el.type === 'file' ? (el.files?.length || remoteAttached ? 'attached' : '') :
     (el.type === 'checkbox' || el.type === 'radio') ? (el.checked ? el.value || 'checked' : '') :
     el.value ?? el.getAttribute('aria-valuetext') ?? '',
   checkable: ['checkbox','radio'].includes(el.type),
   valid: el.validity ? el.validity.valid : true,
   visible: !!(el.getBoundingClientRect().width || el.getBoundingClientRect().height)
 };
}"""


def _frame_retryable(exc):
    message = str(exc).lower()
    return exc.__class__.__name__ == "TimeoutError" or any(
        fragment in message
        for fragment in (
            "frame was detached",
            "frame has been detached",
            "execution context was destroyed",
            "cannot find context",
            "not attached to the dom",
            "target page, context or browser has been closed",
            "page has been closed",
            "browser has been closed",
        )
    )


def _frame_visible(frame):
    if frame.is_detached():
        return False
    current = frame
    while current.parent_frame is not None:
        element = current.frame_element()
        try:
            if not element.is_visible():
                return False
        finally:
            try:
                element.dispose()
            except Exception:
                pass
        current = current.parent_frame
    return True


def _visible_frames(page):
    if page.is_closed():
        return []
    frames = []
    for frame in list(page.frames):
        try:
            if _frame_visible(frame):
                frames.append(frame)
        except Exception as exc:
            if not _frame_retryable(exc):
                raise
    return frames


_SCOPE_ENTRY = re.compile(
    r"(?:easy apply(?: to .*)?|apply now|apply for (?:this|the) job|apply)", re.I
)
_SCOPE_STEP = re.compile(
    r"(?:next|continue|review(?: your application)?|save and continue|"
    r"submit application|send application|complete application|apply(?: now)?)",
    re.I,
)
_SCOPE_INFO = r"""root => {
 const controls = Array.from(root.querySelectorAll('input:not([type="hidden"]),textarea,select'));
 const visible = el => {const r=el.getBoundingClientRect(); return !!(r.width || r.height) &&
   getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'};
 const buttons = Array.from(root.querySelectorAll('button,input[type="submit"],[role="button"]'))
   .filter(visible).map(el => (el.getAttribute('aria-label') || el.innerText || el.value || '').trim());
 const hint = [root.id,root.className,root.getAttribute('action'),root.getAttribute('aria-label'),
   ...controls.map(el => `${el.name || ''} ${el.id || ''}`)].join(' ');
 return {files:root.querySelectorAll('input[type="file"]').length,
   emails:root.querySelectorAll('input[type="email"],input[name*="email" i]').length,
   contacts:root.querySelectorAll('input[name="name"],input[name*="first" i],input[name*="last" i],'
     +'input[type="tel"],input[name*="phone" i],input[autocomplete="given-name"],'
     +'input[autocomplete="family-name"]').length,
   inputs:controls.length, visible_controls:controls.filter(visible).length,
   dialog:root.getAttribute('role') === 'dialog', buttons, hint};
}"""


def _scope_frame(frame):
    best, best_score = None, 0
    candidates = frame.locator('[role="dialog"], form')
    for index in range(min(candidates.count(), 20)):
        candidate = candidates.nth(index)
        if not candidate.is_visible():
            continue
        info = candidate.evaluate(_SCOPE_INFO, timeout=500)
        context = bool(
            re.search(r"application|resume|cover.?letter|easy.?apply", info["hint"], re.I)
        )
        step = any(_SCOPE_STEP.fullmatch(caption) for caption in info["buttons"])
        review = any(
            re.fullmatch(r"(?:submit|send|complete) application", caption, re.I)
            for caption in info["buttons"]
        )
        qualified = (
            info["files"]
            or (step and (info["emails"] or info["contacts"] or context))
            or (context and info["inputs"])
            or (review and (info["dialog"] or context))
        )
        if not qualified:
            continue
        score = (
            info["files"] * 20
            + info["emails"] * 5
            + min(info["contacts"], 8)
            + min(info["inputs"], 8)
            + (5 if context else 0)
            + (10 if info["dialog"] else 0)
        )
        if score > best_score:
            best, best_score = candidate, score
    if best is None:
        candidate = frame.locator("body")
        if candidate.is_visible():
            info = candidate.evaluate(_SCOPE_INFO, timeout=500)
            if info["files"] and (info["visible_controls"] or info["buttons"]):
                best, best_score = candidate, 1
    return best, best_score


def _workday_manual_entry(url, control, caption):
    host = (urlsplit(url).hostname or "").lower()
    return (
        host.endswith(".myworkdayjobs.com")
        and control.get_attribute("data-automation-id") == "applyManually"
        and bool(re.fullmatch(r"apply\s+manually", caption, re.I))
    )


def _scope_readiness_stop(page, stop_on_entry):
    if page.is_closed():
        return True
    if re.search(r"/(?:authwall|login|signin|sign-in|checkpoint)(?:[/?.]|$)", page.url, re.I):
        return True
    headings = page.main_frame.locator('h1,[role="dialog"][aria-modal="true"]')
    for index in range(min(headings.count(), 8)):
        heading = headings.nth(index)
        if heading.is_visible() and re.match(
            r"^(?:request blocked|access denied|verify (?:that )?you are human|security verification|"
            r"login\b|sign in\b|join linkedin\b)",
            heading.inner_text(timeout=500).strip(),
            re.I,
        ):
            return True
    if stop_on_entry:
        entries = page.main_frame.locator('button,a,[role="button"]')
        for index in range(min(entries.count(), 100)):
            entry = entries.nth(index)
            if not entry.is_visible():
                continue
            caption = (
                entry.get_attribute("aria-label")
                or entry.inner_text(timeout=500)
                or entry.get_attribute("value")
                or ""
            ).strip()
            if _SCOPE_ENTRY.fullmatch(caption) or _workday_manual_entry(page.url, entry, caption):
                return True
    return False


def _scope(page, timeout_ms=4000, stop_on_entry=True):
    """Find a live form, retrying detached frames and delayed iframe forms.

    Return early for blockers and, unless disabled, application entry controls.
    """
    deadline = time.monotonic() + max(0, min(float(timeout_ms), 8000)) / 1000
    while not page.is_closed():
        best, best_score = None, 0
        for frame in _visible_frames(page):
            try:
                candidate, score = _scope_frame(frame)
                if candidate is not None and score > best_score:
                    best, best_score = candidate, score
            except Exception as exc:
                if not _frame_retryable(exc):
                    raise
        if best is not None:
            try:
                if best.is_visible():
                    return best
            except Exception as exc:
                if not _frame_retryable(exc):
                    raise
        try:
            if _scope_readiness_stop(page, stop_on_entry) or time.monotonic() >= deadline:
                return None
            page.wait_for_timeout(min(125, max(1, (deadline - time.monotonic()) * 1000)))
        except Exception as exc:
            if not _frame_retryable(exc):
                raise
    return None


def _visible_button(scope, pattern):
    controls = scope.locator('button, input[type="submit"], [role="button"]')
    for index in range(min(controls.count(), 80)):
        control = controls.nth(index)
        if not control.is_visible() or not control.is_enabled():
            continue
        caption = (
            control.get_attribute("aria-label")
            or control.inner_text()
            or control.get_attribute("value")
            or ""
        ).strip()
        if pattern.fullmatch(caption):
            return control, caption
    return None, ""


def _dismiss_cookie_overlays(page):
    decline = re.compile(
        r"^(?:decline all|reject all|reject optional cookies|decline optional cookies|only necessary cookies)$",
        re.I,
    )
    for frame in _visible_frames(page):
        banners = frame.locator(
            '[data-ui="cookie-consent"], [role="dialog"][aria-label*="cookie" i], #onetrust-banner-sdk'
        )
        for banner in banners.all():
            if banner.is_visible():
                button, _ = _visible_button(banner, decline)
                if button is not None:
                    button.click(timeout=2000)
                    page.wait_for_timeout(100)


_CAPTCHA_SIGNAL = re.compile(
    r"verify (?:that )?you are human|complete (?:the )?captcha|"
    r"(?:i am|i.m) not a robot|select all (?:the )?images|"
    r"select (?:all )?(?:images|squares)|click (?:all )?(?:images|tiles)",
    re.I,
)
_AUTH_HEADING = re.compile(
    r"^(?:security verification|two.factor authentication|sign in to apply|"
    r"enter (?:the )?verification code)(?:[.!:\s]|$)",
    re.I,
)


def _challenge_frame(frame, application_present):
    # Invisible reCAPTCHA integrations/badges are part of ordinary forms.
    # A visible interactive checkbox or image challenge is a real blocker.
    frame_url = frame.url.lower()
    if "recaptcha" in frame_url and (
        "/bframe" in frame_url
        or ("/anchor" in frame_url and re.search(r"[?&#]size=(?:normal|compact)", frame_url))
    ):
        return "CAPTCHA challenge requires your review"
    if "hcaptcha" in frame_url and re.search(r"[?#&]frame=(?:checkbox|challenge)", frame_url):
        return "CAPTCHA challenge requires your review"
    if (urlsplit(frame_url).hostname or "").lower() == "challenges.cloudflare.com":
        text = frame.locator("body").inner_text(timeout=500)[:5000]
        if _CAPTCHA_SIGNAL.search(text):
            return "CAPTCHA challenge requires your review"
        if frame.parent_frame is not None and not re.search(
            r"\b(?:success|verification complete)\b", text, re.I
        ):
            element = frame.frame_element()
            try:
                bounds = element.bounding_box()
                if bounds and bounds["width"] >= 200 and bounds["height"] >= 40:
                    return "CAPTCHA challenge requires your review"
            finally:
                element.dispose()
    code_controls = frame.locator(
        'input[autocomplete="one-time-code"], input[maxlength="1"], '
        'input[aria-label*="security code" i]'
    )
    if any(control.is_visible() for control in code_controls.all()[:20]):
        text = frame.locator("body").inner_text(timeout=500)[-12000:]
        if re.search(
            r"(?:verification|security) code (?:was|has been) sent[\s\S]{0,300}(?:submit|enter|confirm)",
            text,
            re.I,
        ):
            return "Email verification requires your review"
    passwords = frame.locator('input[type="password"]')
    for index in range(min(passwords.count(), 20)):
        password = passwords.nth(index)
        if not password.is_visible():
            continue
        blocking = password.evaluate(
            'el => !!el.closest("[role=dialog],[aria-modal=true],.login-modal,.authwall") || '
            '(!!el.required && !!el.closest("form")?.querySelector("input[type=file]"))',
            timeout=500,
        )
        auth_route = bool(
            re.search(r"/(?:authwall|login|signin|sign-in|checkpoint)(?:[/?.]|$)", frame.url, re.I)
        )
        if not application_present or blocking or auth_route:
            return "Login or account verification requires your review"
    signals = frame.locator(
        'h1,h2,[role="alert"],[role="dialog"],[aria-modal="true"],'
        ".g-recaptcha,.h-captcha,.cf-turnstile,#captcha,[data-sitekey]"
    )
    for index in range(min(signals.count(), 30)):
        signal = signals.nth(index)
        if not signal.is_visible():
            continue
        text = signal.inner_text(timeout=500).strip()[:5000]
        if _CAPTCHA_SIGNAL.search(text):
            return "CAPTCHA challenge requires your review"
        if _AUTH_HEADING.match(text):
            return "Login or account verification requires your review"
    if not application_present:
        text = frame.locator("body").inner_text(timeout=500)[:2500]
        if re.search(
            r"\b(?:request blocked|you have been blocked|access denied|too many requests)\b",
            text,
            re.I,
        ):
            return "The platform blocked this request; review it in the JobPilot browser"
    return None


def _challenge(page):
    if page.is_closed():
        return "Browser page was closed; reopen it before applying"
    application_present = _scope(page) is not None
    for attempt in range(2):
        transient = False
        for frame in _visible_frames(page):
            try:
                reason = _challenge_frame(frame, application_present)
                if reason:
                    return reason
            except Exception as exc:
                if not _frame_retryable(exc):
                    raise
                transient = True
        if page.is_closed():
            return "Browser page was closed; reopen it before applying"
        if not transient or attempt:
            return None
        page.wait_for_timeout(50)
    return None


def _enter_application(
    page, platform, settings, result, checkpoint, directory, job_id, evidence_handler=None
):
    capture = evidence_handler or _evidence
    if _scope(page) is not None:
        return page, None
    pattern = re.compile(
        r"(?:easy apply(?: to .*)?|apply now|apply for (?:this|the) job|apply)", re.I
    )
    controls = page.locator('button, a, [role="button"]')
    for index in range(min(controls.count(), 100)):
        control = controls.nth(index)
        if not control.is_visible() or not control.is_enabled():
            continue
        caption = (control.get_attribute("aria-label") or control.inner_text()).strip()
        workday_manual = _workday_manual_entry(page.url, control, caption)
        if not pattern.fullmatch(caption) and not workday_manual:
            continue
        tag = control.evaluate("el => el.tagName.toLowerCase()")
        href = control.get_attribute("href")
        if tag == "a" and href:
            # Navigate directly; clicking an anchor also executes arbitrary
            # site handlers which may submit an application first.
            target = validate_public_url(urljoin(page.url, href), allow_fixture=_fixture(settings))
            page.goto(target, wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            return page, None
        if workday_manual:
            if tag != "button" or (control.get_attribute("type") or "").lower() != "button":
                return (
                    page,
                    "Workday manual application entry requires review; only a non-submit button is supported",
                )
            # This exact Workday control opens the manual form. Final form
            # actions still use the separate checkpoint and unknown-field gates.
            control.click()
            page.wait_for_timeout(400)
            return page, None
        if platform != "linkedin" or "easy apply" not in caption.lower() or tag != "button":
            return (
                page,
                "Application entry button requires review; its submission behavior is unknown",
            )
        if checkpoint is None:
            return page, "Submission checkpoint missing; the Easy Apply button was not clicked"
        # The recognized LinkedIn Easy Apply control normally opens its modal.
        # Still checkpoint and retain uncertainty before touching it: a crash
        # or changed platform behavior must never silently requeue this job.
        result["evidence"] += capture(page, directory, "before-entry")
        checkpoint(
            {
                "url": _intervention_url(page.url) if evidence_handler is not None else page.url,
                "button": caption,
                "evidence": list(result["evidence"]),
                "job_id": job_id,
                "entry": True,
            }
        )
        result["submitted"] = True
        before = _body_text(page)
        pages_before = len(page.context.pages)
        control.click()
        page.wait_for_timeout(800)
        if len(page.context.pages) > pages_before:
            page = page.context.pages[-1]
            page.wait_for_load_state("domcontentloaded")
        text = _body_text(page)
        receipt = _RECEIPT.search(text)
        if receipt and receipt.group(0) not in before:
            result["status"] = "confirmed"
            result["note"] = "Employer receipt verified after application entry: " + receipt.group(
                0
            )
            result["evidence"] += capture(page, directory, "after-entry-receipt")
            return page, "complete"
        if _scope(page) is None:
            return (
                page,
                "Easy Apply was attempted; no supported form or new receipt was verified. Check before retrying.",
            )
        return page, None
    return page, None


def _answer_for(info, profile_values, answers, job_context=None):
    labels = [info["legend"], info["label"], info["name"], info["id"]]
    saved = {
        _normal(key): value for key, value in answers.items() if value is not None and value != ""
    }
    for label in labels:
        if _normal(label) in saved:
            return saved[_normal(label)], True
    canonical = _canonical_answer(info, answers, job_context or {})
    if canonical is not None:
        return canonical, True
    # Personal contact mappings are exact; screening questions never use
    # fuzzy matching, employer job text, or inferred values.
    identifiers = (
        [info["label"]]
        if info["label"]
        else [info["autocomplete"], info["name"], info["id"], info["placeholder"]]
    )
    for label in identifiers:
        normalized = _normal(label).replace(" *", "").strip()
        aliases = {
            "given name": "first name",
            "family name": "last name",
            "tel": "phone",
            "emailaddress": "email",
            "fullname": "full name",
            "e mail": "email",
            "e mail address": "email address",
            "your email": "email",
            "your email address": "email address",
            "full legal name": "full name",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in profile_values and profile_values[normalized]:
            return profile_values[normalized], False
    return None, False


def _canonical_answer(info, answers, context):
    label = _normal(info.get("legend") or info.get("question") or info.get("label") or "")
    country = str(context.get("location", "")).lower()
    us_question = bool(re.search(r"\b(united states|usa|u s)\b", label))
    other_country = bool(
        re.search(r"\b(canada|united kingdom|uk|germany|france|india|australia|singapore)\b", label)
    )
    us_job = bool(re.search(r"\b(us|usa|united states)\b", country))

    def preset(key):
        value = answers.get(key)
        return value if isinstance(value, (str, bool)) and str(value).strip() else None

    if not other_country and (us_question or us_job):
        has_authorization = bool(
            re.search(r"\b(authorized|authorised|authorization|authorisation|eligible)\b", label)
            and "work" in label
        )
        has_sponsorship = bool(re.search(r"\b(sponsorship|sponsor)\b", label))
        # Authorization alone does not answer compound residence, sponsorship
        # or future-status assertions. Exact saved question answers still win.
        if has_authorization and (
            has_sponsorship or re.search(r"\b(live|reside|resident|residency|future)\b", label)
        ):
            return None
        if (
            re.search(r"\b(authorized|authorised|authorization|authorisation|eligible)\b", label)
            and "work" in label
            and not re.search(r"\b(citizen|citizenship|clearance)\b", label)
        ):
            return preset("@work_authorized_us")
        if re.search(r"\b(sponsorship|sponsor)\b", label) and re.search(
            r"\b(require|need|visa)\b", label
        ):
            if re.search(r"\b(without|not|no)\b", label):
                return None
            value = preset("@requires_sponsorship_us")
            both_periods = (
                "future" in label and bool(re.search(r"\b(now|currently|current)\b", label))
            ) or "ever" in label
            if both_periods or _normal(value) in ["no", "false", "0"]:
                return value
            return None
    if (
        "privacy" in label
        and re.search(r"\b(application|candidate|recruitment)\b", label)
        and not re.search(r"\b(marketing|newsletter|terms|contract|waiver|waive|release)\b", label)
    ):
        return preset("@recruitment_privacy_consent")
    if (
        re.search(r"\b(certify|attest)\b", label)
        and "information" in label
        and re.search(r"\b(true|correct|accurate)\b", label)
        and not re.search(r"\b(terms|contract|waive)\b", label)
    ):
        return preset("@application_accuracy_attestation")
    if (
        "available" in label
        and "work" in label
        and re.search(r"\b(cities|city|location|locations)\b", label)
    ):
        return preset("@available_cities")
    if re.search(r"\b(languages|language)\b", label) and re.search(r"\b(fluent|fluently)\b", label):
        return preset("@fluent_languages")
    return None


def _fill_radio_groups(scope, answers, job_context=None):
    """Verify each radio group against an approved answer, including defaults."""
    groups = {}
    controls = scope.locator('input[type="radio"]')
    for index in range(min(controls.count(), 150)):
        control = controls.nth(index)
        info = control.evaluate(_FIELD_INFO)
        if info["disabled"]:
            continue
        groups.setdefault(info["radio_group"], []).append((control, info))
    saved = {
        _normal(key): value for key, value in answers.items() if value is not None and value != ""
    }
    unknown = []
    for members in groups.values():
        first = members[0][1]
        question = first["question"] or first["name"] or "Unlabelled radio question"
        keys = [first["question"], first["name"]]
        approved = [saved[_normal(key)] for key in keys if key and _normal(key) in saved]
        if not approved:
            canonical = _canonical_answer(
                {**first, "legend": first["question"]}, answers, job_context or {}
            )
            if canonical is not None:
                approved = [canonical]
        if not approved:
            if any(info["required"] or info["checked"] for _, info in members):
                unknown.append(question + " (radio choice needs an approved answer)")
            continue
        if len({_normal(value) for value in approved}) != 1:
            unknown.append(question + " (conflicting saved answers)")
            continue
        value = approved[0]
        matches = [
            (control, info)
            for control, info in members
            if _normal(info["label"]) == _normal(value)
            or _normal(info["option_value"]) == _normal(value)
        ]
        if not matches:
            unknown.append(question + " (saved answer not offered)")
            continue
        if len(matches) != 1:
            unknown.append(question + " (saved answer matches multiple options)")
            continue
        selected, _ = matches[0]
        try:
            if not selected.is_checked():
                try:
                    selected.check(timeout=2000)
                except Exception:
                    # Styled native radios may be covered by their visible
                    # label. Use the associated UI, never force a DOM value.
                    labels = selected.locator("xpath=ancestor::label[1]")
                    if labels.count() != 1 and selected.get_attribute("id"):
                        labels = scope.locator(
                            "label[for=" + json.dumps(selected.get_attribute("id")) + "]"
                        )
                    if labels.count() != 1 or not labels.is_visible():
                        raise
                    labels.click(timeout=2500)
            checked = [control for control, _ in members if control.is_checked()]
            if len(checked) != 1 or not selected.is_checked():
                unknown.append(question + " (approved radio choice could not be verified)")
            else:
                checked_info = checked[0].evaluate(_FIELD_INFO)
                if _normal(checked_info["label"]) != _normal(value) and _normal(
                    checked_info["option_value"]
                ) != _normal(value):
                    unknown.append(
                        question + " (checked radio choice differs from the approved answer)"
                    )
        except Exception:
            unknown.append(question + " (could not select the approved radio answer)")
    return unknown


def _answer_like_hidden(info):
    if _normal(info.get("name")) in (
        "timezone",
        "timezone offset",
        "timezoneoffset",
        "utc offset",
        "utcoffset",
    ):
        return False
    clue = _normal(" ".join([info["label"], info["name"], info["id"]]))
    if re.search(r"\b(?:csrf|xsrf|nonce|requisition|posting id|job id|jobid|form id)\b", clue):
        return False
    return bool(
        re.search(
            r"\b(?:salary|compensation|work auth|work authorization|authorized|"
            r"sponsorship|sponsor|visa|veteran|disability|race|ethnicity|gender|"
            r"relocation|clearance|citizenship|nationality|consent|agree|terms|"
            r"background|criminal|felony|eligibility|demographic|birth|age|"
            r"applicant|answer|question|email|phone|full name|first name|last name)\b",
            clue,
        )
    )


def _approved_current_value(info, value, explicit):
    if value is None:
        return False
    if info.get("lever_location"):
        return _normal(info.get("selected_location")) == _normal(value) and _normal(
            info["value"]
        ) == _normal(value)
    if info.get("role") == "combobox" and not info.get("helper"):
        selected = info.get("selected_labels", [])
        expected = [part.strip() for part in str(value).split(";") if part.strip()]
        if "language" in _normal(info.get("label")):
            expected = [part.strip() for part in re.split("[;,]", str(value)) if part.strip()]
        return bool(selected) and {_choice_key(x, info) for x in selected} == {
            _choice_key(x, info) for x in expected
        }
    if info["type"] == "checkbox":
        if not explicit or _normal(value) not in ("true", "yes", "1", "agree", "false", "no", "0"):
            return False
        return info["checked"] == (_normal(value) in ("true", "yes", "1", "agree"))
    if _normal(info.get("label") or info.get("name")) in ("phone", "phone number", "mobile phone"):
        actual, approved = re.sub(r"\D", "", str(info["value"])), re.sub(r"\D", "", str(value))
        if len(approved) == 11 and approved.startswith("1"):
            return actual in [approved, approved[1:]]
        return actual == approved
    return _normal(info["value"]) == _normal(value) or (
        info["tag"] == "select" and _normal(info["selected_label"]) == _normal(value)
    )


def _choice_key(value, info):
    normalized = _normal(value)
    if "country" in _normal(info.get("label")):
        if normalized in ("us", "usa", "u s", "u s a", "united states of america") or re.fullmatch(
            r"united states(?: \d+)?", normalized
        ):
            return "united states"
    positive = {
        "yes",
        "true",
        "i agree",
        "agree",
        "i understand",
        "i acknowledge",
        "acknowledge",
        "i certify",
    }
    negative = {"no", "false", "i do not agree", "decline", "i decline"}
    if normalized in positive:
        return "yes"
    if normalized in negative:
        return "no"
    return normalized


def _select_custom(field, info, value):
    if _approved_current_value(info, value, True):
        return
    values = [x.strip() for x in str(value).split(";") if x.strip()]
    if "language" in _normal(info.get("label")):
        values = [x.strip() for x in re.split("[;,]", str(value)) if x.strip()]
    root = field.locator("xpath=ancestor::body")
    for requested in values:
        field.click()
        field.fill(requested)
        options = root.locator('[role="option"]')
        selected = None
        deadline = time.monotonic() + 3
        reopened = False
        reopen_at = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            matches = []
            choices = options.evaluate_all(
                "els => els.slice(0,1000).map((el,index) => "
                '({index,text:el.innerText.trim(),disabled:el.getAttribute("aria-disabled")==="true",'
                "visible:!!(el.getBoundingClientRect().width || el.getBoundingClientRect().height) && "
                'getComputedStyle(el).visibility!=="hidden" && getComputedStyle(el).display!=="none"}))'
            )
            for choice in choices:
                if (
                    choice["visible"]
                    and not choice["disabled"]
                    and _choice_key(choice["text"], info) == _choice_key(requested, info)
                ):
                    matches.append(options.nth(choice["index"]))
            if len(matches) == 1:
                selected = matches[0]
                break
            if len(matches) > 1:
                raise ValueError("Saved answer matches multiple dropdown options.")
            if (
                not reopened
                and time.monotonic() >= reopen_at
                and field.get_attribute("aria-expanded") == "false"
            ):
                # React hydration can replace the initially focused control.
                # Reacquire by stable field identity and open it once more.
                field.click()
                field.fill(requested)
                reopened = True
            field.page.wait_for_timeout(100)
        if selected is None:
            field.press("Escape")
            raise ValueError("The saved answer is not an offered dropdown option.")
        selected.click()
        field.page.wait_for_timeout(100)
    field.press("Tab")
    fresh = field.evaluate(_FIELD_INFO)
    if not _approved_current_value(fresh, value, True):
        raise ValueError("The dropdown did not commit the selected answer.")


def _select_lever_location(field, info, value):
    if _approved_current_value(info, value, False):
        return
    field.fill(str(value).split(",")[0].strip())
    field.press("End")  # Lever starts its debounced city search on keydown.
    options = field.locator("xpath=ancestor::body").locator(".dropdown-results .dropdown-location")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        matches = [
            option
            for option in options.all()
            if option.is_visible() and _normal(option.inner_text()) == _normal(value)
        ]
        if len(matches) > 1:
            raise ValueError("The current city matches multiple offered locations")
        if matches:
            matches[0].click()
            field.press("Tab")
            if not _approved_current_value(field.evaluate(_FIELD_INFO), value, False):
                raise ValueError("The current city did not commit to the offered location")
            return
        field.page.wait_for_timeout(100)
    raise ValueError("The current city was not among the offered locations")


def _snapshot_fields(scope):
    fields = scope.locator(
        'input, textarea, select, [contenteditable="true"], '
        '[role="combobox"], [role="checkbox"], [role="radiogroup"]'
    )
    stable = []
    for index in range(min(fields.count(), 150)):
        original = fields.nth(index)
        info = original.evaluate(_FIELD_INFO)
        if (
            info.get("select_proxy")
            or info.get("helper")
            or info["type"] == "radio"
            or (
                info.get("role") == "radiogroup" and original.locator('input[type="radio"]').count()
            )
        ):
            continue
        selector = (
            "[id=" + json.dumps(info["id"]) + "]"
            if info["id"]
            else (info["tag"] + "[name=" + json.dumps(info["name"]) + "]" if info["name"] else None)
        )
        field = scope.locator(selector) if selector else None
        if field is None or field.count() != 1:
            marker = uuid.uuid4().hex
            original.evaluate(
                '(el, value) => el.setAttribute("data-jobpilot-field", value)', marker
            )
            field = scope.locator("[data-jobpilot-field=" + json.dumps(marker) + "]")
        stable.append(field)
    return stable


def _attach_file(field, path, info, scope):
    dropzone = field.locator('xpath=ancestor::*[@data-role="dropzone"][1]')
    remote_required = dropzone.count() == 1 and bool(info.get("data_ui"))
    lever_parser = (
        info.get("id") == "resume-upload-input"
        and scope.locator(".resume-upload-working").count() == 1
    )
    page = field.page
    field.set_input_files(str(path))
    if lever_parser:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if any(x.is_visible() for x in scope.locator(".resume-upload-oversize").all()):
                raise ValueError("The resume exceeds the employer upload limit")
            working = scope.locator(".resume-upload-working")
            finished = scope.locator(".resume-upload-success,.resume-upload-failure")
            if not working.is_visible() and any(x.is_visible() for x in finished.all()):
                return  # A parser failure permits manual entry with the attached file.
            page.wait_for_timeout(100)
        raise ValueError("Resume analysis did not finish before field validation")
    # Workable uploads immediately to a presigned file endpoint. Selecting a
    # local file is not enough: await its visible completed remote attachment.
    if not remote_required:
        return
    # Keep the upload proof requirement across React remounts. The original
    # generated input ID may disappear immediately after selecting the file.
    current = scope.locator('input[type="file"][data-ui=' + json.dumps(info["data_ui"]) + "]")
    dropzone = current.locator('xpath=ancestor::*[@data-role="dropzone"][1]')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if current.count() > 1 or dropzone.count() > 1:
            raise ValueError("Attachment upload control is ambiguous")
        errors = dropzone.locator('[role="alert"][aria-live="assertive"]')
        if any(x.is_visible() for x in errors.all()):
            raise ValueError("Attachment upload failed; review the employer error")
        pending = dropzone.locator('[data-action="abort"]')
        view = dropzone.locator('[data-action="view"]')
        names = dropzone.locator('[data-id="filename"]')
        if (
            not any(x.is_visible() for x in pending.all())
            and any(x.is_visible() for x in view.all())
            and any(x.is_visible() and x.inner_text().strip() == path.name for x in names.all())
        ):
            return
        page.wait_for_timeout(100)
    raise ValueError("Attachment upload completion was not verified")


def _fill_fields(scope, profile, answers, documents, job_context=None):
    unknown = []
    # Attachment uploads can remount the complete form with new control IDs.
    # Finish them before capturing contact and screening control identities.
    for field in _snapshot_fields(scope):
        if field.count() != 1:
            continue
        info = field.evaluate(_FIELD_INFO)
        if info["type"] != "file" or info["disabled"]:
            continue
        label = info["label"] or info["name"] or "Required attachment"
        clue = _normal(
            " ".join(
                [
                    info["label"],
                    info["name"],
                    info["id"],
                    info.get("labelled_text", ""),
                    info.get("data_ui", ""),
                ]
            )
        )
        kind = (
            "cover_pdf"
            if "cover" in clue
            else "resume_pdf"
            if ("resume" in clue or "cv" in clue)
            else None
        )
        path = documents.get(kind) if kind else None
        if path and Path(path).is_file():
            try:
                _attach_file(field, Path(path).resolve(), info, scope)
            except Exception as exc:
                unknown.append(label + " (upload could not be verified: " + str(exc)[:160] + ")")
        elif info["required"] and not info["value"]:
            unknown.append(label)
    unknown.extend(_fill_radio_groups(scope, answers, job_context))
    fields = _snapshot_fields(scope)
    profile_values = _profile_values(profile)
    for field in fields:
        if field.count() != 1:
            unknown.append("Application form changed during filling; review the new fields")
            continue
        info = field.evaluate(_FIELD_INFO)
        if (
            info["disabled"]
            or info.get("select_proxy")
            or info.get("helper")
            or info["type"] in ("submit", "button", "reset", "radio", "file")
        ):
            continue
        label = info["label"] or info["legend"] or info["name"] or info["id"] or "Unlabelled field"
        value, explicit = _answer_for(info, profile_values, answers, job_context)
        if info["type"] == "hidden":
            if (
                _answer_like_hidden(info)
                and info["value"]
                and not _approved_current_value(info, value, explicit)
            ):
                unknown.append(label + " (hidden answer needs approval)")
            continue
        if not info["visible"] and info["type"] != "file":
            if info["value"] and not _approved_current_value(info, value, explicit):
                unknown.append(label + " (hidden default answer needs approval)")
            continue
        if value is None:
            if (
                info["name"] == "org"
                and _normal(info["label"]) == "current company"
                and not info["required"]
            ):
                field.fill("")  # Resume parsers can mistake a former employer for a current one.
                continue
            if info["required"] or info["value"]:
                unknown.append(label)
            continue
        try:
            if info.get("lever_location"):
                _select_lever_location(field, info, value)
            elif info.get("role") == "combobox":
                _select_custom(field, info, value)
            elif info["tag"] == "select":
                options = field.locator("option").evaluate_all(
                    "els => els.map(e => ({label:e.label, value:e.value, disabled:e.disabled}))"
                )
                match = next(
                    (
                        option
                        for option in options
                        if not option["disabled"]
                        and (
                            _choice_key(option["label"], info) == _choice_key(value, info)
                            or str(option["value"]) == str(value)
                        )
                    ),
                    None,
                )
                if not match:
                    unknown.append(label + " (saved answer not offered)")
                    continue
                field.select_option(value=match["value"])
            elif info["type"] == "checkbox":
                if not explicit or _normal(value) not in (
                    "true",
                    "yes",
                    "1",
                    "agree",
                    "false",
                    "no",
                    "0",
                ):
                    if info["required"] or info["checked"]:
                        unknown.append(label)
                    continue
                field.set_checked(_normal(value) in ("true", "yes", "1", "agree"))
            elif info["type"] in ("combobox", "radiogroup", "checkbox"):
                if info["required"]:
                    unknown.append(label + " (custom control requires review)")
            elif info["type"] == "password":
                unknown.append("Login requires review")
            else:
                field.fill(str(value))
        except Exception:
            if info["required"] or info["value"]:
                unknown.append(label + " (could not fill saved value)")
    # Validate current values after changes triggered by other field updates.
    unknown.extend(_fill_radio_groups(scope, answers, job_context))
    for field in _snapshot_fields(scope):
        info = field.evaluate(_FIELD_INFO)
        if (
            info["disabled"]
            or info.get("select_proxy")
            or info.get("helper")
            or info["type"] in ("submit", "button", "reset", "radio")
        ):
            continue
        if info["type"] == "file":
            if info["required"] and not info["value"]:
                unknown.append(info["label"] or info["name"] or "Required attachment")
            continue
        value, explicit = _answer_for(info, profile_values, answers, job_context)
        personal = info["type"] != "hidden" or _answer_like_hidden(info)
        if personal and info["value"] and not _approved_current_value(info, value, explicit):
            unknown.append(
                (info["label"] or info["name"] or "Field") + " (unapproved current value)"
            )
        if info["required"] and info["visible"] and not info["valid"]:
            unknown.append(info["label"] or info["legend"] or info["name"] or "Required field")
    return list(dict.fromkeys(unknown))


def _body_text(page):
    texts = []
    for frame in page.frames:
        try:
            texts.append(frame.locator("body").inner_text(timeout=1500))
        except Exception:
            pass
    return "\n".join(texts)


def _evidence(page, directory, stage):
    paths = []
    screenshot = directory / f"{stage}.png"
    try:
        page.screenshot(path=str(screenshot), full_page=True, timeout=5000)
        paths.append(str(screenshot))
    except Exception:
        pass
    receipt = directory / f"{stage}.json"
    receipt.write_text(
        json.dumps(
            {
                "url": page.url,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "text": _body_text(page)[:100000],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths.append(str(receipt))
    return paths


def _intervention_url(url):
    """Do not put authentication query strings or fragments in durable evidence."""
    parts = urlsplit(str(url or ""))
    if parts.scheme not in ("http", "https"):
        return ""
    host = parts.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    if parts.port:
        host += ":" + str(parts.port)
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _intervention_evidence(page, directory, stage):
    """Retain receipt proof, never remote screenshots, input or provider page text."""
    receipt = None
    try:
        receipt = _RECEIPT.search(_body_text(page))
    except Exception:
        pass
    proof = directory / f"{stage}.json"
    proof.write_text(
        json.dumps(
            {
                "url": _intervention_url(page.url),
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "text": receipt.group(0) if receipt else "Remote page content omitted.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return [str(proof)]


def _intervention_receipt(page, initial_url, before):
    try:
        if page.is_closed():
            return None
        observation = page.evaluate(
            '() => ({url:location.href,text:(document.body?.innerText || "").slice(0,100000)})'
        )
        if not _review_receipt_url_matches(initial_url, observation["url"]):
            return None
        identity_keys = {"jk", "jobid", "job_id", "gh_jid", "requisitionid", "requisition_id"}
        initial_query = {
            key.lower(): value for key, value in parse_qsl(urlsplit(initial_url).query)
        }
        current_query = {
            key.lower(): value for key, value in parse_qsl(urlsplit(observation["url"]).query)
        }
        if any(
            current_query.get(key) != value
            for key, value in initial_query.items()
            if key in identity_keys
        ):
            return None
        match = _RECEIPT.search(observation["text"])
        if match and match.group(0) not in before:
            return {"receipt": match.group(0), "url": _intervention_url(observation["url"])}
    except Exception:
        pass
    return None


def _receipt_watcher(page, initial_url, before):
    observed = {}

    def ready():
        if not observed:
            proof = _intervention_receipt(page, initial_url, before)
            if proof:
                observed.update(proof)
        return bool(observed)

    return ready, observed


def _receipt_proof_evidence(proof, directory):
    """Write the frozen atomic observation, not a later potentially changed page."""
    path = directory / "receipt-observed.json"
    path.write_text(
        json.dumps(
            {
                "url": proof["url"],
                "text": proof["receipt"],
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return [str(path)]


def _pause_intervention(handler, page, job, settings, *, kind, note, submitted, ready, auto_resume):
    try:
        timeout = max(0.1, min(float(settings.get("intervention_timeout_seconds", 28800)), 28800))
        outcome = handler(
            page,
            job,
            kind=kind,
            note=note,
            submitted=submitted,
            ready=ready,
            auto_resume=auto_resume,
            timeout_seconds=timeout,
        )
        if outcome not in ("resume", "cancelled", "expired", "closed", "interrupted"):
            return "interrupted"
        if outcome == "resume" and not ready():
            return "interrupted"
        return outcome
    except Exception:
        # The exception may contain a typed password/code or provider page text.
        return "interrupted"


def apply(job, profile, answers, documents, settings, checkpoint=None, intervention_handler=None):
    result = {"status": "needs_review", "note": "", "evidence": [], "submitted": False}
    evidence = _intervention_evidence if intervention_handler is not None else _evidence
    submission_url, submission_before = None, ""

    def pre_submit_challenge(page, note):
        result["note"] = note
        if "Login" in note:
            result.update(
                auth_platform=_platform(page.url),
                auth_url=_intervention_url(page.url)
                if intervention_handler is not None
                else page.url,
                review_reason="auth_required",
            )
        if intervention_handler is None:
            return False
        before_pause = _body_text(page)
        receipt_ready, human_receipt = _receipt_watcher(page, url, before_pause)

        def cleared():
            try:
                return receipt_ready() or (not page.is_closed() and _challenge(page) is None)
            except Exception:
                return False

        kind = "captcha" if re.search(r"captcha|human", note, re.I) else "authentication"
        outcome = _pause_intervention(
            intervention_handler,
            page,
            job,
            settings,
            kind=kind,
            note=note,
            submitted=False,
            ready=cleared,
            auto_resume=False,
        )
        result["intervention_state"] = outcome
        if receipt_ready():
            result.update(
                status="confirmed",
                submitted=True,
                manual_completion=True,
                note="New matching employer receipt observed after the owner completed the application during intervention.",
            )
            result["evidence"] += _receipt_proof_evidence(human_receipt, directory)
            for key in ("auth_platform", "auth_url", "review_reason"):
                result.pop(key, None)
            return False
        if outcome != "resume":
            result["note"] = (
                f"Pre-submission intervention {outcome}; no new submission was attempted."
            )
            return False
        if not _review_receipt_url_matches(url, page.url):
            # Login may land on a feed/account page. A solved challenge on the
            # same job is kept in place, including its live CAPTCHA state.
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(300)
        if not cleared():
            result["note"] = (
                "The application still requires authentication or verification after intervention."
            )
            return False
        for key in ("auth_platform", "auth_url", "review_reason"):
            result.pop(key, None)
        return True

    def post_submit_challenge(page, note, initial_url, before):
        result.update(
            review_reason="verification_required",
            auth_url=_intervention_url(page.url) if intervention_handler is not None else page.url,
            auth_platform=_platform(page.url),
        )
        result["note"] = (
            note
            + " after submit was attempted; no receipt verified. Check the existing attempt before retrying."
        )
        if intervention_handler is None:
            return
        ready_receipt, observed_receipt = _receipt_watcher(page, initial_url, before)
        outcome = _pause_intervention(
            intervention_handler,
            page,
            job,
            settings,
            kind="verification",
            note="Finish verification for the existing submission. Only a new matching receipt can confirm it.",
            submitted=True,
            ready=ready_receipt,
            auto_resume=True,
        )
        result["intervention_state"] = outcome
        proof = observed_receipt if outcome == "resume" else None
        if proof:
            result.update(
                status="confirmed",
                note="Employer receipt verified after human-assisted verification: "
                + proof["receipt"],
            )
            result["evidence"] += _receipt_proof_evidence(proof, directory)
        else:
            result["note"] = (
                f"Verification intervention {outcome}; submission outcome remains uncertain. No second submit was attempted."
            )

    try:
        url = validate_public_url(
            job.get("apply_url") or job.get("url") or "", allow_fixture=_fixture(settings)
        )
    except Exception as exc:
        return {**result, "status": "error", "note": str(exc)}
    if not _session_lock.acquire(blocking=False):
        return {**result, "note": "Close the JobPilot login browser before applying"}
    context = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = _launch(
                playwright,
                settings,
                _platform(url, job.get("source", "")),
                bool(settings.get("browser_headless", True)),
            )
            directory = (
                _data_dir(settings)
                / "evidence"
                / f"{str(job.get('id', 'job'))[:40]}-{uuid.uuid4().hex}"
            )
            directory.mkdir(parents=True, exist_ok=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            challenge = _challenge(page)
            if challenge:
                if not pre_submit_challenge(page, challenge):
                    result["evidence"] += evidence(page, directory, "review")
                    return result
            if _RECEIPT.search(_body_text(page)):
                result["note"] = (
                    "An existing application receipt is shown; verify the prior application"
                )
                result["evidence"] += evidence(page, directory, "existing-receipt")
                return result
            entry_url, entry_before = page.url, _body_text(page)
            entry_options = (
                {"evidence_handler": evidence} if intervention_handler is not None else {}
            )
            page, entry_note = _enter_application(
                page,
                _platform(url),
                settings,
                result,
                checkpoint,
                directory,
                job.get("id"),
                **entry_options,
            )
            if result["submitted"]:
                submission_url, submission_before = entry_url, entry_before
            if entry_note:
                if intervention_handler is not None and result["submitted"]:
                    if entry_note == "complete" and not _intervention_receipt(
                        page, entry_url, entry_before
                    ):
                        result.update(
                            status="needs_review",
                            note="Application entry did not produce a new matching job receipt.",
                        )
                    elif entry_note != "complete" and _challenge(page):
                        post_submit_challenge(page, _challenge(page), entry_url, entry_before)
                        return result
                if entry_note != "complete":
                    result["note"] = entry_note
                    result["evidence"] += evidence(page, directory, "entry-review")
                return result
            for step in range(12):
                challenge = _challenge(page)
                if challenge:
                    if intervention_handler is not None and result["submitted"]:
                        post_submit_challenge(
                            page, challenge, submission_url or url, submission_before
                        )
                        return result
                    if not pre_submit_challenge(page, challenge):
                        break
                scope = _scope(page, timeout_ms=8000, stop_on_entry=False)
                if scope is None:
                    result["note"] = (
                        "No supported application form was found; review the employer page"
                    )
                    break
                _dismiss_cookie_overlays(page)
                unknown = _fill_fields(scope, profile, answers or {}, documents or {}, job)
                if unknown:
                    result["note"] = "Fields need saved answers or review: " + "; ".join(
                        unknown[:12]
                    )
                    result["review_reason"] = "unanswered_fields"
                    break
                final, caption = _visible_button(scope, _FINAL)
                if final is not None:
                    result["evidence"] += evidence(page, directory, "before-submit")
                    if checkpoint is None:
                        result["note"] = "Submission checkpoint missing; fields prepared for review"
                        break
                    checkpoint(
                        {
                            "url": _intervention_url(page.url)
                            if intervention_handler is not None
                            else page.url,
                            "button": caption,
                            "evidence": list(result["evidence"]),
                            "job_id": job.get("id"),
                        }
                    )
                    # Set uncertainty before the click: a click timeout may
                    # occur after an employer actually receives the form.
                    result["submitted"] = True
                    before = _body_text(page)
                    submission_url, submission_before = page.url, before
                    try:
                        final.click()
                    except Exception:
                        if intervention_handler is None:
                            raise
                        # A navigation timeout can occur after the employer
                        # received the click and displayed a live code gate.
                        # Inspect that retained page; never click Submit again.
                        proof = _intervention_receipt(page, submission_url, before)
                        if proof:
                            result.update(
                                status="confirmed",
                                note="Employer receipt verified: " + proof["receipt"],
                            )
                            result["evidence"] += _receipt_proof_evidence(proof, directory)
                            return result
                        verification = _challenge(page)
                        if verification:
                            post_submit_challenge(page, verification, submission_url, before)
                            return result
                        raise
                    deadline = time.monotonic() + max(
                        0.5, min(float(settings.get("receipt_wait_seconds", 12)), 30)
                    )
                    receipt = None
                    verification = None
                    while time.monotonic() < deadline:
                        text = _body_text(page)
                        match = _RECEIPT.search(text)
                        matched_receipt = (
                            _intervention_receipt(page, submission_url, before)
                            if intervention_handler is not None
                            else None
                        )
                        if (matched_receipt is not None) or (
                            intervention_handler is None and match and match.group(0) not in before
                        ):
                            receipt = (
                                matched_receipt["receipt"] if matched_receipt else match.group(0)
                            )
                            break
                        verification = _challenge(page)
                        if verification:
                            break
                        page.wait_for_timeout(200)
                    result["evidence"] += evidence(page, directory, "after-submit")
                    if receipt:
                        result["status"] = "confirmed"
                        result["note"] = "Employer receipt verified: " + receipt
                        if intervention_handler is not None and matched_receipt:
                            result["evidence"] += _receipt_proof_evidence(
                                matched_receipt, directory
                            )
                    elif verification:
                        post_submit_challenge(page, verification, submission_url, before)
                    else:
                        result["note"] = (
                            "Submit was attempted; no new explicit receipt was verified. Check before retrying."
                        )
                    return result
                next_button, caption = _visible_button(scope, _NEXT)
                if next_button is None:
                    result["note"] = "No recognized next or final submit action; review the form"
                    break
                if next_button.get_attribute("type") == "submit":
                    if checkpoint is None:
                        result["note"] = "Submission checkpoint missing; review the form"
                        break
                    checkpoint(
                        {
                            "url": _intervention_url(page.url)
                            if intervention_handler is not None
                            else page.url,
                            "button": caption,
                            "evidence": list(result["evidence"]),
                            "job_id": job.get("id"),
                            "intermediate": True,
                        }
                    )
                    result["submitted"] = True
                    submission_url, submission_before = page.url, _body_text(page)
                next_button.click()
                page.wait_for_timeout(500)
                if _RECEIPT.search(_body_text(page)):
                    result["note"] = (
                        "Receipt appeared during a form transition; verify the submission"
                    )
                    break
            else:
                result["note"] = "Application exceeded the supported number of steps"
            result["evidence"] += evidence(page, directory, "review")
            return result
    except Exception as exc:
        result["status"] = "needs_review" if result["submitted"] else "error"
        result["note"] = (
            "Uncertain submission; verify before retrying. " if result["submitted"] else ""
        ) + (
            f"Browser interruption during remote intervention ({type(exc).__name__})."
            if intervention_handler is not None
            else f"{type(exc).__name__}: {str(exc)[:350]}"
        )
        return result
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        _session_lock.release()


def _review_receipt_url_matches(initial_url, current_url):
    initial, current = urlsplit(initial_url), urlsplit(current_url)
    if (initial.scheme, initial.hostname, initial.port) != (
        current.scheme,
        current.hostname,
        current.port,
    ):
        return False
    base = re.sub(r"/(?:apply|application)/?$", "", initial.path).rstrip("/")
    return bool(base and (current.path.rstrip("/") == base or current.path.startswith(base + "/")))


def open_review(
    job, profile, answers, documents, settings=None, on_closed=None, intervention_handler=None
):
    """Open a review and report matching receipts without submitting the form."""
    settings = settings or {}
    evidence = _intervention_evidence if intervention_handler is not None else _evidence
    try:
        url = validate_public_url(
            job.get("apply_url") or job.get("url") or "", allow_fixture=_fixture(settings)
        )
    except Exception as exc:
        return {"status": "error", "note": str(exc)}
    if not _session_lock.acquire(blocking=False):
        return {
            "status": "needs_review",
            "note": "Close the existing JobPilot browser before opening verification.",
        }
    ready, state = threading.Event(), {}
    session_key = "review:" + uuid.uuid4().hex

    def review_thread():
        context = None
        outcome = {
            "status": "needs_review",
            "submitted": False,
            "evidence": [],
            "note": "Verification browser closed without a new receipt; existing uncertain attempt retained.",
        }
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                context = _launch(playwright, settings, _platform(url), bool(_fixture(settings)))
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(1000 if _fixture(settings) else 3000)
                page.goto(url, wait_until="domcontentloaded")
                initial_url, before = page.url, _body_text(page)
                directory = (
                    _data_dir(settings)
                    / "evidence"
                    / f"review-{job.get('id', 'job')}-{uuid.uuid4().hex}"
                )
                directory.mkdir(parents=True, exist_ok=True)
                existing = _RECEIPT.search(before)
                if not existing:
                    try:
                        _dismiss_cookie_overlays(page)
                        if not _challenge(page):
                            scope = _scope(page, timeout_ms=8000, stop_on_entry=False)
                            if scope is not None:
                                unknown = _fill_fields(
                                    scope, profile, answers or {}, documents or {}, job
                                )
                                if unknown:
                                    outcome["note"] = (
                                        "Verification form still needs review: "
                                        + "; ".join(unknown[:8])
                                    )
                    except Exception:
                        # The user can navigate or finish while preparation is
                        # in progress. Keep observing the live browser.
                        outcome["note"] = (
                            "The form changed during preparation; inspect it in the verification browser."
                        )
                outcome["evidence"] += evidence(page, directory, "review-opened")
                state.update(
                    status="opened",
                    note="Review the prepared form and finish the employer verification in the JobPilot browser. No final action was taken automatically.",
                )
                ready.set()
                if intervention_handler is not None:
                    receipt_ready, observed_receipt = _receipt_watcher(page, initial_url, before)
                    disposition = _pause_intervention(
                        intervention_handler,
                        page,
                        job,
                        settings,
                        kind="verification",
                        note="Review the existing application. Only a new matching employer receipt can confirm its outcome.",
                        submitted=bool(job.get("uncertain") or job.get("submission_checkpoint_at")),
                        ready=receipt_ready,
                        auto_resume=True,
                    )
                    outcome["intervention_state"] = disposition
                    proof = observed_receipt if disposition == "resume" else None
                    if proof:
                        outcome.update(
                            status="confirmed",
                            receipt=proof["receipt"],
                            url=proof["url"],
                            note="New employer receipt observed after user-assisted verification.",
                        )
                        outcome["evidence"] += _receipt_proof_evidence(proof, directory)
                    else:
                        outcome["note"] = (
                            f"Verification intervention {disposition}; no new matching receipt. Existing uncertain attempt retained."
                        )
                    return
                deadline = time.monotonic() + max(
                    0.3, min(float(settings.get("review_hold_seconds", 3600)), 7200)
                )
                while context.pages and time.monotonic() < deadline:
                    for tab in list(context.pages):
                        if tab.is_closed():
                            continue
                        # Read receipt text and its URL in one browser task so
                        # navigation cannot pair one job's URL with another's text.
                        observation = tab.evaluate(
                            '() => ({url:location.href,text:(document.body?.innerText || "").slice(0,100000)})'
                        )
                        if not _review_receipt_url_matches(initial_url, observation["url"]):
                            continue
                        match = _RECEIPT.search(observation["text"])
                        if match and match.group(0) not in before:
                            proof = directory / "receipt-observed.json"
                            proof.write_text(
                                json.dumps(
                                    {
                                        **observation,
                                        "captured_at": time.strftime(
                                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                                        ),
                                    },
                                    indent=2,
                                ),
                                encoding="utf-8",
                            )
                            outcome.update(
                                status="confirmed",
                                receipt=match.group(0),
                                url=observation["url"],
                                note="New employer receipt observed after user-assisted verification.",
                            )
                            outcome["evidence"].append(str(proof))
                            outcome["evidence"] += _evidence(tab, directory, "verified-receipt")
                            return
                    if context.pages:
                        context.pages[0].wait_for_timeout(100 if _fixture(settings) else 500)
        except Exception as exc:
            error = (
                f"Browser interruption ({type(exc).__name__})."
                if intervention_handler is not None
                else f"{type(exc).__name__}: {str(exc)[:200]}"
            )
            if not state:
                state.update(status="error", note="Could not open verification browser: " + error)
            outcome["note"] = "Verification browser ended without a new receipt. " + error
        finally:
            ready.set()
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            _session_lock.release()
            _login_threads.pop(session_key, None)
            if on_closed is not None:
                try:
                    on_closed(outcome)
                except Exception:
                    pass

    thread = threading.Thread(target=review_thread, name="jobpilot-verification", daemon=True)
    _login_threads[session_key] = thread
    thread.start()
    ready.wait(10)
    return (
        dict(state)
        if state
        else {
            "status": "opened",
            "note": "Verification browser is preparing the form; wait for its fields before continuing.",
        }
    )


def _login_verified(page, platform, login_url):
    """Observe login proof in this JobPilot profile without performing auth actions."""
    try:
        if page.is_closed():
            return False
        current, requested = urlsplit(page.url), urlsplit(login_url)
        current_host = (current.hostname or "").lower()
        platform = str(platform).lower()
        if platform in ("linkedin", "indeed"):
            if _platform(page.url) != platform:
                return False
        elif (current.scheme, current.hostname, current.port) != (
            requested.scheme,
            requested.hostname,
            requested.port,
        ):
            return False
        # Never let a cookie or stale account menu override a visible login,
        # verification, CAPTCHA, or blocked-request page. This deliberately
        # avoids the application-form readiness wait used by _challenge.
        frames = _visible_frames(page)
        if not frames or any(_challenge_frame(frame, False) for frame in frames):
            return False
        if re.search(
            r"/(?:authwall|login|signin|sign-in|checkpoint)(?:[/?.]|$)", current.path, re.I
        ):
            return False
        signout = re.compile(r"^(?:sign\s*out|log\s*out|logout)(?:\s+of\s+.*)?$", re.I)
        for frame in frames:
            frame_host = (urlsplit(frame.url).hostname or "").lower()
            if frame_host != current_host:
                continue
            controls = frame.locator('a,button,[role="button"],[role="menuitem"]')
            for index in range(min(controls.count(), 100)):
                control = controls.nth(index)
                if control.is_visible() and signout.fullmatch(
                    (control.get_attribute("aria-label") or control.inner_text(timeout=500)).strip()
                ):
                    return True
        if platform == "linkedin" and re.match(r"^/feed(?:/|$)", current.path, re.I):
            # Read only the isolated context launched by JobPilot. Cookie
            # values are neither logged nor copied outside that context.
            return any(
                cookie.get("name") == "li_at" and bool(cookie.get("value"))
                for cookie in page.context.cookies("https://www.linkedin.com")
            )
        return False
    except Exception:
        # Navigation and window closure race the poll. Missing evidence must
        # remain unverified instead of terminating the login lifecycle.
        return False


def open_login(platform, url=None, settings=None, on_closed=None):
    """Open only JobPilot's persistent profile in a dedicated visible browser."""
    settings = settings or {}
    defaults = {
        "linkedin": "https://www.linkedin.com/login",
        "indeed": "https://secure.indeed.com/account/login",
    }
    url = url or defaults.get(str(platform).lower())
    if not url:
        return {"status": "needs_review", "note": "Provide the employer application URL"}
    try:
        validate_public_url(url, allow_fixture=_fixture(settings))
    except Exception as exc:
        return {"status": "error", "note": str(exc)}
    if not _session_lock.acquire(blocking=False):
        return {"status": "needs_review", "note": "A JobPilot browser session is already open"}
    ready, state = threading.Event(), {}
    target_platform = _platform(url)

    def login_thread():
        context = None
        verified = False
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                context = _launch(playwright, settings, target_platform, False)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                state.update(
                    {
                        "status": "opened",
                        "note": "Log in in the JobPilot browser, then close it to save the session",
                        "url": url,
                        "platform": target_platform,
                    }
                )
                ready.set()
                while context.pages:
                    try:
                        for tab in list(context.pages):
                            verified = _login_verified(tab, target_platform, url) or verified
                        context.pages[0].wait_for_timeout(500)
                    except Exception:
                        break
        except Exception as exc:
            state.update({"status": "error", "note": f"{type(exc).__name__}: {str(exc)[:250]}"})
        finally:
            ready.set()
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            _session_lock.release()
            if on_closed is not None:
                try:
                    on_closed({"platform": target_platform, "url": url, "verified": verified})
                except Exception:
                    # Recording a closed session cannot retain the browser
                    # lock or crash a later application worker.
                    pass

    thread = threading.Thread(target=login_thread, name="jobpilot-login", daemon=True)
    _login_threads[str(platform)] = thread
    thread.start()
    ready.wait(10)
    return (
        dict(state)
        if ready.is_set()
        else {"status": "opening", "note": "JobPilot browser is starting"}
    )
