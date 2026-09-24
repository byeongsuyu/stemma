import {t, language} from './i18n.js';
import {WorkBuffer} from './work-buffer.js';
import {failureKind, failureStatus, refusal, sourceOrigin, dateText, dateDetail} from './feedback.js';
const $ = selector => document.querySelector(selector);
const blank = {title: '', body: '', note: '', selections: [], attachments: []};
let token, workspaceKey, buffer, questions = {}, documentQuestions = {}, source = null, docs = [], total = 0;
let queryGeneration = 0, sourceGeneration = 0, timer, queryTimer, busy = false, ready = false;
let recovery = null, works = [], publicationUrl = null;
function message(text) { $('#error').textContent = text; $('#error').hidden = !text; }
function status(text) { $('#save-status').textContent = text; }
async function api(path, payload) {
  const options = payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Editor-Token': token}, body: JSON.stringify(payload)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    const failure = new Error(result.error || t('editor.error.request'));
    // The server has already decided what kind of refusal this is; keep that decision
    // rather than guessing from the wording, which is prose meant for the author.
    failure.status = response.status;
    throw failure;
  }
  return result;
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(text, action, className = '') {
  const node = el('button', className, text);
  node.type = 'button'; node.onclick = () => run(action); return node;
}
async function run(action) {
  try { await action(); } catch (error) {
    message(error.message);
    // 400 means the request was refused on its merits and 409 that the workspace moved
    // on; re-sending the same draft fixes neither, so offering to retry the save would
    // point the author away from the thing actually blocking them. A guard the desk
    // enforced itself never became a request at all. A dropped connection or a server
    // fault has no status, and that is the case retry exists for.
    const kind = failureKind(error.status);
    status(failureStatus(kind));
    $('#retry').hidden = kind !== 'failed';
  }
}
function backup(value) {
  try { value ? localStorage.setItem(workspaceKey, JSON.stringify(value)) : localStorage.removeItem(workspaceKey); }
  catch { message(t('editor.error.backup')); }
}
function edit(change) {
  if (!ready || busy) return;
  buffer.edit(change); renderHeader();
  clearTimeout(timer); timer = setTimeout(() => run(() => flush()), 650);
}
async function flush() {
  clearTimeout(timer);
  await buffer.flush();
  if (buffer.work) {
    localStorage.setItem(workspaceKey + ':last', buffer.work.id);
    $('#revision-status').textContent = buffer.work.saved_revision ? t('editor.revision.saved', {revision: buffer.work.saved_revision}) : t('editor.revision.unsaved');
  }
  if (buffer.work) rememberWork(buffer.work);
  renderWorkTabs();
  $('#retry').hidden = true;
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll('button,input,textarea,select').forEach(node => { node.disabled = node.closest('#recovery') ? false : value; });
  if (!value) {
    document.querySelectorAll('.document input').forEach(node => { node.disabled = $('#archived').checked; });
    $('#review-open').disabled = buffer?.work?.document_state === 'confirmed';
  }
}
async function exclusive(action) {
  if (busy || !ready) return;
  setBusy(true);
  try { await action(); } finally { setBusy(false); }
}
function panel(name) {
  $('.desk').dataset.panel = name;
  document.querySelectorAll('[data-panel]').forEach(node => {
    if (node.tagName !== 'BUTTON') return;
    const active = node.dataset.panel === name;
    node.classList.toggle('active', active);
    // The narrow-width switcher is navigation, so the current area is announced as such
    // rather than left to the colour that marks it for everybody else.
    if (active) node.setAttribute('aria-current', 'true'); else node.removeAttribute('aria-current');
  });
}
function renderHeader() {
  $('#word-count').textContent = t('editor.characters', {count: buffer.data.body.length.toLocaleString(language)});
  const w = buffer.work;
  $('#work-label').textContent = w?.document_state === 'confirmed' ? t('editor.work.revising') : t('editor.work.private');
  $('#review-open').disabled = w?.document_state === 'confirmed';
  $('#work-context').textContent = w?.document_id
    ? t('editor.work.revising_context', {title: w.title || t('editor.untitled'), revision: w.saved_revision || ''})
    : t('editor.work.new_context');
  const next = $('#prepare-publication');
  next.hidden = !publicationUrl || !w?.document_id || w.document_state !== 'confirmed';
  next.href = publicationUrl + '?' + new URLSearchParams({document:w?.document_id || '', revision:w?.saved_revision || ''});
  renderWorkTabs();
}
function renderWork() {
  $('#title').value = buffer.data.title; $('#body').value = buffer.data.body; $('#note').value = buffer.data.note;
  renderHeader(); renderSelections(); renderDocs(); renderAttachments();
  $('#revision-status').textContent = buffer.work?.saved_revision ? t('editor.revision.saved', {revision: buffer.work.saved_revision}) : t('editor.revision.unsaved');
}
function loadWork(work) {
  buffer.load(work); if (work) rememberWork(work); renderWork();
  status(work ? t('editor.status.opened') : t('editor.status.idle'));
  if (work) localStorage.setItem(workspaceKey + ':last', work.id);
  else localStorage.removeItem(workspaceKey + ':last');
}
async function catalog(append = false) {
  const generation = ++queryGeneration;
  const params = new URLSearchParams({q: $('#search').value, archived: $('#archived').checked, offset: append ? docs.length : 0});
  const result = await api('/api/documents?' + params);
  if (generation !== queryGeneration) return;
  docs = append ? docs.concat(result.documents) : result.documents;
  total = result.total; questions = result.questions; documentQuestions = result.document_questions || {};
  renderDocs();
}
function renderDocs() {
  $('#documents').replaceChildren();
  $('#total').textContent = t('editor.count', {count: total.toLocaleString(language)});
  $('#sort-label').textContent = $('#search').value.trim() ? t('editor.sort.title') : t('editor.sort.recent');
  docs.forEach(doc => {
    const selected = buffer.data.selections.some(item => item.id === doc.id);
    const row = el('div', 'document' + (selected ? ' selected' : '') + (source?.id === doc.id ? ' active' : ''));
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected;
    check.disabled = doc.archived || busy; check.setAttribute('aria-label', t('editor.select', {title: doc.title}));
    check.onchange = () => toggleSelection(doc);
    const open = button('', () => openSource(doc.id), '');
    open.append(el('span', 'doc-title', doc.title), el('span', 'doc-snippet', doc.snippet),
      el('span', 'doc-meta', dateText(doc.date) + ' · ' + doc.platform + (doc.state === 'draft' ? ' · ' + t('editor.draft') : '')));
    row.append(check, open); $('#documents').append(row);
  });
  if (!docs.length) $('#documents').append(el('p', 'subtle', t('editor.no_match')));
  $('#more').hidden = docs.length >= total;
}
function toggleSelection(doc) {
  if (busy) return;
  const items = structuredClone(buffer.data.selections);
  const index = items.findIndex(item => item.id === doc.id);
  if (index >= 0) items.splice(index, 1);
  else items.push({id: doc.id, revision: doc.revision, sha256: doc.sha256, title: doc.title,
    role: 'reference', questions: [], new_questions: [], note: '', archive: false});
  edit({selections: items}); renderSelections(); renderDocs();
  if (index < 0) run(() => openSource(doc.id, doc.revision));
}
function renderReaderTabs() {
  const items = [...buffer.data.selections];
  if (source && !items.some(item => item.id === source.id && item.revision === source.revision)) items.push(source);
  const tabs = $('#reader-tabs');
  tabs.hidden = !items.length;
  tabs.replaceChildren(...items.map((item, index) => {
    const tab = button(item.title, () => openSource(item.id, item.revision), 'reader-tab');
    tab.id = 'reader-tab-' + index;
    tab.title = item.title + ' · ' + item.revision;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', 'source');
    const active = source?.id === item.id && source?.revision === item.revision;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active) $('#source').setAttribute('aria-labelledby', tab.id);
    tab.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
      run(async () => {await openSource(items[next].id, items[next].revision); $('#reader-tab-' + next)?.focus();});
    };
    return tab;
  }));
  if (!source && tabs.firstElementChild) tabs.firstElementChild.tabIndex = 0;
}
function renderSelections() {
  const selections = buffer.data.selections;
  $('#selection-count').textContent = selections.length ? t('editor.selection.count', {count: selections.length}) : t('editor.selection.none');
  $('#selection-chips').replaceChildren(...selections.map(item => {
    const row = el('div', 'selection-chip');
    const remove = button('×', () => toggleSelection(item), 'chip-remove');
    remove.setAttribute('aria-label', t('editor.deselect', {title: item.title}));
    row.append(button(item.title + ' · ' + item.revision, () => openSource(item.id, item.revision), 'chip'), remove);
    return row;
  }));
  const link = $('#genealogy-open');
  link.hidden = !selections.length;
  link.href = '/genealogy?' + new URLSearchParams({ids: selections.map(item => item.id).join(',')});
  renderReaderTabs();
}
async function openSource(id, revision) {
  const generation = ++sourceGeneration;
  const params = new URLSearchParams({id}); if (revision) params.set('revision', revision);
  const doc = await api('/api/document?' + params);
  if (generation !== sourceGeneration) return;
  source = doc; $('#source').hidden = false; $('#source-empty').hidden = true;
  $('#source-kind').textContent = doc.archived ? t('editor.kind.archived') : doc.kind === 'imported' ? t('editor.kind.imported') : t('editor.kind.studio');
  $('#source-title').textContent = doc.title;
  $('#source-meta').textContent = dateDetail(doc.date, doc.date_kind) + (doc.source?.title_origin === 'generated_display_label' ? ' · ' + t('editor.generated_title') : '');
  $('#source-body').textContent = doc.body;
  $('#source-revision').replaceChildren(...doc.revisions.map(rev => {
    const option = el('option', '', rev.id + ' · ' + rev.note); option.value = rev.id; return option;
  }));
  $('#source-revision').value = doc.revision;
  // Provenance reads differently per source: a folder import has no commit to name, and
  // printing the missing field is worse than saying where the writing actually came from.
  $('#source-origin').textContent = sourceOrigin(doc.source);
  const origin = doc.source?.metadata?.original_url;
  if (origin && /^https?:\/\//i.test(origin)) {
    const link = el('a', '', t('editor.source.original')); link.href = origin; link.target = '_blank'; link.rel = 'noreferrer noopener';
    $('#source-origin').append(document.createElement('br'), link);
  }
  $('#source-relations').replaceChildren();
  doc.relations.forEach(edge => {
    const parent = edge.child === doc.id, related = parent ? edge.parent : edge.child;
    const text = (parent ? '← ' : '→ ') + (parent ? edge.parent_title : edge.child_title) + ' · ' + edge.questions.map(id => questions[id]?.text || id).join(' / ');
    $('#source-relations').append(button(text, () => openSource(related, parent ? edge.parent_revision : edge.child_revision)));
  });
  if (!doc.relations.length) $('#source-relations').textContent = t('editor.source.no_relations');
  $('#revise-source').textContent = doc.revision === doc.current_revision ? t('editor.source.revise') : t('editor.source.revise_latest');
  $('#revise-source').hidden = doc.kind !== 'original' || doc.archived;
  $('#restore-source').hidden = !doc.archived;
  renderReaderTabs(); renderDocs(); panel('reader');
}
function selectionEdit(index, change) {
  const items = structuredClone(buffer.data.selections); Object.assign(items[index], change);
  edit({selections: items}); reviewSummary();
}
function reviewSummary() {
  const parents = buffer.data.selections.filter(item => item.role === 'parent');
  $('#review-summary').textContent = t('editor.review.summary', {parents: parents.length, references: buffer.data.selections.length - parents.length, archived: parents.filter(item => item.archive).length});
}
function renderReview() {
  $('#review-parents').replaceChildren(); $('#review-error').textContent = '';
  buffer.data.selections.forEach((item, index) => {
    const card = el('section', 'review-parent'); card.append(el('h3', '', item.title + ' · ' + item.revision));
    const roleLabel = el('label', '', t('editor.review.role'));
    const role = document.createElement('select');
    [['reference', t('editor.review.reference')], ['parent', t('editor.review.parent')]].forEach(([value, label]) => {const option = el('option', '', label); option.value = value; role.append(option);});
    role.value = item.role; role.onchange = () => {selectionEdit(index, {role: role.value, archive: false}); renderReview();};
    roleLabel.append(role); card.append(roleLabel);
    if (item.role === 'parent') {
      const label = el('label', '', t('editor.review.questions')); const choices = el('div', 'question-choices');
      const other = el('details'); other.append(el('summary', '', t('editor.review.other_questions')));
      const related = new Set([...(documentQuestions[item.id] || []), ...item.questions]);
      Object.entries(questions).forEach(([id, question]) => {
        const l = el('label'); const c = document.createElement('input'); c.type = 'checkbox'; c.checked = item.questions.includes(id);
        c.onchange = () => { const ids = new Set(buffer.data.selections[index].questions); c.checked ? ids.add(id) : ids.delete(id); selectionEdit(index, {questions: [...ids]}); };
        l.append(c, document.createTextNode(' ' + question.text)); (related.has(id) ? choices : other).append(l);
      }); if (!related.size) choices.append(el('p', 'subtle', t('editor.review.no_questions'))); label.append(choices); card.append(label, other);
      const newLabel = el('label', '', t('editor.review.new_questions')); const newQ = document.createElement('textarea');
      newQ.rows = 2; newQ.placeholder = t('editor.review.new_questions_placeholder'); newQ.value = item.new_questions.join('\n');
      newQ.oninput = () => selectionEdit(index, {new_questions: newQ.value.split('\n')}); newLabel.append(newQ); card.append(newLabel);
      const noteLabel = el('label', '', t('editor.review.note')); const note = document.createElement('textarea');
      note.rows = 2; note.value = item.note; note.placeholder = t('editor.review.note_placeholder');
      note.oninput = () => selectionEdit(index, {note: note.value}); noteLabel.append(note); card.append(noteLabel);
      const archiveLabel = el('label', 'archive-choice'); const check = document.createElement('input'); check.type = 'checkbox'; check.checked = item.archive;
      check.onchange = () => selectionEdit(index, {archive: check.checked}); archiveLabel.append(check, document.createTextNode(' ' + t('editor.review.archive'))); card.append(archiveLabel);
      card.append(el('p', 'subtle', t('editor.review.archive_note')));
    }
    $('#review-parents').append(card);
  });
  if (!buffer.data.selections.length) $('#review-parents').append(el('p', '', t('editor.review.no_parents')));
  reviewSummary();
}
async function commit(confirm) {
  await exclusive(async () => {
    try {
      message(''); $('#review-error').textContent = '';
      await flush();
      if (!buffer.work) throw refusal(t('editor.error.empty'));
      const work = await api('/api/commit', {id: buffer.work.id, version: buffer.work.version, confirm});
      loadWork(work); backup(null);
      status(confirm ? t('editor.status.confirmed') : t('editor.status.saved', {revision: work.saved_revision}));
      $('#review-dialog').close(); await catalog();
    } catch (error) {
      $('#review-error').textContent = error.message;
      throw error;
    }
  });
}
function rememberWork(work) {
  const index = works.findIndex(item => item.id === work.id);
  if (index < 0) works.push(work); else works[index] = work;
}
function renderWorkTabs() {
  const items = [...works];
  if (!buffer.work) items.push({id: null, title: buffer.data.title || t('editor.new_manuscript')});
  $('#work-tabs').replaceChildren(...items.map(work => {
    const active = work.id === (buffer.work?.id || null);
    const row = el('div', 'work-tab');
    const tab = button(active ? (buffer.data.title || t('editor.new_manuscript')) : (work.title || t('editor.untitled')), () => exclusive(async () => {
      if (active) return;
      await flush(); loadWork(await api('/api/work?id=' + encodeURIComponent(work.id))); panel('writer');
    }), 'reader-tab');
    tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(active));
    tab.setAttribute('aria-controls', 'work-panel');
    const close = button('×', () => closeWork(work.id), 'chip-remove');
    close.setAttribute('aria-label', t('editor.close_work', {title: work.title || t('editor.new_manuscript')}));
    row.append(tab, close); return row;
  }));
}
async function closeWork(id) {
  await exclusive(async () => {
    if (!confirm(t('editor.confirm.close_work'))) return;
    const active = id === (buffer.work?.id || null);
    await flush();
    const targetId = active ? buffer.work?.id : id;
    const work = works.find(item => item.id === targetId);
    if (work) await api('/api/work/delete', {id: work.id, version: work.version});
    works = works.filter(item => item.id !== targetId);
    if (active) {
      backup(null);
      loadWork(works.length ? await api('/api/work?id=' + encodeURIComponent(works[0].id)) : null);
    } else renderWorkTabs();
  });
}
async function init() {
  const session = await api('/api/session'); publicationUrl = session.publication_url; token = session.token; questions = session.questions;
  for (const id of ['#open-import', '#open-publication', '#open-site', '#open-settings']) $(id).hidden = !publicationUrl;
  if (publicationUrl) showSiteState();
  workspaceKey = 'stemma:' + session.workspace;
  buffer = new WorkBuffer(api, backup, status);
  works = await api('/api/works');
  try { recovery = JSON.parse(localStorage.getItem(workspaceKey) || 'null'); } catch { message(t('editor.error.read_backup')); }
  const last = localStorage.getItem(workspaceKey + ':last');
  if (last) {
    try { loadWork(await api('/api/work?id=' + encodeURIComponent(last))); }
    catch (error) { message(error.message); }
  }
  renderWork(); ready = true; setBusy(false);
  if (recovery) { $('#recovery').hidden = false; setBusy(true); }
  await catalog(); panel('shelf');
  const incoming = new URLSearchParams(location.search).get('document');
  if (incoming && !recovery) {
    await openSource(incoming);
    loadWork(await api('/api/works', {document_id:incoming})); panel('writer');
  }
}
/* Pictures. The bytes are stored first and named by their own hash, so the link
   written into the manuscript is stable; the record of what it points at is sent
   with the next autosave, which is what makes the two impossible to disagree. */
function encode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
function renderAttachments() {
  const list = buffer.data.attachments || [], box = $('#attachments');
  box.replaceChildren();
  box.hidden = !list.length;
  for (const asset of list) {
    const chip = el('button', 'chip', asset.archive_path.slice(asset.archive_path.indexOf('/') + 1));
    chip.type = 'button'; chip.title = t('editor.attachment.reinsert');
    if (!asset.media_type.startsWith('image/')) chip.textContent = '📎 ' + chip.textContent;
    chip.onclick = () => {edit({body: insert(picture(asset))}); renderAttachments();};
    box.append(chip);
  }
}
// A picture is shown; anything else is a link, named so the reader knows what it is.
const picture = asset => asset.media_type.startsWith('image/')
  ? '![](' + asset.archive_path + ')'
  : '[' + asset.archive_path.slice(asset.archive_path.indexOf('/') + 1) + '](' + asset.archive_path + ')';
function insert(text) {
  const body = $('#body'), start = body.selectionStart ?? body.value.length, end = body.selectionEnd ?? start;
  const before = body.value.slice(0, start), after = body.value.slice(end);
  const gap = before && !before.endsWith('\n') ? '\n\n' : '';
  body.value = before + gap + text + '\n' + after;
  body.selectionStart = body.selectionEnd = (before + gap + text + '\n').length;
  body.focus();
  return body.value;
}
async function attach(files) {
  const chosen = [...files];
  if (!chosen.length) return;
  if (!ready || busy || recovery) throw refusal(t('editor.error.busy'));
  // The work has to exist before pictures can belong to it.
  if (!buffer.work) {buffer.edit({}); await buffer.flush();}
  const stored = [];
  let batch = [], size = 0;
  const send = async () => {
    if (!batch.length) return;
    status(t('editor.status.uploading', {done: stored.length + batch.length, total: chosen.length}));
    stored.push(...(await api('/api/assets', {id: buffer.work.id, files: batch})).attachments);
    batch = []; size = 0;
  };
  for (const file of chosen) {
    const data = encode(await file.arrayBuffer());
    // Requests are capped at 4MB, and base64 costs a third on top of the bytes.
    if (batch.length >= 20 || size + data.length > 11_000_000) await send();
    batch.push({name: file.name, data}); size += data.length;
  }
  await send();
  const list = (buffer.data.attachments || []).slice();
  for (const asset of stored) if (!list.some(a => a.archive_path === asset.archive_path)) list.push(asset);
  edit({attachments: list, body: insert(stored.map(picture).join('\n\n'))});
  renderAttachments();
  await flush();
  status(t('editor.status.uploaded', {count: stored.length}));
}
$('#attach-open').onclick = () => $('#attach').click();
$('#attach').onchange = () => run(async () => {
  try { await attach($('#attach').files); } finally { $('#attach').value = ''; }
});
$('#title').oninput = () => edit({title: $('#title').value});
$('#body').oninput = () => edit({body: $('#body').value});
$('#note').oninput = () => edit({note: $('#note').value});
$('#search').oninput = () => {clearTimeout(queryTimer); queryGeneration++; queryTimer = setTimeout(() => run(() => catalog()), 200);};
$('#archived').onchange = () => run(() => catalog()); $('#more').onclick = () => run(() => catalog(true));
$('#clear-selection').onclick = () => {edit({selections: []}); renderSelections(); renderDocs();};
$('#source-revision').onchange = () => run(() => openSource(source.id, $('#source-revision').value));
$('#copy-source').onclick = () => {
  if (!source || busy) return;
  const selections = structuredClone(buffer.data.selections);
  const selected = selections.find(item => item.id === source.id);
  if (selected && selected.revision !== source.revision) {
    message(t('editor.error.other_revision'));
    return;
  }
  if (!selected) selections.push({id: source.id, revision: source.revision, sha256: source.sha256, title: source.title, role: 'reference', questions: [], new_questions: [], note: '', archive: false});
  edit({body: buffer.data.body + (buffer.data.body ? '\n\n' : '') + source.body, selections}); renderWork(); panel('writer');
};
$('#revise-source').onclick = () => run(() => exclusive(async () => {await flush(); loadWork(await api('/api/works', {document_id: source.id})); panel('writer');}));
$('#restore-source').onclick = () => run(() => exclusive(async () => {await api('/api/restore', {id: source.id}); await catalog(); await openSource(source.id, source.revision);}));
$('#new-work').onclick = () => run(() => exclusive(async () => {await flush(); loadWork(null); panel('writer');}));
$('#focus').onclick = () => {const focus = $('.desk').classList.toggle('focus'); $('#focus').textContent = focus ? t('editor.focus.expand') : t('editor.focus.collapse');};
$('#save-revision').onclick = () => run(() => commit(false));
$('#review-open').onclick = () => {renderReview(); $('#review-dialog').showModal();};
$('#confirm').onclick = () => run(() => commit(true));
$('#retry').onclick = () => run(async () => {await flush(); message('');});
$('#recover').onclick = () => run(async () => {
  // Recovery starts a separate work so stale versions cannot overwrite newer work.
  buffer.load(null); buffer.edit({title: recovery.data.title, body: recovery.data.body, note: recovery.data.note, selections: recovery.data.selections});
  recovery = null; $('#recovery').hidden = true; setBusy(false); renderWork(); await flush(); panel('writer');
  message(t('editor.status.recovered'));
});
$('#download-recovery').onclick = () => {
  const blob = new Blob([JSON.stringify(recovery, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href=url; a.download='stemma-recovery.json'; a.click(); URL.revokeObjectURL(url);
};
$('#dismiss-recovery').onclick = () => { if (!confirm(t('editor.confirm.dismiss'))) return; backup(null); recovery=null; $('#recovery').hidden=true; setBusy(false); };
for (const node of document.querySelectorAll('[data-close]')) node.onclick = () => $('#' + node.dataset.close).close();
for (const node of document.querySelectorAll('button[data-panel]')) node.onclick = () => panel(node.dataset.panel);
window.addEventListener('beforeunload', event => {if (buffer && buffer.generation !== buffer.savedGeneration) {event.preventDefault(); event.returnValue='';}});
setBusy(true); run(init);

async function showRendered(example = false) {
  const dialog = $('#render-dialog');
  $('#render-heading').textContent = example ? t('editor.markdown_example') : t('editor.render.current');
  $('#render-error').textContent = t('common.loading');
  $('#render-frame').srcdoc = '';
  $('#markdown-source').hidden = !example;
  $('#markdown-source pre').textContent = '';
  dialog.showModal();
  try {
    const result = example ? await api('/api/markdown-example') : await api('/api/render-preview', {title: $('#title').value, body: $('#body').value, id: buffer.work?.id});
    $('#render-frame').srcdoc = result.html;
    if (example) $('#markdown-source pre').textContent = result.source;
    $('#render-error').textContent = '';
  } catch (error) { $('#render-error').textContent = error.message; }
}
$('#render-preview').onclick = () => showRendered();
// The desk's language is a preference of this data root, and the server fills each page in it.
$('#interface-language').onclick = () => run(async () => {
  await flush();
  await api('/api/interface-language', {language: t('nav.other_language_code')});
  location.reload();
});
$('#markdown-help').onclick = () => showRendered(true);

// The shared top bar: leaving for another screen first flushes the manuscript autosave.
for (const [id, suffix] of [['#open-import', '?view=import'], ['#open-publication', ''], ['#open-site', '?view=site'], ['#open-settings', '?view=settings']])
  $(id).onclick = event => {event.preventDefault();run(async () => {await flush();location.href=publicationUrl+suffix;});};
// The badge counts reader-visible changes not yet deployed; failure only hides it.
async function showSiteState() {
  try {
    const response = await fetch(publicationUrl + 'api/catalog');
    if (!response.ok) return;
    const site = await response.json(), badge = $('#nav-pending');
    badge.hidden = !site.site_changes && !site.pending_deployment;
    badge.textContent = site.pending_deployment ? t('nav.pending') : String(site.site_changes);
    if (site.site_url) { $('#site-link').href = site.site_url; $('#site-link').hidden = false; }
    // Rendered at an absolute base by the publication side, so the path is absolute here.
    if (site.latest_release) { $('#release-link').href = '/release/' + site.latest_release + '/'; $('#release-link').hidden = false; }
  } catch (_) {}
}
$('#prepare-publication').onclick = event => {event.preventDefault();run(async () => {
  if (busy || recovery) throw refusal(t('editor.error.busy'));
  await flush();
  const work=buffer.work, doc=await api('/api/document?'+new URLSearchParams({id:work.document_id}));
  if (buffer.data.body!==doc.body || buffer.data.title!==doc.title) throw refusal(t('editor.error.save_first'));
  location.href=publicationUrl+'?'+new URLSearchParams({document:doc.id,revision:doc.current_revision});
});};
