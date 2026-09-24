import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutComponent,dateKey,edgePath} from '../genealogy-layout.js';
test('chronology keeps equal dates and unknown dates separate without overlapping cards',()=>{
  const c={nodes:[{id:'c',date:null},{id:'a',date:'2022-08-03'},{id:'b',date:'2022-08-03'}],edges:[{parent:'a',child:'c'},{parent:'b',child:'c'}]};
  const layout=layoutComponent(c);
  assert.deepEqual(layout.nodes.map(n=>n.id),['a','b','c']);
  assert.equal(new Set([...layout.positions.values()].map(p=>p.y)).size,3);
  assert.ok(layout.positions.get('c').x>layout.positions.get('a').x);
  assert.ok(!edgePath(layout.positions.get('a'),layout.positions.get('c')).includes('NaN'));
});
test('branching and merge layout retains all nodes and accommodates a child dated before its parent',()=>{
  const c={nodes:[{id:'a',date:'2024-01-01'},{id:'b',date:'2024-02-01'},{id:'c',date:'2023-01-01'},{id:'d',date:'2025-01-01'}],edges:[{parent:'a',child:'b'},{parent:'a',child:'c'},{parent:'b',child:'d'},{parent:'c',child:'d'}]};
  const layout=layoutComponent(c);assert.equal(layout.nodes[0].id,'c');assert.equal(layout.positions.get('d').depth,2);assert.equal(layout.positions.size,4);
});
test('missing or malformed dates are never inferred',()=>{
  for(const date of [null,'', '2022-02-30','unknown'])assert.equal(dateKey({date}),null);
  assert.equal(dateKey({date:'2026-09-14T12:00:00Z'}),'2026-09-14');
});

test('the card the stylesheet draws is the card the layout reserves room for',async()=>{
  // Positions, edge endpoints and the drawn box are three views of one size. If the
  // stylesheet and NODE disagree, edges detach from cards and nothing in the layout
  // tests would notice, because they only check ordering.
  const {NODE}=await import('../genealogy-layout.js');
  const css=await (await import('node:fs/promises')).readFile(new URL('../genealogy.css',import.meta.url),'utf8');
  const rule=css.match(/\.graph-node\{[^}]*\}/)[0];
  assert.equal(Number(rule.match(/width:(\d+)px/)[1]),NODE.width);
  assert.equal(Number(rule.match(/max-height:(\d+)px/)[1]),NODE.height);
  assert.ok(NODE.anchor<NODE.height,'edges would leave the card');
  // The grid has to leave room for the card plus a gap, never less than the card.
  assert.ok(NODE.pitchX>NODE.width,'columns would overlap');
  assert.ok(NODE.pitchY>NODE.height,'rows would overlap');
});
