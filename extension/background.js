importScripts('core.js');
const core = self.JobPilotCore;
const API = 'http://127.0.0.1:8765';
// storage.local normally includes content scripts. Restrict it before serving any
// request: profile, resume bytes and pairing credentials stay in trusted contexts.
const ready = chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
const get = async (key) => (await chrome.storage.local.get(key))[key];
function encode(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 16384)
    binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(binary);
}
function decode(base64) {
  return Array.from(atob(base64), (character) => character.charCodeAt(0));
}
async function request(path, { method = 'GET', body, paired = true, binary = false } = {}) {
  if (!/^\/api\/extension\//.test(path) || path.includes('..'))
    throw new Error('Unsupported local API route.');
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (paired) {
    const connection = await get('connection');
    if (!connection?.token)
      throw new Error(
        'Connect JobPilot in Profile & settings first. Your local profile still works offline.',
      );
    headers.Authorization = `Bearer ${connection.token}`;
  }
  let response;
  try {
    response = await fetch(API + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error(
      'JobPilot is unavailable. Start the local app and try again. Your saved profile is unchanged.',
    );
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403)
      throw new Error('Connection was rejected or expired. Connect again in Profile & settings.');
    if (response.status === 413) throw new Error('Resume exceeds the 5 MiB limit.');
    throw new Error(
      'JobPilot could not complete this request. Check the pairing code or try again.',
    );
  }
  if (binary) {
    const length = Number(response.headers.get('Content-Length'));
    if (length > core.MAX_BYTES) throw new Error('Resume exceeds the 5 MiB limit.');
    // Stop a chunked response at the size limit instead of buffering arbitrary data.
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > core.MAX_BYTES) {
        await reader.cancel();
        throw new Error('Resume exceeds the 5 MiB limit.');
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return bytes;
  }
  try {
    return await response.json();
  } catch {
    throw new Error('JobPilot returned an unreadable response. Your local profile is unchanged.');
  }
}
async function saveProfile(input) {
  const profile = core.sanitizeProfile(input);
  const previous = await get('profile');
  await chrome.storage.local.set({ profile, ...(previous ? { profileBackup: previous } : {}) });
}
async function saveResume(file) {
  if (!file || !Array.isArray(file.data)) throw new Error('Choose a local PDF or DOCX resume.');
  if (file.data.length > core.MAX_BYTES) throw new Error('Resume exceeds the 5 MiB limit.');
  const bytes = new Uint8Array(file.data);
  const error = core.validateResume({ name: file.name, size: bytes.length }, bytes);
  if (error) throw new Error(error);
  const name = String(file.name).split(/[\\/]/).at(-1).slice(0, 180);
  await chrome.storage.local.set({ resume: { name, size: bytes.length, base64: encode(bytes) } });
  return { name, size: bytes.length };
}
async function onPage(message) {
  const tab = Number.isInteger(message.tabId)
    ? await chrome.tabs.get(message.tabId)
    : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  if (!tab?.id || !/^https?:\/\//i.test(tab.url || ''))
    throw new Error(
      'Open an application website, then click the JobPilot extension icon on that tab. Chrome internal pages cannot be filled.',
    );
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['core.js', 'content.js'],
    });
    let payload = null;
    if (message.type === 'fill') payload = core.sanitizeProfile((await get('profile')) || {});
    if (message.type === 'attach') {
      const resume = await get('resume');
      if (!resume?.base64) throw new Error('Select a resume in Profile & settings first.');
      payload = { name: resume.name, data: decode(resume.base64) };
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: async (action, data, replace) => {
        if (action === 'undo') return globalThis.JobPilotAutofill.undo();
        if (action === 'attach') return globalThis.JobPilotAutofill.attach(data, replace);
        return globalThis.JobPilotAutofill.fill(data, replace);
      },
      args: [message.type, payload, message.replace === true],
    });
    const report = results[0]?.result;
    if (!report) throw new Error('No form result. Reload the application and try again.');
    await chrome.storage.local.set({ lastReport: { tabId: tab.id, report, time: Date.now() } });
    return { report };
  } catch (error) {
    // Chrome's injection failures can contain the page URL. Keep diagnostics local
    // and simple; do not echo arbitrary page text or credentials.
    if (
      /Cannot access|Missing host permission|cannot be scripted|extensions gallery|No tab with id/i.test(
        error.message,
      )
    )
      throw new Error(
        'Chrome cannot access this page. Click the extension icon on the application tab, or fill this form manually.',
      );
    throw error;
  }
}
async function handle(message) {
  await ready;
  switch (message.type) {
    case 'getState': {
      const values = await chrome.storage.local.get([
        'profile',
        'profileBackup',
        'resume',
        'connection',
        'lastReport',
      ]);
      return {
        profile: core.sanitizeProfile(values.profile || {}),
        hasBackup: !!values.profileBackup,
        resume: values.resume ? { name: values.resume.name, size: values.resume.size } : null,
        connection: values.connection
          ? { pairing_id: values.connection.pairing_id, expires_at: values.connection.expires_at }
          : null,
        lastReport: values.lastReport,
      };
    }
    case 'saveProfile':
      await saveProfile(message.profile);
      return {};
    case 'restoreProfile': {
      const backup = await get('profileBackup');
      if (!backup) throw new Error('No previous profile is saved.');
      await saveProfile(backup);
      return {};
    }
    case 'saveResume':
      return { resume: await saveResume(message.file) };
    case 'removeResume':
      await chrome.storage.local.remove('resume');
      return {};
    case 'connect':
      await chrome.tabs.create({ url: `${API}/?extension_id=${chrome.runtime.id}#settings` });
      return {};
    case 'pair': {
      const code = String(message.code || '').trim();
      if (!code || code.length > 200)
        throw new Error('Paste the five-minute code from JobPilot Settings.');
      const connection = await request('/api/extension/pair', {
        method: 'POST',
        body: { code },
        paired: false,
      });
      if (
        typeof connection.token !== 'string' ||
        connection.token.length < 16 ||
        typeof connection.pairing_id !== 'string' ||
        typeof connection.expires_at !== 'string'
      )
        throw new Error('Invalid pairing response. Try again.');
      await chrome.storage.local.set({
        connection: {
          token: connection.token,
          pairing_id: connection.pairing_id,
          expires_at: connection.expires_at,
        },
      });
      return {};
    }
    case 'importJobPilot': {
      if (message.confirmed !== true) throw new Error('Confirm profile replacement first.');
      const data = await request('/api/extension/profile', { method: 'POST' });
      if (
        data.schema_version !== 1 ||
        !data.profile ||
        typeof data.profile !== 'object' ||
        Array.isArray(data.profile)
      )
        throw new Error('Unsupported JobPilot profile. Your local profile is unchanged.');
      await saveProfile(data.profile);
      return {};
    }
    case 'listDocuments': {
      const data = await request('/api/extension/documents', { method: 'POST' });
      const documents = (Array.isArray(data.documents) ? data.documents : [])
        .filter(
          (doc) =>
            ['resume_pdf', 'resume_docx'].includes(doc.kind) &&
            Number.isInteger(doc.job_id) &&
            typeof doc.name === 'string',
        )
        .map((doc) => ({
          job_id: doc.job_id,
          title: String(doc.title || ''),
          company: String(doc.company || ''),
          kind: doc.kind,
          name: doc.name,
        }));
      return { documents };
    }
    case 'selectDocument': {
      const jobId = Number(message.jobId);
      if (
        !Number.isSafeInteger(jobId) ||
        jobId < 1 ||
        !['resume_pdf', 'resume_docx'].includes(message.kind)
      )
        throw new Error('Choose a prepared resume from JobPilot.');
      // Re-read metadata and construct a fixed route; never follow download URLs supplied by page scripts.
      const data = await request('/api/extension/documents', { method: 'POST' });
      const doc = data.documents?.find((doc) => doc.job_id === jobId && doc.kind === message.kind);
      if (!doc) throw new Error('This prepared resume is no longer available. Refresh the list.');
      const bytes = await request(`/api/extension/documents/${jobId}/${message.kind}`, {
        method: 'POST',
        binary: true,
      });
      return { resume: await saveResume({ name: doc.name, data: Array.from(bytes) }) };
    }
    case 'disconnect': {
      await request('/api/extension/disconnect', { method: 'POST' });
      await chrome.storage.local.remove('connection');
      return {};
    }
    case 'forgetConnection':
      await chrome.storage.local.remove('connection');
      return {};
    case 'fill':
    case 'undo':
    case 'attach':
      return onPage(message);
    default:
      throw new Error('Unsupported extension action.');
  }
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const extensionOrigin = `chrome-extension://${chrome.runtime.id}/`;
  if (
    sender.id !== chrome.runtime.id ||
    !sender.url?.startsWith(extensionOrigin) ||
    !message ||
    typeof message !== 'object'
  )
    return false;
  handle(message)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) =>
      sendResponse({
        ok: false,
        error:
          error instanceof Error
            ? error.message
            : 'The action failed. Your saved profile is unchanged.',
      }),
    );
  return true;
});
