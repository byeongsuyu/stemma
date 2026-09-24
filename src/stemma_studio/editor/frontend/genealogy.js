import {layoutComponent, edgePath, dateKey} from './genealogy-layout.js';
import {DATE_KINDS} from './feedback.js';
import {t} from './i18n.js';
const $ = selector => document.querySelector(selector);
const params = new URLSearchParams(location.search);
const ids = params.get('ids') || '';
let data = null, active = null, request = 0, detailRequest = 0, layout = null;
function el(tag, cls, text) {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function error(text) {$('#atlas-error').hidden=!text;$('#atlas-error').textContent=text;}
async function get(path) {const r=await fetch(path);const result=await r.json();if(!r.ok)throw Error(result.error);return result;}
function titleFor(component) {return component.nodes.find(n=>n.selected)?.title || component.nodes[0].title;}
function svg(tag, attributes) {const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attributes).forEach(([k,v])=>n.setAttribute(k,String(v)));return n;}
function zoom() {if(!layout)return;const factor=$('#zoom').value==='fit'?Math.min(1,($('#map-scroll').clientWidth-16)/layout.width,($('#map-scroll').clientHeight-16)/layout.height):Number($('#zoom').value);$('#map').style.transform=`scale(${factor})`;$('#map-size').style.width=layout.width*factor+'px';$('#map-size').style.height=layout.height*factor+'px';}
function openDialog(label,title) {$('#detail-label').textContent=label;$('#detail-title').textContent=title;$('#detail-meta').textContent='';$('#detail-content').replaceChildren();if(!$('#atlas-detail').open)$('#atlas-detail').showModal();}
async function openNode(id,revision) {
  const generation=++detailRequest;
  const node=data.components.flatMap(c=>c.nodes).find(n=>n.id===id);
  openDialog(t('genealogy.read'),node.title);$('#detail-content').textContent=t('genealogy.loading_text');
  try {
    const query=new URLSearchParams({id});if(revision)query.set('revision',revision);
    const doc=await get('/api/document?'+query);
    if(generation!==detailRequest)return;
    $('#detail-meta').textContent=[dateKey(node)||DATE_KINDS.unknown,DATE_KINDS[node.date_kind]||DATE_KINDS.unknown,doc.revision,doc.archived?t('editor.kind.archived'):t('genealogy.in_use'),doc.state==='draft'?t('editor.draft'):t('genealogy.confirmed')].join(' · ');
    $('#detail-content').replaceChildren(el('div','prose',doc.body));
    const qs=node.questions.map(id=>data.questions[id]?.text||id);
    if(qs.length)$('#detail-content').append(el('p','subtle',t('genealogy.questions',{questions:qs.join(' / ')})));
  } catch(e) {if(generation===detailRequest)$('#detail-content').textContent=e.message;}
}
function openEdge(edge,component) {
  detailRequest++;
  const parent=component.nodes.find(n=>n.id===edge.parent),child=component.nodes.find(n=>n.id===edge.child);
  openDialog(edge.state==='confirmed'?t('genealogy.edge.confirmed'):t('genealogy.edge.proposed'),t('genealogy.edge.title'));
  $('#detail-meta').textContent=edge.questions.map(id=>data.questions[id]?.text||id).join(' / ');
  for(const [node,rid,label] of [[parent,edge.parent_revision,t('genealogy.edge.parent')],[child,edge.child_revision,t('genealogy.edge.child')]]){
    const b=el('button','',`${label} · ${node.title} · ${rid} ↗`);b.onclick=()=>openNode(node.id,rid);$('#detail-content').append(b);
  }
  $('#detail-content').append(el('div','edge-note',edge.change_note));
}
function renderMap(component) {
  active=component.id;layout=layoutComponent(component);
  $('#component-title').textContent=titleFor(component);
  const dates=component.nodes.map(dateKey).filter(Boolean).sort();
  $('#component-description').textContent=t('genealogy.description',{pieces:component.nodes.length,edges:component.edges.length})+' · '+(dates.length?dates[0]+' — '+dates[dates.length-1]:DATE_KINDS.unknown)+(dates.length<component.nodes.length?' · '+t('genealogy.undated',{count:component.nodes.length-dates.length}):'');
  const map=$('#map');map.replaceChildren();map.style.width=layout.width+'px';map.style.height=layout.height+'px';
  const drawn=new Set();
  layout.nodes.forEach(node=>{
    const pos=layout.positions.get(node.id),date=dateKey(node);
    if(!drawn.has(pos.depth)){const label=el('div','depth-label',pos.depth?t('genealogy.depth',{depth:pos.depth}):t('genealogy.start'));label.style.left=pos.x+'px';map.append(label);drawn.add(pos.depth);}
    const tick=el('div','timeline-date');tick.style.top=pos.y+'px';tick.append(el('strong','',date||DATE_KINDS.unknown),el('small','',DATE_KINDS[node.date_kind]||DATE_KINDS.unknown));map.append(tick);
    const rule=el('div','date-rule');rule.style.top=pos.y+'px';rule.style.width=(layout.width-180)+'px';map.append(rule);
  });
  const edges=svg('svg',{width:layout.width,height:layout.height,class:'map-edges','aria-label':t('genealogy.edges')});
  const defs=svg('defs',{}),marker=svg('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(svg('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#889d7d'}));defs.append(marker);edges.append(defs);
  component.edges.forEach(edge=>{
    const d=edgePath(layout.positions.get(edge.parent),layout.positions.get(edge.child));
    const name=component.nodes.find(n=>n.id===edge.parent).title+' → '+component.nodes.find(n=>n.id===edge.child).title;
    const hit=svg('path',{d,class:'edge-hit',role:'button',tabindex:0,'aria-label':name});
    const line=svg('path',{d,class:'edge-line'+(edge.state==='proposed'?' proposed':''),'marker-end':'url(#arrow)'});
    hit.onclick=()=>openEdge(edge,component);hit.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openEdge(edge,component);}};
    edges.append(hit,line);
  });map.append(edges);
  layout.nodes.forEach(node=>{
    const pos=layout.positions.get(node.id),card=el('button','graph-node'+(node.selected?' selected':''));
    card.style.left=pos.x+'px';card.style.top=pos.y+'px';card.title=node.title;
    card.setAttribute('aria-label',node.title+' · '+(dateKey(node)||DATE_KINDS.unknown));
    card.append(el('span','node-title',node.title));const meta=el('span','node-meta');
    if(node.selected)meta.append(el('span','node-selected','● '+t('genealogy.legend.selected')));
    meta.append(el('span','',node.kind==='imported'?t('genealogy.imported'):'Studio'),el('span','',t('genealogy.revisions',{count:node.revision_count})));
    if(node.archived)meta.append(el('span','',t('editor.kind.archived')));
    if(node.state==='draft')meta.append(el('span','',t('editor.draft')));
    card.append(meta);card.onclick=()=>openNode(node.id);map.append(card);
  });
  zoom();$('#map-scroll').scrollTo(0,0);
  document.querySelectorAll('.component-button').forEach(b=>{const selected=b.dataset.id===active;b.classList.toggle('active',selected);b.setAttribute('aria-current',String(selected));});
}
async function load() {
  const generation=++request;error('');
  try {
    const response=await get('/api/genealogy?'+new URLSearchParams({ids,proposed:$('#proposed').checked}));
    if(generation!==request)return;data=response;
    const nodeCount=data.components.reduce((n,c)=>n+c.nodes.length,0);
    $('#summary').textContent=t('genealogy.summary',{selected:data.selected.length,components:data.components.length,pieces:nodeCount});
    $('#proposal-legend').hidden=!data.include_proposed;
    $('#components').replaceChildren(...data.components.map((component,index)=>{
      const b=el('button','component-button');b.dataset.id=component.id;
      b.append(el('span','component-number',t('genealogy.component_number',{number:String(index+1).padStart(2,'0')})),el('span','component-name',titleFor(component)),el('span','component-count',t('genealogy.component_count',{pieces:component.nodes.length,selected:component.nodes.filter(n=>n.selected).length})));
      b.onclick=()=>renderMap(component);return b;
    }));
    if(data.components.length)renderMap(data.components.find(c=>c.id===active)||data.components[0]);
    else {$('#map').replaceChildren(el('div','empty-map',t('genealogy.empty')));$('#component-description').textContent=t('genealogy.empty_note');}
  } catch(e) {if(generation===request)error(e.message);}
}
window.addEventListener('resize',()=>{if($('#zoom').value==='fit')zoom();});
$('#proposed').onchange=load;$('#zoom').onchange=zoom;
/* The map is a workspace screen like the others, so it offers the release too. The
   publication side is only mounted when both run on one listener; nothing to show if not. */
(async()=>{
  try{
    const response=await fetch('/publish/api/catalog');
    if(!response.ok)return;
    const {latest_release:release}=await response.json();
    if(release){$('#release-link').href='/release/'+release+'/';$('#release-link').hidden=false;}
  }catch(_){}
})();
$('#detail-close').onclick=()=>$('#atlas-detail').close();$('#atlas-detail').onclose=()=>detailRequest++;
load();
