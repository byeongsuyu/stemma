import {test} from 'node:test';
import assert from 'node:assert/strict';
import {speak} from './catalog.js';
import {draftFromFields,importMarkdown} from '../../admin_frontend/buffer.js';
test('translation drafts preserve the explicit base and both expressions',()=>{
 const fields={originalTitle:'한국어',originalSummary:'',translationTitle:'English',translationSummary:'',translationBody:'Text'};
 const draft=draftFromFields('r1',fields,'ko','en');
 assert.equal(draft.revision,'r1');assert.equal(draft.en.body,'Text');assert.equal(draft.ko.title,'한국어');
 assert.equal('body' in draft.ko,false);assert.equal('reviewed' in draft,false);
 // Written in English, the same fields make the Korean side the one with a body.
 const turned=draftFromFields('r1',{...fields,originalTitle:'English',translationTitle:'한국어',translationBody:'본문'},'en','ko');
 assert.deepEqual(turned,{revision:'r1',en:{title:'English',summary:''},ko:{title:'한국어',summary:'',body:'본문'}});
});
test('Markdown import preserves UTF-8 and rejects other files and malformed bytes',()=>{
 const bytes=new TextEncoder().encode('한국어\r\n**English**');assert.equal(importMarkdown('translation.md',bytes),'한국어\r\n**English**');
 assert.throws(()=>importMarkdown('translation.html',bytes));assert.throws(()=>importMarkdown('bad.md',new Uint8Array([255])));
 assert.throws(()=>importMarkdown('large.md',new Uint8Array(2_000_001)));
});

test('series starts from saved document membership even with an old blank recovery',async()=>{
 const {seriesSelection}=await import('../../admin_frontend/buffer.js');
 assert.deepEqual(seriesSelection(['s1'],{series:''},['s1']),{value:'s1',changed:false});
 assert.deepEqual(seriesSelection(['s1'],null,['s1']),{value:'s1',changed:false});
 assert.deepEqual(seriesSelection(['s1','s2'],null,['s1','s2']),{value:'keep',changed:false});
});
test('explicit series change or removal survives recovery only on its observed base',async()=>{
 const {seriesSelection}=await import('../../admin_frontend/buffer.js');
 const saved={series:'',seriesChanged:true,seriesBase:['s1']};
 assert.deepEqual(seriesSelection(['s1'],saved,['s1','s2']),{value:'',changed:true});
 assert.deepEqual(seriesSelection(['s1'],{...saved,series:'s2'},['s1','s2']),{value:'s2',changed:true});
 assert.deepEqual(seriesSelection(['s2'],saved,['s1','s2']),{value:'s2',changed:false});
 assert.deepEqual(seriesSelection(['s1'],{...saved,series:'deleted'},['s1']),{value:'s1',changed:false});
});
