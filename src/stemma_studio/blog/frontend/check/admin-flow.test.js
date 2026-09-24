import {test} from 'node:test';
import assert from 'node:assert/strict';
import {speak} from './catalog.js';
import {t} from '../../admin_frontend/i18n.js';
import {groupDocuments,siteLabel,describeRow,describeSite,wordingText,revertPrompt,textChanges,formProblem,structureText,previewMatches,nextStep,historyRows,lineDiff,changePlaces,navParams,deploymentCopy,retryable,deployButton,checkedMessage,importState,importMatches} from '../../admin_frontend/flow.js';

const site=(fields)=>({confirmed:true,change:null,work:null,withdrawn:false,live_revision:null,selected_revision:null,current_revision:'r1',...fields});

test('groups follow the next action and drop empty ones',()=>{
 const groups=groupDocuments([{id:'a',group:'live'},{id:'b',group:'deploy'},{id:'c',group:'deploy'}]);
 assert.deepEqual(groups.map(g=>[g.id,g.documents.map(d=>d.id)]),[['deploy',['b','c']],['live',['a']]]);
});
test('archived posts are listed only while published, and say so',()=>{
 assert.deepEqual(siteLabel(site({live_revision:'r1',selected_revision:'r1'}),{archived:true}).notes,['사이트 r1','사용 종료한 글']);
});
test('state labels name live and selected revisions and pending Korean revisions',()=>{
 assert.deepEqual(siteLabel(site({change:'revision',live_revision:'r3',selected_revision:'r4',current_revision:'r5',work:'revision'})),
  {label:'판본 갱신 · 배포 대기',notes:['사이트 r3 → 확정 r4','원문 r5 작성됨']});
 assert.equal(siteLabel(site({live_revision:'r1',selected_revision:'r1'})).label,'게시 중');
 assert.equal(siteLabel(site({live_revision:'r1',selected_revision:'r1',current_revision:'r2',work:'revision'})).label,'번역 갱신 필요');
 assert.equal(siteLabel(site({withdrawn:true})).label,'공개 회수됨');
 assert.equal(siteLabel(site({})).label,'공개 전');
 assert.equal(siteLabel(site({}),{kind:'imported'}).label,'자료함');
 assert.equal(siteLabel(site({confirmed:false})).label,'작성 중');
});
test('text comparison treats a missing summary as empty and a missing variant as new',()=>{
 const form={ko:{title:'제목',summary:''},en:{title:'Title',summary:'',body:'Body'}};
 const variants={ko:{title:'제목',summary:null},en:{title:'Title',summary:null,text:'Body'}};
 assert.deepEqual(textChanges(form,variants,'en'),[]);
 assert.deepEqual(textChanges({...form,en:{...form.en,body:'Edited'}},variants,'en'),['en.body']);
 assert.deepEqual(textChanges(form,{},'en'),['ko.title','en.title','en.body']);
});
test('an English original is compared the other way round: the Korean side carries the body',()=>{
 const form={en:{title:'Title',summary:''},ko:{title:'제목',summary:'',body:'본문'}};
 const variants={en:{title:'Title',summary:null},ko:{title:'제목',summary:null,text:'본문'}};
 assert.deepEqual(textChanges(form,variants,'ko'),[]);
 assert.deepEqual(textChanges({...form,ko:{...form.ko,body:'고친 본문'}},variants,'ko'),['ko.body']);
 assert.deepEqual(textChanges(form,{},'ko'),['ko.title','ko.body','en.title']);
 assert.equal(formProblem({...form,ko:{...form.ko,body:' '}},'ko'),'번역 본문을 입력해 주세요.');
 assert.equal(formProblem({...form,en:{title:'',summary:''}},'ko'),'원문 공개 제목을 입력해 주세요.');
 assert.equal(formProblem(form,'ko'),'');
});
test('form problems mirror the pair rule that summaries exist in both languages or neither',()=>{
 const form={ko:{title:'제목',summary:''},en:{title:'Title',summary:'Only English',body:'Body'}};
 assert.match(formProblem(form,'en'),/모두/);
 assert.equal(formProblem({...form,ko:{title:'제목',summary:'요약'}},'en'),'');
 assert.match(formProblem({...form,en:{...form.en,body:' '}},'en'),/본문/);
});
test('a genealogy that moved since the last confirmation is a change to review',()=>{
 const detail={structure_changed:true,nodes:[{id:'a'},{id:'b'}],selected_structures:[{nodes:[{document:'a'}]}]};
 assert.equal(structureText(detail),'계보 구조 · 이어진 글 1개 → 2개');
 assert.equal(structureText({...detail,selected_structures:[]}),'계보 구조');
 assert.equal(structureText({...detail,structure_changed:false}),'');
});
test('a preview stays reviewed only while its own inputs do, restored ones included',()=>{
 const inputs={document:'d',revision:'r1',text:{ko:{title:'제목',summary:''},en:{title:'Title',summary:'',body:'Body'}},
  labels:[],series:null,planned_at:'2026-02-01T09:00:00Z'};
 const candidate={id:'preview-one',inputs};
 assert.equal(previewMatches(candidate,{...inputs}),true);
 const restored={...inputs,text:{...inputs.text,en:{...inputs.text.en,body:'복구한 영어 본문'}}};
 assert.equal(previewMatches(candidate,restored),false);
 assert.equal(previewMatches(candidate,{...inputs,series:{existing:null}}),false);
 assert.equal(previewMatches(null,inputs),false);
 // A stale preview never reaches the confirm step; the author is sent back to the preview one.
 assert.equal(nextStep({confirmed:true,readOnly:false,pending:true,previewed:previewMatches(candidate,restored)}),'preview');
});
test('preview then confirm; read-only sessions may preview but never confirm',()=>{
 const base={confirmed:true,readOnly:false,pending:true,previewed:false};
 assert.equal(nextStep(base),'preview');
 assert.equal(nextStep({...base,previewed:true}),'confirm');
 assert.equal(nextStep({...base,pending:false}),null);
 assert.equal(nextStep({...base,readOnly:true}),'preview');
 assert.equal(nextStep({...base,readOnly:true,previewed:true}),null);
 assert.equal(nextStep({...base,confirmed:false}),null);
});
test('Korean line diff keeps changes with context and folds long unchanged runs',()=>{
 const before=['a','b','c','d','e','f'].join('\n'),after=['a','b','C','d','e','f','g'].join('\n');
 const ops=lineDiff(before,after);
 assert.deepEqual(ops.map(op=>op.type==='skip'?'skip'+op.count:op.type+':'+op.text),
  ['skip1','same:b','del:c','add:C','same:d','skip1','same:f','add:g']);
 assert.equal(changePlaces(ops),2);
 assert.deepEqual(lineDiff('same','same'),[{type:'skip',count:1}]);
});
const row=fields=>({document:'d',title:'글',change:'update',before:'r1',after:'r1',text:[],series:[],labels:[],effects:[],...fields});
test('a decision row keeps text, series, wording and consequences of one post together',()=>{
 const edit={kind:'question',original:'무엇을 재는가',language:'en',before:{ko:'무엇을 재는가',en:'Old'},after:{ko:'무엇을 재는가',en:'New'},titles:['글']};
 const described=describeRow(row({before:'r3',after:'r4',text:['en.body','graph'],series:[{change:'removed',title:'감상'}],labels:[edit],
  effects:[{kind:'series-vanishes',title:'감상'},{kind:'genealogy',titles:['다른 글']}]}));
 assert.equal(described.tag,'수정');assert.equal(described.note,'판본 r3 → r4');
 assert.deepEqual(described.lines.map(l=>l[0]),['본문','계보','시리즈','계보 문구','함께 바뀜']);
 assert.equal(described.lines[0][1],'영어 본문');assert.match(described.lines[3][1],/“Old” → “New”/);
 assert.match(described.lines[4][1],/감상.*사라짐.*다른 글/);
});
test('withdrawals and new posts word their own rows; consequences stay attached',()=>{
 const gone=describeRow(row({change:'withdraw',before:'r1',after:null,effects:[{kind:'series-vanishes',title:'사회 모델링'}]}));
 assert.deepEqual([gone.tag,gone.note,gone.lines.length],['회수','사이트에서 내림 (r1)',1]);
 const fresh=describeRow(row({change:'new',before:null,after:'r1',text:['en.body'],series:[{change:'added',title:'감상'}]}));
 assert.deepEqual(fresh.lines,[['시리즈','‘감상’에 추가']]);
});
test('wording, site settings and revert prompts say what changes',()=>{
 assert.match(wordingText({kind:'edge',original:'설명',language:'en',before:null,after:{ko:'설명',en:'Note'}}),/변화 설명.*“Note” 표시/);
 assert.match(wordingText({kind:'question',original:'질문',language:'en',before:{ko:'질문',en:'Q'},after:null}),/표시하지 않음/);
 // Written in English, the Korean side is what readers get as the translation.
 assert.match(wordingText({kind:'question',original:'What is measured',language:'ko',before:{en:'What is measured',ko:'옛 번역'},after:{en:'What is measured',ko:'새 번역'}}),/“What is measured” · 번역 “옛 번역” → “새 번역”/);
 const series=describeSite({kind:'series',title:'감상',parts:['translations','order'],before:{ko:{title:'감상',summary:null},en:{title:'Reflections',summary:null}},
  after:{ko:{title:'드라마',summary:null},en:{title:'Drama',summary:null}},order:[['a','b'],['b','a']]});
 assert.deepEqual(series.lines.map(l=>l[0]),['이름','글 순서']);
 assert.equal(describeSite({kind:'home-order',before:['a','b'],after:['b','a']}).lines[0][1],'a · b → b · a');
 assert.deepEqual(describeSite({kind:'skin',files:['site.css']}).lines,[['파일','site.css']]);
 assert.match(revertPrompt('post',{change:'new',title:'글'}),/번역 입력도 비워/);
 assert.match(revertPrompt('post',{change:'withdraw',title:'글'}),/회수를 취소/);
 assert.match(revertPrompt('label',{titles:['A','B']}),/A, B/);
});
test('failed releases between successes collapse into one history row',()=>{
 const status={a:'succeeded',b:'failed',c:undefined,d:'succeeded',e:'failed'};
 const rows=historyRows(['a','b','c','d','e'].map(id=>({id})),r=>status[r.id]);
 assert.deepEqual(rows.map(r=>r.release?r.release.id:r.failed.map(x=>x.id)),['a',['b','c'],'d',['e']]);
});

test('every top-bar link reaches its own screen',()=>{
 assert.deepEqual(navParams({id:'nav-import'}),{view:'import'});
 assert.deepEqual(navParams({id:'nav-site'}),{view:'site'});
 assert.deepEqual(navParams({id:'nav-settings'}),{view:'settings'});
 assert.deepEqual(navParams({id:'nav-posts'}),{});
 assert.deepEqual(navParams({id:'brand'}),{});
});
test('in-page links carry a document or a named view',()=>{
 assert.deepEqual(navParams({id:'',document:'d1'}),{document:'d1'});
 assert.deepEqual(navParams({id:'',view:'site'}),{view:'site'});
 assert.deepEqual(navParams({id:'',view:'import'}),{view:'import'});
 assert.deepEqual(navParams({id:'nav-import',document:'d1'}),{document:'d1'});
});

test('a root that was never deployed says so instead of reporting a difference',()=>{
 assert.deepEqual(describeSite({kind:'first'}).title,'아직 배포한 적이 없습니다');
 assert.deepEqual(describeSite({kind:'other'}).title,'공개 데이터가 달라졌습니다');
});

test('a folder deployment is never described as a pull request',()=>{
 const folder=deploymentCopy('local-folder');
 for(const text of [folder.lede,folder.sending,folder.deployed,folder.note,...folder.steps])
  assert.ok(!/PR|GitHub|Pages|병합/.test(text),'folder copy mentions the GitHub path: '+text);
 assert.equal(checkedMessage('local-folder','succeeded'),'폴더의 파일이 배포본과 같습니다.');
});
test('the pull-request path keeps its merge and build sequence',()=>{
 const pr=deploymentCopy('homepage-pr');
 assert.deepEqual(pr.steps,['배포본 만들기','PR 생성','GitHub에서 병합','Pages 반영 확인']);
 assert.match(pr.deployed,/GitHub에서 병합/);
 assert.match(checkedMessage('homepage-pr','running'),/Pages/);
});
test('with no destination the site screen asks for one instead of explaining either path',()=>{
 const none=deploymentCopy(null);
 assert.match(none.lede,/설정 화면/);
 assert.ok(!/PR|폴더에 씁니다/.test(none.lede));
});
const screen=(extra={})=>({destination:{mode:'local-folder'},changes:{empty:false},destination_missing_site:false,...extra});
test('a folder that has never had the site is offered it even with nothing to change',()=>{
 const deployed=deployButton(screen({changes:{empty:true}}));
 assert.equal(deployed.disabled,true);
 assert.match(deployed.hint,/같습니다/);
 const fresh=deployButton(screen({changes:{empty:true},destination_missing_site:true}));
 assert.equal(fresh.disabled,false);
 assert.equal(fresh.label,'폴더로 내보내기');
 assert.match(fresh.hint,/이 폴더에는 아직 없습니다/);
});
test('a release frozen for another destination is not offered as a retry',()=>{
 const stale=screen({changes:{empty:true},destination_missing_site:true,
  pending:{release:'r1',status:'failed',current:false,deployable:false}});
 assert.equal(retryable(stale),false);
 assert.equal(deployButton(stale).label,'폴더로 내보내기');
 assert.equal(deployButton(stale).disabled,false);
 const own=screen({pending:{release:'r1',status:'failed',current:true,deployable:true}});
 assert.equal(retryable(own),true);
 assert.equal(deployButton(own).label,'같은 배포 다시 시도');
});
test('a retry offered for a folder is not described as a pull request',()=>{
 const waiting=screen({pending:{release:'r1',status:null,current:true,deployable:true}});
 assert.ok(!/PR/.test(deployButton(waiting).hint),deployButton(waiting).hint);
 assert.match(deployButton({...waiting,destination:{mode:'homepage-pr'}}).hint,/PR/);
});
test('a rollback is offered by its own changes, even when the local selections match the site',()=>{
 const back=deployButton(screen({changes:{empty:true},rollback:{release:'r1',changes:{empty:false}}}));
 assert.equal(back.disabled,false);
 assert.equal(back.label,'되돌려서 폴더로 내보내기');
 const same=deployButton(screen({changes:{empty:false},rollback:{release:'r1',changes:{empty:true}}}));
 assert.equal(same.disabled,true);
 assert.match(same.hint,/현재 사이트와 같은 내용입니다/);
});
test('a running deployment, a missing destination and read-only each take the button away',()=>{
 assert.equal(deployButton(screen({pending:{running:true}})).disabled,true);
 assert.match(deployButton(screen({destination:null})).hint,/설정 화면/);
 assert.match(deployButton(screen({changes:null,changes_error:'x'})).hint,/공개 출력을 만들 수 없습니다/);
 assert.match(deployButton(screen(),{readOnly:true}).hint,/읽기 전용/);
});
test('a finished import does not offer to import again',()=>{
 const applied=importState({status:'imported',counts:{new:2}});
 assert.equal(applied.applied,true);
 assert.equal(applied.ready,false);
 assert.match(applied.state,/가져왔습니다/);
 assert.ok(!/아직 아무것도 저장하지 않았습니다/.test(applied.state));
 assert.equal(applied.action,'2편 가져왔습니다');
});
test('a scan offers to import exactly what it counted',()=>{
 const scanned=importState({status:'scanned',counts:{new:2}});
 assert.equal(scanned.ready,true);
 assert.equal(scanned.action,'2편 가져오기');
 assert.match(scanned.state,/아직 아무것도 저장하지 않았습니다/);
 assert.equal(importState({status:'scanned',counts:{new:0}}).ready,false);
 assert.equal(importState({status:'scanned',counts:{new:2}},{readOnly:true}).ready,false);
});
test('a scan that only found missing pictures still offers to attach them',()=>{
 const scanned=importState({status:'scanned',counts:{new:0,recovered:2}});
 assert.equal(scanned.ready,true);
 assert.equal(scanned.action,'빠졌던 사진 2장 글에 붙이기');
 const applied=importState({status:'imported',counts:{new:0,recovered:2}});
 assert.equal(applied.ready,false);
 assert.match(applied.state,/사진을 글에 붙였습니다/);
 assert.equal(importState({status:'scanned',counts:{new:0,recovered:0}}).ready,false);
});
test('a reviewed plan stops matching as soon as the controls move',()=>{
 const reviewed={folder:'/a',rule:'path'};
 assert.equal(importMatches(reviewed,{folder:'/a',rule:'path'}),true);
 assert.equal(importMatches(reviewed,{folder:'/b',rule:'path'}),false);
 assert.equal(importMatches(reviewed,{folder:'/a',rule:'name'}),false);
 assert.equal(importMatches(null,{folder:'/a',rule:'path'}),false);
});

test('the same rules speak English when the page is served in English',()=>{
  speak('en');
  try {
    assert.equal(siteLabel(site({change:'new',selected_revision:'r2'})).label,'New · waiting to deploy');
    assert.deepEqual(siteLabel(site({change:'new',selected_revision:'r2'})).notes,['r2 confirmed']);
    assert.equal(formProblem({ko:{title:'',summary:''},en:{title:'T',summary:'',body:'B'}},'en'),"Enter the original's public title.");
    assert.equal(deployButton({destination:null,changes:{empty:true}}).hint.startsWith('First choose a folder'),true);
  } finally { speak('ko'); }
});

test('a failure saved as a key is worded; one saved as prose reads as it was written',()=>{
  assert.equal(t('error.deploy.pages'),'GitHub Pages 빌드가 실패했습니다. 같은 배포본으로 재시도할 수 있습니다.');
  const legacy='배포 준비 또는 push에 실패했습니다. 목적지와 인증을 확인한 뒤 재시도하세요.';
  assert.equal(t(legacy),legacy);
  assert.equal(t('flow.revert.new',{title:'{x}'}).startsWith('‘{x}’'),true);
});
