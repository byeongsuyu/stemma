import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {speak} from './catalog.js';
import * as buffer from '../../admin_frontend/buffer.js';
import * as flow from '../../admin_frontend/flow.js';
import * as i18n from '../../admin_frontend/i18n.js';

// Run the full application with browser and HTTP boundaries replaced. Imports use
// the real modules; navigation, timers, the save queue and draft serialization stay real.
const source=readFileSync(new URL('../../admin_frontend/admin.js',import.meta.url),'utf8')
  .replace(/^import .* from .*;\n/gm,'');
async function desk(){
  const nodes=new Map(),windowEvents={},documentEvents={},timers=new Map(),stored=new Map(),requests=[];
  function element(){return {value:'',dataset:{},textContent:'',addEventListener(){},replaceChildren(...children){this.textContent=children.join('');},append(){},setAttribute(){},removeAttribute(){},querySelectorAll(){return [];}};}
  function node(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);}
  const location=new URL('http://localhost/publish/');
  let timerId=0,finishSave,saveStarted;
  const saving=new Promise(resolve=>{saveStarted=resolve;});
  const response=data=>({ok:true,json:async()=>data});
  const context=vm.createContext({...buffer,...flow,t:i18n.t,language:i18n.language,URL,URLSearchParams,location,
    document:{getElementById:node,createElement:element,querySelectorAll:()=>[],addEventListener:(event,fn)=>{documentEvents[event]=fn;}},
    window:{addEventListener:(event,fn)=>{windowEvents[event]=fn;}},
    history:{pushState(state,title,path){location.href=new URL(path,location).href;}},
    localStorage:{getItem:key=>stored.get(key)??null,setItem:(key,value)=>stored.set(key,value)},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:async(url,options)=>{
      const path=url.pathname.split('/api/')[1];
      requests.push({path,body:options.body?JSON.parse(options.body):null});
      if(path==='session')return response({token:'session-token',workspace:'workspace',read_only:false});
      if(path==='catalog')return response({documents:[],series:[],site_changes:0});
      if(path==='draft'){
        saveStarted();
        await new Promise(resolve=>{finishSave=resolve;});
        return response({version:1});
      }
      throw new Error('Unexpected request: '+url);
    }
  });
  vm.runInContext(source,context);
  await vm.runInContext('queue',context);
  assert.equal(node('notice').textContent,'');
  requests.length=0;
  vm.runInContext("detail={id:'original',revision:'r1',token:'document-token',series:[],language:'ko',translation:'en'};",context);
  node('original-title').value='원문';node('translation-title').value='Translation';node('translation-body').value='Unsaved translation';
  vm.runInContext('scheduleSave()',context);
  return {requests,timers,node,saving,
    back(){windowEvents.popstate();},
    click(){let prevented=false;documentEvents.click({target:{closest:()=>({id:'nav-posts',dataset:{}})},preventDefault(){prevented=true;}});assert.ok(prevented);},
    finish(){finishSave();},
    settled:()=>vm.runInContext('queue',context),
    detail:()=>vm.runInContext('detail',context)
  };
}

for(const navigation of ['back','click'])test(navigation+' saves the original draft before leaving the publication screen',async()=>{
  const page=await desk();
  page[navigation]();
  // A missing flush must fail immediately, rather than leave the test waiting on a save.
  assert.equal(page.timers.size,0);
  await Promise.race([page.saving,page.settled()]);
  assert.deepEqual(page.requests.map(r=>r.path),['draft']);
  assert.equal(page.requests[0].body.document,'original');
  assert.equal(page.requests[0].body.draft.revision,'r1');
  assert.equal(page.requests[0].body.draft.en.body,'Unsaved translation');
  assert.equal(page.detail().id,'original');
  page.finish();await page.settled();
  assert.deepEqual(page.requests.map(r=>r.path),['draft','catalog']);
  assert.equal(page.detail(),null);
  assert.match(page.node('draft-status').textContent,/자동 보관됨/);
});
