'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const icons = {
    dashboard:
      '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
    file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    link: '<path d="m10 13 4-4m-5 6-2 2a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m2 1 2-2a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0"/>',
    settings:
      '<path d="m10 3-.5 3-2 1-2.5-1.2L3 9l2.3 1.8v2.4L3 15l2 3.2L7.5 17l2 1 .5 3h4l.5-3 2-1 2.5 1.2 2-3.2-2.3-1.8v-2.4L21 9l-2-3.2L16.5 7l-2-1-.5-3z"/><circle cx="12" cy="12" r="3"/>',
    shield: '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><path d="M12 14v3"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    alert:
      '<path d="m10 4-8 14a2 2 0 0 0 2 3h16a2 2 0 0 0 2-3L14 4a2.3 2.3 0 0 0-4 0zM12 9v5M12 17h.01"/>',
    chart: '<path d="M4 3v17h17M8 15l4-5 4 2 5-7"/>',
    send: '<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
    briefcase:
      '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a20 20 0 0 0 18 0M12 12v3"/>',
    pulse: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    pause: '<path d="M8 5v14M16 5v14" stroke-width="3"/>',
    play: '<path d="m8 4 12 8-12 8z"/>',
    stop: '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2.8 2.8 0 0 0-4-4L5 15z"/>',
    external:
      '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    building: '<path d="M4 21V5l8-3v19M12 9h8v12M8 7v1M8 11v1M8 15v1M16 13v1M16 17v1M2 21h20"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2zM7 3v6h10V3M7 21v-8h10v8"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    location:
      '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0z"/><circle cx="12" cy="10" r="2.5"/>',
    refresh: '<path d="M20 7V3l-3 3a8 8 0 0 0-13 6M4 17v4l3-3a8 8 0 0 0 13-6M16 7h4M4 17h4"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  };
  function icon(name) {
    const span = document.createElement('span');
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = `<svg viewBox="0 0 24 24">${icons[name] || icons.info}</svg>`;
    return span;
  }
  function hydrateIcons(root = document) {
    root.querySelectorAll('[data-icon]').forEach((el) => el.replaceChildren(icon(el.dataset.icon)));
  }
  function el(tag, className = '', value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }
  function button(label, className, iconName, action) {
    const node = el('button', `button ${className}`);
    node.type = 'button';
    if (iconName) node.append(icon(iconName));
    node.append(el('span', '', label));
    if (action) node.addEventListener('click', action);
    return node;
  }
  function text(value, fallback = '—') {
    if (value === null || value === undefined || value === '') return fallback;
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }
  function safeURL(value) {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  }
  function prettyDate(value, includeTime = false) {
    if (!value) return 'Never';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(
      undefined,
      includeTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' },
    ).format(date);
  }
  function relative(value) {
    if (!value) return 'Never';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value);
    const seconds = Math.round((Date.now() - date.getTime()) / 1000);
    if (seconds < 0) return prettyDate(value, true);
    if (seconds < 10) return 'Just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
  const labels = [
    'Posted today',
    'Previous 24 hours',
    'Previous 3 days',
    'Previous 7 days',
    'Older than 7 days',
    'Date unknown',
  ];
  const viewLabels = {
    overview: 'Overview',
    profile: 'Profile & experience',
    answers: 'Application answers',
    connections: 'Connections',
    settings: 'Preferences',
  };
  const commonAnswerSchema = [
    {
      key: '@work_authorized_us',
      label: 'Are you legally authorized to work in the United States?',
      type: 'choice',
      help: 'For roles based in the United States. Your authorization is never inferred.',
    },
    {
      key: '@requires_sponsorship_us',
      label:
        'Will you now or in the future require employer sponsorship to work in the United States?',
      type: 'choice',
      help: 'This combines current and future sponsorship requirements.',
    },
    {
      key: '@available_cities',
      label: 'Which cities are you available to work in?',
      type: 'text',
      help: 'List the cities you personally confirm, separated by semicolons; for example, Chicago, Illinois; Madison, Wisconsin.',
    },
    {
      key: '@fluent_languages',
      label: 'Which languages do you speak fluently?',
      type: 'text',
      help: 'List only languages you speak fluently, separated by commas.',
    },
    {
      key: '@recruitment_privacy_consent',
      label:
        'Do you consent to processing your application under the employer’s recruitment privacy policy?',
      type: 'choice',
      help: 'Read the employer’s policy before answering. Leave this unknown if you have not reviewed it.',
    },
    {
      key: '@application_accuracy_attestation',
      label: 'Do you certify that the information in your application is true and correct?',
      type: 'choice',
      help: 'Confirm only after reviewing your career facts and application. Different employer statements may still require review.',
    },
  ];
  let state = null,
    token = '',
    activeView = 'overview',
    activeFilter = 'all',
    selectedJob = null;
  let settingsDirty = false,
    emailDirty = false,
    polling = false,
    connected = false,
    toastTimer,
    diagnosticsSignature = '';
  const loginResults = {};

  async function session() {
    const response = await fetch('/api/session', { cache: 'no-store' });
    if (!response.ok) throw new Error('Could not establish a local dashboard session.');
    const result = await response.json();
    token = result.token;
    if (!token) throw new Error('The local service did not return a session token.');
  }
  async function api(path, payload, retry = true) {
    if (!token) await session();
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-JobPilot-Token': token },
      body: JSON.stringify(payload || {}),
    });
    if ((response.status === 401 || response.status === 403) && retry) {
      token = '';
      await session();
      return api(path, payload, false);
    }
    let result;
    try {
      result = await response.json();
    } catch (_) {
      result = {};
    }
    if (!response.ok)
      throw new Error(
        text(
          result.detail || result.message,
          `The local service returned HTTP ${response.status}.`,
        ),
      );
    return result;
  }
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $('toast').textContent = message;
    $('toast').classList.toggle('error', error);
    $('toast').hidden = false;
    toastTimer = setTimeout(
      () => {
        $('toast').hidden = true;
      },
      error ? 10000 : 6000,
    );
  }
  function resultMessage(result, fallback) {
    return typeof result?.message === 'string'
      ? result.message
      : typeof result?.note === 'string'
        ? result.note
        : fallback;
  }
  async function action(node, path, payload, success, close = false) {
    if (node) node.disabled = true;
    try {
      const result = await api(path, payload);
      if (close) closeModal();
      toast(resultMessage(result, success));
      await poll();
      return result;
    } catch (error) {
      if ($('modal').open) dialogError(error);
      else toast(error.message, true);
      return null;
    } finally {
      if (node) node.disabled = false;
    }
  }
  function statusGroup(job) {
    const status = String(job.status || '')
      .toLowerCase()
      .replaceAll('_', ' ');
    if (status === 'manually verified') return 'manual';
    if (['applying', 'submitting', 'preparing'].includes(status)) return 'active';
    if (status.includes('confirm') || status === 'submitted' || status === 'success')
      return 'confirmed';
    if (status.includes('review') || status.includes('uncertain') || status.includes('blocked'))
      return 'review';
    if (status.includes('error') || status.includes('fail')) return 'error';
    if (status.includes('skip') || status.includes('reject')) return 'skipped';
    return 'queued';
  }
  function statusLabel(job) {
    const value = String(job.status || 'Queued').replaceAll('_', ' ');
    return value.charAt(0).toUpperCase() + value.slice(1);
  }
  function bucket(job) {
    if (typeof job.bucket === 'number' && job.bucket >= 0 && job.bucket <= 5) return job.bucket;
    if (typeof job.bucket === 'string' && /^\d$/.test(job.bucket))
      return Math.min(5, Number(job.bucket));
    if (job.bucket_label) {
      const index = labels.findIndex(
        (label) => label.toLowerCase() === String(job.bucket_label).toLowerCase(),
      );
      if (index >= 0) return index;
    }
    const date = new Date(job.posted_at || 'invalid');
    const age = Date.now() - date.getTime();
    if (!Number.isFinite(age) || age < 0) return 5;
    const day = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    if (day.format(date) === day.format(new Date())) return 0;
    if (age <= 86400000) return 1;
    if (age <= 3 * 86400000) return 2;
    if (age <= 7 * 86400000) return 3;
    return 4;
  }
  function fitNumber(job) {
    const value = Number(job.fit);
    return job.fit === null || job.fit === undefined || !Number.isFinite(value)
      ? null
      : Math.max(0, Math.min(100, value));
  }
  function sortedJobs(jobs) {
    return [...jobs].sort(
      (a, b) =>
        bucket(a) - bucket(b) ||
        (fitNumber(b) || 0) - (fitNumber(a) || 0) ||
        (Date.parse(b.posted_at) || 0) - (Date.parse(a.posted_at) || 0),
    );
  }
  function badge(job) {
    return el('span', `status-badge ${statusGroup(job)}`, statusLabel(job));
  }
  function number(value) {
    return value === null || value === undefined ? '—' : new Intl.NumberFormat().format(value);
  }
  function renderMetrics() {
    const metrics = state.metrics || {};
    $('metricConfirmed').textContent = number(metrics.confirmed);
    $('metricErrors').textContent = number(metrics.errors);
    const rate = metrics.success_rate;
    $('metricRate').textContent =
      rate === null || rate === undefined ? 'N/A' : `${Math.round(Number(rate))}%`;
    $('metricToday').textContent = number(metrics.applied_today);
    $('metricTodayFoot').textContent =
      `${prettyDate(new Date().toISOString())} · confirmed receipts`;
    $('countAll').textContent = state.jobs.length;
    $('countQueued').textContent = number(
      metrics.queued ?? state.jobs.filter((job) => statusGroup(job) === 'queued').length,
    );
    $('countReview').textContent = number(
      metrics.review ?? state.jobs.filter((job) => statusGroup(job) === 'review').length,
    );
    $('countConfirmed').textContent = number(
      metrics.confirmed ?? state.jobs.filter((job) => statusGroup(job) === 'confirmed').length,
    );
    const reviewCount = state.jobs.filter(
      (job) => statusGroup(job) === 'review' && classifyBlocker(job) === 'unanswered',
    ).length;
    $('answersNavCount').textContent = reviewCount;
    $('answersNavCount').title = `${reviewCount} opportunities have unanswered required fields`;
    $('answersNavCount').hidden = !reviewCount;
  }
  function updateOptions(select, values, label) {
    const current = select.value;
    const allValues = ['all', ...values];
    if (
      Array.from(select.options)
        .map((item) => item.value)
        .join('\n') === allValues.join('\n')
    )
      return;
    select.replaceChildren();
    const all = el('option', '', label);
    all.value = 'all';
    select.append(all);
    values.forEach((value) => {
      const option = el('option', '', value);
      option.value = value;
      select.append(option);
    });
    select.value = allValues.includes(current) ? current : 'all';
  }
  function renderJobs() {
    if (!state) return;
    updateOptions(
      $('sourceFilter'),
      [...new Set(state.jobs.map((job) => String(job.source || 'Unknown source')))].sort(),
      'All sources',
    );
    updateOptions(
      $('statusFilter'),
      [...new Set(state.jobs.map((job) => statusLabel(job)))].sort(),
      'All statuses',
    );
    const query = $('jobQuery').value.toLowerCase().trim();
    const source = $('sourceFilter').value,
      status = $('statusFilter').value;
    const jobs = sortedJobs(
      state.jobs.filter(
        (job) =>
          (activeFilter === 'all' || statusGroup(job) === activeFilter) &&
          (source === 'all' || String(job.source || 'Unknown source') === source) &&
          (status === 'all' || statusLabel(job) === status) &&
          `${job.title || ''} ${job.company || ''}`.toLowerCase().includes(query),
      ),
    );
    const focusedJob = document.activeElement?.closest?.('tr[data-job-id]')?.dataset.jobId;
    const fragment = document.createDocumentFragment();
    jobs.forEach((job) => {
      const tr = el('tr');
      tr.dataset.jobId = String(job.id);
      tr.tabIndex = 0;
      tr.setAttribute(
        'aria-label',
        `View ${job.title || 'opportunity'} at ${job.company || 'company'}, ${statusLabel(job)}`,
      );
      tr.addEventListener('click', () => showJob(job.id));
      tr.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          showJob(job.id);
        }
      });
      const first = el('td'),
        cell = el('div', 'job-cell');
      const company = String(job.company || '?');
      let hash = 0;
      for (let i = 0; i < company.length; i++) hash += company.charCodeAt(i);
      cell.append(el('div', `company-avatar tone-${hash % 4}`, company.slice(0, 1).toUpperCase()));
      const title = el('div');
      title.append(el('div', 'job-title', text(job.title, 'Untitled opportunity')));
      const subtitle = el('div', 'job-sub');
      subtitle.append(
        document.createTextNode(`${company} · `),
        el('span', 'source', text(job.source, 'Unknown source')),
      );
      title.append(subtitle);
      cell.append(title);
      first.append(cell);
      const fresh = el('td');
      fresh.append(
        el(
          'span',
          `freshness ${bucket(job) <= 1 ? 'fresh' : ''}`,
          job.bucket_label || labels[bucket(job)],
        ),
      );
      fresh.title = job.posted_at ? prettyDate(job.posted_at, true) : 'No posting date supplied';
      const fit = el('td'),
        fitContent = el('div', 'fit-cell'),
        score = fitNumber(job);
      const bar = el('span', 'fit-bar'),
        fill = el('i');
      fill.style.width = `${score || 0}%`;
      bar.append(fill);
      fitContent.append(
        bar,
        document.createTextNode(score === null ? '—' : `${Math.round(score)}%`),
      );
      fit.append(fitContent);
      const statusCell = el('td');
      statusCell.append(badge(job));
      const arrow = el('td', 'row-arrow');
      arrow.append(icon('chevron'));
      tr.append(first, fresh, fit, statusCell, arrow);
      fragment.append(tr);
    });
    $('jobsBody').replaceChildren(fragment);
    if (focusedJob) {
      const row = Array.from($('jobsBody').rows).find((item) => item.dataset.jobId === focusedJob);
      if (row) row.focus({ preventScroll: true });
    }
    $('queueEmpty').hidden = jobs.length > 0;
    if (!jobs.length && state.jobs.length) {
      $('queueEmpty').className = 'filter-empty';
      $('queueEmpty').replaceChildren(
        el('p', '', 'No opportunities match these filters.'),
        button('Clear filters', 'secondary', 'refresh', clearFilters),
      );
      $('queueEmpty').lastChild.style.marginTop = '16px';
    } else if (!jobs.length && !state.jobs.length && !$('queueEmpty').querySelector('.empty-art')) {
      $('queueEmpty').className = 'empty-state';
      const art = el('div', 'empty-art');
      art.append(icon('briefcase'), el('span', 'empty-art-spark'));
      $('queueEmpty').replaceChildren(
        art,
        el('h3', '', 'No jobs in the pipeline'),
        el(
          'p',
          '',
          'Add a job link, import an email alert, or run a search. New listings appear here.',
        ),
        button('Add your first opportunity', 'secondary', 'plus', showImport),
      );
    }
    $('visibleCount').textContent =
      `${jobs.length} of ${state.jobs.length} ${state.jobs.length === 1 ? 'opportunity' : 'opportunities'}`;
  }
  function clearFilters() {
    activeFilter = 'all';
    $('jobQuery').value = '';
    $('sourceFilter').value = 'all';
    $('statusFilter').value = 'all';
    updateTabs();
    renderJobs();
  }
  function updateTabs() {
    document.querySelectorAll('[data-filter]').forEach((node) => {
      const active = node.dataset.filter === activeFilter;
      node.classList.toggle('active', active);
      node.setAttribute('aria-selected', String(active));
    });
  }
  function renderWorker() {
    const worker = state.worker || {},
      settings = state.settings || {};
    const reviewing = (state.jobs || []).some((job) =>
      ['opening', 'opened'].includes(job.review_session?.state),
    );
    const heartbeatAge = worker.heartbeat ? Date.now() - Date.parse(worker.heartbeat) : null;
    const remoteWaiting = Number(state.remote_access?.waiting || 0) > 0;
    let workerState = remoteWaiting
      ? 'Waiting for your help'
      : reviewing
        ? 'Verification open'
        : worker.submitting
          ? 'Applying'
          : worker.searching
            ? 'Searching'
            : settings.search_enabled || settings.submission_enabled
              ? 'Idle'
              : 'Paused';
    if (heartbeatAge !== null && Number.isFinite(heartbeatAge) && heartbeatAge > 90000)
      workerState = 'Heartbeat delayed';
    $('workerState').textContent = workerState;
    $('workerDot').className =
      `dot ${workerState === 'Paused' || workerState.includes('delayed') ? 'amber' : 'teal'}`;
    $('workerBadge').textContent = worker.searching || worker.submitting ? 'ACTIVE' : 'LOCAL';
    $('workerCurrent').textContent = remoteWaiting
      ? 'Open Remote access to finish sign-in or verification in the retained browser, then resume the application. Enabled searches continue.'
      : reviewing
        ? 'Finish or close the verification browser to continue the submission queue. Enabled searches continue.'
        : text(
            worker.current,
            settings.search_enabled || settings.submission_enabled
              ? 'Worker enabled. Submission readiness is shown separately above the pipeline.'
              : 'Search and submissions are paused.',
          );
    $('heartbeat').textContent = relative(worker.heartbeat);
    $('lastSearch').textContent = relative(worker.last_search);
    $('heartbeat').title = prettyDate(worker.heartbeat, true);
    $('lastSearch').title = prettyDate(worker.last_search, true);
    $('workerQueued').textContent = number(state.metrics?.queued);
    const queued = sortedJobs(state.jobs.filter((job) => statusGroup(job) === 'queued'));
    $('nextJob').textContent = text(queued[0]?.title, 'No queued opportunities');
    $('nextJob').title = text(queued[0]?.title, 'No queued opportunities');
    const searchLabel = settings.search_enabled ? 'Pause search' : 'Resume search';
    const submissionLabel = settings.submission_enabled
      ? 'Pause submissions'
      : 'Resume submissions';
    $('toggleSearch').replaceChildren(
      icon(settings.search_enabled ? 'pause' : 'play'),
      el('span', '', searchLabel),
    );
    $('toggleSubmissions').replaceChildren(
      icon(settings.submission_enabled ? 'pause' : 'play'),
      el('span', '', submissionLabel),
    );
    const running = settings.search_enabled || settings.submission_enabled;
    $('toggleWorker').replaceChildren(
      icon(running ? 'stop' : 'play'),
      el('span', '', running ? 'Stop worker' : 'Start worker'),
    );
    $('workerError').textContent = text(worker.last_error, '');
    $('workerError').hidden = !worker.last_error;
    let extra = $('workerExtra');
    if (!extra) {
      extra = el('div', 'worker-extended');
      extra.id = 'workerExtra';
      $('workerError').before(extra);
    }
    extra.replaceChildren();
    [
      ['Local model', worker.model_status],
      ['Email alerts', worker.email_status],
      ['Keep awake', worker.keep_awake === true ? 'Active on AC power' : 'Inactive'],
    ].forEach(([label, value]) => {
      if (value === undefined || value === null) return;
      const row = el('div');
      row.append(el('span', '', label), el('strong', '', text(value)));
      extra.append(row);
    });
    ['searchNow', 'toggleSearch', 'toggleSubmissions', 'toggleWorker'].forEach((id) => {
      $(id).disabled = !connected;
    });
    const fragment = document.createDocumentFragment();
    labels.forEach((label, index) => {
      const row = el('div', 'freshness-row');
      row.append(
        el('span', 'freshness-rank', index + 1),
        el('span', 'freshness-label', label),
        el('span', 'freshness-count', queued.filter((job) => bucket(job) === index).length),
      );
      fragment.append(row);
    });
    $('freshnessBuckets').replaceChildren(fragment);
  }
  function renderActivity() {
    const events = [...(state.events || [])]
      .sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0))
      .slice(0, 7);
    const fragment = document.createDocumentFragment();
    events.forEach((event) => {
      const level = String(event.level || 'info').toLowerCase();
      const category = level.includes('error')
        ? 'error'
        : level.includes('warn')
          ? 'warning'
          : level.includes('success')
            ? 'success'
            : '';
      const row = el('div', 'activity-row'),
        indicator = el('div', `activity-icon ${category}`);
      indicator.append(
        icon(
          category === 'error' || category === 'warning'
            ? 'alert'
            : category === 'success'
              ? 'check'
              : 'pulse',
        ),
      );
      const time = el('time', 'activity-time', relative(event.at));
      time.title = prettyDate(event.at, true);
      if (event.at) time.dateTime = event.at;
      row.append(
        indicator,
        el('div', 'activity-message', text(event.message, 'Activity recorded')),
        time,
      );
      fragment.append(row);
    });
    if (!events.length)
      fragment.append(el('div', 'activity-empty', 'No worker activity recorded.'));
    $('activityList').replaceChildren(fragment);
  }
  const blockerTypes = {
    receipt: {
      label: 'Receipt / verification pending',
      icon: 'clock',
      help: 'Submission was attempted, but no employer receipt has been observed. Review the outcome before retrying.',
    },
    authentication: {
      label: 'Sign-in or verification',
      icon: 'lock',
      help: 'Open the application in your regular browser to use its saved sessions and complete any verification.',
    },
    unanswered: {
      label: 'Unanswered required fields',
      icon: 'file',
      help: 'Provide explicit answers; required unknown values hold the application.',
    },
    unsupported: {
      label: 'Unsupported application form',
      icon: 'external',
      help: 'Review the employer form and recorded browser evidence.',
    },
    details: {
      label: 'Missing job details',
      icon: 'briefcase',
      help: 'Import the employer posting with its original description.',
    },
    automation: {
      label: 'Automation error',
      icon: 'alert',
      help: 'Review the recorded error before retrying the opportunity.',
    },
    other: {
      label: 'Other review requirement',
      icon: 'info',
      help: 'Open the opportunity to inspect its recorded review reason.',
    },
  };
  function canOpenApplicationTab(job) {
    return (
      !['active', 'confirmed', 'manual', 'skipped'].includes(statusGroup(job)) &&
      Boolean(safeURL(job.auth_url || job.application?.auth_url || job.apply_url || job.url))
    );
  }
  async function openJobBrowserTab(job, node, purpose = 'application') {
    if (node) node.disabled = true;
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/browser-tab`, { purpose });
      const opened = result.status === 'opened';
      toast(
        resultMessage(
          result,
          opened
            ? 'Opened in your regular browser using its saved sessions. Record the verified application outcome here when finished.'
            : 'The browser tab could not be opened.',
        ),
        !opened,
      );
      await poll();
      if (
        opened &&
        purpose === 'application' &&
        $('modal').open &&
        String(selectedJob) === String(job.id)
      )
        showJob(job.id);
    } catch (error) {
      if ($('modal').open) dialogError(error);
      else toast(error.message, true);
    } finally {
      if (node) node.disabled = false;
    }
  }
  function applicationTabButton(job) {
    const open = button('Open application tab', 'primary', 'external');
    open.addEventListener('click', () => openJobBrowserTab(job, open));
    return open;
  }
  function classifyBlocker(job) {
    if (job.uncertain) return 'receipt';
    const structured = job.blocker_category || job.application?.blocker_category;
    if (structured && blockerTypes[structured]) return structured;
    const reason =
      `${job.note || job.application?.note || ''} ${text(job.unknown_fields, '')}`.toLowerCase();
    if (
      /login|log in|sign[ -]?in|captcha|multi.factor|authentication|verification requires/.test(
        reason,
      )
    )
      return 'authentication';
    if (
      /fields need saved answers|unanswered|unknown required|required.*(?:answer|field)|answer.*required/.test(
        reason,
      )
    )
      return 'unanswered';
    if (
      /no supported application form|no recognized.*(?:next|submit)|unsupported.*form|application form.*not.*found/.test(
        reason,
      )
    )
      return 'unsupported';
    if (
      /usable job description|description unavailable|missing.*(?:description|employer|job detail)|source did not provide/.test(
        reason,
      )
    )
      return 'details';
    if (statusGroup(job) === 'error' || /error:|frame was detached|automation error/.test(reason))
      return 'automation';
    return 'other';
  }
  function blockedJobs(kind) {
    return (state?.jobs || []).filter(
      (job) =>
        ['review', 'error'].includes(statusGroup(job)) && (!kind || classifyBlocker(job) === kind),
    );
  }
  function showBlockers(kind) {
    const type = blockerTypes[kind];
    if (!type || !state) return;
    const content = openModal(type.label, 'RECORDED APPLICATION BLOCKERS', true);
    content.append(el('p', 'modal-note', type.help));
    if (kind === 'unanswered')
      content.append(button('Set up application answers', 'primary', 'edit', showAnswersEditor));
    if (kind === 'details')
      content.append(button('Import employer posting', 'primary', 'plus', showImport));
    const list = el('div', 'blocker-job-list');
    blockedJobs(kind).forEach((job) => {
      const card = el('article', 'blocker-job-card'),
        header = el('div', 'blocker-job-heading');
      header.append(
        el('h3', '', text(job.title, 'Untitled opportunity')),
        el('span', '', text(job.company)),
      );
      card.append(
        header,
        el('p', '', text(job.note || job.application?.note, 'No review reason was returned.')),
      );
      const actions = el('div', 'blocker-job-actions');
      actions.append(button('View details & evidence', 'secondary', 'file', () => showJob(job.id)));
      if (canOpenApplicationTab(job)) actions.append(applicationTabButton(job));
      card.append(actions);
      list.append(card);
    });
    if (!list.childNodes.length)
      list.append(el('p', 'modal-note', 'No opportunities currently have this recorded blocker.'));
    content.append(list);
  }
  function renderDiagnostics() {
    const jobs = blockedJobs(),
      queued =
        state.metrics?.queued ?? state.jobs.filter((job) => statusGroup(job) === 'queued').length;
    const signature = JSON.stringify([
      jobs.map((job) => [
        job.id,
        job.status,
        job.note,
        job.application?.note,
        job.unknown_fields,
        job.uncertain,
        job.blocker_category,
        job.review_reason,
        job.application?.review_reason,
      ]),
      queued,
      state.settings?.search_enabled,
      state.settings?.submission_enabled,
      state.worker?.submitting,
    ]);
    if (signature === diagnosticsSignature) return;
    diagnosticsSignature = signature;
    const panel = $('diagnosticsPanel'),
      heading = el('div', 'panel-heading diagnostics-heading'),
      title = el('div');
    title.append(
      el('h2', '', jobs.length ? 'Why applications are waiting' : 'Submission readiness'),
    );
    title.firstChild.id = 'blockersTitle';
    title.append(
      el(
        'p',
        '',
        jobs.length
          ? `${jobs.length} ${jobs.length === 1 ? 'opportunity needs' : 'opportunities need'} attention. Counts come from their current review and error reasons.`
          : 'Worker activity and submission readiness are tracked separately.',
      ),
    );
    heading.append(title);
    const summary = el(
      'span',
      'readiness-badge',
      state.worker?.submitting
        ? 'Application checks in progress'
        : !state.settings?.submission_enabled
          ? 'Submissions paused'
          : queued
            ? `${queued} queued for form checks`
            : 'No jobs queued to attempt',
    );
    heading.append(summary);
    panel.replaceChildren(heading);
    const readiness = el('div', 'readiness-line');
    readiness.append(
      el('span', '', `Search ${state.settings?.search_enabled ? 'enabled' : 'paused'}`),
      el('span', '', `Submissions ${state.settings?.submission_enabled ? 'enabled' : 'paused'}`),
      el('strong', '', `${queued} queued · ${jobs.length} held`),
    );
    panel.append(
      readiness,
      el(
        'p',
        'readiness-note',
        'An enabled worker does not mean an application can be submitted. Queued opportunities still need form checks; saved answers and successful sign-in do not guarantee submission.',
      ),
    );
    const cards = el('div', 'blocker-grid');
    Object.entries(blockerTypes).forEach(([kind, type]) => {
      const count = jobs.filter((job) => classifyBlocker(job) === kind).length;
      if (kind === 'other' && !count) return;
      const card = el('button', `blocker-card ${count ? 'has-blockers' : ''}`);
      card.type = 'button';
      card.setAttribute(
        'aria-label',
        `${type.label}: ${count} opportunities. View recorded reasons.`,
      );
      const top = el('div', 'blocker-card-top');
      top.append(icon(type.icon), el('strong', '', count));
      card.append(
        top,
        el('span', 'blocker-card-label', type.label),
        el(
          'span',
          'blocker-card-link',
          count ? 'View reasons & next step →' : 'No recorded blockers',
        ),
      );
      card.addEventListener('click', () => showBlockers(kind));
      cards.append(card);
    });
    panel.append(cards);
    const actions = el('div', 'diagnostics-actions');
    actions.append(button('Set up required answers', 'primary', 'edit', showAnswersEditor));
    panel.append(actions);
  }
  function renderIdentity() {
    const profile = state.profile || {};
    const initials = String(profile.name || 'Applicant profile')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase();
    $('profileAvatar').textContent = initials;
    $('profileName').textContent = text(profile.name, 'Applicant profile');
    $('profileLocation').textContent = text(profile.location, 'Location not set');
  }
  function renderProfile() {
    if (!state) return;
    const profile = state.profile || {},
      summary = $('profileSummary');
    summary.replaceChildren(el('div', 'avatar', $('profileAvatar').textContent));
    const info = el('div');
    info.append(el('h2', '', text(profile.name, 'Applicant profile')));
    const contacts = el('div', 'profile-contact');
    [
      ['location', profile.location],
      ['mail', profile.email],
      ['link', profile.linkedin],
    ].forEach(([name, value]) => {
      if (!value) return;
      const item = el('span');
      item.append(icon(name));
      const url = name === 'link' && safeURL(value);
      if (url) {
        const link = el('a', '', 'LinkedIn profile');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        item.append(link);
      } else item.append(document.createTextNode(String(value)));
      contacts.append(item);
    });
    info.append(contacts);
    const skills = el('div', 'skill-chips');
    const skillItems = Array.isArray(profile.skills)
      ? profile.skills
      : typeof profile.skills === 'string'
        ? profile.skills.split(',')
        : [];
    skillItems.forEach((skill) => skills.append(el('span', 'skill-chip', text(skill))));
    info.append(skills);
    summary.append(info);
    const fragment = document.createDocumentFragment();
    (profile.experience || []).forEach((experience) => {
      const card = el('article', 'panel experience-card'),
        heading = el('div', 'experience-heading'),
        title = el('div');
      title.append(
        el('h2', '', text(experience.title, 'Experience')),
        el('div', 'experience-company', text(experience.company)),
      );
      heading.append(
        title,
        el(
          'div',
          'experience-dates',
          `${text(experience.start, '')} — ${text(experience.end, 'Present')}`,
        ),
      );
      card.append(heading);
      const list = el('ul', 'career-facts');
      (experience.facts || []).forEach((fact) => {
        const item = el('li', '', typeof fact === 'string' ? fact : text(fact.text));
        if (fact.id) item.append(el('span', 'fact-id', fact.id));
        list.append(item);
      });
      card.append(list);
      fragment.append(card);
    });
    [
      ['Certifications', profile.certifications],
      ['Education', profile.education],
    ].forEach(([label, entries]) => {
      if (!entries || !entries.length) return;
      const card = el('article', 'panel experience-card');
      card.append(el('h2', '', label));
      const list = el('ul', 'career-facts');
      (Array.isArray(entries) ? entries : [entries]).forEach((entry) =>
        list.append(
          el(
            'li',
            '',
            typeof entry === 'object'
              ? Object.entries(entry)
                  .map(([key, value]) => `${key}: ${text(value)}`)
                  .join(' · ')
              : entry,
          ),
        ),
      );
      card.append(list);
      fragment.append(card);
    });
    if (!fragment.childNodes.length) {
      const card = el('article', 'panel experience-card');
      card.append(
        el('h2', '', 'No profile experience saved'),
        el(
          'p',
          'modal-note',
          'Edit your profile to add work experience, skills, certifications and education.',
        ),
      );
      fragment.append(card);
    }
    $('experienceList').replaceChildren(fragment);
  }
  function renderAnswers() {
    if (!state) return;
    const entries = Object.entries(state.answers || {}),
      fragment = document.createDocumentFragment();
    entries.forEach(([key, value]) => {
      const row = el('div', 'answer-row');
      row.append(
        el(
          'div',
          'answer-key',
          commonAnswerSchema.find((field) => field.key === key)?.label || key,
        ),
        el(
          'div',
          'answer-value',
          value === null || value === '' ? 'Unknown — needs your answer' : text(value),
        ),
      );
      fragment.append(row);
    });
    if (!entries.length)
      fragment.append(
        el(
          'div',
          'answer-empty',
          'No screening answers saved yet. Add answers only after you have confirmed the response. Required unknown answers will hold the application for review.',
        ),
      );
    $('answersList').replaceChildren(fragment);
  }
  function renderSettings(force = false) {
    if (!state || (settingsDirty && !force)) return;
    const settings = state.settings || {},
      form = $('settingsForm');
    Object.entries(settings).forEach(([key, value]) => {
      const input = form.elements.namedItem(key);
      if (!input) return;
      if (input.type === 'checkbox') input.checked = Boolean(value);
      else
        input.value =
          key === 'target_roles' && Array.isArray(value) ? value.join('\n') : text(value, '');
    });
    if (force) settingsDirty = false;
  }
  function renderConnections() {
    const connections = state?.connections || {};
    ['linkedin', 'indeed', 'employer'].forEach((platform) => {
      const result = loginResults[platform] || connections[platform];
      const label = $(platform + 'Status');
      if (!result) return;
      label.textContent = `Worker session: ${typeof result === 'string' ? result : resultMessage(result, result.status ? String(result.status).replaceAll('_', ' ') : 'Sign-in requested; session status is not verified.')}`;
    });
    if (!emailDirty && state?.settings?.email) {
      const email = state.settings.email,
        form = $('emailForm');
      ['host', 'port'].forEach((key) => {
        if (email[key] !== undefined) form.elements.namedItem(key).value = email[key];
      });
      form.elements.namedItem('user').value = text(email.username ?? email.user, '');
      form.elements.namedItem('folder').value = text(email.mailbox ?? email.folder, 'INBOX');
      form.elements.namedItem('enabled').checked = Boolean(email.enabled);
      $('emailStatus').textContent =
        `${text(state.worker?.email_status, email.enabled ? 'Configured' : 'Not configured')}. ${email.credential_saved ? 'Credential saved in Windows storage. ' : ''}Inbox access has not been verified by this dashboard.`;
    }
  }
  function render() {
    renderMetrics();
    renderIdentity();
    renderJobs();
    renderWorker();
    renderActivity();
    renderConnections();
    renderDiagnostics();
    if (activeView === 'profile') renderProfile();
    if (activeView === 'answers') renderAnswers();
    renderSettings();
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch('/api/state', { cache: 'no-store' });
      if (!response.ok) throw new Error(`Local service returned HTTP ${response.status}.`);
      const result = await response.json();
      if (!result || !Array.isArray(result.jobs))
        throw new Error('The local service returned an incomplete dashboard state.');
      state = result;
      connected = true;
      $('connectionDot').className = 'dot teal';
      $('connectionLabel').textContent = 'Local service connected';
      $('serviceBanner').hidden = true;
      $('lastUpdated').textContent =
        `Updated ${new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(new Date())}`;
      render();
    } catch (error) {
      connected = false;
      $('connectionDot').className = 'dot amber';
      $('connectionLabel').textContent = 'Local service unavailable';
      $('serviceBanner').hidden = false;
      $('serviceBanner').textContent =
        `The local service is unavailable. ${error.message} JobPilot will reconnect automatically. ${state ? 'Displayed data is from the last successful update.' : 'Start JobPilot using its desktop launcher.'}`;
      $('workerState').textContent = 'Disconnected';
      $('workerDot').className = 'dot amber';
      ['searchNow', 'toggleSearch', 'toggleSubmissions', 'toggleWorker'].forEach((id) => {
        $(id).disabled = true;
      });
    } finally {
      polling = false;
    }
  }
  function showView(view) {
    if (!viewLabels[view]) return;
    activeView = view;
    document.querySelectorAll('.view').forEach((node) => {
      node.hidden = node.id !== `view-${view}`;
    });
    document.querySelectorAll('#navigation [data-view]').forEach((node) => {
      node.classList.toggle('active', node.dataset.view === view);
      if (node.dataset.view === view) node.setAttribute('aria-current', 'page');
      else node.removeAttribute('aria-current');
    });
    $('breadcrumbCurrent').textContent = viewLabels[view];
    if (view === 'profile') renderProfile();
    if (view === 'answers') renderAnswers();
    if (view === 'settings') renderSettings();
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function openModal(title, eyebrow = '', wide = false) {
    $('modalTitle').textContent = title;
    $('modalEyebrow').textContent = eyebrow;
    $('modalContent').replaceChildren();
    $('modal').style.width = wide ? 'min(820px, calc(100% - 32px))' : '';
    if (!$('modal').open) $('modal').showModal();
    return $('modalContent');
  }
  function closeModal() {
    $('modal').close();
    selectedJob = null;
  }
  function formField(form, label, name, type = 'text', value = '', full = false, placeholder = '') {
    const wrapper = el('label', full ? 'full' : '', label),
      input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = 4;
    input.name = name;
    input.value = text(value, '');
    if (placeholder) input.placeholder = placeholder;
    wrapper.append(input);
    form.append(wrapper);
    return input;
  }
  function dialogError(error) {
    let node = $('modalContent').querySelector('.dialog-error');
    if (!node) {
      node = el('div', 'dialog-error');
      node.setAttribute('role', 'alert');
      $('modalContent').append(node);
    }
    node.textContent = error.message;
    node.scrollIntoView({ block: 'nearest' });
  }
  async function submitModal(form, path, payload, message) {
    const submit = form.querySelector('[type=submit]');
    if (submit) submit.disabled = true;
    const oldError = $('modalContent').querySelector('.dialog-error');
    if (oldError) oldError.remove();
    try {
      const result = await api(path, payload);
      closeModal();
      toast(resultMessage(result, message));
      await poll();
    } catch (error) {
      dialogError(error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }
  async function showCleanupPreview() {
    selectedJob = null;
    const opener = $('cleanupJobs');
    opener.disabled = true;
    const content = openModal('Remove jobs 7+ days old', 'REVIEW BEFORE PERMANENT DELETION', true);
    const loading = el('p', 'modal-note', 'Checking posting dates and protected applications…');
    content.append(loading);
    try {
      if (!token) await session();
      const response = await fetch('/api/jobs/cleanup/preview', {
        cache: 'no-store',
        headers: { 'X-JobPilot-Token': token },
      });
      const preview = await response.json();
      if (!response.ok)
        throw new Error(
          text(preview.detail || preview.message, 'Could not prepare the cleanup preview.'),
        );
      if (!$('modal').open || !loading.isConnected) return;
      if (
        !Array.isArray(preview.jobs) ||
        !Number.isSafeInteger(preview.count) ||
        preview.count < 0 ||
        preview.count !== preview.jobs.length ||
        typeof preview.token !== 'string' ||
        !preview.token ||
        !Number.isFinite(Date.parse(preview.cutoff))
      )
        throw new Error(
          'The cleanup preview is incomplete. Close and reopen it before deleting any jobs.',
        );
      content.replaceChildren();
      content.append(
        el(
          'p',
          'cleanup-summary',
          `${number(preview.count)} ${preview.count === 1 ? 'job is' : 'jobs are'} eligible for permanent deletion.`,
        ),
      );
      const cutoff = el('div', 'cleanup-cutoff-row');
      cutoff.append(
        el('span', '', `Posting date on or before ${prettyDate(preview.cutoff, true)}`),
        el('code', 'cleanup-cutoff', preview.cutoff),
      );
      content.append(cutoff);
      const kept = el(
        'p',
        'modal-note cleanup-kept',
        `${number(preview.protected_count || 0)} protected jobs kept · ${number(preview.unknown_date_count || 0)} jobs with unknown posting dates kept. Jobs with future posting dates are also kept.`,
      );
      content.append(kept);
      const warning = el(
        'p',
        'cleanup-warning',
        'This permanently deletes the listed job listings and their application records. Saved files stay on disk. Matching listings found again will be ignored.',
      );
      content.append(warning);
      if (preview.jobs.length) {
        const list = el('ul', 'cleanup-job-list');
        list.setAttribute('aria-label', 'Jobs to permanently delete');
        preview.jobs.forEach((job) => {
          const item = el('li', 'cleanup-job');
          item.append(
            el('strong', '', text(job.title, 'Untitled opportunity')),
            el('span', '', `${text(job.company, 'Unknown company')} · ${statusLabel(job)}`),
            el('time', '', `Posted ${prettyDate(job.posted_at, true)}`),
          );
          list.append(item);
        });
        content.append(list);
      } else
        content.append(
          el('p', 'modal-note', 'No jobs currently qualify. Nothing will be deleted.'),
        );
      const expired =
        Number.isFinite(Date.parse(preview.expires_at)) &&
        Date.parse(preview.expires_at) <= Date.now();
      if (preview.busy || expired) {
        const note = el(
          'p',
          'notice cleanup-busy',
          preview.busy
            ? 'The worker is busy. Wait for its current application or verification to finish, then reopen this preview.'
            : 'This preview has expired. Reopen it to check the current jobs before deleting.',
        );
        note.setAttribute('role', 'status');
        content.append(note);
      }
      const footer = el('div', 'form-footer cleanup-actions');
      const cancel = button('Cancel', 'secondary', null, closeModal);
      const refresh = button('Refresh preview', 'secondary', 'refresh', showCleanupPreview);
      const confirm = button(
        `Permanently delete ${preview.count} ${preview.count === 1 ? 'job' : 'jobs'}`,
        'danger',
        'trash',
      );
      confirm.disabled = !preview.count || Boolean(preview.busy) || expired;
      confirm.addEventListener('click', async () => {
        if (confirm.disabled) return;
        confirm.disabled = true;
        cancel.disabled = true;
        refresh.disabled = true;
        const priorError = content.querySelector('.dialog-error');
        if (priorError) priorError.remove();
        try {
          const result = await api('/api/jobs/cleanup', { token: preview.token, confirm: true });
          if ($('modal').open && footer.isConnected) closeModal();
          const deleted = Number(result.deleted_count) || 0,
            skipped = Number(result.skipped_count) || 0;
          toast(
            `Permanently deleted ${number(deleted)} ${deleted === 1 ? 'job' : 'jobs'}.${skipped ? ` ${number(skipped)} ${skipped === 1 ? 'job was' : 'jobs were'} kept because the preview changed.` : ''}`,
          );
          await poll();
        } catch (error) {
          const message = `${error.message} Reopen or refresh the preview before trying again.`;
          if ($('modal').open && footer.isConnected) dialogError(new Error(message));
          else toast(message, true);
        } finally {
          cancel.disabled = false;
          refresh.disabled = false;
        }
      });
      footer.append(cancel, refresh, confirm);
      content.append(footer);
      cancel.focus();
    } catch (error) {
      if ($('modal').open && loading.isConnected) {
        loading.remove();
        dialogError(error);
        content.append(button('Cancel', 'secondary', null, closeModal));
      }
    } finally {
      opener.disabled = false;
    }
  }
  function showImport(mode = 'job') {
    mode = mode === 'email' ? 'email' : 'job';
    const content = openModal('Add an opportunity', 'IMPORT A JOB OR EMAIL ALERT');
    const tabs = el('div', 'modal-tabs');
    [
      ['job', 'Job link or details'],
      ['email', 'Email alert / EML'],
    ].forEach(([key, label]) => {
      const tab = el('button', `modal-tab ${mode === key ? 'active' : ''}`, label);
      tab.type = 'button';
      tab.addEventListener('click', () => showImport(key));
      tabs.append(tab);
    });
    content.append(tabs);
    content.append(
      el(
        'p',
        'modal-note',
        mode === 'job'
          ? 'Paste an actual job URL or add the details yourself. JobPilot will assess the opportunity and record any preparation or review requirements.'
          : 'Paste the raw text of an email alert, or choose an .eml file. JobPilot extracts job links into the pipeline.',
      ),
    );
    const form = el('form', 'form-grid');
    if (mode === 'job') {
      formField(form, 'Job URL', 'url', 'url', '', true, 'https://careers.example.com/jobs/123');
      formField(form, 'Role title', 'title', 'text', '', false, 'Security Engineer');
      formField(form, 'Company', 'company', 'text', '', false, 'Company name');
      formField(form, 'Source', 'source', 'text', 'Manual import');
      formField(form, 'Location', 'location', 'text', '', false, 'City, State or Remote');
      formField(
        form,
        'Actual posting date / time (optional)',
        'posted_at',
        'datetime-local',
        '',
        true,
      );
      formField(
        form,
        'Job description (optional)',
        'description',
        'textarea',
        '',
        true,
        'Paste the original job description.',
      );
    } else {
      const fileLabel = el('label', 'file-label full', 'Choose an EML email alert');
      const file = el('input');
      file.type = 'file';
      file.accept = '.eml,message/rfc822,text/plain';
      fileLabel.append(file);
      form.append(fileLabel);
      const eml = formField(
        form,
        'Raw email / alert content',
        'eml',
        'textarea',
        '',
        true,
        'Paste the email content, including the job URLs.',
      );
      eml.rows = 9;
      file.addEventListener('change', async () => {
        if (!file.files.length) return;
        if (file.files[0].size > 5 * 1024 * 1024) {
          toast('Choose an email alert smaller than 5 MB.', true);
          file.value = '';
          return;
        }
        try {
          eml.value = await file.files[0].text();
        } catch (_) {
          toast('Could not read this email alert.', true);
        }
      });
    }
    const footer = el('div', 'form-footer full');
    footer.append(
      el(
        'p',
        'form-note',
        'A recorded opportunity becomes confirmed only after a verified employer receipt.',
      ),
    );
    const submit = button('Add to pipeline', 'primary', 'plus');
    submit.type = 'submit';
    footer.append(submit);
    form.append(footer);
    content.append(form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(form));
      Object.keys(payload).forEach((key) => {
        if (typeof payload[key] === 'string') payload[key] = payload[key].trim();
      });
      if (mode === 'job' && !payload.url && !(payload.title && payload.company)) {
        dialogError(new Error('Add a job URL, or provide both a role title and company.'));
        return;
      }
      if (mode === 'email' && !payload.eml) {
        dialogError(new Error('Choose an EML file or paste an email alert.'));
        return;
      }
      if (payload.posted_at) payload.posted_at = new Date(payload.posted_at).toISOString();
      await submitModal(
        form,
        '/api/import',
        payload,
        'Opportunity imported. Check the pipeline for its current status.',
      );
    });
  }
  function artifactEntries(value, prefix = '') {
    if (!value) return [];
    if (typeof value === 'string') return [[prefix || value.split(/[\\/]/).pop(), value]];
    if (Array.isArray(value))
      return value.flatMap((item, index) =>
        artifactEntries(item, prefix ? `${prefix} ${index + 1}` : ''),
      );
    if (typeof value === 'object') {
      if (typeof value.path === 'string')
        return [[value.label || value.name || prefix || 'Artifact', value.path]];
      return Object.entries(value).flatMap(([key, item]) => artifactEntries(item, key));
    }
    return [];
  }
  function showJob(id) {
    const job = state?.jobs.find((item) => String(item.id) === String(id));
    if (!job) return;
    selectedJob = job.id;
    const content = openModal(text(job.title, 'Opportunity details'), 'OPPORTUNITY DETAILS', true);
    const subtitle = el('div', 'detail-subtitle');
    subtitle.append(el('span', '', `${text(job.company)} · ${text(job.source)}`), badge(job));
    content.append(subtitle);
    const facts = el('div', 'detail-facts');
    [
      ['Posting window', job.bucket_label || labels[bucket(job)]],
      [
        'Fit assessment',
        fitNumber(job) === null ? 'Not assessed' : `${Math.round(fitNumber(job))}%`,
      ],
      ['Location', text(job.location, 'Not specified')],
    ].forEach(([label, value]) => {
      const fact = el('div', 'detail-fact');
      fact.append(el('span', '', label), el('strong', '', value));
      facts.append(fact);
    });
    content.append(facts);
    const link = safeURL(job.url);
    if (link) {
      const original = button('View original posting', 'secondary', 'external');
      original.addEventListener('click', () => openJobBrowserTab(job, original, 'posting'));
      content.append(original);
    }
    if (!job.uncertain && canOpenApplicationTab(job)) {
      content.append(
        applicationTabButton(job),
        el(
          'p',
          'modal-note',
          'Uses your regular browser and its saved sessions. Use browser autofill or complete the fields yourself; application documents are available below. JobPilot cannot observe this tab automatically, so record the verified outcome here.',
        ),
      );
    }
    const status = el('section', 'detail-section');
    status.append(el('h3', '', 'Status & timeline'));
    const imported = el('div', 'timeline-item'),
      importedBody = el('div', '', 'Opportunity added');
    importedBody.append(el('small', '', prettyDate(job.created_at, true)));
    imported.append(importedBody);
    status.append(imported);
    const current = el('div', 'timeline-item'),
      currentBody = el('div', '', statusLabel(job));
    currentBody.append(
      el('small', '', text(job.note || job.application?.note, 'Waiting for worker assessment.')),
    );
    current.append(currentBody);
    status.append(current);
    if (job.posted_at) {
      const date = el('div', 'timeline-item'),
        body = el('div', '', 'Source posting date');
      body.append(el('small', '', prettyDate(job.posted_at, true)));
      date.append(body);
      status.append(date);
    }
    if (Array.isArray(job.timeline))
      job.timeline.forEach((event) => {
        const item = el('div', 'timeline-item'),
          body = el('div', '', text(event.message || event.status));
        body.append(el('small', '', prettyDate(event.at, true)));
        item.append(body);
        status.append(item);
      });
    content.append(status);
    const manualHandoff =
      job.status === 'needs_review' &&
      job.browser_handoff?.mode === 'default_browser' &&
      job.browser_handoff?.state !== 'closed';
    if (job.uncertain || manualHandoff) {
      const resolution = el('section', 'detail-section');
      resolution.append(
        el(
          'h3',
          '',
          job.uncertain ? 'Verify the uncertain submission' : 'Record application outcome',
        ),
        el(
          'p',
          'modal-note',
          'Check the employer portal or receipt email, then record the employer receipt or explain how you verified that no application was submitted. Automatic retries stay paused while this application is in review.',
        ),
      );
      if (job.uncertain && canOpenApplicationTab(job)) {
        resolution.append(
          el(
            'p',
            'modal-note',
            'Submission was already attempted. Check your employer account or receipt email before submitting again. This opens your regular browser with its saved sessions. Use browser autofill or complete the fields yourself; application documents are available below. After completing verification, record the receipt here. JobPilot cannot observe this browser tab automatically.',
          ),
          applicationTabButton(job),
        );
      }
      const form = el('form', 'form-grid');
      const choiceLabel = el('label', 'full', 'Verified outcome'),
        choice = el('select');
      choice.name = 'outcome';
      choice.required = true;
      [
        ['', 'Choose an outcome you verified'],
        ['confirmed', 'I verified an employer submission receipt'],
        ['not_submitted', 'I verified that no application was submitted'],
      ].forEach(([value, label]) => {
        const option = el('option', '', label);
        option.value = value;
        choice.append(option);
      });
      choiceLabel.append(choice);
      form.append(choiceLabel);
      const evidence = formField(
        form,
        'Receipt / verification evidence',
        'evidence',
        'textarea',
        '',
        true,
        'Record the receipt ID, employer message, or how you checked that no application was submitted.',
      );
      evidence.required = true;
      const save = button('Save verified outcome', 'primary', 'check');
      save.type = 'submit';
      form.append(save);
      resolution.append(form);
      content.append(resolution);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const result = await action(
          save,
          `/api/jobs/${encodeURIComponent(job.id)}/resolve`,
          { outcome: choice.value, evidence: evidence.value.trim() },
          'Verified outcome recorded.',
        );
        if (result) showJob(job.id);
      });
    }
    const description = el('section', 'detail-section');
    description.append(
      el('h3', '', 'Job description'),
      el(
        'div',
        'detail-description',
        text(
          job.description,
          'No description was returned for this opportunity. Open the original posting for its current requirements.',
        ),
      ),
    );
    content.append(description);
    [
      ['Application documents', job.application?.documents || job.documents],
      ['Submission evidence', job.application?.evidence || job.evidence],
    ].forEach(([title, artifacts]) => {
      const section = el('section', 'detail-section');
      section.append(el('h3', '', title));
      const entries = artifactEntries(artifacts).filter(
        ([, path]) => typeof path === 'string' && /^(?:[A-Za-z]:[\\/]|\/)/.test(path),
      );
      if (!entries.length)
        section.append(
          el(
            'p',
            '',
            title === 'Submission evidence'
              ? 'No submission evidence recorded yet.'
              : 'No application package prepared yet.',
          ),
        );
      else {
        const links = el('div', 'artifact-links');
        entries.forEach(([label, path]) => {
          const item = el('a', 'button secondary');
          item.href = `/api/artifact?path=${encodeURIComponent(path)}`;
          item.target = '_blank';
          item.rel = 'noopener noreferrer';
          item.append(
            icon(title === 'Submission evidence' ? 'external' : 'download'),
            document.createTextNode(label.replaceAll('_', ' ')),
          );
          links.append(item);
        });
        section.append(links);
      }
      content.append(section);
    });
    const actions = el('div', 'detail-actions');
    const busy = ['applying', 'submitting', 'preparing'].includes(
      String(job.status || '').toLowerCase(),
    );
    const prepare = button('Prepare documents', 'primary', 'file', async () => {
      const result = await action(
        prepare,
        `/api/jobs/${encodeURIComponent(job.id)}/prepare`,
        {},
        'Document preparation requested. Follow its progress in activity.',
      );
      if (result) showJob(job.id);
    });
    prepare.disabled = Boolean(
      job.uncertain ||
      manualHandoff ||
      busy ||
      ['confirmed', 'manual', 'skipped'].includes(statusGroup(job)),
    );
    if (prepare.disabled)
      prepare.title =
        'Preparation is unavailable while this opportunity is complete, skipped, busy or awaiting receipt verification.';
    actions.append(prepare);
    if (!['confirmed', 'manual', 'skipped'].includes(statusGroup(job))) {
      const retry = button('Retry / re-evaluate', 'secondary', 'refresh', async () => {
        const result = await action(
          retry,
          `/api/jobs/${encodeURIComponent(job.id)}/retry`,
          {},
          'Opportunity returned for worker assessment.',
        );
        if (result) showJob(job.id);
      });
      retry.disabled = Boolean(job.uncertain || manualHandoff || busy);
      actions.append(retry);
      const skip = button('Skip opportunity', 'danger-button', 'close', async () => {
        const result = await action(
          skip,
          `/api/jobs/${encodeURIComponent(job.id)}/skip`,
          {},
          'Opportunity skipped.',
        );
        if (result) closeModal();
      });
      skip.disabled = busy;
      actions.append(skip);
    }
    content.append(
      actions,
      el(
        'p',
        'error-help',
        'Preparation creates documents. Automatic confirmations require a verified submission receipt. Manually verified outcomes are tracked separately. Uncertain submissions remain in review.',
      ),
    );
  }
  function showProfileEditor() {
    if (!state) {
      toast('Wait for the local service to connect.', true);
      return;
    }
    const profile = state.profile || {},
      content = openModal('Edit your career profile', 'FACTS FIRST', true);
    content.append(
      el(
        'p',
        'modal-note',
        'Edit your contact details and experience below. Keep dates and accomplishments consistent with your resume.',
      ),
    );
    const form = el('form', 'form-grid');
    [
      ['Full name', 'name', 'text'],
      ['Email', 'email', 'email'],
      ['Phone', 'phone', 'tel'],
      ['Location', 'location', 'text'],
      ['LinkedIn profile URL', 'linkedin', 'url'],
    ].forEach(([label, name, type]) =>
      formField(form, label, name, type, profile[name] || '', name === 'linkedin'),
    );
    const json = formField(
      form,
      'Complete profile JSON · experience, fact IDs, skills, certifications, education',
      'profile_json',
      'textarea',
      JSON.stringify(profile, null, 2),
      true,
    );
    json.className = 'json-editor';
    json.rows = 17;
    json.spellcheck = false;
    const footer = el('div', 'form-footer full');
    footer.append(
      el(
        'p',
        'form-note',
        'Fact IDs link each generated claim to your profile. Preserve those IDs when editing existing facts.',
      ),
    );
    const submit = button('Save profile', 'primary', 'save');
    submit.type = 'submit';
    footer.append(submit);
    form.append(footer);
    content.append(form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const payload = JSON.parse(json.value);
        if (!payload || typeof payload !== 'object' || Array.isArray(payload))
          throw new Error('Profile JSON must be an object.');
        ['name', 'email', 'phone', 'location', 'linkedin'].forEach((key) => {
          payload[key] = form.elements.namedItem(key).value.trim();
        });
        if (payload.experience && !Array.isArray(payload.experience))
          throw new Error('Experience must be an array of roles and facts.');
        await submitModal(form, '/api/profile', payload, 'Career profile saved.');
      } catch (error) {
        dialogError(new Error(`Could not save the profile: ${error.message}`));
      }
    });
  }
  function showAnswersEditor(mode = 'common') {
    if (!state) {
      toast('Wait for the local service to connect.', true);
      return;
    }
    mode = mode === 'advanced' ? 'advanced' : 'common';
    const content = openModal(
      mode === 'common' ? 'Set up common application answers' : 'Edit exact question answers',
      'YOUR EXPLICIT RESPONSES',
      true,
    );
    const tabs = el('div', 'modal-tabs');
    [
      ['common', 'Common answers'],
      ['advanced', 'Exact question answers · advanced'],
    ].forEach(([key, label]) => {
      const tab = el('button', `modal-tab ${mode === key ? 'active' : ''}`, label);
      tab.type = 'button';
      tab.addEventListener('click', () => showAnswersEditor(key));
      tabs.append(tab);
    });
    content.append(tabs);
    if (mode === 'common') {
      content.append(
        el(
          'p',
          'modal-note',
          'Provide these one-time facts only when you know the answer. Unknown values are left out. Your saved contact details supply your name, phone and location; no screening eligibility or consent is guessed.',
        ),
      );
      const form = el('form', 'form-grid common-answers-form');
      commonAnswerSchema.forEach((field) => {
        const label = el('label', 'full', field.label);
        let input;
        if (field.type === 'choice') {
          input = el('select');
          [
            ['', 'Unknown / not provided'],
            ['Yes', 'Yes'],
            ['No', 'No'],
          ].forEach(([value, caption]) => {
            const option = el('option', '', caption);
            option.value = value;
            input.append(option);
          });
          input.value = ['Yes', 'No'].includes(state.answers?.[field.key])
            ? state.answers[field.key]
            : '';
        } else {
          input = el('input');
          input.type = 'text';
          input.value =
            typeof state.answers?.[field.key] === 'string' ? state.answers[field.key] : '';
          input.placeholder = 'Leave blank if unknown';
        }
        input.name = field.key;
        label.append(input, el('span', 'answer-field-help', field.help));
        form.append(label);
      });
      const footer = el('div', 'form-footer full');
      footer.append(
        el(
          'p',
          'form-note',
          'Other saved answers are preserved. Required questions without an explicit answer continue to need review.',
        ),
      );
      const submit = button('Save common answers', 'primary', 'save');
      submit.type = 'submit';
      footer.append(submit);
      form.append(footer);
      content.append(form);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const answers = { ...(state.answers || {}) };
        commonAnswerSchema.forEach((field) => {
          const value = form.elements.namedItem(field.key).value.trim();
          if (value) answers[field.key] = value;
          else delete answers[field.key];
        });
        await submitModal(
          form,
          '/api/answers',
          { answers },
          'Common application answers saved. Remaining unknown questions still require review.',
        );
      });
      return;
    }
    content.append(
      el(
        'p',
        'modal-note',
        'Use a JSON object mapping the exact question text to your confirmed answer. Omit unknown answers. Save only answers you personally confirm; sensitive or eligibility answers are never guessed.',
      ),
    );
    const form = el('form', 'form-grid');
    const json = formField(
      form,
      'Saved answers JSON',
      'answers',
      'textarea',
      JSON.stringify(state.answers || {}, null, 2),
      true,
    );
    json.className = 'json-editor';
    json.spellcheck = false;
    const footer = el('div', 'form-footer full');
    footer.append(
      el(
        'p',
        'form-note',
        'Copy the exact question from the application review message. Values can be text, true/false, or a number. Required unanswered questions remain in review.',
      ),
    );
    const submit = button('Save answers', 'primary', 'save');
    submit.type = 'submit';
    footer.append(submit);
    form.append(footer);
    content.append(form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const answers = JSON.parse(json.value);
        if (!answers || typeof answers !== 'object' || Array.isArray(answers))
          throw new Error('Answers JSON must be an object.');
        if (
          Object.values(answers).some(
            (value) => !['string', 'boolean', 'number'].includes(typeof value),
          )
        )
          throw new Error(
            'Answer values must be text, true/false, or a number. Omit questions you have not answered.',
          );
        await submitModal(form, '/api/answers', { answers }, 'Application answers saved.');
      } catch (error) {
        dialogError(new Error(`Could not save the answers: ${error.message}`));
      }
    });
  }
  async function openBrowserTab(platform, url, node) {
    if (node) node.disabled = true;
    try {
      const result = await api('/api/browser-tab', { platform, ...(url ? { url } : {}) });
      const opened = result.status === 'opened';
      toast(
        resultMessage(
          result,
          opened
            ? 'Opened in your regular browser using its saved sessions.'
            : 'The browser tab could not be opened.',
        ),
        !opened,
      );
      if (opened && $('modal').open) closeModal();
    } catch (error) {
      if ($('modal').open) dialogError(error);
      else toast(error.message, true);
    } finally {
      if (node) node.disabled = false;
    }
  }
  async function openLogin(platform, url, node) {
    if (node) node.disabled = true;
    try {
      const result = await api('/api/login', {
        mode: 'isolated',
        platform,
        ...(url ? { url } : {}),
      });
      loginResults[platform] = resultMessage(
        result,
        'Separate worker browser requested. Complete sign-in there; worker session status is not verified.',
      );
      renderConnections();
      toast(loginResults[platform]);
      if ($('modal').open) closeModal();
    } catch (error) {
      if ($('modal').open) dialogError(error);
      else toast(error.message, true);
      loginResults[platform] = `Could not open login: ${error.message}`;
      renderConnections();
    } finally {
      if (node) node.disabled = false;
    }
  }
  function showEmployerLogin(workerSession = false) {
    const content = openModal(
      workerSession ? 'Connect an employer worker session' : 'Open an employer tab',
      workerSession ? 'SEPARATE WORKER BROWSER' : 'YOUR REGULAR BROWSER',
    );
    content.append(
      el(
        'p',
        'modal-note',
        workerSession
          ? 'This opens JobPilot’s separate browser to sign in the automated worker. Your regular browser’s saved sessions are not shared with it.'
          : 'Enter the employer’s application or sign-in URL. It opens in your regular browser with its saved sessions. Opening this tab does not connect the automated worker.',
      ),
    );
    const form = el('form', 'form-grid'),
      url = formField(
        form,
        'Employer portal URL',
        'url',
        'url',
        '',
        true,
        'https://careers.example.com',
      );
    url.required = true;
    const footer = el('div', 'form-footer full'),
      submit = button(
        workerSession ? 'Connect worker session' : 'Open browser tab',
        'primary',
        'external',
      );
    submit.type = 'submit';
    footer.append(submit);
    form.append(footer);
    content.append(form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      await (workerSession ? openLogin : openBrowserTab)('employer', url.value.trim(), submit);
    });
  }
  hydrateIcons();
  $('todayLabel').textContent = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date());
  $('closeModal').addEventListener('click', closeModal);
  $('modal').addEventListener('click', (event) => {
    if (event.target === $('modal')) {
      const rect = $('modal').getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        closeModal();
    }
  });
  $('modal').addEventListener('close', () => {
    selectedJob = null;
  });
  document
    .querySelectorAll('[data-view]')
    .forEach((node) => node.addEventListener('click', () => showView(node.dataset.view)));
  document.querySelectorAll('[data-filter]').forEach((node) =>
    node.addEventListener('click', () => {
      activeFilter = node.dataset.filter;
      updateTabs();
      renderJobs();
    }),
  );
  document
    .querySelectorAll('[data-open-import]')
    .forEach((node) => node.addEventListener('click', () => showImport()));
  $('openImport').addEventListener('click', () => showImport());
  $('cleanupJobs').addEventListener('click', showCleanupPreview);
  ['jobQuery', 'sourceFilter', 'statusFilter'].forEach((id) =>
    $(id).addEventListener(id === 'jobQuery' ? 'input' : 'change', renderJobs),
  );
  $('searchNow').addEventListener('click', () =>
    action($('searchNow'), '/api/control', { action: 'search' }, 'Discovery search requested.'),
  );
  $('toggleSearch').addEventListener('click', () =>
    action(
      $('toggleSearch'),
      '/api/control',
      { search_enabled: !state.settings.search_enabled },
      state.settings.search_enabled ? 'Automatic search paused.' : 'Automatic search resumed.',
    ),
  );
  $('toggleSubmissions').addEventListener('click', () =>
    action(
      $('toggleSubmissions'),
      '/api/control',
      { submission_enabled: !state.settings.submission_enabled },
      state.settings.submission_enabled
        ? 'Application submissions paused.'
        : 'Eligible application submissions resumed.',
    ),
  );
  $('toggleWorker').addEventListener('click', () => {
    const running = state.settings.search_enabled || state.settings.submission_enabled;
    action(
      $('toggleWorker'),
      '/api/control',
      { action: running ? 'stop' : 'start' },
      running
        ? 'Worker stop requested. In-progress work checkpoints safely.'
        : 'Worker start requested.',
    );
  });
  $('editProfile').addEventListener('click', showProfileEditor);
  $('editAnswers').addEventListener('click', showAnswersEditor);
  document
    .querySelectorAll('[data-browser-tab]')
    .forEach((node) =>
      node.addEventListener('click', () => openBrowserTab(node.dataset.browserTab, null, node)),
    );
  document
    .querySelectorAll('[data-login]')
    .forEach((node) =>
      node.addEventListener('click', () => openLogin(node.dataset.login, null, node)),
    );
  $('employerLogin').addEventListener('click', () => showEmployerLogin());
  $('employerWorkerLogin').addEventListener('click', () => showEmployerLogin(true));
  $('settingsForm').addEventListener('input', () => {
    settingsDirty = true;
  });
  $('settingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      fields = form.elements;
    const payload = {};
    ['location', 'ollama_url', 'model'].forEach((key) => {
      payload[key] = fields.namedItem(key).value.trim();
    });
    ['search_interval_minutes', 'min_fit'].forEach((key) => {
      payload[key] = Number(fields.namedItem(key).value);
    });
    ['remote', 'search_enabled', 'submission_enabled', 'keep_awake', 'startup'].forEach((key) => {
      payload[key] = fields.namedItem(key).checked;
    });
    payload.target_roles = fields
      .namedItem('target_roles')
      .value.split(/[\n,]+/)
      .map((role) => role.trim())
      .filter(Boolean);
    if (!payload.target_roles.length) {
      toast('Add at least one target role.', true);
      return;
    }
    const result = await action(
      form.querySelector('[type=submit]'),
      '/api/settings',
      payload,
      'Search preferences saved.',
    );
    if (result) {
      settingsDirty = false;
      renderSettings(true);
    }
  });
  $('emailForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      fields = form.elements;
    const payload = {
      host: fields.namedItem('host').value.trim(),
      port: Number(fields.namedItem('port').value),
      user: fields.namedItem('user').value.trim(),
      password: fields.namedItem('password').value,
      folder: fields.namedItem('folder').value.trim(),
      enabled: fields.namedItem('enabled').checked,
    };
    const result = await action(
      form.querySelector('[type=submit]'),
      '/api/email',
      payload,
      'Email settings saved. Connection verification will appear in worker activity.',
    );
    if (result) {
      emailDirty = false;
      fields.namedItem('password').value = '';
      $('emailStatus').textContent = resultMessage(
        result,
        'Configuration saved. Inbox access has not been verified by this dashboard; check worker activity.',
      );
    }
  });
  $('emailForm').addEventListener('input', () => {
    emailDirty = true;
  });
  window.addEventListener('hashchange', () => showView(location.hash.slice(1) || 'overview'));
  window.addEventListener('focus', () => poll());
  showView(location.hash.slice(1) || 'overview');
  session().catch(() => {});
  poll().then(() => {
    if (state && new URLSearchParams(location.search).get('setup') === 'answers') {
      showView('answers');
      showAnswersEditor();
    }
  });
  setInterval(poll, 3000);
})();
