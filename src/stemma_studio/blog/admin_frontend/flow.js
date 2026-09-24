/* Pure view rules for the publication screen: list groups, state wording, the next step
   and change descriptions. The server decides states; these only word and order them.
   Wording is looked up when a function runs, never when the module loads, so it is always
   in the language the page was served in. */
import {t} from './i18n.js';

export function groups() {
  return [
    {id:'deploy', title:t('flow.group.deploy'), description:t('flow.group.deploy_note')},
    {id:'prepare', title:t('flow.group.prepare'), description:t('flow.group.prepare_note')},
    {id:'live', title:t('flow.group.live'), description:t('flow.group.live_note')},
    {id:'rest', title:t('flow.group.rest'), description:t('flow.group.rest_note'), folded:true},
    {id:'other', title:t('flow.group.other'), description:t('flow.group.other_note')},
  ];
}

export function groupDocuments(documents) {
  return groups().map(group=>({...group, documents:documents.filter(d=>d.group===group.id)}))
    .filter(group=>group.documents.length);
}

// A short state tag and notes naming the revisions involved, for list rows and the post header.
export function siteLabel(site, {archived=false, kind='original'}={}) {
  const {change, work, live_revision:live, selected_revision:selected, current_revision:current} = site;
  const notes = [];
  let label;
  if (!site.confirmed) return {label:t('flow.label.writing'), notes:[t('flow.note.confirm_in_editor')]};
  if (change === 'new') {label = t('flow.label.new'); notes.push(t('flow.note.confirmed', {revision:selected}));}
  else if (change === 'withdraw') {label = t('flow.label.withdraw'); notes.push(t('flow.note.live', {revision:live}));}
  else if (change === 'revision') {label = t('flow.label.revision'); notes.push(t('flow.note.revision', {live, selected}));}
  else if (change === 'translation') {label = t('flow.label.translation'); notes.push(t('flow.note.translation', {revision:live}));}
  else if (selected) {
    label = work === 'revision' ? t('flow.label.needs_translation') : work ? t('flow.label.editing') : t('flow.label.live');
    notes.push(work === 'revision' ? t('flow.note.written', {revision:current}) + ' · ' + t('flow.note.site', {revision:live}) : t('flow.note.site', {revision:live}));
    if (work === 'translation') notes.push(t('flow.note.unconfirmed'));
  }
  else if (site.withdrawn) {label = t('flow.group.rest'); notes.push(current);}
  else if (work) {label = t('flow.label.translating'); notes.push(current + ' · ' + t('flow.note.kept'));}
  else if (kind === 'original') {label = t('flow.label.unpublished'); notes.push(current + ' · ' + t('flow.note.no_translation'));}
  else {label = t('flow.group.other'); notes.push(current);}
  if (change && change !== 'withdraw' && work === 'revision') notes.push(t('flow.note.written', {revision:current}));
  else if (change && work === 'translation') notes.push(t('flow.note.unconfirmed'));
  // Archived posts appear only while something of them is still on, or bound for, the site.
  if (archived) notes.push(t('flow.note.archived'));
  return {label, notes};
}

const partLabels = () => ({'ko.title':t('flow.part.ko.title'),'ko.summary':t('flow.part.ko.summary'),'ko.body':t('flow.part.ko.body'),
  'en.title':t('flow.part.en.title'),'en.summary':t('flow.part.en.summary'),'en.body':t('flow.part.en.body'),
  assets:t('flow.part.assets'),slug:t('flow.part.slug'),date:t('flow.part.date')});

export function partNames(parts, names=partLabels()) {
  return parts.map(part=>names[part]||part);
}

const quote = (text, limit=40) => '“' + (text.length > limit ? text.slice(0, limit) + '…' : text) + '”';

// One genealogy wording edit: which question or note, and what readers will see instead.
// `original` is the wording as written; `language` names the side that is its translation.
export function wordingText(edit) {
  const what = (edit.kind === 'question' ? t('flow.wording.question') : t('flow.wording.note')) + ' ' + quote(edit.original);
  const translated = side => side?.[edit.language] || '';
  if (!edit.before) return what + ' · ' + t('flow.wording.shown', {text:quote(translated(edit.after))});
  if (!edit.after) return what + ' · ' + t('flow.wording.hidden');
  if (translated(edit.before) !== translated(edit.after)) return what + ' · ' + t('flow.wording.changed', {before:quote(translated(edit.before)), after:quote(translated(edit.after))});
  return what + ' · ' + t('flow.wording.original_changed');
}

/* A decision row of the site screen: what the author decided about one post and what
   changes with it. Lines are [heading, text] pairs in a fixed order. */
export function describeRow(row) {
  const tag = {new:t('flow.row.new'), withdraw:t('flow.row.withdraw'), update:t('flow.row.update')}[row.change];
  const note = row.change === 'new' ? (row.after ? t('flow.row.published', {revision:row.after}) : '') :
    row.change === 'withdraw' ? t('flow.row.taken_down') + (row.before ? ' (' + row.before + ')' : '') :
    row.before && row.after && row.before !== row.after ? t('flow.row.revision', {before:row.before, after:row.after}) : '';
  const lines = [];
  const text = row.text.filter(part=>part !== 'graph');
  if (row.change === 'update' && text.length) lines.push([t('flow.line.text'), partNames(text).join(' · ')]);
  if (row.text.includes('graph')) lines.push([t('flow.line.genealogy'), t('flow.line.genealogy_changed')]);
  if (row.series.length) lines.push([t('flow.line.series'), row.series.map(s=>t(s.change === 'added' ? 'flow.series.added' : 'flow.series.removed', {title:s.title})).join(' · ')]);
  for (const edit of row.labels) lines.push([t('flow.line.wording'), wordingText(edit)]);
  const effects = row.effects.map(e=>e.kind === 'genealogy' ? t('flow.effect.genealogy', {titles:e.titles.map(title=>'‘' + title + '’').join(', ')}) :
    e.kind === 'series-vanishes' ? t('flow.effect.series_vanishes', {title:e.title}) : t('flow.effect.series_appears', {title:e.title}));
  if (effects.length) lines.push([t('flow.line.effects'), effects.join(' · ')]);
  return {tag, note, lines};
}

// Site-level rows: series settings and the home order, edited on the site screen.
export function describeSite(item) {
  if (item.kind === 'home-order') return {tag:t('flow.site.home_order'), title:t('flow.site.home_order_title'), lines:[[t('flow.site.order'), item.before.join(' · ') + ' → ' + item.after.join(' · ')]]};
  if (item.kind === 'first') return {tag:t('flow.site.first'), title:t('flow.site.first_title'), lines:[[t('flow.site.content'), t('flow.site.first_note')]]};
  if (item.kind === 'other') return {tag:t('flow.site.other'), title:t('flow.site.other_title'), lines:[]};
  // Skin files change with the code, not with a decision here, so they have no ✕.
  if (item.kind === 'skin') return {tag:t('flow.site.skin'), title:t('flow.site.skin_title'), lines:[[t('flow.site.files'), item.files.join(', ')]]};
  const lines = [];
  if (item.parts.includes('appears')) lines.push([t('flow.site.shown'), t('flow.site.appears')]);
  if (item.parts.includes('vanishes')) lines.push([t('flow.site.shown'), t('flow.site.vanishes')]);
  if (item.parts.includes('translations')) {
    const name = names=>names.ko.title + ' / ' + names.en.title;
    if (name(item.before) !== name(item.after)) lines.push([t('flow.site.name'), name(item.before) + ' → ' + name(item.after)]);
    if (item.before.ko.summary !== item.after.ko.summary || item.before.en.summary !== item.after.en.summary) lines.push([t('flow.site.summary'), t('flow.site.summary_changed')]);
  }
  if (item.parts.includes('order')) lines.push([t('flow.site.post_order'), item.order[0].join(' · ') + ' → ' + item.order[1].join(' · ')]);
  if (item.parts.includes('slug')) lines.push([t('flow.site.address'), t('flow.site.address_changed')]);
  return {tag:t('flow.line.series'), title:item.title, lines};
}

// What ✕ (return to the site state) does, confirmed before anything is written.
export function revertPrompt(kind, item) {
  const kept = '\n' + t('flow.revert.kept');
  if (kind === 'post' && item.change === 'new') return t('flow.revert.new', {title:item.title}) + kept;
  if (kind === 'post' && item.change === 'withdraw') return t('flow.revert.withdraw', {title:item.title});
  if (kind === 'post') return t('flow.revert.post', {title:item.title}) + kept;
  if (kind === 'label') return t('flow.revert.label', {titles:item.titles.join(', ')});
  if (kind === 'series') return t('flow.revert.series', {title:item.title});
  return t('flow.revert.home_order');
}

// Which of the form's public texts differ from stored variants (`text` is the translated body).
export function textChanges(form, variants, translation) {
  const changed = [];
  for (const lang of ['ko','en']) {
    const variant = variants[lang];
    for (const field of lang === translation ? ['title','summary','body'] : ['title','summary']) {
      const stored = variant ? (field === 'body' ? variant.text : variant[field]) || '' : null;
      if (stored === null ? form[lang][field] !== '' : form[lang][field] !== stored) changed.push(lang + '.' + field);
    }
  }
  return changed;
}

// Rules the domain enforces later (at variant save or pair approval), reported before any request.
export function formProblem(form, translation) {
  const original = translation === 'ko' ? 'en' : 'ko';
  if (!form[original].title.trim()) return t('flow.problem.original_title');
  if (!form[translation].title.trim()) return t('flow.problem.translation_title');
  if (!form[translation].body.trim()) return t('flow.problem.translation_body');
  if (!form.ko.summary.trim() !== !form.en.summary.trim()) return t('flow.problem.summaries');
  return '';
}

/* The genealogy the post now sits in, against the structure its last confirmation approved.
   The server compares the two; this only words the difference for the change line. */
export function structureText({structure_changed, nodes, selected_structures}) {
  if (!structure_changed) return '';
  const approved = selected_structures[0]?.nodes.length;
  return t('flow.structure') + (approved === undefined || approved === nodes.length ? '' :
    ' · ' + t('flow.structure_count', {before:approved, after:nodes.length}));
}

/* A preview is the review of the exact inputs it was made from, so it survives only while
   they are unchanged. Comparing them at every refresh keeps a stale preview out of the
   confirm step without each input path having to remember to discard it. */
export function previewMatches(candidate, inputs) {
  return !!candidate && JSON.stringify(candidate.inputs) === JSON.stringify(inputs);
}

/* Two steps: a preview stages saving and review in memory, and confirming it records
   them together. `pending` means the confirmable state differs from the local selection.
   A read-only session may preview but never confirm. */
export function nextStep({confirmed, readOnly, pending, previewed}) {
  if (!confirmed || !pending) return null;
  if (!previewed) return 'preview';
  return readOnly ? null : 'confirm';
}

export const STEPS = {
  preview:{get label() {return t('flow.step.preview');}, get hint() {return t('flow.step.preview_hint');}},
  confirm:{get label() {return t('flow.step.confirm');}, get hint() {return t('flow.step.confirm_hint');}},
};

/* Line diff of two Korean revisions for translators: changed lines with `context`
   unchanged neighbours, longer unchanged runs folded into {type:'skip', count}. */
export function lineDiff(before, after, context=1) {
  const a=before.split('\n'), b=after.split('\n'), n=a.length, m=b.length;
  const lcs=Array.from({length:n+1},()=>new Uint32Array(m+1));
  for (let i=n-1;i>=0;i--) for (let j=m-1;j>=0;j--) lcs[i][j]=a[i]===b[j]?lcs[i+1][j+1]+1:Math.max(lcs[i+1][j],lcs[i][j+1]);
  const ops=[];let i=0,j=0;
  while (i<n&&j<m) {
    if (a[i]===b[j]) {ops.push({type:'same',text:a[i]});i++;j++;}
    else if (lcs[i+1][j]>=lcs[i][j+1]) ops.push({type:'del',text:a[i++]});
    else ops.push({type:'add',text:b[j++]});
  }
  while (i<n) ops.push({type:'del',text:a[i++]});
  while (j<m) ops.push({type:'add',text:b[j++]});
  const near=k=>ops.slice(Math.max(0,k-context),k+context+1).some(op=>op.type!=='same');
  const out=[];
  ops.forEach((op,k)=>{
    if (op.type!=='same'||near(k)) out.push(op);
    else if (out.at(-1)?.type==='skip') out.at(-1).count++;
    else out.push({type:'skip',count:1});
  });
  return out;
}

// Number of separate changed places, for the summary line.
export function changePlaces(ops) {
  return ops.filter((op,k)=>op.type!=='same'&&op.type!=='skip'&&!['add','del'].includes(ops[k-1]?.type)).length;
}

/* Consecutive failed or never-sent releases collapse into one row between successes.
   Input is newest first; output rows are either {release} or {failed:[...]}. */
export function historyRows(releases, statusOf) {
  const rows = [];
  for (const release of releases) {
    if (statusOf(release) === 'succeeded') rows.push({release});
    else if (rows.length && rows.at(-1).failed) rows.at(-1).failed.push(release);
    else rows.push({failed:[release]});
  }
  return rows;
}

/* Which screen a clicked link asks for. The top bar and in-page links share one handler,
   so every destination has to be named here: anything unnamed falls back to the post list. */
export function navParams({id, view, document:doc}) {
  if (doc) return {document:doc};
  const named = id==='nav-site'||view==='site' ? 'site'
    : id==='nav-import'||view==='import' ? 'import'
    : id==='nav-settings'||view==='settings' ? 'settings' : '';
  return named ? {view:named} : {};
}

/* What a deployment says about itself depends on where it is going. A folder is finished
   the moment its bytes are read back, so nothing about merging or building applies to it;
   the pull-request path has stages the author has to act on elsewhere. Keeping these as
   values rather than branches in the view is what lets both modes be checked. */
export function deploymentCopy(mode) {
  const folder = mode === 'local-folder';
  return {
    folder,
    lede: !mode ? t('flow.deploy.lede_none') : folder ? t('flow.deploy.lede_folder') : t('flow.deploy.lede_pr'),
    sending: folder ? t('flow.deploy.sending_folder') : t('flow.deploy.sending_pr'),
    deployed: folder ? t('flow.deploy.deployed_folder') : t('flow.deploy.deployed_pr'),
    steps: folder
      ? [t('flow.deploy.step.freeze'), t('flow.deploy.step.write'), t('flow.deploy.step.verify')]
      : [t('flow.deploy.step.freeze'), t('flow.deploy.step.pr'), t('flow.deploy.step.merge'), t('flow.deploy.step.pages')],
    note: folder ? t('flow.deploy.note_folder') : t('flow.deploy.note_pr'),
  };
}

/* A failed or unstarted release that still matches the local selections and is still
   aimed at the destination configured now. The server decides both of those; this only
   reads the answer, so one frozen release is never offered from a screen that has since
   been pointed somewhere else. */
export function retryable({pending, rollback}) {
  return !rollback && !!pending && !pending.running && pending.current;
}

/* The one control that sends a release, and every reason it is or is not offered. It is
   a decision rather than rendering: 'the writing has not changed' and 'this destination
   does not have it yet' pull in opposite directions, and while this lived inline in the
   view the first silently won, which left a newly chosen folder unreachable. */
export function deployButton(data, {readOnly = false} = {}) {
  const {pending, rollback} = data;
  // A rollback is judged by what it would change, not by the local selections: those can
  // match the live site exactly while the release being restored differs from it.
  const changes = rollback ? rollback.changes : data.changes;
  const running = !!pending?.running, folder = data.destination?.mode === 'local-folder';
  let label = folder ? t('flow.deploy.folder') : t('flow.deploy.pr'), hint = '', disabled = false;
  if (running) { disabled = true; hint = t('flow.deploy.hint.running'); }
  else if (!data.destination) { disabled = true; hint = t('flow.deploy.hint.no_destination'); }
  else if (!changes) { disabled = true; hint = t('flow.deploy.hint.no_output', {error:data.changes_error}); }
  else if (retryable(data)) {
    if (pending.status === 'failed') label = t('flow.deploy.retry');
    disabled = !pending.deployable;
    hint = pending.status === 'failed' ? t('flow.deploy.hint.retry_failed')
      : folder ? t('flow.deploy.hint.prepared_folder') : t('flow.deploy.hint.prepared_pr');
  }
  else if (changes.empty && !data.destination_missing_site) {
    disabled = true;
    hint = rollback ? t('flow.deploy.hint.same_as_site') : t('flow.deploy.hint.nothing');
  }
  else if (rollback) {
    label = folder ? t('flow.deploy.rollback_folder') : t('flow.deploy.rollback_pr');
    hint = folder ? t('flow.deploy.hint.rollback_folder') : t('flow.deploy.hint.rollback_pr');
  }
  else if (changes.empty) {
    hint = folder ? t('flow.deploy.hint.missing_folder') : t('flow.deploy.hint.missing_pr');
  }
  else hint = folder ? t('flow.deploy.hint.folder') : t('flow.deploy.hint.pr');
  if (readOnly) { disabled = true; hint = t('flow.read_only'); }
  return {label, disabled, hint};
}

export function checkedMessage(mode, status) {
  const folder = mode === 'local-folder';
  if (status === 'running') return folder ? t('flow.checked.running_folder') : t('flow.checked.running_pr');
  if (status === 'succeeded') return folder ? t('flow.checked.succeeded_folder') : t('flow.checked.succeeded_pr');
  return t('flow.checked.failed');
}

/* A scan is a proposal and an import is a result; they are different states even though
   the server describes both with the same counts. Only a proposal offers to import.

   New posts are not the only work a scan can find: a picture that was missing when a post
   arrived can be attached now, and a folder whose posts are all here already is exactly
   where that happens. Counting only the new ones left that scan with nothing to press. */
export function importState(report, {readOnly = false} = {}) {
  const applied = report.status === 'imported' || report.status === 'nothing_to_import';
  const count = report.counts.new, recovered = report.counts.recovered || 0;
  const what = count || recovered;
  // Each action names what it moves: new pieces, or pictures that were missing before.
  const action = count ? (applied ? 'flow.import.imported' : 'flow.import.import')
    : applied ? 'flow.import.attached' : 'flow.import.attach';
  return {
    applied,
    ready: !applied && !!what && !readOnly,
    state: applied
      ? (count ? t('flow.import.state.imported')
        : recovered ? t('flow.import.state.attached')
          : t('flow.import.state.nothing'))
      : t('flow.import.state.scanned'),
    action: what ? t(action, {count, pictures:recovered})
      : applied ? t('flow.import.none_imported') : t('flow.import.none'),
    hint: applied
      ? t('flow.import.hint.again')
      : readOnly ? t('flow.read_only') : what ? t('flow.import.hint.skipped') : '',
  };
}

/* The reviewed plan describes the controls as they were; once they move it describes
   nothing the author can still see, so it is dropped rather than confirmed blindly. */
export function importMatches(reviewed, inputs) {
  return !!reviewed && reviewed.folder === inputs.folder && reviewed.rule === inputs.rule;
}
