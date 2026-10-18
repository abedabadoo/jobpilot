'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    paired: false,
    cases: [],
    active: null,
    viewId: null,
    frameWidth: 0,
    frameHeight: 0,
    imageUrl: null,
    busy: false,
    loadingFrame: false,
    inputErrorSource: null,
  };
  const waiting = (item) => ['waiting', 'open', 'active'].includes(item.state);
  let foregroundSeen = new Set();
  let registration = null;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (!response.ok) {
      let message = 'JobPilot could not complete that request. Try again.';
      try {
        message = (await response.json()).detail || message;
      } catch (_) {
        /* Keep the fallback message for non-JSON responses. */
      }
      if (response.status === 401) setPaired(false);
      throw new Error(message);
    }
    return response;
  }

  function setPaired(value) {
    state.paired = value;
    $('paired-content').hidden = !value;
    $('pairing').hidden = value;
    $('logout').hidden = !value;
    if (!value) {
      state.viewId = null;
      $('connection-status').textContent = 'This device needs pairing.';
      $('connection-status').classList.remove('connected');
      clearFrame();
      $('text-input').value = '';
      $('code-input').value = '';
    }
  }

  function clearFrame() {
    $('browser-frame').hidden = true;
    $('browser-frame').removeAttribute('src');
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    state.imageUrl = null;
    state.viewId = null;
  }

  function inputError(message = '', source = 'local') {
    $('input-error').textContent = message;
    $('input-error').hidden = !message;
    state.inputErrorSource = message ? source : null;
  }

  function renderCases() {
    $('case-count').textContent = String(state.cases.filter(waiting).length);
    $('empty-cases').hidden = state.cases.length > 0;
    $('cases').replaceChildren();
    for (const item of state.cases) {
      const button = document.createElement('button');
      button.className = 'case-card' + (item.id === state.active ? ' selected' : '');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(item.id === state.active));
      const company = document.createElement('strong');
      company.textContent = item.company || 'Application';
      const title = document.createElement('span');
      title.textContent = item.title || 'Application';
      const tag = document.createElement('span');
      tag.className = 'case-tag';
      tag.textContent = waiting(item)
        ? 'Needs your help'
        : item.state === 'completed'
          ? 'Step complete'
          : String(item.state || 'Closed').replaceAll('_', ' ');
      button.append(company, title, tag);
      button.addEventListener('click', () => selectCase(item.id));
      $('cases').append(button);
    }
    const item = state.cases.find((candidate) => candidate.id === state.active);
    $('browser-panel').hidden = !item;
    $('choose-case').hidden = !!item;
    if (!item) return;
    $('case-company').textContent = item.company || 'Application';
    $('case-title').textContent = item.title || 'Application';
    $('case-state').textContent = waiting(item)
      ? 'Browser open · waiting for you'
      : item.state === 'completed'
        ? 'Step complete · worker resumed'
        : 'Session ' + String(item.state || 'closed').replaceAll('_', ' ');
    $('case-url').textContent = item.url || '';
    $('case-note').textContent = item.note || '';
    $('submitted-warning').hidden = !item.submitted;
    $('controls').hidden = !waiting(item);
    if (!waiting(item) || state.inputErrorSource !== 'local')
      inputError(item.last_error || '', 'broker');
    if (!waiting(item)) {
      clearFrame();
      $('frame-status').textContent =
        item.last_error ||
        (item.state === 'completed'
          ? 'The worker has resumed. Check JobPilot for the application result; this step alone is not a submission confirmation.'
          : 'This browser session has ended.');
    }
  }

  function selectCase(id) {
    if (id !== state.active) {
      state.active = id;
      clearFrame();
      inputError();
      $('text-input').value = '';
      $('code-input').value = '';
    }
    renderCases();
    updateFrame();
  }

  async function updateCases() {
    if (!state.paired) return;
    try {
      const data = await (await api('/api/cases')).json();
      state.cases = data.cases || [];
      const pending = state.cases.filter(waiting);
      if (!state.active && pending.length) state.active = pending[0].id;
      if (!state.cases.some((item) => item.id === state.active)) {
        state.active = null;
        clearFrame();
      }
      for (const item of pending) {
        if (
          !foregroundSeen.has(item.id) &&
          document.hidden &&
          'Notification' in window &&
          Notification.permission === 'granted'
        ) {
          const options = {
            body: 'Open JobPilot to continue an application.',
            icon: '/icons/icon-192.png',
            tag: 'jobpilot-intervention',
          };
          try {
            if (registration)
              registration.showNotification('JobPilot needs your help', options).catch(() => {});
            else new Notification('JobPilot needs your help', options);
          } catch (_) {
            /* Waiting cases remain visible if notifications fail. */
          }
        }
        foregroundSeen.add(item.id);
      }
      $('connection-status').textContent = pending.length
        ? 'Connected · ' +
          pending.length +
          (pending.length === 1 ? ' application needs' : ' applications need') +
          ' your help'
        : 'Connected · no steps waiting';
      $('connection-status').classList.add('connected');
      renderCases();
    } catch (error) {
      if (state.paired)
        $('connection-status').textContent = 'Connection interrupted. Reconnecting…';
    }
  }

  async function updateFrame() {
    const item = state.cases.find((candidate) => candidate.id === state.active);
    if (!state.paired || !item || !waiting(item) || state.loadingFrame || document.hidden) return;
    state.loadingFrame = true;
    const selectedId = item.id;
    try {
      const response = await api('/api/cases/' + encodeURIComponent(selectedId) + '/frame');
      const viewId = response.headers.get('X-View-Id');
      const width = Number(response.headers.get('X-Browser-Width'));
      const height = Number(response.headers.get('X-Browser-Height'));
      const blob = await response.blob();
      if (state.active !== selectedId || !state.paired) return;
      if (!viewId || width <= 0 || height <= 0) throw new Error('The browser view is not ready.');
      const nextUrl = URL.createObjectURL(blob);
      const image = new Image();
      image.src = nextUrl;
      try {
        await image.decode();
      } catch (_) {
        URL.revokeObjectURL(nextUrl);
        throw new Error('The browser view is not ready.');
      }
      if (state.active !== selectedId || !state.paired) {
        URL.revokeObjectURL(nextUrl);
        return;
      }
      const previous = state.imageUrl;
      state.imageUrl = nextUrl;
      state.viewId = viewId;
      state.frameWidth = width;
      state.frameHeight = height;
      $('browser-frame').src = nextUrl;
      $('browser-frame').hidden = false;
      if (previous) URL.revokeObjectURL(previous);
      $('frame-status').textContent = 'Live browser view';
    } catch (error) {
      if (state.active === selectedId) {
        state.viewId = null;
        $('frame-status').textContent = error.message;
      }
    } finally {
      state.loadingFrame = false;
    }
  }

  async function command(kind, payload = {}) {
    if (state.busy) return;
    if (!state.viewId || !state.active) {
      inputError('Wait for the browser view to load before using its controls.');
      return;
    }
    state.busy = true;
    inputError();
    const caseId = state.active;
    try {
      const result = await (
        await api('/api/cases/' + encodeURIComponent(caseId) + '/input', {
          method: 'POST',
          body: JSON.stringify({ kind, view_id: state.viewId, ...payload }),
        })
      ).json();
      if (result && result.ok === false)
        throw new Error(result.error || 'The browser could not use that control.');
      if (kind === 'resume')
        $('frame-status').textContent = 'Checking whether the application can continue…';
      if (kind === 'cancel') $('frame-status').textContent = 'Closing this browser session…';
    } catch (error) {
      inputError(error.message);
    } finally {
      state.busy = false;
      await updateCases();
      await updateFrame();
    }
  }

  let pointerStart = null;
  $('browser-frame').addEventListener('pointerdown', (event) => {
    pointerStart = { x: event.clientX, y: event.clientY };
  });
  $('browser-frame').addEventListener('pointercancel', () => {
    pointerStart = null;
  });
  $('browser-frame').addEventListener('pointerup', (event) => {
    if (
      !pointerStart ||
      Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 10
    ) {
      pointerStart = null;
      return;
    }
    pointerStart = null;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(
      0,
      Math.min(state.frameWidth - 1, ((event.clientX - rect.left) * state.frameWidth) / rect.width),
    );
    const y = Math.max(
      0,
      Math.min(
        state.frameHeight - 1,
        ((event.clientY - rect.top) * state.frameHeight) / rect.height,
      ),
    );
    command('click', { x: Math.round(x), y: Math.round(y) });
  });
  document
    .querySelectorAll('[data-key]')
    .forEach((button) =>
      button.addEventListener('click', () => command('key', { key: button.dataset.key })),
    );
  document
    .querySelectorAll('[data-scroll]')
    .forEach((button) =>
      button.addEventListener('click', () =>
        command('scroll', { delta_y: Number(button.dataset.scroll) }),
      ),
    );
  $('text-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const text = $('text-input').value;
    $('text-input').value = '';
    if (text) command('text', { text });
  });
  $('code-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const code = $('code-input').value;
    $('code-input').value = '';
    if (code) command('code', { code });
  });
  $('resume').addEventListener('click', () => command('resume'));
  $('cancel').addEventListener('click', () => command('cancel'));
  $('refresh').addEventListener('click', () => updateFrame());
  $('logout').addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST' });
      setPaired(false);
    } catch (error) {
      inputError(error.message);
    }
  });

  function vapidBytes(value) {
    const padding = '='.repeat((4 - (value.length % 4)) % 4);
    const raw = atob((value + padding).replaceAll('-', '+').replaceAll('_', '/'));
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  }

  async function pushState() {
    if (
      !('serviceWorker' in navigator) ||
      !('PushManager' in window) ||
      !('Notification' in window)
    ) {
      $('push-status').textContent =
        'This browser can show waiting steps while JobPilot is open. For background alerts, use a browser that supports notifications.';
      $('enable-push').hidden = true;
      return;
    }
    try {
      registration = await navigator.serviceWorker.register('/sw.js');
      const subscription = await registration.pushManager.getSubscription();
      const enabled = !!subscription && Notification.permission === 'granted';
      if (enabled)
        await api('/api/push/subscribe', {
          method: 'POST',
          body: JSON.stringify(subscription.toJSON()),
        });
      $('push-status').textContent = enabled
        ? 'This device has a notification subscription. Send a test to check delivery.'
        : Notification.permission === 'denied'
          ? 'Notifications are blocked in this browser’s settings. You can still finish steps while this page is open.'
          : 'Notifications are off. Enable them here when you are ready.';
      $('enable-push').hidden = enabled || Notification.permission === 'denied';
      $('test-push').hidden = !enabled;
      $('disable-push').hidden = !subscription;
    } catch (_) {
      $('push-status').textContent =
        'Background notifications are unavailable. Keep this page open to see waiting applications.';
      $('test-push').hidden = true;
      $('disable-push').hidden = false;
    }
  }

  $('enable-push').addEventListener('click', async () => {
    try {
      if (!registration) await pushState();
      if (!registration)
        throw new Error('Open JobPilot in a supported browser to enable notifications.');
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        await pushState();
        return;
      }
      const { public_key: publicKey } = await (await api('/api/push/key')).json();
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription)
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: vapidBytes(publicKey),
        });
      await api('/api/push/subscribe', {
        method: 'POST',
        body: JSON.stringify(subscription.toJSON()),
      });
      await pushState();
    } catch (error) {
      $('push-status').textContent = error.message;
    }
  });
  $('test-push').addEventListener('click', async () => {
    try {
      await api('/api/push/test', { method: 'POST' });
      $('push-status').textContent = 'Test requested. Check your notifications.';
    } catch (error) {
      $('push-status').textContent = error.message;
    }
  });
  $('disable-push').addEventListener('click', async () => {
    try {
      await api('/api/push/unsubscribe', { method: 'POST' });
      const subscription = registration && (await registration.pushManager.getSubscription());
      if (subscription) await subscription.unsubscribe();
      await pushState();
    } catch (error) {
      $('push-status').textContent = error.message;
    }
  });

  async function caseLoop() {
    if (state.paired) await updateCases();
    setTimeout(caseLoop, 3000);
  }
  async function frameLoop() {
    await updateFrame();
    setTimeout(frameLoop, 1000);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.paired) {
      updateCases();
      updateFrame();
    }
  });
  async function activatePaired() {
    await api('/api/cases');
    setPaired(true);
    await updateCases();
    await updateFrame();
    await pushState();
  }

  function pairingValue(value) {
    const validSecret = (candidate) => /^[A-Za-z0-9_-]{32,256}$/.test(candidate || '');
    if (validSecret(value)) return value;
    let link;
    try {
      link = new URL(value);
    } catch (_) {
      throw new Error('Paste the private pairing link or code shown in JobPilot.');
    }
    if (link.origin !== location.origin || link.username || link.password)
      throw new Error('Use the pairing link for this JobPilot page.');
    const secret = new URLSearchParams(link.hash.slice(1)).get('pair');
    if (!validSecret(secret))
      throw new Error(
        'This link does not contain a valid pairing code. Open a new link from JobPilot.',
      );
    return secret;
  }

  $('manual-pair-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    let value = $('manual-pair-input').value.trim();
    $('manual-pair-input').value = '';
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    $('pairing-error').textContent = '';
    let secret = null;
    try {
      secret = pairingValue(value);
      value = null;
      await api('/api/pair', { method: 'POST', body: JSON.stringify({ secret }) });
      secret = null;
      await activatePaired();
    } catch (error) {
      $('pairing-error').textContent = error.message;
    } finally {
      value = null;
      secret = null;
      button.disabled = false;
    }
  });

  async function boot() {
    let secret = new URLSearchParams(location.hash.slice(1)).get('pair');
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    try {
      if (secret) await api('/api/pair', { method: 'POST', body: JSON.stringify({ secret }) });
      secret = null;
      await activatePaired();
    } catch (error) {
      setPaired(false);
      $('pairing-error').textContent = error.message;
    } finally {
      secret = null;
    }
    caseLoop();
    frameLoop();
  }
  boot();
})();
