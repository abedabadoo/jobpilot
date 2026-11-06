/* Runs only in Chrome's isolated extension world, on an explicit user action. */
(() => {
  if (globalThis.JobPilotAutofill) return;
  const core = globalThis.JobPilotCore;
  let lastChanges = [];
  function roots() {
    const found = [];
    const visit = (root) => {
      found.push(root);
      for (const element of root.querySelectorAll('*')) {
        if (element.shadowRoot) visit(element.shadowRoot);
        if (element.tagName === 'IFRAME') {
          try {
            if (element.contentDocument) visit(element.contentDocument);
          } catch {
            /* Cross-origin frames require manual entry. */
          }
        }
      }
    };
    visit(document);
    return found;
  }
  function accessibleText(element) {
    const root = element.getRootNode();
    const ids = (element.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    const labelled = ids
      .map((id) => root.getElementById?.(id)?.textContent || '')
      .join(' ')
      .trim();
    const labels = Array.from(element.labels || [])
      .map((label) => {
        const copy = label.cloneNode(true);
        for (const control of copy.querySelectorAll('input,select,textarea,button'))
          control.remove();
        return copy.textContent;
      })
      .join(' ')
      .trim();
    return (
      labelled ||
      element.getAttribute('aria-label') ||
      labels ||
      element.getAttribute('placeholder') ||
      ''
    );
  }
  function contextFor(element) {
    const fieldset = element.closest('fieldset');
    const group = element.closest('[role="group"], [role="radiogroup"]');
    const section = element.closest('section, article');
    return (
      fieldset?.querySelector(':scope > legend')?.textContent ||
      (group && accessibleText(group)) ||
      section?.querySelector('h1,h2,h3,h4')?.textContent ||
      ''
    ).trim();
  }
  function descriptor(element) {
    return {
      label: accessibleText(element),
      name: element.name || element.id || '',
      type: element.type || '',
      autocomplete: element.autocomplete || '',
      context: contextFor(element),
    };
  }
  function visible(element) {
    const view = element.ownerDocument.defaultView;
    if (
      !view ||
      element.disabled ||
      element.readOnly ||
      element.closest('[inert]') ||
      element.getAttribute('aria-disabled') === 'true'
    )
      return false;
    // getClientRects alone includes opacity-zero and clipped honeypots. Walk
    // rendering ancestors, including shadow hosts and same-origin frame hosts.
    // Do not require viewport intersection: ordinary below-fold fields are safe.
    if (!Array.from(element.getClientRects()).some((rect) => rect.width > 1 && rect.height > 1))
      return false;
    let current = element;
    while (current) {
      const currentView = current.ownerDocument.defaultView;
      if (!currentView) return false;
      const style = currentView.getComputedStyle(current);
      if (
        style.display === 'none' ||
        ['hidden', 'collapse'].includes(style.visibility) ||
        Number(style.opacity) === 0 ||
        current.hasAttribute('inert') ||
        current.getAttribute('aria-hidden') === 'true'
      )
        return false;
      const rect = current.getBoundingClientRect();
      if (
        (['hidden', 'clip'].includes(style.overflowX) && rect.width <= 1) ||
        (['hidden', 'clip'].includes(style.overflowY) && rect.height <= 1)
      )
        return false;
      const clip = style.clip.match(/^rect\((.+)\)$/);
      if (clip) {
        const edges = clip[1]
          .split(/[,\s]+/)
          .filter(Boolean)
          .map(Number.parseFloat);
        if (
          edges.length === 4 &&
          edges.every(Number.isFinite) &&
          (edges[1] <= edges[3] || edges[2] <= edges[0])
        )
          return false;
      }
      if (/^inset\(50%(?:\s|\))|^circle\(0(?:px|%|\))/.test(style.clipPath)) return false;
      const root = current.getRootNode();
      current = current.parentElement || root.host || currentView.frameElement;
    }
    return true;
  }
  function setNative(element, property, value) {
    let prototype = Object.getPrototypeOf(element);
    while (prototype) {
      const setter = Object.getOwnPropertyDescriptor(prototype, property)?.set;
      if (setter) {
        setter.call(element, value);
        break;
      }
      prototype = Object.getPrototypeOf(prototype);
    }
    const EventClass = element.ownerDocument.defaultView.Event;
    element.dispatchEvent(new EventClass('input', { bubbles: true, composed: true }));
    element.dispatchEvent(new EventClass('change', { bubbles: true, composed: true }));
  }
  function fileList(element, files) {
    const transfer = new element.ownerDocument.defaultView.DataTransfer();
    for (const file of files) transfer.items.add(file);
    return transfer.files;
  }
  function report() {
    return {
      filled: [],
      preserved: [],
      unanswered: [],
      skipped: [],
      notes: [
        'Review every answer. Submit and Next are always yours to click.',
        'Custom controls and cross-origin or closed-shadow forms may need manual entry.',
      ],
    };
  }
  function item(label, reason) {
    return { label: String(label).trim().slice(0, 180) || 'Unlabelled field', reason };
  }
  function resolve(profile, key, descriptor, counts) {
    if (!key.includes('.')) return profile[key];
    const [list, field] = key.split('.');
    const entries = profile[list] || [];
    // Only numbered sections or one unique record/control are unambiguous.
    const number = descriptor.context.match(
      /\b(?:employment|experience|work history|education|school)\s*(?:#|number)?\s*(\d+)\b/i,
    );
    const index = number
      ? Number(number[1]) - 1
      : entries.length === 1 && counts.get(key) === 1
        ? 0
        : -1;
    return index >= 0 ? entries[index]?.[field] : undefined;
  }
  function controls() {
    return roots().flatMap((root) => Array.from(root.querySelectorAll('input, textarea, select')));
  }
  async function fill(profileInput, replace = false) {
    const profile = core.sanitizeProfile(profileInput);
    const result = report();
    const changes = [];
    const elements = controls();
    const descriptors = new Map(elements.map((element) => [element, descriptor(element)]));
    const matches = new Map(
      elements.map((element) => [element, core.inferField(descriptors.get(element))]),
    );
    const counts = new Map();
    for (const [element, match] of matches)
      if (match.key && element.type !== 'radio')
        counts.set(match.key, (counts.get(match.key) || 0) + 1);
    const seenRadio = new Set();
    for (const element of elements) {
      if (!visible(element) || /^(file|hidden|button|submit|reset|image)$/i.test(element.type))
        continue;
      const desc = descriptors.get(element);
      let match = matches.get(element);
      let label = desc.label || desc.name;
      if (element.type === 'radio') {
        if (seenRadio.has(element)) continue;
        const group = elements.filter(
          (other) =>
            other.type === 'radio' &&
            other.name &&
            other.name === element.name &&
            other.form === element.form &&
            other.getRootNode() === element.getRootNode(),
        );
        for (const radio of group) seenRadio.add(radio);
        const question =
          desc.context || element.closest('[role="radiogroup"]')?.getAttribute('aria-label') || '';
        label = question || label;
        match = core.inferField({ ...desc, label: question, name: element.name });
        if (match.blocked) {
          result.skipped.push(item(label, 'Sensitive or consent question: answer manually.'));
          continue;
        }
        if (
          !match.key ||
          !core.BOOLEAN_FIELDS.includes(match.key) ||
          typeof profile[match.key] !== 'boolean'
        ) {
          result.unanswered.push(
            item(label, 'No unambiguous explicit yes/no answer in your profile.'),
          );
          continue;
        }
        if (!replace && group.some((radio) => radio.checked)) {
          result.preserved.push(item(label, 'Existing choice kept.'));
          continue;
        }
        const value = match.invert ? !profile[match.key] : profile[match.key];
        const selected = core.selectOption(
          group.map((radio, index) => ({
            value: String(index),
            label: accessibleText(radio),
            disabled: !visible(radio),
          })),
          value,
        );
        if (selected === null) {
          result.unanswered.push(item(label, 'No exact Yes/No choice found.'));
          continue;
        }
        const target = group[Number(selected)];
        const before = group.map((radio) => ({ element: radio, checked: radio.checked }));
        setNative(target, 'checked', true);
        changes.push({ kind: 'radio', before, target });
        result.filled.push(item(label, 'Selected explicit profile answer.'));
        continue;
      }
      if (match.blocked || element.type === 'checkbox') {
        result.skipped.push(
          item(label, 'Sensitive, consent, or checkbox control: answer manually.'),
        );
        continue;
      }
      if (!replace && String(element.value || '').trim()) {
        result.preserved.push(item(label, 'Existing answer kept.'));
        continue;
      }
      if (!match.key) {
        result.unanswered.push(item(label, 'No confident profile match. Answer manually.'));
        continue;
      }
      let value = resolve(profile, match.key, desc, counts);
      if (
        value === null ||
        value === undefined ||
        value === '' ||
        (Array.isArray(value) && !value.length)
      ) {
        result.unanswered.push(
          item(
            label,
            match.key.includes('.')
              ? 'History record is missing or ambiguous. Use numbered sections or enter manually.'
              : 'Add this answer to your profile or enter it manually.',
          ),
        );
        continue;
      }
      if (match.invert && typeof value === 'boolean') value = !value;
      if (Array.isArray(value)) value = value.join(', ');
      if (element.tagName === 'SELECT') {
        value = core.selectOption(
          Array.from(element.options).map((option) => ({
            value: option.value,
            label: option.label,
            disabled: option.disabled,
          })),
          value,
          match.key,
        );
        if (value === null || element.multiple) {
          result.unanswered.push(item(label, 'No exact supported option. Choose manually.'));
          continue;
        }
      } else if (typeof value === 'boolean') {
        result.unanswered.push(
          item(label, 'Yes/no questions need a native select or radio group.'),
        );
        continue;
      } else value = String(value);
      if (
        (element.type === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(value)) ||
        (element.type === 'month' && !/^\d{4}-\d{2}$/.test(value))
      ) {
        result.unanswered.push(item(label, 'Date format needs manual review.'));
        continue;
      }
      const before = element.value;
      setNative(element, 'value', value);
      if (element.value !== String(value)) {
        setNative(element, 'value', before);
        result.unanswered.push(item(label, 'The form rejected this value. Enter manually.'));
        continue;
      }
      changes.push({ kind: 'value', element, before, after: element.value });
      result.filled.push(item(label, 'Filled from your local profile.'));
    }
    for (const root of roots()) {
      for (const element of root.querySelectorAll(
        '[role="combobox"], [role="listbox"], [role="textbox"], [role="checkbox"], [contenteditable="true"]',
      )) {
        if (element.matches('input,textarea,select') || !visible(element)) continue;
        result.unanswered.push(
          item(
            accessibleText(element) || element.getAttribute('role'),
            'Custom control: answer manually.',
          ),
        );
      }
    }
    if (changes.length) lastChanges = changes;
    return result;
  }
  async function attach(file, replace = false) {
    const result = report();
    const bytes = new Uint8Array(file.data || []);
    const error = core.validateResume({ name: file.name, size: bytes.length }, bytes);
    if (error) throw new Error(error);
    const candidates = controls().filter(
      (element) =>
        element.type === 'file' &&
        !element.disabled &&
        /\b(resume|résumé|cv|curriculum vitae)\b/i.test(
          `${accessibleText(element)} ${element.name} ${element.id}`,
        ) &&
        !/cover|portfolio|photo|passport/i.test(
          `${accessibleText(element)} ${element.name} ${element.id}`,
        ),
    );
    if (candidates.length !== 1) {
      result.unanswered.push(
        item(
          'Resume attachment',
          candidates.length
            ? 'Multiple resume upload fields. Choose and upload manually.'
            : 'No clearly labelled resume file input found. Upload manually.',
        ),
      );
      return result;
    }
    const element = candidates[0];
    if (element.files.length && !replace) {
      result.preserved.push(
        item('Resume attachment', 'Existing file kept. Enable replacement to change it.'),
      );
      return result;
    }
    const accepts = (element.accept || '')
      .toLowerCase()
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    const mime = /\.pdf$/i.test(file.name)
      ? 'application/pdf'
      : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    const ext = /\.pdf$/i.test(file.name) ? '.pdf' : '.docx';
    if (
      accepts.length &&
      !accepts.includes(ext) &&
      !accepts.includes(mime) &&
      !accepts.includes('*/*') &&
      !accepts.includes('application/*')
    ) {
      result.unanswered.push(
        item('Resume attachment', 'This upload field does not accept the selected file type.'),
      );
      return result;
    }
    const before = Array.from(element.files);
    const selected = new element.ownerDocument.defaultView.File([bytes], file.name, { type: mime });
    setNative(element, 'files', fileList(element, [selected]));
    lastChanges = [{ kind: 'file', element, before, after: selected }];
    result.filled.push(
      item('Resume attachment', `Attached ${file.name}. Review the website preview.`),
    );
    return result;
  }
  async function undo() {
    const result = report();
    for (const change of lastChanges.slice().reverse()) {
      if (change.kind === 'radio') {
        if (!change.target.isConnected || !change.target.checked) {
          result.preserved.push(item('Choice', 'Changed since autofill; kept your edit.'));
          continue;
        }
        for (const before of change.before) setNative(before.element, 'checked', before.checked);
      } else {
        if (!change.element.isConnected) continue;
        if (change.kind === 'file') {
          if (change.element.files.length !== 1 || change.element.files[0] !== change.after) {
            result.preserved.push(item('Resume', 'Changed since attachment; kept your file.'));
            continue;
          }
          setNative(change.element, 'files', fileList(change.element, change.before));
        } else {
          if (change.element.value !== change.after) {
            result.preserved.push(
              item(accessibleText(change.element), 'Changed since autofill; kept your edit.'),
            );
            continue;
          }
          setNative(change.element, 'value', change.before);
        }
      }
      result.filled.push(item('Undo', 'Restored previous answer.'));
    }
    if (!lastChanges.length) result.notes.unshift('Nothing to undo on this page.');
    lastChanges = [];
    return result;
  }
  globalThis.JobPilotAutofill = { fill, attach, undo };
})();
