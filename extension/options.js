const $ = (id) => document.getElementById(id);
const core = globalThis.JobPilotCore;
const sections = [
  [
    'Contact',
    [
      ['name', 'Full name'],
      ['first_name', 'First name'],
      ['last_name', 'Last name'],
      ['email', 'Email address', 'email'],
      ['phone', 'Phone number', 'tel'],
      ['location', 'Current location'],
    ],
  ],
  [
    'Address',
    [
      ['address_line1', 'Address line 1'],
      ['address_line2', 'Address line 2'],
      ['city', 'City'],
      ['state', 'State / province'],
      ['postal_code', 'Postal / ZIP code'],
      ['country', 'Country'],
    ],
  ],
  [
    'Links',
    [
      ['linkedin', 'LinkedIn URL', 'url'],
      ['website', 'Website URL', 'url'],
      ['github', 'GitHub URL', 'url'],
      ['portfolio', 'Portfolio URL', 'url'],
    ],
  ],
  [
    'Work & preferences',
    [
      ['current_employer', 'Current employer'],
      ['current_title', 'Current title'],
      ['work_authorized', 'Legally authorized to work?', 'boolean'],
      ['requires_sponsorship', 'Require visa sponsorship?', 'boolean'],
      ['willing_to_relocate', 'Willing to relocate?', 'boolean'],
      ['salary_expectation', 'Salary expectation'],
      ['salary_currency', 'Salary currency'],
      ['available_date', 'Available start date', 'date'],
      ['years_experience', 'Years of professional experience'],
      ['skills', 'Skills · one per line', 'list'],
      ['certifications', 'Certifications · one per line', 'list'],
      ['interests', 'Professional interests · one per line', 'list'],
    ],
  ],
];
const recordLabels = {
  company: 'Company',
  title: 'Job title',
  start: 'Start date or year',
  end: 'End date or year',
  location: 'Location',
  description: 'Description',
  institution: 'Institution',
  degree: 'Degree',
  field_of_study: 'Field of study',
  gpa: 'GPA',
};
async function send(message) {
  const result = await chrome.runtime.sendMessage(message);
  if (!result?.ok)
    throw new Error(result?.error || 'The extension could not complete this action.');
  return result;
}
function notice(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}
function field(key, label, type = 'text', value = '', prefix = '') {
  const wrapper = document.createElement('label');
  const span = document.createElement('span');
  span.textContent = label;
  let input;
  if (type === 'boolean') {
    input = document.createElement('select');
    for (const [v, text] of [
      ['', 'Unknown / leave blank'],
      ['true', 'Yes'],
      ['false', 'No'],
    ]) {
      const option = document.createElement('option');
      option.value = v;
      option.textContent = text;
      input.append(option);
    }
    input.value = typeof value === 'boolean' ? String(value) : '';
  } else {
    input = document.createElement(['list', 'textarea'].includes(type) ? 'textarea' : 'input');
    if (input.tagName === 'INPUT') input.type = type;
    else input.rows = type === 'textarea' ? 4 : 3;
    input.value = Array.isArray(value) ? value.join('\n') : (value ?? '');
  }
  input.id = prefix + key;
  input.dataset.key = key;
  input.autocomplete = 'off';
  wrapper.append(span, input);
  return wrapper;
}
function addRecord(kind, values = {}) {
  const container = $(`${kind}-records`);
  const card = document.createElement('div');
  card.className = 'record';
  const heading = document.createElement('div');
  heading.className = 'section-heading';
  const title = document.createElement('h3');
  title.textContent = `${kind === 'experience' ? 'Employment' : 'Education'} ${container.children.length + 1}`;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'link';
  remove.textContent = 'Remove';
  remove.addEventListener('click', () => card.remove());
  heading.append(title, remove);
  card.append(heading);
  const grid = document.createElement('div');
  grid.className = 'field-grid';
  for (const key of core.RECORD_FIELDS[kind])
    grid.append(
      field(
        key,
        recordLabels[key],
        key === 'description' ? 'textarea' : 'text',
        values[key] || '',
        `${kind}-${crypto.randomUUID()}-`,
      ),
    );
  card.append(grid);
  container.append(card);
}
function renderProfile(profile) {
  $('profile-fields').replaceChildren();
  for (const [title, fields] of sections) {
    const section = document.createElement('section');
    section.className = 'card';
    const heading = document.createElement('h2');
    heading.textContent = title;
    const grid = document.createElement('div');
    grid.className = 'field-grid';
    for (const [key, label, type] of fields) grid.append(field(key, label, type, profile[key]));
    section.append(heading, grid);
    $('profile-fields').append(section);
  }
  for (const kind of Object.keys(core.RECORD_FIELDS)) {
    $(`${kind}-records`).replaceChildren();
    for (const record of profile[kind] || []) addRecord(kind, record);
  }
}
function readProfile() {
  const profile = {};
  for (const [, fields] of sections)
    for (const [key, , type] of fields) {
      const value = $(key).value.trim();
      profile[key] =
        type === 'boolean'
          ? value
            ? value === 'true'
            : null
          : type === 'list'
            ? value
                .split('\n')
                .map((v) => v.trim())
                .filter(Boolean)
            : value;
    }
  for (const kind of Object.keys(core.RECORD_FIELDS))
    profile[kind] = Array.from($(`${kind}-records`).children).map((card) =>
      Object.fromEntries(
        Array.from(card.querySelectorAll('[data-key]')).map((input) => [
          input.dataset.key,
          input.value.trim(),
        ]),
      ),
    );
  return core.sanitizeProfile(profile);
}
async function refresh(render = false) {
  const state = await send({ type: 'getState' });
  if (render) renderProfile(state.profile);
  $('restore').disabled = !state.hasBackup;
  $('resume-status').textContent = state.resume
    ? `${state.resume.name} · ${(state.resume.size / 1024).toFixed(0)} KiB · saved locally`
    : 'No resume selected.';
  $('remove-resume').disabled = !state.resume;
  $('connection-status').textContent = state.connection
    ? `CONNECTED · expires ${new Date(state.connection.expires_at).toLocaleDateString()}`
    : 'NOT CONNECTED';
  for (const id of ['sync', 'disconnect', 'forget', 'refresh-documents'])
    $(id).disabled = !state.connection;
}
function action(id, fn) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true;
    try {
      await fn();
    } catch (error) {
      notice(error.message, true);
    } finally {
      $(id).disabled = false;
    }
  });
}
$('profile-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await send({ type: 'saveProfile', profile: readProfile() });
    await refresh();
    notice('Profile saved locally. Open an application tab and click JobPilot Autofill.');
  } catch (error) {
    notice(error.message, true);
  }
});
for (const kind of Object.keys(core.RECORD_FIELDS))
  $(`add-${kind}`).addEventListener('click', () => addRecord(kind));
action('restore', async () => {
  if (
    !confirm('Restore the previous saved profile? Your current saved profile becomes the backup.')
  )
    return;
  await send({ type: 'restoreProfile' });
  await refresh(true);
  notice('Previous profile restored.');
});
action('export', async () => {
  const blob = new Blob(
    [JSON.stringify({ schema_version: 1, profile: readProfile() }, null, 2) + '\n'],
    { type: 'application/json' },
  );
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'jobpilot-profile.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  notice('Profile exported. Keep this file private; it contains your application details.');
});
$('import').addEventListener('change', async (event) => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) throw new Error('Profile JSON must be smaller than 1 MiB.');
    const data = JSON.parse(await file.text());
    if (data.schema_version !== undefined && data.schema_version !== 1)
      throw new Error('This profile version is not supported.');
    const profile = core.sanitizeProfile(data.profile || data);
    if (
      !confirm(
        'Replace your local profile with this JSON file? Your previous saved profile will be available through Restore previous profile.',
      )
    )
      return;
    await send({ type: 'saveProfile', profile });
    await refresh(true);
    notice('JSON profile imported and saved locally.');
  } catch (error) {
    notice(
      error instanceof SyntaxError
        ? 'This file is not valid profile JSON. Your profile is unchanged.'
        : error.message,
      true,
    );
  } finally {
    event.target.value = '';
  }
});
$('resume-file').addEventListener('change', async (event) => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > core.MAX_BYTES) throw new Error('Resume exceeds the 5 MiB limit.');
    const data = Array.from(new Uint8Array(await file.arrayBuffer()));
    const error = core.validateResume(file, data);
    if (error) throw new Error(error);
    await send({ type: 'saveResume', file: { name: file.name, data } });
    await refresh();
    notice('Resume saved locally. Attach it from the extension only when you are ready.');
  } catch (error) {
    notice(error.message, true);
  } finally {
    event.target.value = '';
  }
});
action('remove-resume', async () => {
  await send({ type: 'removeResume' });
  await refresh();
  notice('Saved resume removed.');
});
action('connect', async () => {
  await send({ type: 'connect' });
  notice('JobPilot Settings opened. Generate a connection code there, then paste it here.');
});
action('pair', async () => {
  await send({ type: 'pair', code: $('pair-code').value });
  $('pair-code').value = '';
  await refresh();
  notice('JobPilot connected. You can now import your profile or choose a prepared resume.');
});
action('sync', async () => {
  if (
    !confirm(
      'Replace your local profile with your JobPilot profile? The previous saved profile will be available through Restore previous profile.',
    )
  )
    return;
  await send({ type: 'importJobPilot', confirmed: true });
  await refresh(true);
  notice('JobPilot profile imported. Review the authorization choices before filling forms.');
});
action('disconnect', async () => {
  await send({ type: 'disconnect' });
  await refresh();
  notice('Connection revoked. Your saved local profile and resume are still available.');
});
action('forget', async () => {
  await send({ type: 'forgetConnection' });
  await refresh();
  notice('Local connection removed. To revoke its access too, open JobPilot Settings.');
});
let documents = [];
action('refresh-documents', async () => {
  const response = await send({ type: 'listDocuments' });
  documents = response.documents;
  $('documents').replaceChildren();
  const first = document.createElement('option');
  first.value = '';
  first.textContent = documents.length
    ? 'Choose a prepared resume'
    : 'No prepared resumes available';
  $('documents').append(first);
  documents.forEach((doc, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = `${doc.company || 'Application'} · ${doc.title || doc.name} · ${doc.name}`;
    $('documents').append(option);
  });
  notice(`${documents.length} prepared resumes available.`);
});
action('select-document', async () => {
  if ($('documents').value === '') throw new Error('Choose a prepared resume first.');
  const doc = documents[Number($('documents').value)];
  if (!doc) throw new Error('Load and choose a prepared resume first.');
  await send({ type: 'selectDocument', jobId: doc.job_id, kind: doc.kind });
  await refresh();
  notice('Prepared resume saved locally. Attach it from the extension when ready.');
});
refresh(true)
  .then(() =>
    notice(
      'Your profile stays in this Chrome profile. Changes are saved only when you click Save profile.',
    ),
  )
  .catch((error) => notice(error.message, true));
