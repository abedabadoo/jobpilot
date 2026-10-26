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
    overview: 'Opportunities',
    applied: 'Applied',
    problems: 'Problems',
    profile: 'Profile & experience',
    connections: 'Email & alerts',
    settings: 'Preferences',
  };
  let state = null,
    token = '',
    activeView = 'overview',
    selectedJob = null;
  let settingsDirty = false,
    emailDirty = false,
    polling = false,
    connected = false,
    toastTimer,
    detailSignature = '';
  let problemItems = [],
    problemsAvailable = true;
  const resolvedProblems = new Set(),
    resolvingProblems = new Set();

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
          friendlyMessage(
            result.detail || result.message,
            `This action could not finish (HTTP ${response.status}). Please try again.`,
          ),
          `The local service returned HTTP ${response.status}.`,
        ),
      );
    return result;
  }
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $('toast').textContent = friendlyMessage(
      message,
      'This action could not finish. Please try again.',
    );
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
  function isApplied(job) {
    return (
      job.applied === true ||
      job.manual_applied === true ||
      ['applied', 'manual_applied', 'confirmed', 'manually_verified'].includes(
        String(job.status || '').toLowerCase(),
      )
    );
  }
  function friendlyMessage(
    value,
    fallback = 'Something needs attention. Review this opportunity and try again.',
  ) {
    const message = text(value, fallback);
    return /traceback|[A-Za-z]:[\\/]|\/(?:Users|home|tmp|var|workspace)\/|\b[A-Za-z]+(?:Error|Exception):/i.test(
      message,
    )
      ? fallback
      : message;
  }
  function renderMetrics() {
    $('appliedTotal').textContent = number(state.jobs.filter(isApplied).length);
  }
  function updateOptions(select, values, label) {
    const current = select.value,
      allValues = ['all', ...values];
    if (
      Array.from(select.options)
        .map((item) => item.value)
        .join('\n') === allValues.join('\n')
    )
      return;
    select.replaceChildren();
    [['all', label], ...values.map((value) => [value, value])].forEach(([value, label]) => {
      const option = el('option', '', label);
      option.value = value;
      select.append(option);
    });
    select.value = allValues.includes(current) ? current : 'all';
  }
  function externalJobLink(job, label, value = job.url) {
    const url = safeURL(value);
    if (!url) return el('span', '', label);
    const link = el('a', '', label);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.addEventListener('click', async (event) => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
        return;
      event.preventDefault();
      try {
        const result = await api('/api/browser/open_external', { job_id: job.id, url });
        if (!result.opened && result.status !== 'opened')
          throw new Error(
            'Your browser could not open the job link. Copy the link and open it in your browser.',
          );
      } catch (error) {
        toast(
          friendlyMessage(
            error.message,
            'Your browser could not open the job link. Copy the link and open it in your browser.',
          ),
          true,
        );
      }
    });
    return link;
  }
  function documentEntries(job) {
    const names = {
      resume_pdf: 'Resume PDF',
      resume_docx: 'Resume Word',
      cover_pdf: 'Cover letter PDF',
      cover_docx: 'Cover letter Word',
    };
    return artifactEntries(job.documents || job.application?.documents)
      .filter(
        ([, path]) =>
          typeof path === 'string' &&
          /^(?:[A-Za-z]:[\\/]|\/)/.test(path) &&
          /\.(?:pdf|docx)$/i.test(path),
      )
      .map(([key, path]) => [names[key] || path.split(/[\\/]/).pop(), path]);
  }
  async function setApplied(job, applied, node) {
    const result = await action(
      node,
      `/api/jobs/${encodeURIComponent(job.id)}/applied`,
      { applied },
      applied ? 'Application added to Applied.' : 'Moved back to opportunities.',
    );
    if (result && selectedJob === job.id && $('modal').open) showJob(job.id);
  }
  async function removeJob(job, node) {
    const result = await action(
      node,
      `/api/jobs/${encodeURIComponent(job.id)}/remove`,
      {},
      'Opportunity removed.',
    );
    if (result && selectedJob === job.id) closeModal();
  }
  function jobRow(job, applied) {
    const row = el('tr');
    row.dataset.jobId = String(job.id);
    const first = el('td'),
      cell = el('div', 'job-cell'),
      company = String(job.company || 'Unknown company');
    cell.append(el('div', 'company-avatar', company.slice(0, 1).toUpperCase()));
    const details = el('div');
    const title = externalJobLink(job, text(job.title, 'Untitled opportunity'));
    title.className = 'job-title';
    details.append(
      title,
      el('div', 'job-sub', `${company} · ${text(job.source, 'Unknown source')}`),
    );
    cell.append(details);
    first.append(cell);
    const fresh = el(
      'td',
      'freshness',
      applied
        ? prettyDate(job.applied_at || job.confirmed_at || job.created_at)
        : job.bucket_label || labels[bucket(job)],
    );
    const fit = el('td'),
      score = fitNumber(job),
      fitContent = el('div', 'fit-cell');
    const bar = el('span', 'fit-bar'),
      fill = el('i');
    fill.style.width = `${score || 0}%`;
    bar.append(fill);
    fitContent.append(bar, el('strong', '', score === null ? '—' : `${Math.round(score)}%`));
    fit.append(fitContent);
    const reviewCell = el('td'),
      review = button('Review', 'secondary compact', 'file', () => showJob(job.id));
    reviewCell.append(review);
    const appliedCell = el('td'),
      track = button(
        applied ? 'Move back' : 'Applied?',
        applied ? 'quiet compact' : 'track-button compact',
        applied ? 'arrow' : 'check',
      );
    track.addEventListener('click', () => setApplied(job, !applied, track));
    appliedCell.append(track);
    const removeCell = el('td'),
      remove = button('Remove', 'quiet danger-text compact', 'trash');
    remove.addEventListener('click', () => removeJob(job, remove));
    const busy = ['preparing', 'applying', 'submitting'].includes(job.status);
    track.disabled = busy;
    remove.disabled = busy;
    removeCell.append(remove);
    row.append(first, fresh, fit, reviewCell, appliedCell, removeCell);
    return row;
  }
  function renderJobs() {
    if (!state) return;
    const pool = state.jobs.filter((job) => !isApplied(job));
    updateOptions(
      $('sourceFilter'),
      [...new Set(pool.map((job) => String(job.source || 'Unknown source')))].sort(),
      'All sources',
    );
    const query = $('jobQuery').value.toLowerCase().trim(),
      source = $('sourceFilter').value;
    const jobs = sortedJobs(
      pool.filter(
        (job) =>
          (source === 'all' || String(job.source || 'Unknown source') === source) &&
          `${job.title || ''} ${job.company || ''}`.toLowerCase().includes(query),
      ),
    );
    $('jobsBody').replaceChildren(...jobs.map((job) => jobRow(job, false)));
    $('queueEmpty').hidden = jobs.length > 0;
    $('queueEmpty').querySelector('h3').textContent = pool.length
      ? 'No matching opportunities'
      : 'Your next role starts here';
    $('queueEmpty').querySelector('p').textContent = pool.length
      ? 'Try another role, company or source.'
      : 'Run a search or add a job link to start preparing.';
    $('visibleCount').textContent =
      `${number(jobs.length)} ${jobs.length === 1 ? 'opportunity' : 'opportunities'}`;
    renderApplied();
  }
  function renderApplied() {
    if (!state) return;
    const query = $('appliedQuery').value.toLowerCase().trim();
    const jobs = state.jobs
      .filter(
        (job) =>
          isApplied(job) && `${job.title || ''} ${job.company || ''}`.toLowerCase().includes(query),
      )
      .sort(
        (a, b) =>
          (Date.parse(b.applied_at || b.confirmed_at) || 0) -
          (Date.parse(a.applied_at || a.confirmed_at) || 0),
      );
    $('appliedBody').replaceChildren(...jobs.map((job) => jobRow(job, true)));
    $('appliedEmpty').hidden = jobs.length > 0;
    $('appliedCount').textContent =
      `${number(jobs.length)} ${jobs.length === 1 ? 'application' : 'applications'}`;
  }
  function renderWorker() {
    const worker = state.worker || {},
      settings = state.settings || {};
    $('workerState').textContent = worker.searching
      ? 'Searching for roles'
      : settings.search_enabled
        ? 'Search scheduled'
        : 'Search paused';
    $('workerDot').className =
      `dot ${worker.searching || settings.search_enabled ? 'teal' : 'amber'}`;
    $('workerCurrent').textContent = worker.searching
      ? 'New listings will appear in your opportunities.'
      : settings.search_enabled
        ? `Checks every ${settings.search_interval_minutes || 30} minutes.`
        : 'Search when you want, or enable automatic discovery.';
    $('heartbeat').textContent = relative(worker.heartbeat);
    $('lastSearch').textContent = relative(worker.last_search);
    $('toggleSearch').replaceChildren(
      icon(settings.search_enabled ? 'pause' : 'play'),
      el('span', '', settings.search_enabled ? 'Pause search' : 'Resume search'),
    );
    $('toggleSearch').disabled = !connected;
    $('searchNow').disabled = !connected;
    $('workerExtra').replaceChildren(
      el('span', '', 'Document preparation'),
      el(
        'strong',
        '',
        worker.model_status
          ? friendlyMessage(worker.model_status, 'Local model status unavailable')
          : 'Uses your saved career facts',
      ),
    );
  }
  function renderProblems() {
    const open = problemItems.filter(
      (problem) => !problem.resolved && !resolvedProblems.has(String(problem.id)),
    );
    $('problemsNavCount').hidden = !open.length;
    $('problemsNavCount').textContent = number(open.length);
    $('problemCount').textContent = open.length ? `${open.length} to review` : '';
    const items = open.map((problem) => {
      const card = el('article', 'panel problem-card'),
        body = el('div');
      const heading = el('h2');
      heading.append(
        externalJobLink(
          { id: problem.job_id || null, url: problem.url },
          `${text(problem.title, 'Job search')} · ${text(problem.company, 'JobPilot')}`,
        ),
      );
      const fallback = /email/i.test(problem.category || '')
        ? 'Email alerts could not be checked. Review your email connection and try again.'
        : /search|discovery/i.test(problem.category || '')
          ? 'This search could not finish. Try again later or add the job link yourself.'
          : 'Documents could not be prepared. Open this opportunity and try generating them again.';
      body.append(
        heading,
        el('p', '', friendlyMessage(problem.message, fallback)),
        el('time', '', prettyDate(problem.created_at, true)),
      );
      const resolve = button('Mark resolved', 'secondary compact', 'check');
      resolve.disabled = resolvingProblems.has(String(problem.id));
      resolve.addEventListener('click', async () => {
        const id = String(problem.id);
        if (resolvingProblems.has(id)) return;
        resolvingProblems.add(id);
        resolve.disabled = true;
        try {
          await api(`/api/problems/${encodeURIComponent(problem.id)}/resolve`, {});
          resolvedProblems.add(id);
          toast('Problem marked resolved.');
        } catch (error) {
          toast(error.message, true);
        } finally {
          resolvingProblems.delete(id);
          renderProblems();
        }
      });
      card.append(body, resolve);
      return card;
    });
    if (!items.length) {
      const empty = el('div', 'panel empty-state');
      empty.append(
        icon(problemsAvailable ? 'check' : 'info'),
        el(
          'h2',
          '',
          problemsAvailable ? 'No problems to review' : 'Problems are temporarily unavailable',
        ),
        el(
          'p',
          '',
          problemsAvailable
            ? 'Messages that need your attention will appear here.'
            : 'The local service will reconnect automatically.',
        ),
      );
      items.push(empty);
    }
    $('problemsList').replaceChildren(...items);
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
      ['Interests', profile.interests],
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
    const email = state?.settings?.email || {},
      sync = state?.email_sync || {};
    const form = $('emailForm');
    if (!emailDirty) {
      ['host', 'port', 'limit', 'lookback_days'].forEach((key) => {
        if (email[key] !== undefined) form.elements.namedItem(key).value = email[key];
      });
      form.elements.namedItem('user').value = text(email.username ?? email.user, '');
      form.elements.namedItem('folder').value = text(email.mailbox ?? email.folder, 'INBOX');
      form.elements.namedItem('enabled').checked = email.enabled ?? true;
    }
    const busy = ['checking', 'syncing'].includes(sync.state);
    form.querySelector('[type=submit]').disabled = busy || !connected;
    $('syncEmail').disabled = busy || !connected;
    $('emailStatus').textContent = friendlyMessage(
      sync.message,
      busy
        ? 'Checking your inbox…'
        : sync.state === 'connected'
          ? 'Inbox connection verified.'
          : sync.credential_saved || email.credential_saved
            ? 'App password saved. Connect & test to verify the inbox.'
            : 'Not connected. Add your Gmail address and an app password.',
    );
    const stats = $('emailSyncStats');
    stats.replaceChildren();
    stats.hidden = !sync.checked_at && sync.messages_checked === undefined;
    if (!stats.hidden) {
      [
        ['Last checked', sync.checked_at ? prettyDate(sync.checked_at, true) : 'Not checked'],
        ['Messages checked', sync.messages_checked ?? 0],
        ['Job links found', sync.links_found ?? 0],
        ['Opportunities added', sync.imported ?? 0],
      ].forEach(([label, value]) => {
        const item = el('div');
        item.append(el('span', '', label), el('strong', '', value));
        stats.append(item);
      });
      if (sync.truncated)
        stats.append(
          el(
            'p',
            'truncated-warning',
            `Checked ${number(sync.messages_checked ?? 0)} of ${number(sync.messages_available ?? 0)} recent messages; increase the scan limit in Advanced.`,
          ),
        );
    }
  }
  async function emailOperation(operation) {
    const form = $('emailForm'),
      fields = form.elements,
      save = form.querySelector('[type=submit]'),
      sync = $('syncEmail');
    if (!form.reportValidity()) return;
    save.disabled = true;
    sync.disabled = true;
    try {
      if (operation === 'check' || emailDirty) {
        await api('/api/email', {
          host: fields.namedItem('host').value.trim(),
          port: Number(fields.namedItem('port').value),
          user: fields.namedItem('user').value.trim(),
          password: fields.namedItem('password').value,
          folder: fields.namedItem('folder').value.trim(),
          enabled: fields.namedItem('enabled').checked,
          limit: Number(fields.namedItem('limit').value),
          lookback_days: Number(fields.namedItem('lookback_days').value),
        });
        emailDirty = false;
        fields.namedItem('password').value = '';
      }
      const result = await api(`/api/email/${operation}`, {});
      $('emailStatus').textContent =
        operation === 'check'
          ? 'Checking the inbox connection…'
          : 'Checking recent messages for job links…';
      toast(operation === 'check' ? 'Inbox check started.' : 'Email sync started.');
      await poll();
      return result;
    } catch (error) {
      $('emailStatus').textContent = friendlyMessage(
        error.message,
        'The inbox could not be checked. Verify your Gmail address and app password, then try again.',
      );
      toast($('emailStatus').textContent, true);
    } finally {
      renderConnections();
    }
  }
  function render() {
    renderMetrics();
    renderIdentity();
    renderJobs();
    renderWorker();
    renderConnections();
    renderProblems();
    if (activeView === 'profile') renderProfile();
    renderSettings();
    if (selectedJob !== null && $('modal').open && $('modalContent').dataset.jobId) {
      const job = state.jobs.find((item) => String(item.id) === String(selectedJob));
      if (job && JSON.stringify(job) !== detailSignature) showJob(job.id);
    }
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const [response, issues] = await Promise.all([
        fetch('/api/state', { cache: 'no-store' }),
        fetch('/api/problems', { cache: 'no-store' }).catch(() => null),
      ]);
      if (!response.ok) throw new Error('The local service is unavailable.');
      const result = await response.json();
      if (!result || !Array.isArray(result.jobs))
        throw new Error('Dashboard data is not ready yet.');
      state = result;
      connected = true;
      try {
        const data = issues?.ok ? await issues.json() : null;
        problemsAvailable = Array.isArray(data?.problems);
        if (problemsAvailable) problemItems = data.problems;
      } catch (_) {
        problemsAvailable = false;
      }
      $('connectionDot').className = 'dot teal';
      $('connectionLabel').textContent = 'Local service connected';
      $('serviceBanner').hidden = true;
      $('lastUpdated').textContent =
        `Updated ${new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(new Date())}`;
      render();
    } catch (_) {
      connected = false;
      $('connectionDot').className = 'dot amber';
      $('connectionLabel').textContent = 'Local service unavailable';
      $('serviceBanner').hidden = false;
      $('serviceBanner').textContent =
        'The local service is unavailable. JobPilot will reconnect automatically. Displayed data may be from the last update.';
      ['searchNow', 'toggleSearch'].forEach((id) => {
        $(id).disabled = true;
      });
    } finally {
      polling = false;
    }
  }
  function showView(view) {
    if (!viewLabels[view]) view = 'overview';
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
    if (view === 'settings') renderSettings();
    if (view === 'applied') renderApplied();
    if (view === 'problems') renderProblems();
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function openModal(title, eyebrow = '', wide = false) {
    $('modalTitle').textContent = title;
    $('modalEyebrow').textContent = eyebrow;
    $('modalContent').replaceChildren();
    delete $('modalContent').dataset.jobId;
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
    footer.append(el('p', 'form-note', 'Imported jobs appear in your opportunities.'));
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
    const content = openModal(text(job.title, 'Opportunity details'), 'REVIEW & PREPARE', true);
    selectedJob = job.id;
    content.dataset.jobId = String(job.id);
    detailSignature = JSON.stringify(job);
    content.append(
      el(
        'p',
        'detail-subtitle',
        `${text(job.company)} · ${text(job.location, 'Location not specified')}`,
      ),
    );
    const facts = el('div', 'detail-facts');
    [
      ['Fit', fitNumber(job) === null ? 'Not assessed' : `${Math.round(fitNumber(job))}%`],
      ['Posted', job.bucket_label || labels[bucket(job)]],
      ['Tracking', isApplied(job) ? 'Applied' : 'Not applied'],
    ].forEach(([label, value]) => {
      const fact = el('div', 'detail-fact');
      fact.append(el('span', '', label), el('strong', '', value));
      facts.append(fact);
    });
    content.append(facts);
    const links = el('div', 'detail-links');
    const posting = externalJobLink(job, 'View job posting');
    posting.classList.add('button', 'secondary');
    posting.prepend(icon('external'));
    links.append(posting);
    if (safeURL(job.apply_url) && job.apply_url !== job.url) {
      const apply = externalJobLink(job, 'Open application page', job.apply_url);
      apply.classList.add('button', 'secondary');
      apply.prepend(icon('external'));
      links.append(apply);
    }
    content.append(links);
    const keywordSection = el('section', 'detail-section');
    keywordSection.append(el('h3', '', 'Keywords from the job posting'));
    const keywords = job.keywords || {},
      terms =
        Array.isArray(keywords.terms) && keywords.terms.length
          ? keywords.terms
          : [...(keywords.tools || []), ...(keywords.skills || [])];
    const unique = [...new Set(terms.filter((term) => typeof term === 'string' && term.trim()))],
      chips = el('div', 'keyword-chips');
    unique.forEach((term) => {
      const matched = (keywords.matched || []).some(
        (value) => String(value).toLowerCase() === term.toLowerCase(),
      );
      const chip = el('span', `keyword-chip ${matched ? 'matched' : ''}`, term);
      if (matched) chip.title = 'Also present in your saved profile';
      chips.append(chip);
    });
    keywordSection.append(
      unique.length
        ? chips
        : el('p', 'modal-note', 'Keywords will appear after the job description is assessed.'),
    );
    content.append(keywordSection);
    const docs = el('section', 'detail-section document-section');
    docs.append(
      el('h3', '', 'Your application documents'),
      el('p', 'modal-note', 'Built from your saved career facts. Review them before applying.'),
    );
    const entries = documentEntries(job),
      downloads = el('div', 'artifact-links');
    entries.forEach(([label, path]) => {
      const row = el('div', 'document-file'),
        open = button(`Open ${label}`, 'secondary', 'file'),
        link = el('a', 'button quiet');
      open.addEventListener('click', async () => {
        open.disabled = true;
        try {
          const result = await api('/api/artifact/open', { path });
          toast(`Opening ${text(result.name, label)} in your document app.`);
        } catch (error) {
          dialogError(error);
        } finally {
          open.disabled = false;
        }
      });
      link.href = `/api/artifact?path=${encodeURIComponent(path)}`;
      link.setAttribute('download', '');
      link.setAttribute('aria-label', `Download ${label}`);
      link.append(icon('download'), document.createTextNode('Download'));
      row.append(open, link);
      downloads.append(row);
    });
    if (entries.length) docs.append(downloads);
    else docs.append(el('p', 'document-empty', 'No documents generated for this role yet.'));
    const busy = ['preparing', 'applying', 'submitting'].includes(job.status),
      prepare = button(
        busy
          ? 'Generating documents…'
          : entries.length
            ? 'Regenerate documents'
            : 'Generate documents',
        'primary',
        'file',
      );
    prepare.disabled = busy;
    prepare.addEventListener('click', async () => {
      const result = await action(
        prepare,
        `/api/jobs/${encodeURIComponent(job.id)}/prepare`,
        {},
        'Document generation requested.',
      );
      if (result) showJob(job.id);
    });
    docs.append(prepare);
    content.append(docs);
    const description = el('section', 'detail-section');
    description.append(
      el('h3', '', 'Job description'),
      el(
        'div',
        'detail-description',
        text(
          job.description,
          'No description is available. Open the job posting for the current requirements.',
        ),
      ),
    );
    content.append(description);
    const actions = el('div', 'detail-actions'),
      track = button(
        isApplied(job) ? 'Move back to opportunities' : 'Mark as applied',
        'secondary',
        'check',
      );
    track.disabled = busy;
    track.addEventListener('click', () => setApplied(job, !isApplied(job), track));
    const remove = button('Remove opportunity', 'quiet danger-text', 'trash');
    remove.disabled = busy;
    remove.addEventListener('click', () => removeJob(job, remove));
    actions.append(track, remove);
    content.append(
      actions,
      el('p', 'form-note', 'Apply in your regular browser, then mark the role as applied here.'),
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
  hydrateIcons();
  $('todayLabel').textContent = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date());
  $('closeModal').addEventListener('click', closeModal);
  $('modal').addEventListener('close', () => {
    selectedJob = null;
    detailSignature = '';
  });
  document
    .querySelectorAll('[data-view]')
    .forEach((node) => node.addEventListener('click', () => showView(node.dataset.view)));
  document
    .querySelectorAll('[data-open-import]')
    .forEach((node) => node.addEventListener('click', () => showImport('email')));
  $('openImport').addEventListener('click', () => showImport());
  $('cleanupJobs').addEventListener('click', showCleanupPreview);
  ['jobQuery', 'sourceFilter'].forEach((id) =>
    $(id).addEventListener(id === 'jobQuery' ? 'input' : 'change', renderJobs),
  );
  $('appliedQuery').addEventListener('input', renderApplied);
  $('searchNow').addEventListener('click', () =>
    action($('searchNow'), '/api/control', { action: 'search' }, 'Search requested.'),
  );
  $('toggleSearch').addEventListener('click', () =>
    action(
      $('toggleSearch'),
      '/api/control',
      { search_enabled: !state.settings.search_enabled },
      state.settings.search_enabled ? 'Automatic search paused.' : 'Automatic search resumed.',
    ),
  );
  $('editProfile').addEventListener('click', showProfileEditor);
  $('settingsForm').addEventListener('input', () => {
    settingsDirty = true;
  });
  $('settingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      fields = form.elements,
      payload = {};
    ['location', 'ollama_url', 'model'].forEach((key) => {
      payload[key] = fields.namedItem(key).value.trim();
    });
    ['search_interval_minutes', 'min_fit'].forEach((key) => {
      payload[key] = Number(fields.namedItem(key).value);
    });
    ['remote', 'search_enabled', 'keep_awake', 'startup'].forEach((key) => {
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
      'Preferences saved.',
    );
    if (result) {
      settingsDirty = false;
      renderSettings(true);
    }
  });
  $('emailForm').addEventListener('input', () => {
    emailDirty = true;
  });
  $('emailForm').addEventListener('submit', (event) => {
    event.preventDefault();
    emailOperation('check');
  });
  $('syncEmail').addEventListener('click', () => emailOperation('sync'));
  $('gmailHelp').addEventListener('click', async (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    try {
      await api('/api/browser/open_external', { url: event.currentTarget.href });
    } catch (error) {
      toast(
        friendlyMessage(error.message, 'Copy the Google app-password link into your browser.'),
        true,
      );
    }
  });
  window.addEventListener('hashchange', () => showView(location.hash.slice(1) || 'overview'));
  window.addEventListener('focus', () => poll());
  showView(location.hash.slice(1) || 'overview');
  session().catch(() => {});
  poll();
  setInterval(poll, 3000);
})();
