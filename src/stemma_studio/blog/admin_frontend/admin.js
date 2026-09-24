import {t,language} from './i18n.js';
import {draftFromFields,importMarkdown,seriesSelection} from './buffer.js';
import {groupDocuments,siteLabel,describeRow,describeSite,wordingText,revertPrompt,textChanges,formProblem,structureText,previewMatches,nextStep,STEPS,historyRows,partNames,lineDiff,changePlaces,navParams,deploymentCopy,retryable,deployButton,checkedMessage,importState,importMatches as planMatches} from './flow.js';
const $=id=>document.getElementById(id);
let session, catalog, detail, candidate=null, draftVersion=0, saveTimer=null, queue=Promise.resolve();
let appliedQuery='', seriesChanged=false;
let releaseState=null,rollbackRelease=null,seriesEditing=null,identityState=null;
const slugify=text=>text.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'series';
// A notice may carry one action, e.g. reloading after another screen changed the data.
function notice(message,action){$('notice').replaceChildren(message);if(action)$('notice').append(' ',action);}
function el(tag,text,className){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;}
function button(text,fn,className){const b=el('button',text,className);b.type='button';b.addEventListener('click',()=>run(fn));return b;}
function link(text,href){const a=el('a',text);a.href=href;a.target='_blank';a.rel='noopener noreferrer';return a;}
async function api(path,body){const response=await fetch(new URL('api/'+path,location.href),body?{method:'POST',headers:{'Content-Type':'application/json','X-Blog-Token':session.token},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw Object.assign(new Error(data.error),{status:response.status});return data;}
function run(fn){queue=queue.then(fn).catch(error=>notice(error.message,error.status===409?button(t('admin.reload'),()=>{notice('');return route();},'quiet'):null));return queue;}

/* Views: the post list, one post's public edition, and the site with its deployments.
   `go` queues the route instead of awaiting it, so callers already inside `run` never wait on themselves. */
function show(view){
  for(const name of ['posts','post','site','import','settings'])$(name+'-view').hidden=name!==view;
  const named=['site','import','settings'];
  for(const [id,active] of [['nav-posts',!named.includes(view)],['nav-site',view==='site'],['nav-import',view==='import'],['nav-settings',view==='settings']])active?$(id).setAttribute('aria-current','page'):$(id).removeAttribute('aria-current');
  if(view!=='post')detail=null;
}
/* Leaving a screen has an order to it. The pending draft save has to be queued *before*
   the navigation is: a flush started from inside the queue only runs once the navigation
   it was meant to precede has already replaced the document and the fields it would have
   read. Both ways out of a screen go through here — in-app links and the browser's own
   back and forward buttons — so neither can quietly lose the ordering. */
function leaveScreen(){if(detail){flushSave();backup();backupScope();}}
function go(params={}){
  leaveScreen();
  const query=new URLSearchParams(params).toString();
  history.pushState(null,'',location.pathname+(query?'?'+query:''));
  run(route);
}
async function route(){
  const params=new URLSearchParams(location.search);notice('');
  if(params.get('view')==='settings')return showSettings();
  if(params.get('view')==='import')return showImport();
  if(params.get('view')==='site')return showSite();
  if(params.has('document'))return openDocument(params.get('document'),params.get('revision'));
  return showList();
}
window.addEventListener('popstate',()=>{leaveScreen();run(route);});
document.addEventListener('click',event=>{
  const target=event.target.closest('a[data-view],a[data-document],#nav-posts,#nav-site,#nav-import,#nav-settings,#brand');
  if(!target||event.metaKey||event.ctrlKey||event.shiftKey)return;
  event.preventDefault();
  go(navParams({id:target.id, view:target.dataset.view, document:target.dataset.document}));
});
function badge(){
  const count=catalog?.site_changes,running=catalog?.pending_deployment,b=$('nav-pending');
  b.hidden=!count&&!running;b.textContent=running?t('nav.pending'):String(count);
}

// ----- Post list
async function loadCatalog(){
  catalog=await api('catalog?q='+encodeURIComponent(appliedQuery));
  $('site-link').hidden=!catalog.site_url;if(catalog.site_url)$('site-link').href=catalog.site_url;
  // The frozen release is offered from every screen's banner, not only the site screen.
  $('release-link').hidden=!catalog.latest_release;
  if(catalog.latest_release)$('release-link').href='/release/'+catalog.latest_release+'/';
  badge();
}
async function showList(){await loadCatalog();show('posts');renderList();}
function renderList(){
  const count=catalog.site_changes;
  $('deploy-banner').hidden=!!appliedQuery||!(count||catalog.pending_deployment);
  $('deploy-banner-text').textContent=catalog.pending_deployment?t('admin.banner.running'):t('admin.banner.changes',{count});
  const note=$('list-note');note.replaceChildren();
  if(appliedQuery){note.append(t('admin.list.results',{query:appliedQuery,count:catalog.documents.length})+' ');note.append(button(t('admin.list.clear'),()=>{appliedQuery='';$('query').value='';return showList();},'quiet'));}
  else note.textContent=t('admin.list.note');
  const box=$('catalog');box.replaceChildren();
  if(!catalog.documents.length){box.append(el('p',appliedQuery?t('admin.list.none_found'):t('admin.list.empty'),'empty'));return;}
  for(const group of groupDocuments(catalog.documents)){
    const section=el(group.folded&&!appliedQuery?'details':'section',null,'group');
    const head=el(section.tagName==='DETAILS'?'summary':'div',null,'group-head');
    head.append(el('h2',group.title),el('span',String(group.documents.length),'count'),el('span',group.description,'subtle'));
    const rows=el('ul',null,'rows');
    for(const d of group.documents){
      const {label,notes}=siteLabel(d.site,d),row=el('button',null,'row');row.type='button';
      row.append(el('span',label,'tag tag-'+d.group),el('span',d.title,'row-title'),el('span',notes.join(' · '),'row-note'));
      row.addEventListener('click',()=>go({document:d.id}));
      const item=el('li');item.append(row);rows.append(item);
    }
    section.append(head,rows);box.append(section);
  }
}
$('search').addEventListener('submit',event=>{event.preventDefault();appliedQuery=$('query').value.trim();run(showList);});

// ----- One post: translation, public information, preview and confirmation
/* Keys carry the workspace as well as the document and revision. The same local origin
   serves whichever data root was opened last, and two roots can hold the same imported
   ID, so without this a draft could be offered back against somebody else's writing.
   Every writer and reader of these keys goes through here, so they cannot disagree. */
function draftKey(kind,document,revision){return 'writing-blog-'+kind+':'+session.workspace+':'+document+':'+revision;}
function recoveryKey(){return draftKey('draft',detail.id,detail.revision);}
/* A post is written in one language and translated into the other; `detail.language` and
   `detail.translation` say which, and are null until the author has named the language they
   write in. Nothing below builds a draft without them, so none is ever saved on a guess. */
function formDraft(){return draftFromFields(detail.revision,{originalTitle:$('original-title').value,originalSummary:$('original-summary').value,
  translationTitle:$('translation-title').value,translationSummary:$('translation-summary').value,translationBody:$('translation-body').value},detail.language,detail.translation);}
function fillDraft(d){const o=d[detail.language],tr=d[detail.translation];$('original-title').value=o.title;$('original-summary').value=o.summary;
  $('translation-title').value=tr.title;$('translation-summary').value=tr.summary;$('translation-body').value=tr.body;}
const languageName=code=>code==='ko'?t('common.lang.ko'):t('common.lang.en'),languageCode=code=>code==='ko'?'KR':'EN';
function scopeKey(){return draftKey('scope',detail.id,detail.revision);}
function scopeFields(){return {labels:Object.fromEntries(labelRows().map(row=>[row.dataset.kind+':'+row.dataset.target,row.querySelector('textarea').value])),series:$('series-choice').value,seriesChanged,seriesBase:detail.series,ko:$('new-series-ko').value,en:$('new-series-en').value};}
function readScope(){try{return JSON.parse(localStorage.getItem(scopeKey()));}catch(_){return null;}}
function restoreScope(value){if(!value)return;for(const row of labelRows()){const key=row.dataset.kind+':'+row.dataset.target;if(value.labels && key in value.labels)row.querySelector('textarea').value=value.labels[key];}const restored=seriesSelection(detail.series,value,catalog.series.map(s=>s.id));seriesChanged=restored.changed;$('series-choice').value=restored.value;$('new-series-ko').value=value.ko||'';$('new-series-en').value=value.en||'';$('new-series-fields').hidden=restored.value!=='new';}
function backupScope(){if(!detail?.language)return;try{localStorage.setItem(scopeKey(),JSON.stringify(scopeFields()));}catch(_){notice(t('admin.error.scope_backup'));}}
function backup(){if(!detail?.language)return;try{localStorage.setItem(recoveryKey(),JSON.stringify(formDraft()));}catch(_){notice(t('admin.error.backup'));}}
function invalidatePreview(){candidate=null;$('preview-review').hidden=true;}
async function openDocument(id,revision){
  // Reached from inside the queue, so a flush here would land after renderDetail. The
  // navigation entry points have already queued it; these copies are synchronous.
  if(detail){backup();backupScope();}
  if(!catalog)await loadCatalog();
  const data=await api('document?id='+encodeURIComponent(id)+(revision?'&revision='+encodeURIComponent(revision):''));
  show('post');renderDetail(data);window.scrollTo(0,0);
}
function setOpen(step,open){
  const body=$(step+'-body'),toggle=document.querySelector('[aria-controls="'+step+'-body"]');
  body.hidden=!open;toggle.setAttribute('aria-expanded',String(open));toggle.textContent=open?t('admin.step.fold'):t('admin.step.edit');
}
for(const toggle of document.querySelectorAll('.step-toggle'))toggle.addEventListener('click',()=>setOpen(toggle.getAttribute('aria-controls').replace('-body',''),$(toggle.getAttribute('aria-controls')).hidden));

function renderDetail(data,keepInputs=false){const scope=detail&&keepInputs&&detail.id===data.id&&detail.revision===data.revision?scopeFields():null;const previous=detail?.language&&keepInputs?formDraft():null;detail=data;invalidatePreview();
  $('title').textContent=detail.title;
  const {label,notes}=siteLabel(detail.site,detail);
  $('site-line').replaceChildren(el('span',label,'tag tag-'+detail.site.group),el('span',notes.join(' · ')));
  const known=!!detail.language;
  $('language-needed').hidden=known;$('text-sides').hidden=!known;
  for(const id of ['step-meta','step-preview','actionbar'])$(id).hidden=!known;
  if(!known){$('more').hidden=true;setOpen('text',true);return;}
  $('tab-original').textContent=t('admin.text.tab_original',{code:languageCode(detail.language)});
  $('tab-translation').textContent=t('admin.text.tab_translation',{code:languageCode(detail.translation)});
  $('original-heading').textContent=t('admin.text.original_heading',{language:languageName(detail.language)});
  $('translation-heading').textContent=languageName(detail.translation);
  $('revision').replaceChildren(...detail.revisions.map(r=>{const o=el('option',r+(r===detail.current_revision?' '+t('admin.text.latest'):''));o.value=r;return o;}));$('revision').value=detail.revision;
  $('old-base').textContent=detail.revision!==detail.current_revision?t('admin.text.old_base'):'';
  $('original-body').textContent=detail.body;
  // A new base revision is translated against the confirmed one: show only what moved.
  $('original-diff').hidden=!detail.compare;
  if(detail.compare){
    const ops=lineDiff(detail.compare.body,detail.body);
    $('original-diff-title').textContent=t('admin.text.diff',{before:detail.compare.revision,after:detail.revision,count:changePlaces(ops)});
    $('original-diff-body').replaceChildren(...ops.filter(op=>op.type!=='same'||op.text.trim()).map(op=>
      op.type==='skip'?el('p','⋯ '+t('admin.text.diff_skip',{count:op.count}),'diff-skip'):el('p',op.text||' ','diff-'+op.type)));
  }
  const work=detail.draft&&detail.draft.revision===detail.revision?detail.draft:null;draftVersion=detail.draft?.version||0;
  // Start from the confirmed (or live) text of this revision; a reverted variant is not a start.
  const baseline={},variant=id=>detail.variants.find(v=>v.id===id),pairs=[detail.pairs[detail.selected_pair],detail.pairs[detail.live_pair]].filter(Boolean);
  for(const lang of ['ko','en']) baseline[lang]=variant(pairs.find(p=>p.base_revision===detail.revision)?.variants[lang])||
    detail.variants.filter(v=>v.language===lang&&v.base_revision===detail.revision).at(-1)||variant(pairs[0]?.variants[lang]);
  const [o,tr]=[baseline[detail.language],baseline[detail.translation]];
  fillDraft(previous||work||{[detail.language]:{title:o?.title||detail.title,summary:o?.summary||''},[detail.translation]:{title:tr?.title||'',summary:tr?.summary||'',body:tr?.text||''}});
  $('edit-document').hidden=!session.editor_url||detail.kind!=='original'||detail.archived||session.read_only;
  $('edit-document').href='/?'+new URLSearchParams({document:detail.id});
  $('read-public').hidden=!detail.public_url;
  if(detail.public_url)$('read-public').href=detail.public_url;
  $('draft-status').textContent=session.read_only?t('admin.draft.read_only'):work?t('admin.draft.kept',{version:work.version}):tr && tr.base_revision!==detail.revision?t('admin.draft.from_previous'):t('admin.draft.idle');
  refreshRecover();
  const seriesChoice=$('series-choice');seriesChoice.replaceChildren(new Option(t('admin.series.none'),''),new Option(t('admin.series.new'),'new'),...catalog.series.map(s=>new Option(s.translations[detail.language]?.title||s.id,s.id)));if(detail.series.length>1)seriesChoice.append(new Option(t('admin.series.keep'),'keep'));seriesChoice.value=seriesSelection(detail.series,null,[]).value;seriesChanged=false;$('series-current').textContent=t('admin.series.current',{names:currentSeriesNames()});$('new-series-fields').hidden=true;$('new-series-ko').value='';$('new-series-en').value='';
  // Readers see a question's wording only if the question is public, and a change note only
  // between two published posts; other rows stay translatable but are folded away.
  const published=new Set([detail.id,...detail.nodes.filter(n=>n.selected).map(n=>n.id)]);
  const labelItems=[...Object.entries(detail.questions).map(([target,title])=>({kind:'question',target,title,visible:detail.public_questions.includes(target)})),
    ...detail.edges.map(e=>({kind:'edge',target:e.id,title:t('admin.labels.edge',{title:detail.nodes.find(n=>n.id===e.child)?.title||''}),visible:e.public&&published.has(e.parent)&&published.has(e.child)}))];
  const shown=el('div'),hidden=el('details',null,'hidden-labels');
  for(const item of labelItems){const row=el('div',null,'label-row');row.dataset.kind=item.kind;row.dataset.target=item.target;row.dataset.visible=item.visible;const existing=detail.labels[item.kind][item.target]||{translations:{}};const original=item.kind==='question'?item.title:detail.edges.find(e=>e.id===item.target).change_note;if(!original)continue;/* Wording is shared across posts and keeps the language it was written in, which the server names. */const written=detail.label_languages[item.kind][item.target]||detail.language,into=written==='ko'?'en':'ko';row.dataset.language=written;row.dataset.translation=into;row.dataset.original=original;row.dataset.translated=existing.translations[into]||'';row.append(el('p',original));const label=el('label',t('admin.labels.translation',{language:languageName(into)}));const input=el('textarea');input.dataset.lang=into;input.value=row.dataset.translated;label.append(input);row.append(label);(item.visible?shown:hidden).append(row);}
  if(!shown.children.length)shown.append(el('p',t('admin.labels.none'),'subtle'));
  if(hidden.children.length)hidden.prepend(el('summary',t('admin.labels.hidden',{count:hidden.children.length})),el('p',t('admin.labels.hidden_note'),'subtle'));
  $('labels').replaceChildren(shown,...(hidden.children.length?[hidden]:[]));
  $('attachments').replaceChildren(el('p',detail.attachments.length ? t('admin.attachments.included',{count:detail.attachments.length}) : t('admin.attachments.none'),'subtle'));
  $('missing').textContent=detail.missing_assets.length?t('admin.attachments.missing',{count:detail.missing_assets.length}):'';
  $('planned').value=new Date().toISOString().replace(/\.\d{3}Z$/,'Z');
  restoreScope(scope || readScope());
  $('revert-post').hidden=!detail.site_row;$('unselect').hidden=!(detail.live_pair&&detail.selected_pair);
  $('more').hidden=$('revert-post').hidden&&$('unselect').hidden;
  $('revert-post').disabled=$('unselect').disabled=session.read_only;
  const isNew=!detail.selected_pair;
  setOpen('text',isNew||!!detail.site.work||!!detail.compare);
  setOpen('meta',isNew);
  refresh();
}
// Offer the browser copy only when it holds something the screen does not show.
function refreshRecover(){try{const kept=localStorage.getItem(recoveryKey());$('recover').hidden=!kept||kept===JSON.stringify(formDraft());}catch(_){$('recover').hidden=true;}}

function variantsOf(ids){return {ko:detail.variants.find(v=>v.id===ids?.ko),en:detail.variants.find(v=>v.id===ids?.en)};}
function currentSeriesNames(){return detail.series.map(id=>catalog.series.find(s=>s.id===id)?.translations[detail.language]?.title||id).join(' · ')||t('common.none');}
function seriesName(value){return value==='keep'?currentSeriesNames():value===''?t('common.none'):value==='new'?t('admin.series.new_named',{name:$('new-series-'+detail.language).value||t('admin.series.unnamed')}):catalog.series.find(s=>s.id===value)?.translations[detail.language]?.title||value;}
function seriesChange(){const baseline=seriesSelection(detail.series,null,[]).value,value=$('series-choice').value;return seriesChanged&&value!==baseline&&value!=='keep'?t('admin.series.change',{before:currentSeriesNames(),after:seriesName(value)}):'';}
function labelRows(){return [...$('labels').querySelectorAll('.label-row')];}
// Everything that confirming now would change relative to the post's current local selection.
function status(){
  const form=formDraft(),pair=detail.selected_pair?detail.pairs[detail.selected_pair]:null;
  const changes=[];
  if(!pair)changes.push(t('admin.changes.new'));
  else{
    if(pair.base_revision!==detail.revision)changes.push(t('admin.changes.base',{before:pair.base_revision,after:detail.revision}));
    const parts=textChanges(form,variantsOf(pair.variants),detail.translation);
    if(parts.length)changes.push(partNames(parts).join(' · '));
    const structure=structureText(detail);if(structure)changes.push(structure);
  }
  const series=seriesChange();if(series)changes.push(series);
  const labels=labelRows().filter(row=>row.querySelector('textarea').value.trim()!==row.dataset.translated.trim()).length;
  if(labels)changes.push(t('admin.changes.labels',{count:labels}));
  const previewed=previewMatches(candidate,previewInputs());
  const step=nextStep({confirmed:detail.state==='confirmed',readOnly:session.read_only,pending:changes.length>0,previewed});
  return {form,changes,step,pair,previewed};
}
function refresh(){
  if(!detail?.language)return;
  const state=status(),{step,pair}=state;
  if(candidate&&!state.previewed)invalidatePreview();
  $('changes-line').textContent=state.changes.length?t('admin.changes.line',{changes:state.changes.join(' · ')}):pair?t('admin.changes.same'):'';
  const problem=step?formProblem(state.form,detail.translation):'';
  $('primary').hidden=!step;if(step)$('primary').textContent=STEPS[step].label;
  $('primary').disabled=!!problem;
  $('step-hint').textContent=problem||(step?STEPS[step].hint:detail.state!=='confirmed'?t('admin.hint.unconfirmed'):session.read_only&&candidate?t('admin.hint.read_only'):detail.site.change?t('admin.hint.waiting'):detail.live_pair&&!state.changes.length?t('admin.hint.live'):catalog.site_changes?t('admin.banner.changes',{count:catalog.site_changes}):'');
  $('to-site').hidden=!!step||!(detail.site.change||catalog.site_changes);
  const edited=pair&&pair.base_revision===detail.revision&&textChanges(state.form,variantsOf(pair.variants),detail.translation).length===0;
  $('text-summary').textContent=t('admin.summary.base',{revision:detail.revision})+(detail.revision===detail.current_revision?'':' · '+t('admin.summary.latest',{revision:detail.current_revision}))+' · '+
    (!$('translation-body').value.trim()?t('admin.summary.empty'):edited?t('admin.summary.same'):pair&&pair.base_revision!==detail.revision?t('admin.summary.recheck'):pair?t('admin.summary.edited'):t('admin.summary.entered'));
  const rows=labelRows().filter(row=>row.dataset.visible==='true'),translated=rows.filter(row=>row.querySelector('textarea').value.trim()).length;
  $('meta-summary').textContent=t('admin.summary.series',{names:seriesChange()?seriesName($('series-choice').value):currentSeriesNames()})+' · '+(rows.length?t('admin.summary.labels',{done:translated,total:rows.length}):t('admin.summary.no_labels'))+' · '+t('admin.summary.attachments',{count:detail.attachments.length});
  $('preview-summary').textContent=candidate?t('admin.summary.check_preview'):step==='preview'?t('admin.summary.make_preview'):pair?t('admin.summary.confirmed',{revision:pair.base_revision}):t('admin.summary.unconfirmed');
}
/* The mutable translation draft saves itself shortly after typing stops. The browser copy
   covers the gap; immutable variants are only written when a preview is confirmed. */
async function saveDraft(){
  const draft=formDraft();if(detail.draft&&JSON.stringify(draft)===JSON.stringify({revision:detail.draft.revision,ko:detail.draft.ko,en:detail.draft.en}))return;
  const result=await api('draft',{document:detail.id,token:detail.token,version:draftVersion,draft});draftVersion=result.version;detail.draft=result;
}
async function autosave(){
  if(!detail?.language||session.read_only)return;
  $('draft-status').textContent=t('admin.draft.saving');
  try{await saveDraft();$('draft-status').textContent=t('admin.draft.kept_at',{time:new Date().toLocaleTimeString(language,{hour:'2-digit',minute:'2-digit'})});}
  catch(error){$('draft-status').textContent=t('admin.draft.failed');throw error;}
}
function scheduleSave(){if(session.read_only)return;clearTimeout(saveTimer);$('draft-status').textContent=t('admin.draft.typing');saveTimer=setTimeout(()=>{saveTimer=null;run(autosave);},1200);}
function flushSave(){if(saveTimer){clearTimeout(saveTimer);saveTimer=null;run(autosave);}}
/* Everything a preview is made from, kept with the candidate so that later edits are
   noticed. Only edited wording is sent; the server keeps each question's or relation's
   own publicity, and the genealogy structure comes from the stored component. */
function previewInputs(){
  const labels=labelRows().filter(row=>row.querySelector('textarea').value.trim()!==row.dataset.translated.trim())
    .map(row=>({kind:row.dataset.kind,target:row.dataset.target,translations:{[row.dataset.language]:row.dataset.original,...(row.querySelector('textarea').value.trim()?{[row.dataset.translation]:row.querySelector('textarea').value}: {})}}));
  const choice=$('series-choice').value;
  const series=!seriesChanged||choice==='keep'?null:choice==='new'?{slug:slugify($('new-series-en').value),translations:{ko:{title:$('new-series-ko').value,summary:null},en:{title:$('new-series-en').value,summary:null}}}:{existing:choice||null};
  const {ko,en}=formDraft();
  return {document:detail.id,revision:detail.revision,text:{ko,en},labels,series,planned_at:$('planned').value};
}
async function preview(){
  const inputs=previewInputs();
  candidate={...await api('preview',{...inputs,token:detail.token}),inputs};
  $('preview-review').hidden=false;showFrame(detail.language==='en'?'en_url':'url');refresh();$('step-preview').scrollIntoView({block:'start'});
  notice(t('admin.notice.previewed'));
}
const previewTabs=()=>[...document.querySelectorAll('.preview-tabs [data-frame]')];
/* The same keyboard contract the reader's own tabs use: one stop in the tab order,
   arrows to move between them, and the frame named by whichever tab is selected. */
function showFrame(key){
  $('preview-frame').src=candidate[key];$('preview-open').href=candidate[key];
  $('preview-frame').setAttribute('aria-labelledby','tab-'+key);
  for(const tab of previewTabs()){
    const active=tab.dataset.frame===key;
    tab.setAttribute('aria-selected',String(active));
    tab.tabIndex=active?0:-1;
  }
}
async function confirmSelection(){
  if(!candidate)throw new Error(t('admin.error.preview_again'));
  const result=await api('select',{preview:candidate.id,token:candidate.token});
  await loadCatalog();seriesChanged=false;renderDetail(result,true);backupScope();
  notice(t('admin.notice.confirmed'));
}
const ACTIONS={preview,confirm:confirmSelection};
for(const tab of previewTabs()){
  tab.tabIndex=tab===previewTabs()[0]?0:-1;
  tab.addEventListener('click',()=>candidate&&showFrame(tab.dataset.frame));
  tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const items=previewTabs(),at=items.indexOf(tab);
    const next=event.key==='Home'?0:event.key==='End'?items.length-1:(at+(event.key==='ArrowRight'?1:-1)+items.length)%items.length;
    items[next].focus();if(candidate)showFrame(items[next].dataset.frame);
  });
}
$('primary').addEventListener('click',()=>run(()=>ACTIONS[status().step]?.()));
$('series-choice').addEventListener('change',()=>{seriesChanged=true;backupScope();$('new-series-fields').hidden=$('series-choice').value!=='new';refresh();});
$('revision').addEventListener('change',()=>{flushSave();run(()=>{backup();return openDocument(detail.id,$('revision').value);});});
for(const id of ['original-title','original-summary','translation-title','translation-summary','translation-body'])$(id).addEventListener('input',()=>{backup();refresh();scheduleSave();});
$('recover').addEventListener('click',()=>run(()=>{const d=JSON.parse(localStorage.getItem(recoveryKey()));
  // A copy kept for the other side of this post, from before its language was settled, is not offered.
  if(d?.revision===detail.revision&&d[detail.language]&&'body' in (d[detail.translation]||{})){const staged=!!candidate;fillDraft(d);refresh();refreshRecover();scheduleSave();
  notice(t('admin.notice.recovered')+(staged?' '+t('admin.notice.recovered_preview'):''));}}));
$('import').addEventListener('change',()=>run(async()=>{const file=$('import').files[0];if(file){$('translation-body').value=importMarkdown(file.name,await file.arrayBuffer());backup();refresh();scheduleSave();notice(t('admin.notice.loaded'));}$('import').value='';}));
$('meta-body').addEventListener('input',()=>{backupScope();refresh();});
$('revert-post').addEventListener('click',()=>run(async()=>{
  if(!confirm(revertPrompt('post',detail.site_row)))return;
  flushSave();
  const data=await api('revert',{token:detail.token,kind:'post',target:detail.id});
  if(data.discarded)keepDiscarded(data.discarded);
  await loadCatalog();await openDocument(detail.id);
  notice(t('admin.notice.reverted')+(data.discarded?' '+t('admin.notice.reverted_below'):''));
}));
$('unselect').addEventListener('click',()=>{
  if(!confirm(t('admin.confirm.unselect')))return;
  run(async()=>{const result=await api('unselect',{document:detail.id,revision:detail.revision,token:detail.token});await loadCatalog();renderDetail(result,true);notice(t('admin.notice.unselected'));});
});
for(const b of document.querySelectorAll('.language-tabs [data-side]'))b.addEventListener('click',()=>document.querySelector('.compare[data-side]').dataset.side=b.dataset.side);
async function renderSide(side){
  const original=side==='original';
  const result=await api('render-preview',{title:$(side+'-title').value,summary:$(side+'-summary').value,
    body:original?detail.body:$('translation-body').value,language:original?detail.language:detail.translation});
  $('render-frame').srcdoc=result.html;$('render-dialog').showModal();
}
for(const side of ['original','translation'])$('render-'+side).onclick=()=>run(()=>renderSide(side));
$('close-render').onclick=()=>$('render-dialog').close();
// Leaving for the editor waits for a pending autosave, as the editor does in the other direction.
for(const id of ['open-editor','edit-document'])$(id).addEventListener('click',event=>{
  if(!detail)return;backup();backupScope();
  if(saveTimer){event.preventDefault();clearTimeout(saveTimer);saveTimer=null;const href=$(id).href;run(async()=>{await autosave();location.href=href;});}
});

// ----- Site: what readers will see change, the running PR, series and history
async function showSite(){
  show('site');
  renderReleases(await api('releases'+(rollbackRelease?'?rollback='+encodeURIComponent(rollbackRelease):'')));
}
/* Set once, rarely changed: what the blog is called and where it is published.
   Kept off the site screen so that screen is only what a publication needs. */
async function showSettings(){
  show('settings');
  renderIdentity(await api('site-settings'));
  renderReleases(await api('releases'));
}
/* The blog's own name, byline and the terms its writing carries. Identity is the
   author's, not the tool's, so it is configuration here rather than code. */
const LANGS=['ko','en'],IDENTITY=['name','author','byline','intro'];
function licenseFields(){
  if(!identityState)return;
  const custom=$('site-license').value===identityState.custom_id;
  $('license-custom').hidden=!custom;
  const chosen=identityState.licenses.find(l=>l.id===$('site-license').value);
  // The footer is previewed as it reads in the language the author writes in.
  const lang=$('site-language').value;
  const label=custom?($('site-license-'+lang).value.trim()||t('admin.license.reserved')):chosen?.[lang]||'';
  const url=custom?$('site-license-url').value.trim():chosen?.url||'';
  $('license-preview').replaceChildren('© '+($('site-'+lang+'-author').value.trim()||t('admin.license.author'))+'. ',
    url?link(label,url):label,'.');
}
function renderIdentity(data){
  identityState=data;
  const site=data.settings;
  // Unchosen, the screen offers what the author is taken to write in, and says so.
  $('site-language').value=site.language||data.writing_language||document.documentElement.lang;
  $('site-language-state').textContent=site.language?'':data.writing_language?t('admin.identity.language_inferred'):t('admin.identity.language_unset');
  for(const lang of LANGS)for(const field of IDENTITY)$('site-'+lang+'-'+field).value=site[lang][field];
  const select=$('site-license');
  // Presets are named in the desk's language; the footer preview below shows the published wording.
  select.replaceChildren(...data.licenses.map(l=>{const o=el('option',l[language]||l.en);o.value=l.id;return o;}),
    Object.assign(el('option',t('admin.license.custom')),{value:data.custom_id}));
  select.value=site.license.id;
  if(site.license.id===data.custom_id){
    $('site-license-ko').value=site.license.ko;$('site-license-en').value=site.license.en;
    $('site-license-url').value=site.license.url;
  }
  const shown=site.language||data.writing_language||language;
  $('identity-summary').textContent='· '+site[shown].name+' · '+site.license[shown];
  for(const id of ['site-language','site-license','save-identity',...LANGS.flatMap(l=>IDENTITY.map(f=>'site-'+l+'-'+f))])
    $(id).disabled=session.read_only;
  licenseFields();
}
async function saveIdentity(){
  const settings={language:$('site-language').value,license:{id:$('site-license').value,ko:$('site-license-ko').value,
                           en:$('site-license-en').value,url:$('site-license-url').value}};
  for(const lang of LANGS)settings[lang]=Object.fromEntries(IDENTITY.map(f=>[f,$('site-'+lang+'-'+f).value]));
  renderIdentity(await api('site-settings',{settings}));
  // Identity reaches readers through a deployment like any other change.
  renderReleases(await api('releases'));
  notice(t('admin.notice.identity_saved'));
}
/* One row per decision: a post (with its text, series, wording and consequences), a shared
   wording edit no changed post explains, or a site-level series setting. ✕ returns the row
   to the site state when `revertable`. */
function fillChanges(list,changes,revertable=false){
  list.replaceChildren();
  const add=(kind,tag,title,note,lines,revert)=>{
    const li=el('li',null,'change change-'+kind),head=el('div',null,'change-head');
    head.append(el('span',tag,'tag'),title,el('span',note,'row-note'));
    if(revertable&&revert){const x=button('✕',revert,'revert');x.title=x.ariaLabel=t('admin.changes.revert');head.append(x);}
    li.append(head);
    if(lines.length){const dl=el('dl',null,'change-lines');for(const [term,text] of lines)dl.append(el('dt',term),el('dd',text));li.append(dl);}
    list.append(li);
  };
  for(const row of changes.posts){
    const {tag,note,lines}=describeRow(row),title=el('a',row.title,'row-title');
    if(row.document){title.href='./?'+new URLSearchParams({document:row.document});title.dataset.document=row.document;}
    add(row.change,tag,title,note,lines,row.document&&(()=>revert('post',row.document,revertPrompt('post',row))));
  }
  for(const edit of changes.labels)
    add('label',t('flow.line.wording'),el('span',wordingText(edit),'row-title'),'',[[t('admin.changes.shown_on'),edit.titles.join(', ')]],
        edit.target&&(()=>revert('label',[edit.kind,edit.target],revertPrompt('label',edit))));
  for(const item of changes.site){
    const {tag,title,lines}=describeSite(item);
    add('site',tag,el('span',title,'row-title'),'',lines,item.kind==='home-order'?()=>revert('home-order',null,revertPrompt('home-order',item)):
        item.kind==='series'?()=>revert('series',item.id,revertPrompt('series',item)):null);
  }
}
// Reverting replaces a post's translation input; keep it once for the post page's recovery button.
function keepDiscarded(draft){try{localStorage.setItem(draftKey('draft',draft.document,draft.revision),JSON.stringify({revision:draft.revision,ko:draft.ko,en:draft.en}));}catch(_){}}
async function revert(kind,target,prompt){
  if(!confirm(prompt))return;
  const data=await api('revert',{token:releaseState.token,kind,target});
  if(data.discarded)keepDiscarded(data.discarded);
  renderReleases(data);await loadCatalog();
  notice(t('admin.notice.reverted')+(data.discarded?' '+t('flow.revert.kept'):''));
}
function releaseTitle(r){return r.planned_published_at.slice(0,10)+' · '+t('admin.release.posts',{count:Object.keys(r.selections).length});}
function destinationFields(){
  const folder=$('release-mode').value==='local-folder';
  $('mode-local').hidden=!folder;$('mode-homepage').hidden=folder;
}
function renderReleases(data){
  releaseState=data;
  const pending=data.pending,running=!!pending?.running,rollback=data.rollback;
  $('site-url').hidden=!data.site_url;if(data.site_url){$('site-url').href=data.site_url;$('site-url').textContent=data.site_url.replace(/^https:\/\//,'')+' ↗';}
  $('progress-panel').hidden=!running;
  if(running){
    const copy=deploymentCopy(data.destination?.mode);
    $('progress-steps').replaceChildren(...copy.steps.map((text,index)=>{
      const step=el('li',text);if(index<2)step.className='done';return step;
    }));
    $('progress-note').textContent=copy.note;
    const pr=data.pull_requests?.[pending.release];
    $('pr-link').hidden=!pr?.url;if(pr?.url)$('pr-link').href=pr.url;
    $('release-preview').hidden=false;$('release-preview').href='/release/'+pending.release+'/';
    fillChanges($('progress-changes'),pending.changes);
    $('check').disabled=$('interrupt').disabled=session.read_only;
  }
  // A failed or unstarted release that still matches local selections is retried as is;
  // while a PR runs, only what was confirmed after its release belongs to the next one.
  const retry=retryable(data);
  const changes=rollback?rollback.changes:running?pending.next:retry?pending.changes:data.changes;
  $('changes-title').textContent=running?t('admin.changes.after_pr'):rollback?t('admin.changes.rollback'):t('admin.changes.title');
  $('rollback-banner').hidden=!rollback;
  if(rollback){const r=data.releases.find(x=>x.id===rollback.release);$('rollback-text').textContent=t('admin.changes.rollback_note',{release:releaseTitle(r)});}
  // Reverting rewrites local selections, so it is offered only against the live site itself.
  const revertable=!running&&!rollback&&!session.read_only;
  if(changes)fillChanges($('changes'),changes,revertable);else $('changes').replaceChildren();
  $('revert-note').hidden=!revertable||!changes||changes.empty;
  const touched=new Set((changes?.posts||[]).map(c=>c.document));
  const unchanged=rollback||running?[]:data.selected_posts.filter(p=>!touched.has(p.id)).map(p=>p.title);
  $('unchanged').textContent=running&&changes?.empty?t('admin.changes.none_after_pr'):unchanged.length?t('admin.changes.unchanged',{titles:unchanged.join(', ')}):'';
  $('pending-error').textContent=retry&&pending.error?t(pending.error):'';
  const folder=data.destination?.mode==='local-folder';
  $('site-lede').textContent=deploymentCopy(data.destination?.mode).lede;
  const deploy=deployButton(data,{readOnly:session.read_only});
  $('deploy').textContent=deploy.label;$('deploy').disabled=deploy.disabled;$('deploy-hint').textContent=deploy.hint;
  const waiting=!running&&pending&&pending.release;
  $('pending-preview').hidden=!waiting;
  if(waiting)$('pending-preview').href='/release/'+pending.release+'/';
  renderSeries(data);
  renderHistory(data,running);
  $('homepage-summary').textContent=data.destination?'· '+(folder?t('admin.destination.summary_local',{path:data.destination.path}):data.destination.repository+' · '+data.destination.branch):'· '+t('admin.destination.needed');
  if(data.destination)$('release-mode').value=data.destination.mode;
  if(data.local_folder){$('release-folder').value=data.local_folder.path;$('release-base').value=data.local_folder.base;}
  if(data.homepage){$('release-destination').value=data.homepage.path;$('release-branch').value=data.homepage.branch;}
  destinationFields();
  for(const id of ['save-homepage','release-mode','release-folder','release-base','release-destination','release-branch'])
    $(id).disabled=session.read_only||running;
}
// Series are site-level: names, summaries, reading order and home order. Membership stays per post.
function renderSeries(data){
  const box=$('series-list');box.replaceChildren();
  if(!data.series.length){box.append(el('p',t('admin.series.empty'),'subtle'));return;}
  const order=data.series.map(s=>s.id);
  data.series.forEach((s,index)=>{
    const card=el('section',null,'series-card'),head=el('div',null,'series-head'),names=el('div'),tools=el('div',null,'series-tools');
    const published=s.documents.filter(d=>d.selected).length;
    names.append(el('h3',s.translations.ko.title+' / '+s.translations.en.title),el('p',(published?t('admin.series.published',{count:published}):t('admin.series.unpublished'))+(s.public?'':' · '+t('admin.series.private')),'subtle'));
    const move=delta=>{const b=button(delta<0?'↑':'↓',()=>{const next=[...order];[next[index],next[index+delta]]=[next[index+delta],next[index]];return seriesAction('series-order',{order:next});},'quiet');
      b.setAttribute('aria-label',delta<0?t('admin.series.up'):t('admin.series.down'));b.disabled=session.read_only||!order[index+delta];return b;};
    const edit=button(seriesEditing===s.id?t('admin.series.editing'):t('admin.series.edit'),()=>{seriesEditing=s.id;renderSeries(releaseState);},'quiet');edit.disabled=session.read_only||seriesEditing===s.id;
    tools.append(move(-1),move(1),edit);head.append(names,tools);card.append(head);
    card.append(seriesEditing===s.id?seriesForm(s):el('p',s.documents.map((d,i)=>(i+1)+'. '+d.title+(d.selected?'':' '+t('admin.series.draft'))).join('   ')||t('admin.series.no_posts'),'series-docs'));
    box.append(card);
  });
}
function seriesForm(s){
  const form=el('div',null,'series-form'),docs=[...s.documents],list=el('ol',null,'series-order');
  const field=(label,value,name)=>{const l=el('label',label),input=el('input');input.value=value||'';input.name=name;l.append(input);return l;};
  const names=el('div',null,'series-names');
  names.append(field(t('admin.series.name_ko'),s.translations.ko.title,'ko-title'),field(t('admin.series.name_en'),s.translations.en.title,'en-title'),
    field(t('admin.series.summary_ko'),s.translations.ko.summary,'ko-summary'),field(t('admin.series.summary_en'),s.translations.en.summary,'en-summary'));
  const draw=()=>list.replaceChildren(...docs.map((d,i)=>{
    const li=el('li'),swap=j=>{[docs[i],docs[j]]=[docs[j],docs[i]];draw();};
    const up=el('button','↑','quiet'),down=el('button','↓','quiet');up.type=down.type='button';
    up.disabled=i===0;down.disabled=i===docs.length-1;up.onclick=()=>swap(i-1);down.onclick=()=>swap(i+1);
    li.append(el('span',d.title+(d.selected?'':' '+t('admin.series.draft'))),up,down);return li;}));
  draw();
  const value=name=>form.querySelector('[name="'+name+'"]').value;
  const actions=el('div',null,'panel-actions');
  actions.append(button(t('common.save'),()=>seriesAction('series-save',{series:s.id,documents:docs.map(d=>d.id),
    translations:{ko:{title:value('ko-title'),summary:value('ko-summary')},en:{title:value('en-title'),summary:value('en-summary')}}}),'primary'),
    button(t('common.cancel'),()=>{seriesEditing=null;renderSeries(releaseState);},'quiet'));
  form.append(names,el('p',t('admin.series.order'),'subtle'),list,el('p',t('admin.series.form_note'),'subtle'),actions);
  return form;
}
async function seriesAction(name,body){
  const data=await api(name,{...body,token:releaseState.token});
  if(name==='series-save')seriesEditing=null;
  renderReleases(data);await loadCatalog();
  notice((name==='series-order'?t('admin.notice.series_order'):t('admin.notice.series_saved'))+' '+t('admin.notice.series_deploy'));
}
function renderHistory(data,running){
  const box=$('history-list');box.replaceChildren();
  const statusOf=r=>data.attempts.filter(a=>a.release===r.id).at(-1)?.status;
  const card=r=>{
    const status=statusOf(r),row=el('div',null,'release-card');
    row.append(el('h3',releaseTitle(r)+' · '+(r.id===data.active_release?t('admin.release.current'):{succeeded:t('admin.release.succeeded'),failed:t('admin.release.failed'),running:t('admin.release.running')}[status]||t('admin.release.prepared'))));
    const pr=data.pull_requests?.[r.id];if(pr?.url)row.append(link('GitHub PR ↗',pr.url));
    row.append(link(t('admin.release.preview'),'/release/'+r.id+'/'));
    const error=data.attempts.filter(a=>a.release===r.id).at(-1)?.error;if(status==='failed'&&error)row.append(el('p',t(error),'subtle'));
    if(status==='succeeded'&&r.id!==data.active_release){const back=button(t('admin.release.rollback'),()=>{rollbackRelease=r.id;return showSite().then(()=>$('changes-panel').scrollIntoView({block:'start'}));},'quiet');back.disabled=session.read_only||running;row.append(back);}
    return row;
  };
  const past=[...data.releases].reverse().filter(r=>r.id!==data.pending?.release);
  for(const row of historyRows(past,statusOf)){
    if(row.release){box.append(card(row.release));continue;}
    const group=el('details',null,'failed-group');group.append(el('summary',t('admin.release.failed_group',{count:row.failed.length})),...row.failed.map(card));box.append(group);
  }
  if(!past.length)box.append(el('p',t('admin.release.none'),'subtle'));
}
function deployMode(){return releaseState?.destination?.mode||null;}
function doneMessage(name){
  if(name==='release-deploy')return deploymentCopy(deployMode()).deployed;
  return {'release-configure':t('admin.notice.destination_saved'),'release-interrupt':t('admin.notice.interrupted')}[name];
}
async function releaseAction(name,body){
  let data;
  try{data=await api(name,{...body,token:releaseState.token});}
  catch(error){renderReleases(await api('releases'));throw error;}
  renderReleases(data);await loadCatalog();
  if(name==='release-check')notice(checkedMessage(deployMode(),data.attempts.at(-1)?.status));
  else notice(doneMessage(name)||t('admin.notice.release_updated'));
  return data;
}
async function deploy(){
  const pending=releaseState.pending,sending=deploymentCopy(deployMode()).sending;
  if(!releaseState.rollback&&pending&&!pending.running&&pending.current){notice(sending);return releaseAction('release-deploy',{release:pending.release});}
  notice(t('admin.notice.freezing'));
  const frozen=await releaseAction('release-freeze-home',{rollback:rollbackRelease});
  rollbackRelease=null;notice(sending);
  return releaseAction('release-deploy',{release:frozen.frozen});
}
$('deploy').addEventListener('click',()=>run(deploy));
$('check').addEventListener('click',()=>run(()=>releaseAction('release-check',{})));
$('interrupt').addEventListener('click',()=>{if(confirm(t('admin.confirm.interrupt')))run(()=>releaseAction('release-interrupt',{}));});
$('cancel-rollback').addEventListener('click',()=>{rollbackRelease=null;run(showSite);});
$('save-identity').addEventListener('click',()=>run(saveIdentity));
$('site-license').addEventListener('change',licenseFields);
for(const id of ['site-license-ko','site-license-en','site-license-url','site-ko-author','site-en-author'])$(id).addEventListener('input',licenseFields);
$('site-language').addEventListener('change',licenseFields);
$('release-mode').addEventListener('change',destinationFields);
$('save-homepage').addEventListener('click',()=>run(()=>releaseAction('release-configure',
  $('release-mode').value==='local-folder'
    ?{mode:'local-folder',destination:$('release-folder').value,base:$('release-base').value||'/'}
    :{mode:'homepage-pr',destination:$('release-destination').value,branch:$('release-branch').value})));

/* Importing an existing folder. The scan writes nothing; grouping follows the site
   screen, so a folder of hundreds of files is read as a handful of decisions. */
let importReport=null;
const RULE_EXAMPLE={path:'posts/2009/cat.md → posts-2009-cat',name:'posts/2009/cat.md → cat'};
const SKIP_REASON={duplicate_id:'admin.import.skip.duplicate_id',content_changed:'admin.import.skip.content_changed',unreadable:'admin.import.skip.unreadable',empty:'admin.import.skip.empty'};
function ruleExample(){$('import-rule-example').textContent=t('admin.import.example',{example:RULE_EXAMPLE[$('import-rule').value]});}
async function showImport(){
  show('import');ruleExample();
  if(!importReport)$('import-result').hidden=true;
}
function importGroup(title,rows,open){
  const box=el('details',null,'panel');if(open)box.open=true;
  box.append(el('summary',title+' ('+rows.length+')'));
  for(const row of rows)box.append(row);
  return box;
}
function importInputs(){return {folder:$('import-folder').value.trim(),rule:$('import-rule').value};}
function importMatches(){return planMatches(importReport&&importReport.inputs,importInputs());}
/* The reviewed plan stops describing the controls as soon as they move, so the screen
   drops it rather than letting a confirmation apply something the reader never saw. */
function invalidateImport(){
  if(!importReport||importMatches())return;
  importReport=null;$('import-result').hidden=true;
}
function renderImport(report){
  importReport={...report,inputs:importInputs()};
  const c=report.counts;
  $('import-result').hidden=false;
  $('import-summary').textContent=t('admin.import.summary',{pieces:c.new+c.unchanged,pictures:c.images,attention:c.skipped+c.warnings});
  const box=$('import-groups');box.replaceChildren();
  const attention=[];
  for(const s of report.skipped){
    const line=el('p',null,'change-line');
    line.append(el('b',SKIP_REASON[s.reason]?t(SKIP_REASON[s.reason]):s.reason),' '+s.path+(s.id?' → '+s.id:''));
    if(s.reason==='duplicate_id')line.append(el('span',' '+t('admin.import.duplicate',{path:s.detail}),'subtle'));
    if(s.reason==='content_changed')line.append(el('span',' '+t('admin.import.changed_note'),'subtle'));
    attention.push(line);
  }
  for(const w of report.warnings){
    const line=el('p',null,'change-line'),outside=w.reason==='image_outside_folder';
    line.append(el('b',outside?t('admin.import.outside'):t('admin.import.missing')),' '+t(outside?'admin.import.points_outside':'admin.import.not_found',{path:w.path,target:w.detail}));
    line.append(el('span',' '+(outside?t('admin.import.outside_note'):t('admin.import.missing_note')),'subtle'));
    attention.push(line);
  }
  if(attention.length)box.append(importGroup(t('admin.import.group.attention'),attention,true));
  box.append(importGroup(t('admin.import.group.new'),report.new.map(n=>{
    const line=el('p',null,'change-line');
    line.append(el('b',n.title),' '+n.path+' → '+n.id);
    line.append(el('span',(n.date?' · '+n.date:'')+(n.images?' · '+t('admin.import.pictures',{count:n.images}):''),'subtle'));
    return line;
  })));
  if(report.recovered?.length)box.append(importGroup(t('admin.import.group.recovered'),report.recovered.map(r=>{
    const line=el('p',null,'change-line');
    line.append(el('b',r.path),' → '+r.id);
    line.append(el('span',' · '+t('admin.import.pictures',{count:r.images})+' · '+t('admin.import.unchanged_text'),'subtle'));
    return line;
  })));
  if(report.unchanged.length)box.append(importGroup(t('admin.import.group.unchanged'),report.unchanged.map(u=>el('p',u.path+' → '+u.id,'change-line'))));
  if(report.orphan_assets.length)box.append(importGroup(t('admin.import.group.orphans'),report.orphan_assets.map(a=>el('p',a,'change-line'))));
  if(report.remote_links)box.append(importGroup(t('admin.import.group.remote'),[el('p',t('admin.import.links',{count:report.remote_links}),'change-line')]));
  const state=importState(report,{readOnly:session.read_only});
  $('import-state').textContent=state.state;
  $('import-apply').textContent=state.action;
  $('import-apply').disabled=!state.ready;
  $('import-hint').textContent=state.hint;
}
$('import-rule').addEventListener('change',()=>{ruleExample();invalidateImport();});
$('import-folder').addEventListener('input',invalidateImport);
$('import-scan').addEventListener('click',()=>run(async()=>{
  notice(t('admin.notice.scanning'));
  renderImport(await api('import-scan',{folder:$('import-folder').value,rule:$('import-rule').value}));
  notice(t('admin.notice.scanned'));
}));
$('import-apply').addEventListener('click',()=>run(async()=>{
  if(!importReport||!importMatches())throw new Error(t('admin.error.rescan'));
  const report=await api('import-apply',{...importReport.inputs,plan:importReport.plan,token:importReport.token});
  renderImport(report);
  await loadCatalog();
  notice(importState(report).state);
}));

run(async()=>{
  session=await api('session');$('open-editor').hidden=!session.editor_url;
  // Global navigation goes to one place whatever screen it is used from. Continuing with
  // a particular document is the detail page's own labelled link, not this one.
  if(session.editor_url)$('open-editor').href=session.editor_url;
  $('mode').textContent=(session.demo?t('admin.mode.demo'):'')+(session.read_only?(session.demo?' · ':'')+t('admin.mode.read_only'):'');
  await loadCatalog();await route();
});
// The desk's language is a preference of this data root, and the server fills each page in it.
// Leaving queues the pending draft save first, so the switch waits behind it.
$('interface-language').addEventListener('click',()=>{
  leaveScreen();
  run(async()=>{await api('interface-language',{language:t('nav.other_language_code')});location.reload();});
});
