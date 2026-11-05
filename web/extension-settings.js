'use strict';

(() => {
  const panel = document.getElementById('extensionPanel');
  if (!panel) return;
  const $ = (id) => document.getElementById(id);
  const extensionId = $('extensionId');
  const create = $('createExtensionPairing');
  const status = $('extensionConnectionStatus');
  const list = $('extensionConnections');
  let sessionToken = '';
  let busy = false;
  let refreshing = false;
  let expiresAt = 0;
  const validId = (value) => /^[a-p]{32}$/.test(value);

  function message(value, error = false) {
    status.textContent = value;
    status.classList.toggle('inline-error', error);
  }

  async function request(path, body, retry = true) {
    if (!sessionToken) {
      const response = await fetch('/api/session', { cache: 'no-store' });
      if (!response.ok) throw new Error('Open JobPilot and try the connection again.');
      sessionToken = (await response.json()).token;
      if (!sessionToken) throw new Error('The local dashboard session is unavailable.');
    }
    const headers = { 'X-JobPilot-Token': sessionToken };
    const options = { headers, cache: 'no-store' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      options.method = 'POST';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    if ([401, 403].includes(response.status) && retry) {
      sessionToken = '';
      return request(path, body, false);
    }
    let result = {};
    try {
      result = await response.json();
    } catch (_) {
      // An unavailable service may return a non-JSON error page.
    }
    if (!response.ok) {
      if (response.status === 404)
        throw new Error('Update JobPilot to use Chrome autofill connections.');
      throw new Error(
        typeof result.detail === 'string'
          ? result.detail
          : 'The connection could not finish. Try again.',
      );
    }
    return result;
  }

  function date(value) {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleDateString() : '';
  }

  function renderConnections(pairings) {
    list.replaceChildren();
    if (!pairings.length) {
      const empty = document.createElement('p');
      empty.className = 'form-note';
      empty.textContent = 'No Chrome connections yet.';
      list.append(empty);
      return;
    }
    for (const pairing of pairings) {
      if (!pairing.pairing_id || !validId(pairing.extension_id || '')) continue;
      const row = document.createElement('div');
      row.className = 'extension-connection';
      const description = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = 'Chrome Autofill';
      const details = document.createElement('p');
      details.className = 'form-note';
      details.textContent = `Connected ${date(pairing.created_at)} · Expires ${date(pairing.expires_at)}`;
      description.append(title, details);
      const disconnect = document.createElement('button');
      disconnect.type = 'button';
      disconnect.className = 'button secondary';
      disconnect.textContent = 'Disconnect';
      disconnect.addEventListener('click', async () => {
        disconnect.disabled = true;
        try {
          await request(
            `/api/extension/pairings/${encodeURIComponent(pairing.pairing_id)}/revoke`,
            {},
          );
          await refresh();
          message('Chrome connection removed. You can connect it again at any time.');
        } catch (error) {
          message(error.message, true);
          disconnect.disabled = false;
        }
      });
      row.append(description, disconnect);
      list.append(row);
    }
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const result = await request('/api/extension/pairings');
      renderConnections(Array.isArray(result.pairings) ? result.pairings : []);
    } catch (error) {
      message(error.message, true);
    } finally {
      refreshing = false;
    }
  }

  function updateReady() {
    create.disabled = busy || !validId(extensionId.value.trim());
  }

  extensionId.addEventListener('input', updateReady);
  create.addEventListener('click', async () => {
    const id = extensionId.value.trim();
    if (!validId(id) || busy) return;
    busy = true;
    updateReady();
    try {
      const result = await request('/api/extension/pairing', { extension_id: id });
      if (typeof result.code !== 'string' || !result.code)
        throw new Error('JobPilot did not return a pairing code. Please try again.');
      $('extensionPairingCode').value = result.code;
      expiresAt = Date.parse(result.expires_at);
      $('extensionPairing').hidden = false;
      $('copyExtensionCode').disabled = false;
      $('extensionPairingHelp').textContent =
        'Paste this code into JobPilot Autofill in Chrome. It works once and expires in five minutes.';
      message('Pairing code ready. Finish connecting in Chrome.');
      await refresh();
    } catch (error) {
      message(error.message, true);
    } finally {
      busy = false;
      updateReady();
    }
  });

  $('copyExtensionCode').addEventListener('click', async () => {
    const code = $('extensionPairingCode');
    if (!code.value) return;
    try {
      await navigator.clipboard.writeText(code.value);
      message('Code copied. Paste it into Chrome Autofill.');
    } catch (_) {
      code.focus();
      code.select();
      message('The code is selected. Copy it, then paste it into Chrome Autofill.');
    }
  });
  $('refreshExtensionConnections').addEventListener('click', refresh);
  window.addEventListener('hashchange', () => {
    if (location.hash === '#settings') refresh();
  });
  document.querySelector('[data-view="settings"]')?.addEventListener('click', refresh);
  const requested = new URLSearchParams(location.search).get('extension_id');
  if (validId(requested || '')) {
    extensionId.value = requested;
    message('Ready to connect Chrome Autofill. Create a pairing code below.');
    const clean = new URL(location.href);
    clean.searchParams.delete('extension_id');
    history.replaceState(null, '', clean.pathname + clean.search + '#settings');
  }
  updateReady();
  if (location.hash === '#settings') refresh();
  setInterval(() => {
    if (location.hash === '#settings' && !document.hidden) refresh();
    if (expiresAt && Date.now() >= expiresAt) {
      expiresAt = 0;
      $('extensionPairingCode').value = '';
      $('copyExtensionCode').disabled = true;
      $('extensionPairingHelp').textContent =
        'This code expired. Create a new one to connect Chrome.';
    }
  }, 10000);
})();
