/* Mini DFS dashboard: polls /api/state once a second and draws the cluster. */
'use strict';

/* ------------------------------------------------------------------ helpers */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const now = () => Date.now() / 1000;
const MB = 1048576;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'html') el.innerHTML = value;
    else if (key === 'style') el.style.cssText = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const ICONS = {
  upload: '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/>',
  zap: '<path d="M13 2 4 14h8l-1 8 9-12h-8z"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5 8.5 8.5 0 1 0 20.5 14.5z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  cpu: '<rect x="5" y="5" width="14" height="14" rx="2.5"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  laptop: '<rect x="4" y="5" width="16" height="11" rx="2"/><path d="M2 20h20"/>',
  file: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>',
  shield: '<path d="M12 3 4.5 6v6c0 4.6 3.2 7.9 7.5 9 4.3-1.1 7.5-4.4 7.5-9V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
  network: '<rect x="9" y="2.5" width="6" height="5" rx="1.2"/><rect x="2.5" y="16.5" width="6" height="5" rx="1.2"/><rect x="9" y="16.5" width="6" height="5" rx="1.2"/><rect x="15.5" y="16.5" width="6" height="5" rx="1.2"/><path d="M12 7.5v9M5.5 16.5V12h13v4.5"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  activity: '<path d="M3 12h4l3 7 4-14 3 7h4"/>',
  dice: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8.5 8.5h.01M15.5 8.5h.01M12 12h.01M8.5 15.5h.01M15.5 15.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  heart: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
  save: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  logout: '<path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="m15 16 4-4-4-4"/><path d="M19 12H9"/>',
};

function svgIcon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}
function icon(name, extra = '') {
  return h('span', { class: `icon ${extra}`.trim(), html: svgIcon(name) });
}
const spinner = () => h('span', { class: 'spinner', 'aria-hidden': 'true' });

const fmtSize = (b) => (!b ? '0 KB' : b >= MB ? `${+(b / MB).toFixed(b >= 10 * MB ? 0 : 2)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour12: false });
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const chunkIndex = (id) => Number((id.match(/_(\d+)$/) || [])[1] ?? 0);
const chunkFile = (id) => id.replace(/_\d+$/, '');

const PALETTE = ['#5b8cff', '#f472b6', '#34d399', '#fbbf24', '#a78bfa', '#22d3ee', '#fb7185', '#a3e635', '#f97316', '#2dd4bf'];
const EVENT_TONE = {
  node_joined: 'info', node_back: 'info', node_dead: 'bad', repaired: 'accent', healthy: 'ok',
  degraded: 'warn', upload: 'accent', delete: 'muted', cleanup: 'info', repair_failed: 'bad',
  error: 'bad', info: 'muted',
};
const EVENT_LABEL = {
  node_joined: 'join', node_back: 'rejoin', node_dead: 'dead', repaired: 'repair', healthy: 'healthy',
  degraded: 'degraded', upload: 'upload', delete: 'delete', cleanup: 'cleanup', repair_failed: 'failed',
  error: 'error', info: 'master',
};
const TONE_ICON = { ok: 'check', bad: 'alert', warn: 'alert', info: 'info', accent: 'info', muted: 'info' };

/* -------------------------------------------------------------------- state */

const S = {
  data: null,
  cfg: null,
  first: true,
  online: true,
  since: 0,
  events: [],
  owners: new Map(),        // chunk id -> {file, index, nodes, live_nodes, size}
  lastSeen: {},             // port -> estimated time of last heartbeat (s)
  wires: {},                // port -> bezier points for the node -> master wire
  colors: new Map(),
  selected: null,
  sigs: {},
  mapPrev: {},
  timer: null,
  polling: false,
  pollAgain: false,
  resultsLoaded: false,
  busy: 0,
  admin: { configured: true, signed_in: false },
  activityAt: 0,            // when the activity log was last fetched (ms)
};

function colorFor(name) {
  if (!S.colors.has(name)) S.colors.set(name, PALETTE[S.colors.size % PALETTE.length]);
  return S.colors.get(name);
}
const fileByName = (name) => S.data?.files.find((f) => f.name === name);
const nodeBy = (port) => S.data?.nodes.find((n) => n.port === port);
const nodeCard = (port) => document.getElementById(`node-${port}`);
const eventsAfter = (t) => S.events.filter((e) => e.time > t);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = null;
  try { body = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    if (response.status === 401) setAdmin({ ...S.admin, signed_in: false });
    throw new Error(body?.error || `HTTP ${response.status}`);
  }
  return body;
}

const postJSON = (data) => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
});

/* ----------------------------------------------------------------- polling */

async function poll() {
  clearTimeout(S.timer);
  if (S.polling) { S.pollAgain = true; return; }
  S.polling = true;
  try {
    const data = await api(`/api/state?since=${S.since}`);
    S.online = true;
    ingest(data);
  } catch (err) {
    S.online = false;
    renderOffline();
  } finally {
    S.polling = false;
    S.timer = setTimeout(poll, S.pollAgain ? 0 : 1000);
    S.pollAgain = false;
  }
}
const pollNow = () => poll();

function ingest(d) {
  const t = now();
  const first = S.first;
  S.data = d;
  S.cfg = d.config;
  setAdmin(d.admin);
  if (first) {
    buildNodes(d.config.node_ports);
    buildAdminNodes(d.config.node_ports);
    fillConfig(d.config);
  }

  S.owners = new Map();
  for (const f of d.files) {
    colorFor(f.name);
    f.chunks.forEach((c, i) => S.owners.set(c.id, { ...c, file: f.name, index: i }));
  }
  if (!S.selected || !fileByName(S.selected)) S.selected = d.files[0]?.name ?? null;

  for (const n of d.nodes) {
    if (n.last_seen_ago == null) { delete S.lastSeen[n.port]; continue; }
    const seen = t - n.last_seen_ago;
    const prev = S.lastSeen[n.port];
    if (prev == null || Math.abs(seen - prev) >= 1.2) {
      if (prev != null && seen > prev && !first && n.reachable) heartbeatPulse(n.port);
      S.lastSeen[n.port] = seen;
    }
  }

  if (d.events.length) {
    S.since = Math.max(S.since, ...d.events.map((e) => e.time));
    S.events.push(...d.events);
    if (S.events.length > 600) S.events = S.events.slice(-600);
    renderEvents(d.events, !first);
    if (!first) d.events.forEach(onEvent);
  } else if (first) {
    renderEvents([], false);
  }

  renderAll();
  checkDemo();
  if (first) requestAnimationFrame(layoutWires);
  S.first = false;
}

function renderAll() {
  const d = S.data;
  $('#banner').hidden = d.master.up;
  if (!d.master.up) {
    $('#banner').replaceChildren(icon('alert'), h('span', {}, `The master (${d.master.url}) is not answering. Files cannot be listed or stored until it is back.`));
  }
  renderHealth();
  renderKPIs();
  renderMaster();
  renderNodes();
  renderWireStates();
  renderFiles();
  renderMap();
  renderAdmin();
  $('#footer-status').textContent = `${d.managed ? 'cluster started by the dashboard' : 'attached to a running cluster'} · updated ${clock(d.time)}`;
}

function renderOffline() {
  const pill = $('#health-pill');
  pill.className = 'pill pill-lg tone-bad';
  pill.replaceChildren(h('span', { class: 'dot' }), h('span', {}, 'Dashboard offline'));
  const banner = $('#banner');
  banner.hidden = false;
  banner.replaceChildren(icon('alert'), h('span', {}, 'Lost the connection to dashboard.py. Is it still running? Retrying every second…'));
}

/* ------------------------------------------------------------ summary bits */

function clusterNumbers() {
  const d = S.data;
  const R = d.config.replication_factor;
  let chunks = 0, live = 0, under = 0, lost = 0;
  for (const f of d.files) {
    for (const c of f.chunks) {
      chunks += 1;
      live += Math.min(c.live_nodes.length, R);
      if (c.live_nodes.length < R) under += 1;
      if (c.live_nodes.length === 0) lost += 1;
    }
  }
  return {
    R, chunks, live, under, lost,
    online: d.nodes.filter((n) => n.reachable).length,
    alive: d.nodes.filter((n) => n.alive).length,
    bytes: d.nodes.reduce((a, n) => a + (n.reachable ? n.bytes : 0), 0),
    logical: d.files.reduce((a, f) => a + f.size, 0),
  };
}

function renderHealth() {
  const d = S.data;
  const n = clusterNumbers();
  let tone = 'ok', text = 'Healthy';
  if (!d.master.up) { tone = 'bad'; text = 'Master offline'; }
  else if (n.lost) { tone = 'bad'; text = 'Data unavailable'; }
  else if (n.under) { tone = 'warn'; text = n.alive > n.R - 1 ? 'Degraded · repairing' : 'Degraded'; }
  else if (n.online < d.nodes.length) { tone = 'warn'; text = 'Node down · data safe'; }
  const pill = $('#health-pill');
  pill.className = `pill pill-lg tone-${tone}`;
  pill.replaceChildren(h('span', { class: 'dot' }), h('span', {}, text));
}

function setKpi(key, value, sub, tone = 'muted') {
  const el = $(`[data-kpi="${key}"]`);
  el.className = `kpi tone-${tone}`;
  const v = el.querySelector('.kpi-value');
  if (value instanceof Node) v.replaceChildren(value); else v.textContent = value;
  el.querySelector('.kpi-sub').textContent = sub;
}

function renderKPIs() {
  const d = S.data;
  const n = clusterNumbers();
  const total = d.nodes.length;
  setKpi('nodes', h('span', {}, n.online, h('small', {}, ` / ${total}`)),
    `master sees ${n.alive} alive`, n.online === total ? 'ok' : n.online === 0 ? 'bad' : 'warn');
  setKpi('files', String(d.files.length), `${fmtSize(n.logical)} of data`, 'accent');
  setKpi('chunks', String(n.chunks), `${fmtSize(d.config.chunk_size)} each (last one smaller)`, 'accent');
  setKpi('copies', h('span', {}, n.live, h('small', {}, ` / ${n.chunks * n.R}`)),
    `master's view · ${n.R} per chunk`, n.live === n.chunks * n.R ? 'ok' : 'warn');
  setKpi('under', String(n.under), n.under ? `chunks with < ${n.R} live copies` : 'master: every chunk fully replicated',
    n.lost ? 'bad' : n.under ? 'warn' : 'ok');
  setKpi('disk', fmtSize(n.bytes), `≈ ${n.R} × the stored data`, 'muted');
}

function fillConfig(cfg) {
  const values = { ...cfg, chunk_size_mb: fmtSize(cfg.chunk_size) };
  for (const el of $$('[data-cfg]')) {
    const v = values[el.dataset.cfg];
    if (v != null) el.textContent = v;
  }
  $('#master-url').textContent = `127.0.0.1:${cfg.master_port}`;
}

/* ------------------------------------------------------------- topology */

function buildNodes(ports) {
  const wrap = $('#nodes');
  wrap.replaceChildren(...ports.map((port) => h('article', { class: 'node', id: `node-${port}`, 'data-state': 'offline' },
    h('div', { class: 'node-head' },
      h('span', { class: 'node-icon' }, icon('server')),
      h('div', {},
        h('div', { class: 'node-name' }, `Storage node ${port}`),
        h('div', { class: 'node-url mono' }, `127.0.0.1:${port} · storage/node_${port}/`)),
      h('span', { class: 'pill tone-muted', 'data-role': 'pill' }, h('span', { class: 'dot' }), h('span', {}, '…'))),
    h('div', { class: 'hb' },
      h('div', { class: 'hb-top' }, h('span', { 'data-role': 'hb-label' }, 'Last heartbeat'), h('b', { 'data-role': 'hb-age' }, '–')),
      h('div', { class: 'hb-track' },
        h('div', { class: 'hb-fill', 'data-role': 'hb-fill' }),
        h('div', { class: 'hb-mark', 'data-role': 'hb-mark' })),
      h('div', { class: 'hb-scale' }, h('span', {}, '0 s'), h('span', { 'data-role': 'hb-mid' }, ''), h('span', { 'data-role': 'hb-end' }, 'dead'))),
    h('div', { class: 'blocks', 'data-role': 'blocks' }),
    h('div', { class: 'node-foot' },
      h('div', { class: 'node-stats' },
        h('span', {}, h('b', { 'data-role': 'count' }, '0'), ' chunks'),
        h('span', {}, h('b', { 'data-role': 'disk' }, '0 KB'), ' on disk')),
      h('button', { class: 'btn btn-sm', type: 'button', 'data-role': 'action', onclick: () => nodeAction(port) }, '…')))));

  const cfg = S.cfg;
  for (const port of ports) {
    const card = nodeCard(port);
    const pct = (cfg.heartbeat_interval / cfg.dead_after) * 100;
    card.querySelector('[data-role="hb-mark"]').style.left = `${pct}%`;
    card.querySelector('[data-role="hb-end"]').textContent = `${cfg.dead_after} s · dead`;
  }
  layoutWires();
}

function nodeStatus(n) {
  const masterUp = S.data.master.up;
  if (n.reachable && !masterUp) return { key: 'online', label: 'Running', tone: 'info' };
  if (n.reachable && n.alive) return { key: 'online', label: 'Online', tone: 'ok' };
  if (n.reachable && n.known) return { key: 'rejoining', label: 'Rejoining', tone: 'info' };
  if (n.reachable) return { key: 'joining', label: 'Joining', tone: 'info' };
  if (n.known && n.alive) return { key: 'unresponsive', label: 'No heartbeat', tone: 'warn' };
  if (n.known) return { key: 'dead', label: 'Dead', tone: 'bad' };
  return { key: 'offline', label: 'Offline', tone: 'muted' };
}

/* What a node physically holds, or (when it is down) what the master says it held. */
function nodeItems(n) {
  if (n.reachable && n.held) {
    return n.held.map((id) => {
      const owner = S.owners.get(id);
      return { id, stale: !owner || !owner.nodes.includes(n.port), ghost: false };
    });
  }
  return [...S.owners.values()].filter((c) => c.nodes.includes(n.port)).map((c) => ({ id: c.id, stale: false, ghost: true }));
}

function paintNodeButton(btn, n) {
  const busy = nodeCard(n.port)?.dataset.busy === '1';
  const admin = S.admin.signed_in;
  if (n.reachable) {
    btn.className = 'btn btn-sm btn-outline-bad';
    btn.replaceChildren(busy ? spinner() : icon(admin ? 'zap' : 'lock'), 'Crash node');
    btn.disabled = busy || !n.managed;
    btn.title = !n.managed ? 'This node was started outside the dashboard; stop it in its own terminal'
      : admin ? 'Kill this node without warning (SIGKILL)' : 'Admin only: sign in to crash this node';
  } else {
    btn.className = 'btn btn-sm btn-outline-ok';
    btn.replaceChildren(busy ? spinner() : icon(admin ? 'play' : 'lock'), 'Restart node');
    btn.disabled = busy;
    btn.title = admin ? 'Start this storage node again' : 'Admin only: sign in to restart this node';
  }
}

function renderNodes() {
  for (const n of S.data.nodes) {
    const card = nodeCard(n.port);
    if (!card) continue;
    const st = nodeStatus(n);
    card.dataset.state = st.key;
    const pill = card.querySelector('[data-role="pill"]');
    pill.className = `pill tone-${st.tone}`;
    pill.lastChild.textContent = st.label;

    const items = nodeItems(n);
    diffBlocks(card.querySelector('[data-role="blocks"]'), items, n);
    const stale = items.filter((i) => i.stale).length;
    card.querySelector('[data-role="count"]').textContent = stale ? `${items.length - stale} + ${stale} stale` : String(items.length);
    card.querySelector('[data-role="disk"]').textContent = n.reachable ? fmtSize(n.bytes) : '—';

    paintNodeButton(card.querySelector('[data-role="action"]'), n);
  }
}

function diffBlocks(container, items, node) {
  const map = container._blocks || (container._blocks = new Map());
  const wanted = new Map(items.map((i) => [i.id, i]));
  for (const [id, el] of map) {
    if (!wanted.has(id)) {
      map.delete(id);
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 360);
    }
  }
  const order = items.slice().sort((a, b) => (a.stale - b.stale)
    || chunkFile(a.id).localeCompare(chunkFile(b.id)) || chunkIndex(a.id) - chunkIndex(b.id));
  let changedOrder = false;
  for (const item of order) {
    let el = map.get(item.id);
    if (!el) {
      el = h('span', { class: S.first ? 'block' : 'block pop' }, String(chunkIndex(item.id)));
      map.set(item.id, el);
      changedOrder = true;
    }
    const owner = S.owners.get(item.id);
    const file = owner ? owner.file : chunkFile(item.id);
    el.style.setProperty('--c', owner ? colorFor(file) : '#94a3b8');
    el.classList.toggle('ghost', item.ghost);
    el.classList.toggle('stale', item.stale);
    el.title = item.stale
      ? `${item.id}: stale copy (the master no longer lists node ${node.port} for it)`
      : `${file} · chunk ${chunkIndex(item.id)}${owner ? ` · ${fmtSize(owner.size)} · copies on ${owner.nodes.join(', ')}` : ''}${item.ghost ? ' · unreachable while the node is down' : ''}`;
  }
  const current = [...container.children].filter((c) => c.classList.contains('block') && !c.classList.contains('leaving'));
  if (changedOrder || current.length !== order.length || current.some((c, i) => c !== map.get(order[i].id))) {
    const leaving = [...container.children].filter((c) => c.classList.contains('leaving'));
    container.replaceChildren(...order.map((i) => map.get(i.id)), ...leaving);
  }
  if (!order.length) {
    const text = node.reachable ? 'No chunks stored' : 'Node is down';
    const empty = container.querySelector('.blocks-empty') || container.appendChild(h('span', { class: 'blocks-empty' }));
    empty.textContent = text;
  } else {
    container.querySelector('.blocks-empty')?.remove();
  }
}

function renderMaster() {
  const d = S.data;
  const pill = $('#master-pill');
  pill.className = `pill tone-${d.master.up ? 'ok' : 'bad'}`;
  pill.lastChild.textContent = d.master.up ? 'Online' : 'Offline';
  const n = clusterNumbers();
  $('#ms-files').textContent = d.files.length;
  $('#ms-chunks').textContent = n.chunks;
  $('#ms-alive').textContent = `${n.alive}/${d.nodes.length}`;
  const last = S.events[S.events.length - 1];
  $('#master-last').textContent = last ? `Last: ${last.message}` : 'Keeps the chunk map, watches heartbeats, repairs lost copies.';
  $('#master-last').title = last ? last.message : '';
}

/* wires between the boxes (SVG behind the cards) */

function rel(el, side) {
  const r = el.getBoundingClientRect();
  const base = $('#topology').getBoundingClientRect();
  const x = r.left - base.left, y = r.top - base.top;
  if (side === 'top') return { x: x + r.width / 2, y };
  if (side === 'bottom') return { x: x + r.width / 2, y: y + r.height };
  if (side === 'left') return { x, y: y + r.height / 2 };
  if (side === 'right') return { x: x + r.width, y: y + r.height / 2 };
  return { x: x + r.width / 2, y: y + r.height / 2 };
}

function sCurve(a, b) {
  const midY = (a.y + b.y) / 2;
  return [a, { x: a.x, y: midY }, { x: b.x, y: midY }, b];
}
function arc(a, b, lift = 70) {
  return [a, { x: a.x, y: a.y - lift }, { x: b.x, y: b.y - lift }, b];
}
const pathD = ([p0, p1, p2, p3]) => `M ${p0.x} ${p0.y} C ${p1.x} ${p1.y}, ${p2.x} ${p2.y}, ${p3.x} ${p3.y}`;

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function layoutWires() {
  const topo = $('#topology');
  const svg = $('#wires');
  if (!topo || !S.cfg || topo.offsetParent === null) return;
  svg.setAttribute('viewBox', `0 0 ${topo.clientWidth} ${topo.clientHeight}`);
  svg.replaceChildren();
  const master = $('#actor-master');
  const client = $('#actor-client');
  const a = rel(client, 'right'), b = rel(master, 'left');
  svg.append(svgEl('path', { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, class: 'wire', id: 'wire-client' }));
  const ports = S.cfg.node_ports;
  const masterBottom = rel(master, 'bottom');
  ports.forEach((port, i) => {
    const card = nodeCard(port);
    if (!card) return;
    const from = rel(card, 'top');
    const to = { x: masterBottom.x + (i - (ports.length - 1) / 2) * 34, y: masterBottom.y };
    const pts = sCurve(from, to);
    S.wires[port] = pts;
    svg.append(svgEl('path', { d: pathD(pts), class: 'wire', id: `wire-${port}` }));
  });
  renderWireStates();
}

function renderWireStates() {
  if (!S.data) return;
  for (const n of S.data.nodes) {
    const wire = document.getElementById(`wire-${n.port}`);
    if (wire) wire.setAttribute('class', `wire ${nodeStatus(n).tone === 'info' ? 'ok' : nodeStatus(n).tone}`);
  }
  const cw = document.getElementById('wire-client');
  if (cw) cw.setAttribute('class', `wire ${S.data.master.up ? 'ok' : 'bad'}`);
}

/* animation: something flying along a bezier curve */

const motionOK = () => !matchMedia('(prefers-reduced-motion: reduce)').matches
  && matchMedia('(min-width: 901px)').matches && !$('#view-live').hidden && !document.hidden;

function bezier([p0, p1, p2, p3], steps = 24) {
  const pts = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps, u = 1 - t;
    pts.push({
      x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
      y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
    });
  }
  return pts;
}

function fly(curve, { color, label = '', cls = '', duration = 950, delay = 0 } = {}) {
  if (!motionOK()) return Promise.resolve();
  const el = h('span', { class: `flyer ${cls}`.trim(), style: color ? `--c:${color}` : '' }, label);
  el.style.opacity = '0';
  $('#topology').append(el);
  const pts = bezier(curve);
  const last = pts.length - 1;
  const frames = pts.map((p, i) => ({
    transform: `translate(${p.x}px, ${p.y}px) translate(-50%, -50%) scale(${i === 0 || i === last ? 0.55 : 1})`,
    opacity: i === 0 || i === last ? 0 : 1,
    offset: i / last,
  }));
  const anim = el.animate(frames, { duration, delay, easing: 'cubic-bezier(.45,.05,.35,1)', fill: 'both' });
  return anim.finished.catch(() => {}).then(() => el.remove());
}

function heartbeatPulse(port) {
  const curve = S.wires[port];
  if (curve) fly(curve, { cls: 'beat', duration: 800 });
}

function clientToNode(port, opts) {
  const card = nodeCard(port);
  if (!card) return Promise.resolve();
  return fly(sCurve(rel($('#actor-client'), 'bottom'), rel(card, 'top')), opts);
}
function nodeToClient(port, opts) {
  const card = nodeCard(port);
  if (!card) return Promise.resolve();
  return fly(sCurve(rel(card, 'top'), rel($('#actor-client'), 'bottom')), opts);
}
function nodeToNode(from, to, opts) {
  const a = nodeCard(from), b = nodeCard(to);
  if (!a || !b) return Promise.resolve();
  return fly(arc(rel(a, 'top'), rel(b, 'top'), 80), { duration: 1100, ...opts });
}

function flash(el, cls, ms = 1000) {
  if (!el) return;
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), ms);
}

/* heartbeat meters and demo timer, updated every frame */

function tick() {
  if (S.data && S.cfg) {
    const t = now();
    const dead = S.cfg.dead_after;
    for (const n of S.data.nodes) {
      const card = nodeCard(n.port);
      if (!card) continue;
      const seen = S.lastSeen[n.port];
      const age = seen == null ? null : Math.max(0, t - seen);
      const fill = card.querySelector('[data-role="hb-fill"]');
      const ageEl = card.querySelector('[data-role="hb-age"]');
      const label = card.querySelector('[data-role="hb-label"]');
      if (age == null) {
        fill.style.width = '0%';
        ageEl.textContent = '–';
        label.textContent = S.data.master.up ? 'Waiting for first heartbeat' : 'Master offline';
        continue;
      }
      const shown = n.alive ? age : Math.max(age, dead);
      fill.style.width = `${Math.min(shown / dead, 1) * 100}%`;
      const tone = !n.alive ? 'var(--bad)' : age > S.cfg.heartbeat_interval + 1.5 ? 'var(--warn)' : 'var(--ok)';
      fill.style.background = tone;
      ageEl.textContent = `${age.toFixed(1)} s`;
      label.textContent = !n.alive ? 'Marked dead · silent for' : age > S.cfg.heartbeat_interval + 1.5 ? 'Silent for' : 'Last heartbeat';
    }
    const timer = $('#heal-timer');
    if (timer) {
      const v = nodeBy(demo.victim);
      const seen = S.lastSeen[demo.victim];
      const age = seen == null ? 0 : Math.max(0, t - seen);
      const fillEl = $('#heal-fill');
      if (v && !v.alive) {
        timer.textContent = `Node ${demo.victim} marked dead · re-replicating…`;
        if (fillEl) { fillEl.style.width = '100%'; fillEl.style.background = 'var(--ok)'; }
      } else {
        timer.textContent = `Node ${demo.victim} silent for ${age.toFixed(1)} s of ${dead} s`;
        if (fillEl) fillEl.style.width = `${Math.min(age / dead, 1) * 100}%`;
      }
    }
  }
  requestAnimationFrame(tick);
}

/* --------------------------------------------------------- files & map */

function statusPill(status) {
  const tone = { healthy: 'ok', degraded: 'warn', unavailable: 'bad' }[status] || 'muted';
  return h('span', { class: `pill tone-${tone}` }, h('span', { class: 'dot' }), status);
}

function renderFiles() {
  const files = S.data.files;
  const sig = JSON.stringify([S.selected, S.admin.signed_in, files.map((f) => [f.name, f.status, f.size, f.uploaded])]);
  if (sig === S.sigs.files) return;
  S.sigs.files = sig;
  const list = $('#file-list');
  if (!files.length) {
    list.replaceChildren(h('li', { class: 'empty' }, S.data.master.up ? 'No files yet. Drop one above or try the sample CSV.' : 'Master offline.'));
    return;
  }
  list.replaceChildren(...files.map((f) => h('li', {
    class: `file-row ${f.name === S.selected ? 'selected' : ''}`,
    title: `${f.name} · click to show its chunk map`,
    onclick: () => selectFile(f.name),
  },
  h('span', { class: 'swatch', style: `--c:${colorFor(f.name)}` }),
  h('div', { class: 'file-main' },
    h('div', { class: 'file-name' }, f.name),
    h('div', { class: 'file-meta' }, `${fmtSize(f.size)} · ${plural(f.chunks.length, 'chunk')} · ${f.uploaded.slice(11)}`)),
  statusPill(f.status),
  h('div', { class: 'row-actions' },
    h('button', { class: 'icon-btn sm', type: 'button', title: 'Download and verify', 'aria-label': `Download ${f.name}`, onclick: (e) => { e.stopPropagation(); downloadFile(f.name).catch(showError); } }, icon('download')),
    S.admin.signed_in ? h('button', { class: 'icon-btn sm', type: 'button', title: 'Delete', 'aria-label': `Delete ${f.name}`, onclick: (e) => { e.stopPropagation(); deleteFile(f.name); } }, icon('trash')) : null))));
}

function selectFile(name) {
  S.selected = name;
  $('#map-file').value = name;
  renderFiles();
  renderMap();
}

function renderMap() {
  const d = S.data;
  const select = $('#map-file');
  const names = d.files.map((f) => f.name);
  if (select.dataset.names !== JSON.stringify(names)) {
    select.replaceChildren(...names.map((n) => h('option', { value: n }, n)));
    select.dataset.names = JSON.stringify(names);
  }
  select.hidden = !names.length;
  if (S.selected) select.value = S.selected;

  const f = fileByName(S.selected);
  $('#map-empty').hidden = !!f;
  $('#chunk-map').parentElement.hidden = !f;
  $('#map-summary').hidden = !f;
  if (!f) return;

  const ports = d.config.node_ports;
  const status = Object.fromEntries(d.nodes.map((n) => [n.port, n.alive]));
  const sig = JSON.stringify([f.name, f.sha256, f.chunks.map((c) => [c.nodes, c.live_nodes]), status]);
  if (sig === S.sigs.map) return;
  S.sigs.map = sig;

  $('#map-summary').replaceChildren(
    h('span', { class: 'name' }, h('span', { class: 'swatch', style: `--c:${colorFor(f.name)}` }), f.name),
    statusPill(f.status),
    h('span', {}, fmtSize(f.size)),
    h('span', { class: 'mono', title: f.sha256 }, `sha256 ${f.sha256.slice(0, 12)}…`));

  const R = d.config.replication_factor;
  const color = colorFor(f.name);
  const head = h('tr', {}, h('th', {}, 'Chunk'),
    ports.map((p) => h('th', { class: status[p] ? '' : 'down' }, `Node ${p}`, status[p] ? null : h('span', { class: 'th-down' }, 'DOWN'))),
    h('th', {}, 'Live copies'));
  const rows = f.chunks.map((c) => {
    const key = `${f.name}/${c.id}`;
    const nodesNow = c.nodes.join(',');
    const changed = S.mapPrev[key] != null && S.mapPrev[key] !== nodesNow;
    S.mapPrev[key] = nodesNow;
    const tone = c.live_nodes.length >= R ? 'ok' : c.live_nodes.length ? 'warn' : 'bad';
    return h('tr', { class: changed ? 'changed' : '' },
      h('td', { title: `${fmtSize(c.size)} · sha256 ${c.sha256}` }, c.id),
      ports.map((p) => {
        if (!c.nodes.includes(p)) return h('td', {}, h('span', { class: 'cell none' }, '·'));
        const live = c.live_nodes.includes(p);
        return h('td', {}, h('span', { class: `cell ${live ? '' : 'down'}`, style: `--c:${color}`, title: live ? 'live copy' : 'copy on a dead node' }, icon(live ? 'check' : 'x')));
      }),
      h('td', {}, h('span', { class: `pill tone-${tone}` }, `${c.live_nodes.length}/${R}`)));
  });
  $('#chunk-map').replaceChildren(h('thead', {}, head), h('tbody', {}, rows));
}

/* --------------------------------------------------------------- events */

function renderEvents(list, fresh) {
  const ol = $('#events');
  for (const e of list) {
    const tone = EVENT_TONE[e.kind] || 'muted';
    ol.prepend(h('li', { class: `event tone-${tone} ${fresh ? 'fresh' : ''}` },
      h('span', { class: 'event-dot' }),
      h('time', { class: 'mono' }, clock(e.time)),
      h('span', { class: 'event-msg' }, h('span', { class: 'event-kind' }, EVENT_LABEL[e.kind] || e.kind), e.message)));
  }
  while (ol.children.length > 200) ol.lastChild.remove();
  $('#events-empty').hidden = ol.children.length > 0;
}

function onEvent(e) {
  switch (e.kind) {
    case 'repaired': {
      const owner = S.owners.get(e.chunk);
      nodeToNode(e.source, e.target, { color: colorFor(owner ? owner.file : chunkFile(e.chunk)), label: String(chunkIndex(e.chunk)) });
      break;
    }
    case 'node_dead':
      flash(nodeCard(e.port), 'shake', 600);
      toast(`Node ${e.port} marked DEAD after ${Math.round(e.silent)} s without a heartbeat`, 'bad');
      break;
    case 'healthy':
      flash($('#actor-master'), 'glow', 1700);
      toast('Cluster healthy: every chunk has 2 live copies again', 'ok');
      break;
    case 'degraded':
      toast(e.message, 'warn');
      break;
    case 'node_back':
      toast(`Node ${e.port} is back online`, 'info');
      break;
    case 'cleanup':
      flash(nodeCard(e.port), 'refused', 900);
      toast(`Removed ${plural(e.chunks, 'stale copy', 'stale copies')} from node ${e.port}`, 'info');
      break;
    case 'repair_failed':
    case 'error':
      toast(e.message, 'bad');
      break;
    default:
  }
}

/* -------------------------------------------------------------- actions */

function setClient(text, busy) {
  const el = $('#client-status');
  el.classList.toggle('busy', !!busy);
  el.lastChild.textContent = text;
}

async function withClient(text, fn) {
  S.busy += 1;
  setClient(text, true);
  try { return await fn(); } finally {
    S.busy -= 1;
    if (!S.busy) setClient('Idle', false);
  }
}

function showError(err) { toast(err.message || String(err), 'bad', 6000); }

async function animateUpload(result) {
  const color = colorFor(result.name);
  const flights = [];
  result.chunks.forEach((c, i) => c.nodes.forEach((p, j) => {
    flights.push(clientToNode(p, { color, label: String(i), delay: i * 160 + j * 70 }));
  }));
  await Promise.all(flights);
}

function showUploadResult(r) {
  const speed = r.size / MB / Math.max(r.seconds, 1e-6);
  const box = $('#op-result');
  box.hidden = false;
  box.className = 'op-result tone-ok';
  box.replaceChildren(
    h('div', { class: 'op-head' }, icon('upload'), `Uploaded ${r.name}`),
    h('div', { class: 'op-sub' }, `${fmtSize(r.size)} · ${plural(r.chunks.length, 'chunk')} · ${r.seconds.toFixed(2)} s (${speed.toFixed(0)} MB/s) · sha256 ${r.sha256.slice(0, 12)}…`),
    h('div', { class: 'op-rows' }, r.chunks.slice(0, 12).map((c) => h('div', { class: 'op-row' },
      h('span', { class: 'chunk-id' }, c.id), ...c.nodes.map((p) => h('span', { class: 'chip' }, p)))),
    r.chunks.length > 12 ? h('div', { class: 'op-sub' }, `+ ${r.chunks.length - 12} more chunks`) : null),
    r.warnings.map((w) => h('div', { class: 'op-sub', style: 'color:var(--warn)' }, w)));
}

async function afterUpload(result) {
  S.selected = result.name;
  S.sigs.files = null;
  showUploadResult(result);
  pollNow();
  await animateUpload(result);
  toast(`Stored ${result.name}: ${plural(result.chunks.length, 'chunk')} × 2 copies`, 'ok');
  return result;
}

function uploadSample() {
  return withClient('Uploading reviews.csv…', async () => afterUpload(await api('/api/upload/sample', { method: 'POST' })));
}

function uploadRandom() {
  const size = Number($('#random-size').value);
  return withClient(`Uploading a random ${size} MB file…`, async () => afterUpload(await api('/api/upload/random', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ size_mb: size }),
  })));
}

async function uploadFiles(fileList) {
  for (const file of fileList) {
    const form = new FormData();
    form.append('file', file);
    try {
      await withClient(`Uploading ${file.name}…`, async () => afterUpload(await api('/api/upload', { method: 'POST', body: form })));
    } catch (err) { showError(err); }
  }
}

async function downloadFile(name) {
  return withClient(`Downloading ${name}…`, async () => {
    const r = await api(`/api/files/${encodeURIComponent(name)}/download`, { method: 'POST' });
    const color = colorFor(name);
    const skipped = new Set(r.chunks.flatMap((c) => c.skipped.map(([p]) => p)));
    skipped.forEach((p) => flash(nodeCard(p), 'refused', 900));
    const backups = r.chunks.filter((c) => c.skipped.length).length;
    const box = $('#op-result');
    box.hidden = false;
    box.className = 'op-result tone-ok';
    box.replaceChildren(
      h('div', { class: 'op-head', style: '--tone:var(--ok)' }, icon('shield'), `Downloaded ${name}: checksum OK`),
      h('div', { class: 'op-sub' }, `${fmtSize(r.size)} in ${r.seconds.toFixed(2)} s · sha256 ${r.sha256.slice(0, 12)}… matches the original`
        + (backups ? ` · ${plural(backups, 'chunk')} read from a backup copy` : '')),
      h('div', { class: 'op-rows' }, r.chunks.slice(0, 12).map((c) => h('div', { class: 'op-row' },
        h('span', { class: 'chunk-id' }, c.id),
        c.skipped.length ? h('span', { class: 'via' }, `node ${c.skipped.map(([p, why]) => `${p} ${why}`).join(', ')} →`) : null,
        h('span', { class: 'chip' }, `from ${c.node}`)))),
      h('div', { class: 'op-actions' }, h('a', { class: 'btn btn-sm', href: r.url, download: name }, icon('save'), 'Save file')));
    await Promise.all(r.chunks.map((c, i) => nodeToClient(c.node, { color, label: String(i), delay: i * 160 })));
    toast(backups ? `${name} downloaded intact; ${plural(backups, 'chunk')} came from a backup copy` : `${name} downloaded; checksum OK`, 'ok');
    return r;
  });
}

async function deleteFile(name) {
  const ok = await confirmDialog(`Delete ${name}?`, 'The file and all of its chunk copies are removed from every storage node.', 'Delete file');
  if (!ok) return;
  try {
    await api(`/api/files/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast(`Deleted ${name}`, 'info');
    pollNow();
  } catch (err) { showError(err); }
}

async function setNodeBusy(port, busy) {
  const card = nodeCard(port);
  if (card) card.dataset.busy = busy ? '1' : '0';
  if (S.data) renderNodes();
}

async function crashNode(port) {
  await requireAdmin();
  await setNodeBusy(port, true);
  try {
    await api(`/api/nodes/${port}/crash`, { method: 'POST' });
    flash(nodeCard(port), 'shake', 600);
    toast(`Node ${port} crashed: process killed without warning`, 'warn');
  } finally {
    await setNodeBusy(port, false);
    pollNow();
  }
}

async function startNode(port) {
  await requireAdmin();
  await setNodeBusy(port, true);
  try {
    await api(`/api/nodes/${port}/start`, { method: 'POST' });
    toast(`Node ${port} started`, 'info');
  } finally {
    await setNodeBusy(port, false);
    pollNow();
  }
}

function nodeAction(port) {
  const n = nodeBy(port);
  if (!n) return;
  (n.reachable ? crashNode(port) : startNode(port)).catch(showError);
}

async function resetCluster() {
  const ok = await confirmDialog('Reset the cluster?', 'This stops the master and all storage nodes, deletes every stored chunk and the metadata, then starts a fresh, empty cluster.', 'Delete everything');
  if (!ok) return;
  try {
    await withClient('Resetting the cluster…', () => api('/api/reset', { method: 'POST' }));
    S.events = [];
    $('#events').replaceChildren();
    $('#op-result').hidden = true;
    S.lastSeen = {};
    S.mapPrev = {};
    resetDemo();
    toast('Fresh cluster started: all data deleted', 'info');
    pollNow();
  } catch (err) { showError(err); }
}

/* --------------------------------------------------------- guided demo */

const demo = {
  step: 0, busy: false, auto: false, file: 'reviews.csv', victim: 5002,
  flags: {}, results: {}, doneAt: null, crashSince: 0, restartSince: 0, restartAt: 0,
};

function pickVictim() {
  const f = fileByName(demo.file);
  const up = (S.data?.nodes || []).filter((n) => n.reachable);
  if (!f || !up.length) return 5002;
  const holds = (p) => f.chunks.filter((c) => c.nodes.includes(p)).length;
  if (up.some((n) => n.port === 5002) && holds(5002) > 0) return 5002;
  return up.slice().sort((a, b) => holds(b.port) - holds(a.port))[0].port;
}

const STEPS = [
  {
    title: 'Store a file', short: 'upload + replicate', icon: 'upload',
    text: () => 'The client splits <b>reviews.csv</b> (3 MB) into 1 MB chunks. The master picks the two least-loaded nodes for every chunk, and the client sends each chunk <em>directly</em> to those nodes. File data never passes through the master.',
    watch: () => 'Chunks fly from the client into two different nodes each, and the chunk map fills in.',
    action: () => 'Upload sample file',
    run: async () => {
      const r = await uploadSample();
      demo.flags.uploaded = true;
      demo.results[0] = `${plural(r.chunks.length, 'chunk')} × 2 copies stored in ${r.seconds.toFixed(2)} s`;
    },
    done: () => demo.flags.uploaded && !!fileByName(demo.file),
  },
  {
    title: 'Crash a node', short: 'kill -9, no warning', icon: 'zap', admin: true,
    text: () => `Storage node <b>${demo.victim}</b> is killed without warning (SIGKILL), like a power cut. It stops answering and stops sending heartbeats. Nobody tells the master.`,
    watch: () => `Node ${demo.victim} turns amber and its “silent for” timer starts counting toward the ${S.cfg?.dead_after ?? 10} s limit.`,
    action: () => `Crash node ${demo.victim}`,
    run: async () => {
      demo.crashSince = S.since;
      await crashNode(demo.victim);
      demo.flags.crashed = true;
      demo.results[1] = `Node ${demo.victim} killed while holding ${plural(fileByName(demo.file)?.chunks.filter((c) => c.nodes.includes(demo.victim)).length ?? 0, 'chunk copy', 'chunk copies')}`;
    },
    done: () => demo.flags.crashed && !nodeBy(demo.victim)?.reachable,
  },
  {
    title: 'Read during the failure', short: 'download while down', icon: 'download',
    text: () => `Download the file while node ${demo.victim} is down. For each chunk the client tries a copy; when a node does not answer it immediately uses the second copy, then checks the SHA-256 of the whole file.`,
    watch: () => 'Chunks come back from the surviving nodes. The result box shows which chunks used a backup copy.',
    action: () => `Download ${demo.file}`,
    run: async () => {
      const r = await downloadFile(demo.file);
      const backups = r.chunks.filter((c) => c.skipped.length).length;
      demo.flags.downloaded = true;
      demo.results[2] = `Checksum OK: ${backups} of ${plural(r.chunks.length, 'chunk')} read from a backup copy`;
    },
    done: () => !!demo.flags.downloaded,
  },
  {
    title: 'Detect and self-heal', short: 'dead after 10 s', icon: 'heart',
    text: () => `The master checks every second. Once node ${demo.victim} has been silent for ${S.cfg?.dead_after ?? 10} s it is marked <b>dead</b>. For every chunk left with one live copy, the master tells a surviving node to copy it to a healthy node (<code>POST /replicate</code>).`,
    watch: () => 'The timer reaches the limit, the node turns red, and chunk copies jump node to node. Every chunk is back to 2 live copies.',
    action: null,
    done: () => {
      const dead = eventsAfter(demo.crashSince).find((e) => e.kind === 'node_dead' && e.port === demo.victim);
      return !!dead && S.data.files.every((f) => f.status === 'healthy');
    },
    result: () => {
      const ev = eventsAfter(demo.crashSince);
      const dead = ev.find((e) => e.kind === 'node_dead' && e.port === demo.victim);
      const copies = ev.filter((e) => e.kind === 'repaired').length;
      return `Marked dead after ${dead.silent.toFixed(1)} s of silence · ${plural(copies, 'copy', 'copies')} re-created node to node`;
    },
  },
  {
    title: 'Bring it back', short: 'rejoin + cleanup', icon: 'play', admin: true,
    text: () => `Restart node ${demo.victim}. It rejoins with its old chunk files, but those chunks already have 2 copies elsewhere. The master spots the <b>stale</b> copies and deletes them.`,
    watch: () => 'The node turns green; its dashed (stale) squares disappear.',
    action: () => `Restart node ${demo.victim}`,
    run: async () => {
      demo.restartSince = S.since;
      demo.restartAt = Date.now();
      await startNode(demo.victim);
      demo.flags.restarted = true;
    },
    done: () => {
      if (!demo.flags.restarted) return false;
      const n = nodeBy(demo.victim);
      if (!n?.reachable || !n.alive) return false;
      return eventsAfter(demo.restartSince).some((e) => e.kind === 'cleanup' && e.port === demo.victim)
        || Date.now() - demo.restartAt > 6000;
    },
    result: () => {
      const c = eventsAfter(demo.restartSince).find((e) => e.kind === 'cleanup' && e.port === demo.victim);
      return `Node ${demo.victim} rejoined · ${plural(c ? c.chunks : 0, 'stale copy', 'stale copies')} deleted`;
    },
  },
];

function resetDemo() {
  Object.assign(demo, { step: 0, busy: false, flags: {}, results: {}, doneAt: null });
  renderDemo(true);
}

async function runStep(i) {
  const step = STEPS[i];
  if (!step?.run || demo.busy) return;
  demo.busy = true;
  renderDemo(true);
  try { await step.run(); } catch (err) { showError(err); } finally {
    demo.busy = false;
    renderDemo(true);
    checkDemo();
  }
}

function checkDemo() {
  if (S.data && demo.step < STEPS.length) {
    if (demo.step === 1 && !demo.flags.crashed && !demo.busy) demo.victim = pickVictim();
    const step = STEPS[demo.step];
    if (!demo.busy && step.done()) {
      if (step.result && !demo.results[demo.step]) demo.results[demo.step] = step.result();
      if (!demo.doneAt) demo.doneAt = Date.now();
      else if (Date.now() - demo.doneAt > 1100) { demo.step += 1; demo.doneAt = null; }
    }
  }
  renderDemo();
}

async function autoPlay() {
  if (demo.auto) { demo.auto = false; renderDemo(true); return; }
  try { await requireAdmin(); } catch (err) { showError(err); return; }   // the demo crashes a node
  if (demo.step >= STEPS.length) resetDemo();
  demo.auto = true;
  renderDemo(true);
  try {
    while (demo.auto && demo.step < STEPS.length) {
      const i = demo.step;
      if (STEPS[i].run && !demo.busy) await runStep(i);
      const deadline = Date.now() + 45000;
      while (demo.auto && demo.step === i && Date.now() < deadline) await sleep(200);
      if (demo.step === i) throw new Error(`Step “${STEPS[i].title}” did not finish; auto-play stopped`);
      await sleep(2000);
    }
  } catch (err) { showError(err); }
  demo.auto = false;
  renderDemo(true);
}

function renderDemo(force) {
  const sig = JSON.stringify([demo.step, demo.busy, demo.auto, demo.results, demo.victim, !!S.data, S.admin.signed_in]);
  if (!force && sig === S.sigs.demo) return;
  S.sigs.demo = sig;

  const autoBtn = $('#demo-auto');
  autoBtn.replaceChildren(icon(demo.auto ? 'stop' : 'play'), h('span', {}, demo.auto ? 'Stop auto-play' : demo.step >= STEPS.length ? 'Play again' : 'Auto-play'));

  $('#stepper').replaceChildren(...STEPS.map((s, i) => h('li', {
    class: `step ${i < demo.step ? 'done' : i === demo.step ? 'current' : ''}`,
    title: `${i + 1}. ${s.title}`,
  },
  h('span', { class: 'step-dot' }, i < demo.step ? icon('check') : String(i + 1)),
  h('span', { class: 'step-text' }, h('span', { class: 'step-title' }, s.title), h('span', { class: 'step-short' }, s.short)))));

  const box = $('#step-detail');
  if (demo.step >= STEPS.length) {
    box.replaceChildren(h('div', { class: 'step-done' }, icon('shield'), h('div', {},
      h('h3', {}, 'Demo complete: a node crashed and no data was lost'),
      h('ul', { class: 'result-list' }, STEPS.map((s, i) => h('li', {}, icon('check'), h('span', {}, h('b', {}, `${s.title}: `), demo.results[i] || 'done')))),
      h('button', { class: 'btn', type: 'button', onclick: resetDemo }, icon('refresh'), 'Run it again'))));
    return;
  }
  const s = STEPS[demo.step];
  const label = s.action ? s.action() : null;
  const doneNow = !!demo.results[demo.step];
  const locked = s.admin && !S.admin.signed_in;
  let side;
  if (label) {
    side = h('button', {
      class: 'btn btn-primary btn-lg', type: 'button',
      disabled: demo.busy || demo.auto || doneNow || !S.data,
      onclick: () => runStep(demo.step),
    }, demo.busy ? spinner() : icon(locked ? 'lock' : s.icon), demo.busy ? 'Working…' : label);
  } else {
    side = h('div', { class: 'waiting' },
      h('div', { class: 'timer-row' }, h('span', { id: 'heal-timer' }, 'Waiting for the master…'), spinner()),
      h('div', { class: 'timer-track' }, h('div', { class: 'timer-fill', id: 'heal-fill' })));
  }
  box.replaceChildren(
    h('div', { class: 'step-copy' },
      h('div', { class: 'step-kicker' }, `Step ${demo.step + 1} of ${STEPS.length}`),
      h('h3', {}, s.title),
      h('p', { html: s.text() }),
      h('p', { class: 'watch' }, icon('info'), h('span', {}, h('b', {}, 'Watch: '), s.watch()))),
    h('div', { class: 'step-side' },
      side,
      locked && !doneNow ? h('p', { class: 'muted small' }, 'This step needs the admin sign-in.') : null,
      doneNow ? h('p', { class: 'step-result' }, icon('check'), demo.results[demo.step]) : null));
}

/* ----------------------------------------------------------------- admin */

function setAdmin(next) {
  const changed = next.signed_in !== S.admin.signed_in || next.configured !== S.admin.configured;
  S.admin = next;
  if (changed || S.first) renderAccess();
}

/* Show what the viewer may do: the sign-in button, and the locked or the open Admin tab. */
function renderAccess() {
  const { configured, signed_in: signedIn } = S.admin;
  $('#admin-toggle').replaceChildren(icon(signedIn ? 'logout' : 'lock'), signedIn ? 'Sign out' : 'Admin sign-in');
  $('#admin-toggle').title = signedIn ? 'Signed in as admin. Click to sign out.' : 'Sign in as admin';
  $('#admin-locked').hidden = signedIn;
  $('#admin-panel').hidden = !signedIn;
  $('#locked-title').textContent = configured ? 'Admin sign-in' : 'Create the admin password';
  $('#locked-text').textContent = configured
    ? 'Viewers can watch, upload and download. Anything that can lose data needs the admin password.'
    : 'No admin password has been set yet. Whoever sets it first becomes the admin of this dashboard.';
  $('#locked-action').textContent = configured ? 'Sign in' : 'Create password';
}

function adminDialog() {
  const first = !S.admin.configured;
  const dialog = $('#admin-dialog');
  $('#admin-title').textContent = first ? 'Create the admin password' : 'Sign in as admin';
  $('#admin-text').textContent = first
    ? 'Use at least 8 characters, with letters and numbers. It is stored only as a hash.'
    : 'Crashing nodes, deleting files and resetting the cluster need the admin password.';
  $('#admin-submit').textContent = first ? 'Create and sign in' : 'Sign in';
  $('#admin-repeat-row').hidden = !first;
  $('#admin-repeat').required = first;
  $('#admin-password').autocomplete = first ? 'new-password' : 'current-password';
  $('#admin-form').reset();
  $('#admin-error').hidden = true;
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true }));
}

function formError(id, message) {
  const el = $(id);
  el.textContent = message;
  el.hidden = false;
}

async function submitAdminDialog(event) {
  event.preventDefault();
  const first = !S.admin.configured;
  const password = $('#admin-password').value;
  if (first && password !== $('#admin-repeat').value) { formError('#admin-error', 'The two passwords do not match.'); return; }
  try {
    setAdmin(await api(`/api/admin/${first ? 'setup' : 'login'}`, postJSON({ password })));
    $('#admin-dialog').close('ok');
    toast('Signed in as admin', 'ok');
    pollNow();
  } catch (err) { formError('#admin-error', err.message); }
}

/* Call before any admin action: asks for the password if needed, throws if refused. */
async function requireAdmin() {
  if (!S.admin.signed_in && !(await adminDialog())) throw new Error('Sign in as admin to do this');
}

async function signOut() {
  try {
    setAdmin(await api('/api/admin/logout', { method: 'POST' }));
    toast('Signed out', 'info');
    pollNow();
  } catch (err) { showError(err); }
}

function buildAdminNodes(ports) {
  const cells = () => ['status', 'seen', 'chunks', 'disk'].map((role) => h('td', { 'data-role': role, class: 'nowrap' }));
  $('#admin-nodes').replaceChildren(
    h('thead', {}, h('tr', {}, ['Process', 'Status', 'Last heartbeat', 'Chunks on disk', 'Disk used', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {},
      h('tr', { id: 'admin-master' }, h('td', { class: 'nowrap' }, h('b', {}, 'Master')), cells(), h('td', {})),
      ports.map((port) => h('tr', { id: `admin-node-${port}` },
        h('td', { class: 'nowrap' }, h('b', {}, `Storage node ${port}`)), cells(),
        h('td', {}, h('div', { class: 'cell-actions' },
          h('button', { class: 'btn btn-sm', type: 'button', 'data-role': 'action', onclick: () => nodeAction(port) }, '…')))))));
  $('#inspect-node').replaceChildren(...ports.map((port) => h('option', { value: port }, `Node ${port}`)));
}

function setCell(row, role, value) {
  const cell = row.querySelector(`[data-role="${role}"]`);
  const shown = value instanceof Node ? value.outerHTML : value;
  if (cell.dataset.shown === shown) return;       // leave it alone: pills keep blinking smoothly
  cell.dataset.shown = shown;
  if (value instanceof Node) cell.replaceChildren(value); else cell.textContent = value;
}

function renderAdminNodes() {
  const master = $('#admin-master');
  setCell(master, 'status', h('span', { class: `pill tone-${S.data.master.up ? 'ok' : 'bad'}` }, h('span', { class: 'dot' }), S.data.master.up ? 'Online' : 'Offline'));
  setCell(master, 'seen', '—');
  setCell(master, 'chunks', 'none, metadata only');
  setCell(master, 'disk', '—');
  for (const n of S.data.nodes) {
    const row = document.getElementById(`admin-node-${n.port}`);
    const st = nodeStatus(n);
    const seen = S.lastSeen[n.port];
    setCell(row, 'status', h('span', { class: `pill tone-${st.tone}` }, h('span', { class: 'dot' }), st.label));
    setCell(row, 'seen', seen == null ? '—' : `${Math.max(0, now() - seen).toFixed(0)} s ago`);
    setCell(row, 'chunks', n.reachable ? String(n.held?.length ?? 0) : '—');
    setCell(row, 'disk', n.reachable ? fmtSize(n.bytes) : '—');
    paintNodeButton(row.querySelector('[data-role="action"]'), n);
  }
}

function renderAdminFiles() {
  const files = S.data.files;
  const sig = JSON.stringify(files.map((f) => [f.name, f.status, f.size, f.uploaded]));
  if (sig === S.sigs.adminFiles) return;
  S.sigs.adminFiles = sig;
  $('#admin-files-empty').hidden = files.length > 0;
  $('#admin-files').parentElement.hidden = !files.length;
  $('#admin-files').replaceChildren(
    h('thead', {}, h('tr', {}, ['File', 'Size', 'Chunks', 'Health', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, files.map((f) => h('tr', {},
      h('td', { class: 'cell-name', title: `Uploaded ${f.uploaded}` }, f.name),
      h('td', { class: 'nowrap' }, fmtSize(f.size)),
      h('td', {}, f.chunks.length),
      h('td', {}, statusPill(f.status)),
      h('td', {}, h('div', { class: 'cell-actions' },
        h('button', { class: 'icon-btn sm', type: 'button', title: 'Download and verify', 'aria-label': `Download ${f.name}`, onclick: () => downloadFile(f.name).catch(showError) }, icon('download')),
        h('button', { class: 'icon-btn sm', type: 'button', title: 'Delete', 'aria-label': `Delete ${f.name}`, onclick: () => deleteFile(f.name) }, icon('trash'))))))));
}

function renderInspector() {
  const n = nodeBy(Number($('#inspect-node').value));
  if (!n) return;
  const items = nodeItems(n);
  const sig = JSON.stringify([n.port, n.reachable, items.map((i) => [i.id, i.stale, i.ghost, S.owners.get(i.id)?.nodes])]);
  if (sig === S.sigs.inspector) return;
  S.sigs.inspector = sig;
  const stale = items.filter((i) => i.stale).length;
  $('#inspect-summary').textContent = n.reachable
    ? `${plural(items.length, 'chunk')} on disk${stale ? `, ${stale} stale` : ''}`
    : `Node ${n.port} is down. These are the copies the master lists for it.`;
  $('#inspect-empty').hidden = items.length > 0;
  $('#inspect-empty').textContent = n.reachable ? 'No chunks stored on this node.' : 'The master lists no chunks for this node.';
  $('#inspect-table').parentElement.hidden = !items.length;
  const state = (i) => (i.ghost ? ['Unreachable', 'bad'] : i.stale ? ['Stale', 'warn'] : ['Stored', 'ok']);
  $('#inspect-table').replaceChildren(
    h('thead', {}, h('tr', {}, ['Chunk', 'Size', 'Copies on', 'State'].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, items.map((i) => {
      const owner = S.owners.get(i.id);
      const [label, tone] = state(i);
      return h('tr', {},
        h('td', { class: 'cell-name' }, i.id),
        h('td', { class: 'nowrap' }, owner ? fmtSize(owner.size) : '—'),
        h('td', { class: 'nowrap' }, owner ? owner.nodes.join(', ') : 'not in the map'),
        h('td', {}, h('span', { class: `pill tone-${tone}` }, label)));
    })));
}

async function loadActivity() {
  S.activityAt = Date.now();
  if (!S.admin.signed_in) return;
  try { renderActivity((await api('/api/admin/activity')).activity); } catch { /* the next poll tries again */ }
}

function renderActivity(list) {
  const sig = JSON.stringify(list);
  if (sig === S.sigs.activity) return;
  S.sigs.activity = sig;
  $('#admin-activity-empty').hidden = list.length > 0;
  $('#admin-activity').parentElement.hidden = !list.length;
  const when = (t) => new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  $('#admin-activity').replaceChildren(
    h('thead', {}, h('tr', {}, ['Time', 'Who', 'Action', 'Detail'].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, list.map((e) => h('tr', {},
      h('td', { class: 'nowrap mono small' }, when(e.time)),
      h('td', {}, h('span', { class: `pill tone-${e.who === 'admin' ? 'accent' : 'muted'}` }, e.who)),
      h('td', {}, e.action),
      h('td', { class: 'cell-name' }, e.detail)))));
}

function renderAdmin() {
  if (!S.admin.signed_in || $('#view-admin').hidden || !S.data) return;
  renderAdminNodes();
  renderAdminFiles();
  renderInspector();
  if (Date.now() - S.activityAt > 3000) loadActivity();
}

async function runIntegrityCheck() {
  const btn = $('#verify-run');
  const label = btn.lastChild;
  btn.disabled = true;
  label.textContent = 'Checking…';
  try {
    renderIntegrity(await api('/api/admin/verify', { method: 'POST' }));
    loadActivity();
  } catch (err) { showError(err); } finally {
    btn.disabled = false;
    label.textContent = 'Check every copy';
  }
}

function renderIntegrity(r) {
  const box = $('#verify-result');
  if (!r.files.length) { box.replaceChildren(h('p', { class: 'empty' }, 'No files stored yet.')); return; }
  const all = r.readable === r.files.length;
  const whole = all && r.good_copies === r.expected_copies;
  const tones = { ok: 'ok', 'at risk': 'warn', unreadable: 'bad' };
  box.replaceChildren(h('div', { class: `op-result ${whole ? 'tone-ok' : ''}` },
    h('div', { class: 'op-head', style: `--tone:var(--${whole ? 'ok' : all ? 'warn' : 'bad'})` }, icon(all ? 'shield' : 'alert'),
      `${r.readable} of ${plural(r.files.length, 'file')} readable`),
    h('div', { class: 'op-sub' }, `${r.good_copies} of ${r.expected_copies} chunk copies good · checked in ${r.seconds.toFixed(2)} s at ${clock(now())}`),
    r.files.map((f) => h('div', { class: 'verify-file' },
      h('div', { class: 'op-row' }, h('span', { class: 'chunk-id' }, f.name),
        h('span', { class: 'chip' }, `${f.good_copies}/${f.expected_copies}`),
        h('span', { class: `pill tone-${tones[f.status]}` }, f.status)),
      f.problems.map((p) => h('div', { class: 'op-row' }, h('span', { class: 'chunk-id' }, p.chunk),
        h('span', { class: 'via' }, p.problem), h('span', { class: 'chip' }, `node ${p.node}`)))))));
}

async function changePassword(event) {
  event.preventDefault();
  const form = event.target;
  $('#pw-error').hidden = true;
  if ($('#pw-new').value !== $('#pw-repeat').value) { formError('#pw-error', 'The two new passwords do not match.'); return; }
  try {
    await api('/api/admin/password', postJSON({ current: $('#pw-current').value, new: $('#pw-new').value }));
    form.reset();
    toast('Password changed; other browsers are signed out', 'ok');
    loadActivity();
  } catch (err) { formError('#pw-error', err.message); }
}

/* ------------------------------------------------------------- results */

async function loadResults() {
  if (S.resultsLoaded) return;
  try {
    const r = await api('/api/results');
    renderResults(r);
    S.resultsLoaded = true;
  } catch (err) {
    $('#results-meta').textContent = err.message;
  }
}

function renderResults(r) {
  $('#results-meta').textContent = `Run on ${r.generated} · ${r.environment}`;
  const passed = r.tests.filter((t) => t.passed).length;
  const tl = r.timeline || {};
  const last = r.performance[r.performance.length - 1];
  const kpi = (label, value, sub, tone) => h('div', { class: `kpi tone-${tone}` },
    h('span', { class: 'kpi-label' }, label), h('span', { class: 'kpi-value' }, value), h('span', { class: 'kpi-sub' }, sub));
  $('#results-kpis').replaceChildren(
    kpi('Tests passed', `${passed} / ${r.tests.length}`, 'T1–T6 plus extra rejoin check', passed === r.tests.length ? 'ok' : 'bad'),
    kpi('Failure detected', tl.marked_dead != null ? `${tl.marked_dead.toFixed(1)} s` : '–', 'after the node was killed', 'warn'),
    kpi('Copies restored', tl.re_replicated != null ? `+${(tl.re_replicated - tl.marked_dead).toFixed(2)} s` : '–', `after detection · ${tl.copies_made ?? 0} lost copies re-created`, 'ok'),
    kpi(`${last?.size_mb ?? ''} MB upload`, last ? `${last.upload_s.toFixed(2)} s` : '–', last ? `download ${last.download_s.toFixed(2)} s` : '', 'accent'));

  $('#tests-table').replaceChildren(
    h('thead', {}, h('tr', {}, ['#', 'Test', 'Expected', 'Observed', 'Result'].map((c) => h('th', {}, c)))),
    h('tbody', {}, r.tests.map((t) => h('tr', {},
      h('td', {}, t.id), h('td', {}, t.name), h('td', {}, t.expected), h('td', {}, t.observed),
      h('td', {}, h('span', { class: `pill tone-${t.passed ? 'ok' : 'bad'}` }, icon(t.passed ? 'check' : 'x'), t.passed ? 'PASS' : 'FAIL'))))));

  const charts = [
    ['chart_recovery_timeline.png', 'Recovery timeline', 'The file stays readable while the master waits 10 s, then restores 2 copies within a fraction of a second.'],
    ['chart_chunks_per_node.png', 'Chunks per node', 'The master always picks the least-loaded nodes, so chunk copies spread evenly.'],
    ['chart_transfer_time.png', 'Transfer time', 'Upload and download time grow in step with file size.'],
  ];
  const v = encodeURIComponent(r.generated);
  $('#charts').replaceChildren(...charts.map(([file, title, text]) => h('section', { class: 'card chart-card' },
    h('h3', {}, title), h('p', {}, text),
    h('button', { class: 'chart-frame', type: 'button', 'aria-label': `Enlarge ${title}`, onclick: () => openLightbox(`/results/${file}?v=${v}`, title) },
      h('img', { src: `/results/${file}?v=${v}`, alt: title, loading: 'lazy' })))));

  const max = Math.max(...r.performance.flatMap((p) => [p.upload_s, p.download_s]));
  $('#perf').replaceChildren(
    h('div', { class: 'perf-legend' }, h('span', {}, h('i', { style: '--c:var(--accent)' }), 'Upload'), h('span', {}, h('i', { style: '--c:#f472b6' }), 'Download')),
    ...r.performance.map((p) => h('div', { class: 'perf-row' },
      h('span', { class: 'perf-size' }, `${p.size_mb} MB`),
      h('div', { class: 'perf-bars' },
        h('div', { class: 'perf-bar', style: `--c:var(--accent); width:${(p.upload_s / max) * 100}%` }),
        h('div', { class: 'perf-bar', style: `--c:#f472b6; width:${(p.download_s / max) * 100}%` })),
      h('div', { class: 'perf-times' }, `↑ ${p.upload_s.toFixed(3)} s`, h('br'), `↓ ${p.download_s.toFixed(3)} s`))));
}

function openLightbox(src, alt) {
  const img = $('#lightbox-img');
  img.src = src;
  img.alt = alt;
  $('#lightbox').showModal();
}

/* --------------------------------------------------------------- chrome */

function toast(message, tone = 'info', ms = 4500) {
  const el = h('div', { class: `toast tone-${tone}`, role: 'status' }, icon(TONE_ICON[tone] || 'info'), h('span', {}, message));
  $('#toasts').append(el);
  while ($('#toasts').children.length > 4) $('#toasts').firstChild.remove();
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
}

function confirmDialog(title, text, okLabel) {
  const dialog = $('#confirm');
  $('#confirm-title').textContent = title;
  $('#confirm-text').textContent = text;
  $('#confirm-ok').textContent = okLabel;
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true }));
}

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function paintThemeButton() {
  const dark = currentTheme() === 'dark';
  $('#theme-toggle').replaceChildren(icon(dark ? 'sun' : 'moon'));
  $('#theme-toggle').title = dark ? 'Switch to light theme' : 'Switch to dark theme';
}
function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('dfs-theme', next); } catch { /* storage blocked */ }
  paintThemeButton();
}

function showView(name) {
  if (!['live', 'results', 'how', 'admin'].includes(name)) name = 'live';
  for (const tab of $$('.tab')) {
    const on = tab.dataset.view === name;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', String(on));
  }
  for (const view of $$('.view')) view.hidden = view.dataset.view !== name;
  if (name === 'live') requestAnimationFrame(layoutWires);
  if (name === 'results') loadResults();
  if (name === 'admin') { renderAdmin(); loadActivity(); }
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
}

function setupDropzone() {
  const zone = $('#dropzone');
  const input = $('#file-input');
  input.addEventListener('change', () => { if (input.files.length) uploadFiles([...input.files]); input.value = ''; });
  ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.remove('over'); }));
  zone.addEventListener('drop', (e) => { if (e.dataTransfer.files.length) uploadFiles([...e.dataTransfer.files]); });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());
}

function init() {
  for (const el of $$('[data-icon]')) el.innerHTML = svgIcon(el.dataset.icon);
  paintThemeButton();
  $('#theme-toggle').addEventListener('click', toggleTheme);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paintThemeButton);

  for (const tab of $$('.tab')) tab.addEventListener('click', () => showView(tab.dataset.view));
  $('[data-view-link="live"]').addEventListener('click', (e) => { e.preventDefault(); showView('live'); });
  window.addEventListener('hashchange', () => showView(location.hash.slice(1)));
  showView(location.hash.slice(1) || 'live');

  $('#up-sample').addEventListener('click', () => uploadSample().catch(showError));
  $('#up-random').addEventListener('click', () => uploadRandom().catch(showError));
  $('#reset-cluster').addEventListener('click', resetCluster);
  $('#admin-toggle').addEventListener('click', () => (S.admin.signed_in ? signOut() : adminDialog()));
  $('#locked-signin').addEventListener('click', adminDialog);
  $('#admin-form').addEventListener('submit', submitAdminDialog);
  $('#admin-cancel').addEventListener('click', () => $('#admin-dialog').close('cancel'));
  $('#verify-run').addEventListener('click', runIntegrityCheck);
  $('#password-form').addEventListener('submit', changePassword);
  $('#inspect-node').addEventListener('change', renderInspector);
  $('#map-file').addEventListener('change', (e) => selectFile(e.target.value));
  $('#events-clear').addEventListener('click', () => { $('#events').replaceChildren(); $('#events-empty').hidden = false; });
  setupDropzone();

  $('#demo-auto').addEventListener('click', autoPlay);
  $('#demo-restart').addEventListener('click', () => { demo.auto = false; resetDemo(); });
  $('#demo-collapse').addEventListener('click', () => {
    const card = $('#demo');
    const collapsed = card.classList.toggle('collapsed');
    $('#demo-collapse').setAttribute('aria-expanded', String(!collapsed));
    try { localStorage.setItem('dfs-demo-collapsed', collapsed ? '1' : '0'); } catch { /* ignore */ }
    requestAnimationFrame(layoutWires);
  });
  try { if (localStorage.getItem('dfs-demo-collapsed') === '1') $('#demo').classList.add('collapsed'); } catch { /* ignore */ }

  $('#lightbox').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  new ResizeObserver(() => layoutWires()).observe($('#topology'));
  window.addEventListener('resize', layoutWires);

  renderAccess();
  renderDemo(true);
  requestAnimationFrame(tick);
  poll();
}

document.addEventListener('DOMContentLoaded', init);
