import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../site.js',import.meta.url),'utf8');
function visit(path,{map=false,state={},pending=null}={}) {
  const handlers={}, win={}, saved=new Map(pending?[['blog-map-from',JSON.stringify(pending)]]:[]);
  let restored=null,backs=0;
  const history={state,replaceState(value){this.state=value;},back(){backs++;},scrollRestoration:'auto'};
  const context={history,location:{pathname:path},URL,sessionStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
    document:{querySelector:selector=>selector==='[data-close-map]'&&map?{}:null,addEventListener:(event,fn)=>handlers[event]=fn},
    window:{scrollY:700,scrollTo:(x,y)=>restored=y,addEventListener:(event,fn)=>win[event]=fn},requestAnimationFrame:fn=>fn()};
  vm.runInNewContext(source,context);
  return {history,saved,win,context,get restored(){return restored;},get backs(){return backs;},click(href,kind){let prevented=false;handlers.click({button:0,target:{closest:()=>({href,matches:s=>s===kind,closest:()=>kind==='language'?{}:null})},preventDefault(){prevented=true;}});return prevented;}};
}
test('map close returns through history even with no referrer',()=>{
  const page=visit('/blog/en/posts/a/genealogy/',{map:true,pending:{path:'/blog/en/posts/a/'}});
  assert.equal(page.click('http://localhost/blog/en/posts/a/','[data-close-map]'),true);
  assert.equal(page.backs,1);
  assert.equal(page.saved.has('blog-map-from'),false);
});
test('direct map entry does not navigate back to an unrelated page',()=>{
  const page=visit('/blog/ko/posts/a/genealogy/',{map:true,pending:{path:'/blog/ko/posts/b/'}});
  assert.equal(page.click('http://localhost/blog/ko/posts/a/','[data-close-map]'),false);
  assert.equal(page.backs,0);
});
test('article scroll belongs to history entry and survives pagehide',()=>{
  const page=visit('/blog/en/posts/a/',{state:{scrollY:430}});
  page.win.pageshow();assert.equal(page.restored,430);
  page.win.pagehide();assert.equal(page.history.state.scrollY,700);
  page.click('http://localhost/blog/en/posts/a/genealogy/','[data-open-map]');
  assert.equal(JSON.parse(page.saved.get('blog-map-from')).path,'/blog/en/posts/a/');
});

test('map language change keeps the corresponding article and return position',()=>{
  const page=visit('/blog/ko/posts/a/genealogy/',{map:true,pending:{path:'/blog/ko/posts/a/',y:820}});
  page.click('http://localhost/blog/en/posts/a/genealogy/','language');
  const pending=JSON.parse(page.saved.get('blog-map-from'));
  assert.equal(pending.path,'/blog/en/posts/a/');assert.equal(pending.y,820);
  const translated=visit('/blog/en/posts/a/genealogy/',{map:true,pending});
  assert.equal(translated.click('http://localhost/blog/en/posts/a/','[data-close-map]'),false);
  const restore=JSON.parse(translated.saved.get('blog-article-return'));
  assert.equal(restore.path,'/blog/en/posts/a/');assert.equal(restore.y,820);
});
