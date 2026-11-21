const $ = (id) => document.getElementById(id);
let activeTabId;
async function send(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.ok)
    throw new Error(response?.error || 'The extension could not complete this action.');
  return response;
}
function renderReport(report) {
  const container = $('report');
  container.replaceChildren();
  container.hidden = false;
  for (const [key, title] of [
    ['filled', 'Updated'],
    ['preserved', 'Kept'],
    ['unanswered', 'Needs your answer'],
    ['skipped', 'Answer manually'],
  ]) {
    const rows = report[key] || [];
    const details = document.createElement('details');
    details.open = key === 'unanswered';
    const summary = document.createElement('summary');
    summary.textContent = `${title} · ${rows.length}`;
    details.append(summary);
    if (rows.length) {
      const list = document.createElement('ul');
      for (const row of rows) {
        const li = document.createElement('li');
        const label = document.createElement('strong');
        label.textContent = row.label;
        const reason = document.createElement('span');
        reason.textContent = row.reason;
        li.append(label, reason);
        list.append(li);
      }
      details.append(list);
    }
    container.append(details);
  }
}
async function run(type) {
  const buttons = [$('fill'), $('undo'), $('attach')];
  buttons.forEach((button) => (button.disabled = true));
  $('message').textContent =
    type === 'attach' ? 'Attaching your selected resume…' : 'Working on this page…';
  try {
    const { report } = await send({ type, tabId: activeTabId, replace: $('replace').checked });
    renderReport(report);
    $('message').textContent =
      type === 'undo'
        ? 'Undo finished. Later edits were kept.'
        : `${report.filled.length} updated · ${report.preserved.length} kept · ${report.unanswered.length} need your answer.`;
  } catch (error) {
    $('message').textContent = error.message;
  } finally {
    buttons.forEach((button) => (button.disabled = false));
  }
}
$('fill').addEventListener('click', () => run('fill'));
$('undo').addEventListener('click', () => run('undo'));
$('attach').addEventListener('click', () => run('attach'));
$('settings').addEventListener('click', () => chrome.runtime.openOptionsPage());
(async () => {
  try {
    activeTabId = (await chrome.tabs.query({ active: true, currentWindow: true }))[0]?.id;
    const state = await send({ type: 'getState' });
    const name =
      state.profile.name ||
      [state.profile.first_name, state.profile.last_name].filter(Boolean).join(' ');
    $('profile-summary').textContent = name
      ? `Local profile · ${name}`
      : 'Add your details in Profile & settings to get started.';
    $('resume-summary').textContent = state.resume
      ? `Selected · ${state.resume.name}`
      : 'No resume selected. Add one in settings.';
    if (state.lastReport?.tabId === activeTabId) renderReport(state.lastReport.report);
  } catch (error) {
    $('message').textContent = error.message;
  }
})();
