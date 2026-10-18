'use strict';
let token = '',
  privateLink = '',
  busy = false;
const $ = (id) => document.getElementById(id);
async function call(path, body) {
  if (!token) token = (await (await fetch('/api/session')).json()).token;
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-JobPilot-Token': token },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.detail || 'Request failed');
  return data;
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const data = await call('/api/remote/setup', {}),
      s = data.status;
    privateLink = data.pairing_link;
    $('status').textContent = s.starting ? 'Connecting…' : s.gateway.state;
    $('message').textContent =
      s.error ||
      s.gateway.error ||
      (s.gateway.url
        ? 'Remote access is connected. Pair a device below.'
        : 'Enable remote access to create a private pairing link.');
    $('pairing').hidden = !privateLink;
    if (privateLink) {
      $('qr').src = data.qr;
      $('pairLink').href = privateLink;
    }
    const items = data.cases.filter((c) => c.state === 'waiting');
    $('cases').replaceChildren();
    if (!items.length)
      $('cases').textContent =
        'No waiting browser sessions. Applications that need sign-in or verification will appear here.';
    for (const c of items) {
      const box = document.createElement('div');
      box.className = 'case';
      const name = document.createElement('strong');
      name.textContent = c.title + ' · ' + c.company;
      const description = document.createElement('p');
      description.textContent = c.note;
      box.append(name, description);
      $('cases').append(box);
    }
  } catch (e) {
    $('error').textContent = e.message;
  } finally {
    busy = false;
  }
}
for (const [id, action] of [
  ['enable', 'enable'],
  ['disable', 'disable'],
  ['revoke', 'revoke_devices'],
])
  $(id).onclick = async () => {
    try {
      $('error').textContent = '';
      await call('/api/remote/control', { action });
      await refresh();
    } catch (e) {
      $('error').textContent = e.message;
    }
  };
$('copy').onclick = async () => {
  try {
    await navigator.clipboard.writeText(privateLink);
    $('copy').textContent = 'Private link copied';
    setTimeout(() => ($('copy').textContent = 'Copy private link'), 2000);
  } catch (e) {
    $('error').textContent =
      'Open the remote application browser, then copy its address to your phone.';
  }
};
refresh();
setInterval(refresh, 4000);
