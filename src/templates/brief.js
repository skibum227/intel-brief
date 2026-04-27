marked.use({ breaks: true, gfm: true });

// -- Theme ------------------------------------------------------------------
function toggleTheme() {
  const dark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('intel-theme', dark ? 'dark' : 'light');
  document.getElementById('icon-sun').classList.toggle('hidden', dark);
  document.getElementById('icon-moon').classList.toggle('hidden', !dark);
}
(function () {
  const saved = localStorage.getItem('intel-theme');
  const dark = saved ? saved === 'dark' : true;
  document.documentElement.classList.toggle('dark', dark);
  document.getElementById('icon-sun').classList.toggle('hidden', dark);
  document.getElementById('icon-moon').classList.toggle('hidden', !dark);
})();

// -- Item normalization (for diff) -----------------------------------------
function normalizeItem(text) {
  return text
    .replace(/[*_`\[\]]/g, '')
    .replace(/[^\x00-\x7F]/g, '')
    .replace(/[^\w\s]/g, ' ')
    .toLowerCase().trim()
    .split(/\s+/).slice(0, 6).join(' ');
}

// -- Checkbox state ---------------------------------------------------------
function getState() {
  try { return JSON.parse(localStorage.getItem(CONFIG.REPORT_KEY) || '{}'); }
  catch { return {}; }
}
function setState(s) { localStorage.setItem(CONFIG.REPORT_KEY, JSON.stringify(s)); }

// -- Sync toast -------------------------------------------------------------
let toastTimer;
function showSyncToast(ok, msg) {
  const t = document.getElementById('sync-toast');
  t.textContent = ok ? (msg || 'Saved to Obsidian') : ('Sync failed: ' + (msg || 'unknown error'));
  t.classList.toggle('error', !ok);
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), ok ? 2000 : 5000);
}

// -- Sparkline --------------------------------------------------------------
function renderSparkline(data) {
  const svgEl = document.getElementById('sparkline');
  if (!svgEl || !data || data.length < 2) return;
  const w = 52, h = 22, pad = 2;
  const max = Math.max(...data, 1);
  const xStep = (w - pad * 2) / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = pad + i * xStep;
    const y = h - pad - (v / max) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = data[data.length - 1];
  const lastX = (pad + (data.length - 1) * xStep).toFixed(1);
  const lastY = (h - pad - (last / max) * (h - pad * 2)).toFixed(1);
  svgEl.innerHTML = `
    <polyline points="${pts}" fill="none" stroke="#6366f1" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round" opacity="0.6"/>
    <circle cx="${lastX}" cy="${lastY}" r="2" fill="#6366f1" opacity="0.9"/>`;
  svgEl.classList.remove('hidden');
}

// -- Next meeting widget ----------------------------------------------------
function renderMeetingWidget() {
  if (!CONFIG.NEXT_MEETING) return;
  const w = document.getElementById('meeting-widget');
  const att = CONFIG.NEXT_MEETING.attendees > 0 ? ` · ${CONFIG.NEXT_MEETING.attendees} attendees` : '';
  w.innerHTML = `<span class="meeting-chip">
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
      <rect x="2" y="3" width="12" height="11" rx="2"/>
      <path stroke-linecap="round" d="M5 1v3M11 1v3M2 7h12"/>
    </svg>
    ${CONFIG.NEXT_MEETING.title} &middot; ${CONFIG.NEXT_MEETING.when}${att}
  </span>`;
  w.classList.remove('hidden');
}

// -- Progress bar -----------------------------------------------------------
function updateProgress() {
  const total = document.querySelectorAll('#brief-content .task-item').length;
  const done  = document.querySelectorAll('#brief-content .task-item.done').length;
  const fill  = document.getElementById('brief-progress-fill');
  const label = document.getElementById('brief-progress-label');
  if (fill)  fill.style.width  = total ? `${Math.round((done / total) * 100)}%` : '0%';
  if (label) label.textContent = `${done} / ${total}`;
}

// -- Collapsible h2 sections ------------------------------------------------
function makeCollapsible(el) {
  el.querySelectorAll('h2').forEach(h => {
    h.addEventListener('click', () => {
      const collapsed = h.classList.toggle('section-collapsed');
      let next = h.nextElementSibling;
      while (next && next.tagName !== 'H2') {
        next.classList.toggle('section-hidden', collapsed);
        next = next.nextElementSibling;
      }
    });
  });
}

// -- Active sidebar highlight -----------------------------------------------
function setupActiveNav() {
  const nav = document.getElementById('nav-links');
  if (!nav) return;
  const headings = Array.from(document.querySelectorAll('h2[id], h3[id]'));
  if (!headings.length) return;

  function setActive() {
    // Find the last heading whose top edge is at or above 25% down the viewport
    const threshold = window.scrollY + window.innerHeight * 0.25;
    let active = headings[0];
    for (const h of headings) {
      if (h.getBoundingClientRect().top + window.scrollY <= threshold) {
        active = h;
      }
    }
    nav.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('nav-active', link.getAttribute('href') === '#' + active.id);
    });
  }

  window.addEventListener('scroll', setActive, { passive: true });
  // Re-run after layout settles (fonts/images may shift positions)
  requestAnimationFrame(() => setTimeout(setActive, 100));
}

// -- Process rendered markdown ----------------------------------------------
function processContent(el, keyPrefix, startSyncIdx, enableSync) {
  const state = getState();
  let syncIdx = startSyncIdx;

  el.querySelectorAll('li').forEach((li, i) => {
    const inputEl = li.querySelector('input[type="checkbox"]');
    if (!inputEl) {
      li.classList.add('plain-li');
      return;
    }
    const isChecked = inputEl.checked;
    const cbSyncIdx = syncIdx++;
    const key = keyPrefix + '-' + i;
    const done = state[key] !== undefined ? state[key] : isChecked;

    inputEl.remove();
    const inner = li.innerHTML.trim();

    li.innerHTML = '';
    li.style.cssText = 'list-style:none;padding:0';

    const wrap = document.createElement('div');
    wrap.className = 'task-item' + (done ? ' done' : '');

    // Urgency border
    const text = inner.replace(/<[^>]+>/g, '');
    if (text.includes('🔴')) wrap.classList.add('urgency-red');
    else if (text.includes('🟡')) wrap.classList.add('urgency-yellow');
    else if (text.includes('🟢')) wrap.classList.add('urgency-green');

    const box = document.createElement('div');
    box.className = 'task-checkbox';

    const txt = document.createElement('span');
    txt.className = 'task-text';
    txt.innerHTML = inner;

    // Diff badge: mark items not present in yesterday's brief
    if (CONFIG.PREV_FINGERPRINTS.length > 0 && enableSync) {
      const fp = normalizeItem(txt.textContent || '');
      const isNew = !CONFIG.PREV_FINGERPRINTS.some(pf => {
        const minLen = Math.min(fp.length, pf.length, 20);
        return minLen > 4 && fp.slice(0, minLen) === pf.slice(0, minLen);
      });
      if (isNew) {
        const badge = document.createElement('span');
        badge.className = 'new-badge';
        badge.textContent = 'NEW';
        txt.prepend(badge);
      }
    }

    // Dismiss button — mark item as noise
    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'dismiss-btn';
    dismissBtn.title = 'Dismiss — de-prioritize similar items in future briefs';
    dismissBtn.textContent = '✕';
    dismissBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const fp = normalizeItem(txt.textContent || '');
      if (!fp || fp.length < 5) return;
      if (CONFIG.SYNC_PORT) {
        fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/dismiss`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fingerprint: fp }),
        })
        .then(r => {
          if (r.ok) {
            wrap.style.opacity = '0.3';
            showSyncToast(true, 'Dismissed — similar items de-prioritized');
          } else {
            showSyncToast(false, 'Dismiss failed');
          }
        })
        .catch(() => showSyncToast(false, 'Dismiss failed'));
      }
    });

    wrap.append(box, txt, dismissBtn);
    li.appendChild(wrap);

    wrap.addEventListener('click', () => {
      const s = getState();
      const nowDone = !wrap.classList.contains('done');
      wrap.classList.toggle('done', nowDone);
      s[key] = nowDone;
      setState(s);
      updateProgress();

      if (enableSync && CONFIG.SYNC_PORT) {
        console.log(`[sync] POST index=${cbSyncIdx} checked=${nowDone} → http://127.0.0.1:${CONFIG.SYNC_PORT}/sync`);
        fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/sync`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: cbSyncIdx, checked: nowDone }),
        })
        .then(r => r.json().then(body => {
          console.log('[sync] response:', r.status, body);
          if (r.ok) showSyncToast(true);
          else showSyncToast(false, body.error || r.status);
        }))
        .catch(err => {
          console.error('[sync] fetch error:', err);
          showSyncToast(false, err.message || 'network error');
        });
      }
    });
  });

  el.querySelectorAll('h2').forEach(h => {
    h.id = h.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
  });
  el.querySelectorAll('h3').forEach(h => {
    if (!h.id) h.id = h.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
  });

  return syncIdx;
}

// -- Extract executive summary lede -----------------------------------------
function extractLede(el) {
  const firstH2 = el.querySelector('h2');
  if (!firstH2) return;
  const toMove = [];
  let node = el.firstChild;
  while (node && node !== firstH2) { toMove.push(node); node = node.nextSibling; }
  if (!toMove.length) return;
  const ledeDiv = document.createElement('div');
  ledeDiv.className = 'brief-lede';
  toMove.forEach(n => ledeDiv.appendChild(n));
  el.insertBefore(ledeDiv, el.firstChild);
  const divider = document.createElement('div');
  divider.className = 'lede-divider';
  el.insertBefore(divider, ledeDiv.nextSibling);
}

// -- Sidebar nav ------------------------------------------------------------
function buildNav() {
  const nav = document.getElementById('nav-links');
  if (!nav) return;
  const briefH2s = document.querySelectorAll('#brief-content h2');
  if (briefH2s.length) {
    const lbl = document.createElement('p');
    lbl.className = 'nav-section'; lbl.textContent = 'Brief';
    nav.appendChild(lbl);
    briefH2s.forEach(h => {
      if (!h.id) return;
      nav.appendChild(Object.assign(document.createElement('a'), {
        href: '#' + h.id, className: 'nav-link', textContent: h.textContent.trim(),
      }));
    });
  }
  const projH = document.querySelectorAll('#project-content h2, #project-content h3');
  if (projH.length) {
    const lbl = document.createElement('p');
    lbl.className = 'nav-section'; lbl.textContent = 'Projects';
    nav.appendChild(lbl);
    projH.forEach(h => {
      if (!h.id) return;
      nav.appendChild(Object.assign(document.createElement('a'), {
        href: '#' + h.id, className: 'nav-link', textContent: h.textContent.trim(),
      }));
    });
  }
}

// -- My ToDos ---------------------------------------------------------------
let _todos = [];

function loadTodos() {
  if (!CONFIG.SYNC_PORT) return;
  fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/todos`)
    .then(r => r.json())
    .then(data => {
      _todos = data.todos || [];
      renderTodos();
    }).catch(() => {});
}

function saveTodos() {
  if (!CONFIG.SYNC_PORT) return;
  fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/todos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ todos: _todos }),
  })
  .then(r => {
    if (r.ok) showSyncToast(true, 'ToDos saved');
    else showSyncToast(false, 'ToDo save failed');
  }).catch(() => showSyncToast(false, 'ToDo save failed'));
}

function renderTodos() {
  const list = document.getElementById('todos-list');
  if (!list) return;
  list.innerHTML = '';

  // Show unchecked first, then checked
  const sorted = [..._todos].sort((a, b) => (a.checked === b.checked) ? 0 : a.checked ? 1 : -1);

  sorted.forEach((todo, _) => {
    const idx = _todos.indexOf(todo);
    const div = document.createElement('div');
    div.className = 'todo-item' + (todo.checked ? ' done' : '');

    const box = document.createElement('div');
    box.className = 'todo-checkbox';

    const txt = document.createElement('span');
    txt.className = 'todo-text';
    txt.textContent = todo.text;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'todo-remove';
    removeBtn.textContent = '✕';
    removeBtn.title = 'Remove';
    removeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _todos.splice(idx, 1);
      renderTodos();
      saveTodos();
    });

    div.append(box, txt, removeBtn);
    div.addEventListener('click', () => {
      _todos[idx].checked = !_todos[idx].checked;
      renderTodos();
      saveTodos();
    });

    list.appendChild(div);
  });

  if (_todos.length === 0) {
    list.innerHTML = '<p class="text-xs dark:text-slate-600 text-slate-400 italic">No tasks yet</p>';
  }
}

function addTodo() {
  const input = document.getElementById('todo-input');
  const text = (input.value || '').trim();
  if (!text) return;
  _todos.push({ text, checked: false });
  input.value = '';
  renderTodos();
  saveTodos();
}

// -- My Notes ---------------------------------------------------------------
function loadNotes() {
  if (!CONFIG.SYNC_PORT) return;
  fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/notes`)
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('notes-input');
      if (el && data.notes) el.value = data.notes;
    }).catch(() => {});
}

function saveNotes() {
  if (!CONFIG.SYNC_PORT) return;
  const notes = document.getElementById('notes-input').value;
  fetch(`http://127.0.0.1:${CONFIG.SYNC_PORT}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes }),
  })
  .then(r => r.json().then(body => {
    if (r.ok) showSyncToast(true, 'Notes saved');
    else showSyncToast(false, body.error || 'save failed');
  })).catch(err => showSyncToast(false, err.message));
}

// -- Render -----------------------------------------------------------------
(function () {
  const briefEl = document.getElementById('brief-content');
  briefEl.innerHTML = marked.parse(CONFIG.BRIEF_MD);
  extractLede(briefEl);
  let nextSyncIdx = processContent(briefEl, CONFIG.REPORT_KEY + '-brief', 0, true);
  makeCollapsible(briefEl);
  updateProgress();

  if (CONFIG.PROJECT_MD.trim()) {
    const body = CONFIG.PROJECT_MD.replace(/^##[^\n]*\n/m, '');
    const projEl = document.getElementById('project-content');
    projEl.innerHTML = marked.parse(body);
    processContent(projEl, CONFIG.REPORT_KEY + '-proj', nextSyncIdx, false);
    makeCollapsible(projEl);
    document.getElementById('project-card').classList.remove('hidden');
  }

  buildNav();
  setupActiveNav();
  renderSparkline(CONFIG.SPARKLINE_DATA);
  renderMeetingWidget();
  loadTodos();
  loadNotes();
  document.getElementById('todo-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addTodo(); }
  });
  document.getElementById('notes-input').addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') saveNotes();
  });
})();
