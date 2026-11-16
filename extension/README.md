# JobPilot Autofill 1.0.0

Fill application forms in your normal signed-in Chrome tab using a local profile.
This extension never clicks Next or Submit. Review every answer before submitting.

## Install in Chrome

1. Extract the extension ZIP into a permanent folder.
2. Open `chrome://extensions`, turn on **Developer mode**, and click **Load unpacked**.
3. Select the folder containing `manifest.json`.
4. Pin JobPilot Autofill from Chrome's extensions menu, then open **Profile & settings**.

The unpacked extension is not a Chrome Web Store release. Keep the folder in place;
Chrome loads it from there. Use Chrome's **Reload** button after replacing its files.

## Standalone use

Enter your contact details, links, address, explicit authorization choices and any
employment or education records, then **Save profile**. Unknown answers stay blank.
You can import/export profile JSON and restore the previous saved profile after a
replacement. These features work without JobPilot running.

Open an application website and click the extension icon, then **Autofill this
page**. It keeps nonempty answers by default. Enable **Replace existing answers
and files** only when you intend to replace them. **Undo last change** restores the
last operation while keeping later edits. Click Autofill again after the website
adds fields or displays the next page.

Choose a local PDF or DOCX resume, up to 5 MiB, in settings. **Attach resume** is a
separate explicit action in the popup. It needs one clearly labelled Resume/CV file
input. Existing files are kept unless replacement is enabled. You can undo an
attachment, including restoring the previous selected file.

## Optional JobPilot connection

Start JobPilot locally. In extension settings, click **Open JobPilot Settings**,
generate a code in the dashboard, then paste it into the extension and click
**Connect**. Codes are single use, expire after five minutes, and are bound to this
extension's exact ID. Credentials last up to 90 days and can be revoked from either
app. The extension does not receive the dashboard session token.

**Import JobPilot profile** asks before replacing your local profile and saves the
previous version for restoration. A failed import keeps your saved profile.
**Load prepared resumes** lets you choose a document for a specific job. **Use this
resume** downloads a local copy; uploading to the website still requires the
separate **Attach resume** action.

**Disconnect & revoke** revokes the credential in JobPilot. If JobPilot is offline,
**Forget local connection** removes this browser's credential; revoke the old
connection later in the dashboard. Saved local profiles and resumes remain usable.

## Supported forms and limits

- Native inputs, textareas, exact-match selects and clearly labelled yes/no radio
  groups. Matching uses labels, ARIA, supported autocomplete hints and field names.
- Controlled inputs receive native value setters plus bubbling input/change events.
- Open shadow roots and same-origin frames are scanned on each click. Cross-origin
  frames, closed shadow roots and custom controls may require manual entry.
- Numbered Employment/Experience/Education sections can map corresponding records.
  A single record can fill unique fields; ambiguous repeated records are skipped.
- Passwords, national IDs, payment data, demographic questions, consent and
  attestations stay manual. Unknown questions are reported, without guessed answers.

No universal ATS compatibility is promised. Check the popup's **Needs your answer**
and **Answer manually** lists, and review what the website actually accepted.

## Privacy and permissions

The shipping manifest requests `activeTab`, `scripting`, `storage`, and access only
to `http://127.0.0.1:8765/*`. It has no permanent all-sites grant, externally
connectable endpoint or remote JavaScript. Clicking the Chrome action grants the
current website access. Data is stored in this Chrome profile, not synced to a
third party. Protect exported JSON because it contains your application details.

Chrome storage is restricted to trusted extension contexts. The pairing credential
and saved resume bytes never go to a content script during Autofill. Only profile
fields and, on Attach, the explicitly selected resume are passed to the isolated
filling engine. Website scripts can read answers and files you choose to fill,
just as they can read answers entered manually.

Protected JobPilot reads use POST aliases so Chrome supplies its extension Origin;
the service checks both that Origin and the independent bearer credential. All
document requests are fixed loopback API paths; filesystem paths are not exposed.

## Development checks

No build or npm install is needed. Run `node --test extension/tests/*.test.cjs`
from the repository root. Real Chromium integration tests are in
`tests/test_extension_browser.py`. They use fictional data, temporary profiles and
a test-only localhost fixture grant to simulate a toolbar `activeTab` gesture in
headless Chrome. That grant is never added to the release manifest.
