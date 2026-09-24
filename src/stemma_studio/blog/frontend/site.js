/* History entries own their scroll positions, including repeated article visits. */
(() => {
  if (document.querySelector('[data-default-language]')) {
    location.replace(document.querySelector('main a').href);
    return;
  }
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  let entry = history.state || {};
  const isMap = !!document.querySelector('[data-close-map]');
  let pending;
  try {
    pending = JSON.parse(sessionStorage.getItem('blog-map-from') || 'null');
    sessionStorage.removeItem('blog-map-from');
  } catch (_) {}
  if (isMap && pending && location.pathname === pending.path + 'genealogy/') {
    entry = {...entry, returnPath: pending.path, returnY: pending.y, returnDirect: pending.direct};
  }
  try {
    const article = JSON.parse(sessionStorage.getItem('blog-article-return') || 'null');
    sessionStorage.removeItem('blog-article-return');
    if (article?.path === location.pathname) entry = {...entry, scrollY: article.y};
  } catch (_) {}
  history.replaceState({...entry, blog: true}, '');
  function save() {
    history.replaceState({...history.state, scrollY: window.scrollY}, '');
  }
  window.addEventListener('pagehide', save);
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a');
    if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    save();
    if (anchor.matches('[data-open-map]')) {
      try { sessionStorage.setItem('blog-map-from', JSON.stringify({path:location.pathname,y:window.scrollY})); } catch (_) {}
    }
    if (isMap && anchor.closest('nav[aria-label="Language"]') && history.state?.returnPath) {
      const path = new URL(anchor.href).pathname.replace(/genealogy\/$/, '');
      try {sessionStorage.setItem('blog-map-from', JSON.stringify({path,y:history.state.returnY,direct:true}));} catch (_) {}
    }
    if (anchor.matches('[data-close-map]')) {
      if (history.state?.returnPath === new URL(anchor.href).pathname) {
        if (history.state.returnDirect) {
          try {sessionStorage.setItem('blog-article-return', JSON.stringify({path:history.state.returnPath,y:history.state.returnY}));} catch (_) {}
        } else { event.preventDefault(); history.back(); }
      }
    }
  });
  window.addEventListener('pageshow', () => {
    requestAnimationFrame(() => window.scrollTo(0, history.state?.scrollY || 0));
  });
  const svg = document.querySelector('.genealogy');
  if (!svg) return;
  const tooltip = document.querySelector('.edge-tooltip');
  function showNote(node) { tooltip.textContent = node.dataset.edgeNote; tooltip.hidden = false; }
  svg.querySelectorAll('[data-edge-note]').forEach(node => {
    node.addEventListener('mouseenter', () => showNote(node));
    node.addEventListener('focus', () => showNote(node));
    node.addEventListener('mouseleave', () => {tooltip.hidden = true;});
    node.addEventListener('blur', () => {tooltip.hidden = true;});
    node.addEventListener('click', event => {event.stopPropagation();showNote(node);});
    node.addEventListener('keydown', event => {if (event.key === 'Escape') tooltip.hidden = true; if (event.key === 'Enter' || event.key === ' ') {event.preventDefault();showNote(node);}});
  });
  const viewport = svg.parentElement;
  const width = Number(svg.dataset.width), height = Number(svg.dataset.height);
  let view = [0, 0, width, height];
  const update = () => svg.setAttribute('viewBox', view.join(' '));
  function fit() { view = [0, 0, width, height]; update(); }
  function zoom(factor, cx = view[0] + view[2]/2, cy = view[1] + view[3]/2) {
    const w = Math.max(160, Math.min(width * 3, view[2] * factor));
    const ratio = w / view[2];
    view = [cx - (cx-view[0])*ratio, cy - (cy-view[1])*ratio, w, view[3]*ratio]; update();
  }
  function center() {
    const node = svg.querySelector('[data-current]');
    const p = node.transform.baseVal.getItem(0).matrix;
    const ratio = viewport.clientHeight / viewport.clientWidth;
    const w = Math.min(width, Math.max(400, viewport.clientWidth));
    view = [p.e + 120 - w/2, p.f + 50 - w*ratio/2, w, w*ratio]; update();
  }
  document.querySelectorAll('[data-map]').forEach(button => button.addEventListener('click', () => {
    const action = button.dataset.map;
    if (action === 'fit') fit();
    else if (action === 'center') center();
    else zoom(action === 'in' ? .75 : 1.333);
  }));
  viewport.addEventListener('keydown', event => {
    const step = view[2] * .1;
    const moves = {ArrowLeft:[-step,0], ArrowRight:[step,0], ArrowUp:[0,-step], ArrowDown:[0,step]};
    if (moves[event.key]) {event.preventDefault();view[0]+=moves[event.key][0];view[1]+=moves[event.key][1];update();}
    else if (event.key === '+' || event.key === '=') {event.preventDefault();zoom(.75);}
    else if (event.key === '-') {event.preventDefault();zoom(1.333);}
    else if (event.key === 'Home') {event.preventDefault();fit();}
  });
  let drag = null, dragged = false;
  viewport.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('[data-edge-note]')) return;
    drag = {x:event.clientX,y:event.clientY,view:[...view],id:event.pointerId}; dragged = false;
  });
  viewport.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX-drag.x, dy = event.clientY-drag.y;
    if (Math.abs(dx)+Math.abs(dy)>6) {dragged=true;viewport.setPointerCapture(event.pointerId);}
    if (!dragged) return;
    const scale = Math.max(drag.view[2]/viewport.clientWidth, drag.view[3]/viewport.clientHeight);
    view=[drag.view[0]-dx*scale,drag.view[1]-dy*scale,...drag.view.slice(2)];update();
  });
  window.addEventListener('pointerup', () => {drag=null;});
  viewport.addEventListener('pointercancel', () => {drag=null;});
  viewport.addEventListener('click', event => {if(dragged){event.preventDefault();event.stopPropagation();dragged=false;}},true);
  center();
})();
