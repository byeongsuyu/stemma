import test from 'node:test';
import assert from 'node:assert/strict';
import {speak} from './catalog.js';
import {WorkBuffer} from '../work-buffer.js';
const deferred = () => {let resolve; const promise = new Promise(r => resolve=r); return {promise, resolve};};
const work = {id:'w', version:1, title:'', body:'', note:'', selections:[]};
test('typing during autosave remains in the next request with the advanced version', async () => {
  const first=deferred(), started=deferred(), requests=[];
  const buffer=new WorkBuffer(async (path,payload)=>{requests.push(payload); if(requests.length===1){started.resolve(); await first.promise;} return {...payload, version:payload.version+1};});
  buffer.load(work); buffer.edit({body:'first'}); const saved=buffer.flush(); await started.promise;
  buffer.edit({body:'newer'}); first.resolve(); await saved;
  assert.deepEqual(requests.map(r=>[r.body,r.version]), [['first',1],['newer',2]]);
  assert.equal(buffer.data.body,'newer'); assert.equal(buffer.work.version,3);
});
test('failed save retains buffer and backup until a successful retry', async()=>{
  let fail=true; const backups=[];
  const buffer=new WorkBuffer(async(p,v)=>{if(fail)throw Error('offline');return {...v,version:2};},v=>backups.push(v));
  buffer.load(work); buffer.edit({body:'do not lose'});
  await assert.rejects(buffer.flush()); assert.equal(buffer.data.body,'do not lose');
  assert.notEqual(buffer.generation,buffer.savedGeneration); assert.equal(backups.at(-1).data.body,'do not lose');
  fail=false; await buffer.flush(); assert.equal(backups.at(-1),null);
});
test('concurrent flushes create a single work and serialize saves',async()=>{
  const gate=deferred(); let created=0;
  const buffer=new WorkBuffer(async(path,payload)=>{if(path==='/api/works'){created++;await gate.promise;return work;}return {...payload,version:2};});
  buffer.edit({body:'new'}); const a=buffer.flush(),b=buffer.flush(); gate.resolve();await Promise.all([a,b]);assert.equal(created,1);
});
