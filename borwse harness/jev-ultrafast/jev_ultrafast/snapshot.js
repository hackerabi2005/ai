(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const hiddenCache = new WeakMap();
  const hiddenAncestor = e => {
    if (!e || e.nodeType !== 1) return false;
    if (hiddenCache.has(e)) return hiddenCache.get(e);
    const parent = e.parentElement || e.getRootNode?.()?.host || null;
    const res = e.getAttribute?.('aria-hidden') === 'true' || e.hasAttribute?.('inert') || hiddenAncestor(parent);
    hiddenCache.set(e, res);
    return res;
  };
  const visible = e => !hiddenAncestor(e) &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const hashStr = s => {
    let h1 = 0xdeadbeef ^ s.length, h2 = 0x41c6ce57 ^ s.length;
    for (let i = 0; i < s.length; i++) {
      const ch = s.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761);
      h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h2 >>> 0).toString(36) + ':' + (h1 >>> 0).toString(36);
  };
  const getSR = e => e?.shadowRoot || window.__jevShadowRoots?.get(e) || null;
  const deepElementFromPoint = (x, y) => {
    let cur = document.elementFromPoint(x, y);
    while (cur) {
      const sr = getSR(cur);
      if (!sr) break;
      const inner = sr.elementFromPoint(x, y);
      if (!inner || inner === cur) break;
      cur = inner;
    }
    return cur;
  };
  const deepContains = (container, node) => {
    for (let cur = node; cur; cur = cur.parentNode || cur.host || null) {
      if (cur === container) return true;
    }
    return false;
  };
  const cleanText = s => String(s || '').replace(/\s+/g, ' ').trim();
  const clippedRect = e => {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    const left = Math.max(0, r.left), right = Math.min(innerWidth, r.right);
    const top = Math.max(0, r.top), bottom = Math.min(innerHeight, r.bottom);
    const w = right - left, h = bottom - top;
    if (w < 4 || h < 4) return null;
    return {x: left, y: top, w, h};
  };
  const roots = [document];
  const seenRoots = new Set([document]);
  const customTagEls = [];
  let innerScroller = null, bestScrollArea = 0;
  for (const r of roots) {
    for (const el of r.querySelectorAll('*')) {
      const sr = getSR(el);
      if (sr && !seenRoots.has(sr)) {
        seenRoots.add(sr);
        roots.push(sr);
      }
      if (el.tagName && el.tagName.includes('-')) customTagEls.push(el);
      if (el !== document.documentElement && el !== document.body &&
          el.scrollHeight > el.clientHeight + 20 && el.clientHeight >= 120) {
        const vr = clippedRect(el);
        if (vr && vr.w >= 120 && vr.h >= 120) {
          const area = vr.w * vr.h;
          if (area > bestScrollArea) {
            const ov = getComputedStyle(el).overflowY;
            if (ov === 'auto' || ov === 'scroll' || ov === 'overlay') {
              bestScrollArea = area;
              innerScroller = el;
            }
          }
        }
      }
    }
  }
  const resolveDocNode = id => {
    if (!id) return null;
    for (const r of roots) {
      const found = r.getElementById?.(id);
      if (found) return found;
    }
    return null;
  };
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute?.('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(resolveDocNode(id),seen)).filter(Boolean).join(' ');
    const svgTitle = e.tagName?.toLowerCase?.() === 'svg'
      ? cleanText(e.querySelector?.(':scope > title')?.textContent) : '';
    const fallbackAttr = (() => {
      const a = e.getAttribute?.('data-testid') || e.getAttribute?.('data-test-id') || e.getAttribute?.('name') || '';
      const cleaned = cleanText(a.replace(/[-_]+/g, ' '));
      return cleaned.length <= 40 ? cleaned : '';
    })();
    const childText = e.tagName==='INPUT' ? '' : cleanText([...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
      n.nodeType===1 && n.getAttribute?.('aria-hidden')!=='true' ? name(n,seen) : '').join(' '));
    const raw = referenced || cleanText(e.getAttribute?.('aria-label')) ||
      cleanText([...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ')) ||
      cleanText(['button','submit','reset'].includes(e.type) ? e.value : '') || cleanText(e.getAttribute?.('alt')) ||
      svgTitle || childText ||
      cleanText(e.getAttribute?.('title')) || cleanText(e.getAttribute?.('data-tooltip')) ||
      cleanText(e.getAttribute?.('data-original-title')) || cleanText(e.getAttribute?.('aria-description')) ||
      cleanText(e.getAttribute?.('placeholder')) || fallbackAttr || '';
    return raw.slice(0, 140);
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'menuitemcheckbox','option','gridcell','treeitem','combobox','textbox','searchbox','spinbutton','slider'];
  const semanticSelector='a[href],a[onclick],area[href],button,input,textarea,select,summary,'+
    '[contenteditable]:not([contenteditable="false"]),'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const extraSelector='label,[onclick],[tabindex]:not([tabindex="-1"]),[aria-haspopup],[aria-expanded],'+
    '[jsaction*="click"],[data-action],[data-href],[data-url],[ng-click]';
  const selector=semanticSelector+','+extraSelector;
  const labelTargetControl = e => {
    if (e.tagName !== 'LABEL') return null;
    return e.control || resolveDocNode(e.getAttribute?.('for'));
  };
  const role = e => {
    const explicit=e.getAttribute?.('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A' || e.tagName==='AREA') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='range') return 'slider';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel','date','time','datetime-local','month','week'].includes(e.type)) return 'textbox';
      return null;
    }
    if (e.tagName==='LABEL') {
      const ctrl = labelTargetControl(e);
      if (ctrl && ctrl.tagName === 'INPUT') {
        if (['checkbox','radio'].includes(ctrl.type)) return ctrl.type;
        if (['button','submit','reset'].includes(ctrl.type)) return 'button';
      }
      return null;
    }
    if (e.hasAttribute?.('data-href') || e.hasAttribute?.('data-url')) return 'link';
    if (e.hasAttribute?.('onclick') || e.hasAttribute?.('aria-haspopup') || e.hasAttribute?.('aria-expanded') ||
        e.hasAttribute?.('data-action') || e.hasAttribute?.('ng-click') ||
        (e.getAttribute?.('jsaction') || '').includes('click') ||
        (e.hasAttribute?.('tabindex') && e.getAttribute('tabindex') !== '-1')) return 'button';
    return null;
  };
  const allBySelector = [];
  const seenEls = new Set();
  const collectedEls = new Set();
  const customClickable = new Set();
  const medias = [];
  const seenMedias = new Set();
  const iframes = [];
  const seenIframes = new Set();
  const allInputs = [];
  for (const r of roots) {
    for (const el of r.querySelectorAll(selector)) if (!seenEls.has(el)) { seenEls.add(el); allBySelector.push(el); }
    for (const m of r.querySelectorAll('video,audio')) if (!seenMedias.has(m)) { seenMedias.add(m); medias.push(m); }
    for (const f of r.querySelectorAll('iframe')) if (!seenIframes.has(f)) { seenIframes.add(f); iframes.push(f); }
    for (const inp of r.querySelectorAll('input,textarea,select')) if (safe(inp)) allInputs.push(inp);
  }
  const hasCollectedAncestor = el => {
    for (let cur = el.parentElement || el.getRootNode?.()?.host; cur; cur = cur.parentElement || cur.getRootNode?.()?.host) {
      if (collectedEls.has(cur)) return true;
    }
    return false;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    allInputs.map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly]),
    innerScroller?.isConnected ? innerScroller.scrollTop : 0];
  const liveHiddenAncestor = e => {
    for (let cur = e; cur; cur = cur.parentElement || cur.getRootNode?.()?.host || null) {
      if (cur.nodeType === 1 && (cur.getAttribute?.('aria-hidden') === 'true' || cur.hasAttribute?.('inert'))) return true;
    }
    return false;
  };
  const liveVisible = e => !liveHiddenAncestor(e) &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  cache.guard=(e, scopeMemo)=>{
    if (!e?.isConnected) return null;
    if (e.tagName==='AUDIO') {
      return [identity(e),'audio',e.paused,e.muted,Math.round((e.volume||0)*100),e.playbackRate];
    }
    if (!(scopeMemo ? visible(e) : liveVisible(e))) return null;
    if (e.tagName==='VIDEO') {
      return [identity(e),'video',e.paused,e.muted,Math.round((e.volume||0)*100),e.playbackRate];
    }
    const scope=e.closest?.('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement || e.getRootNode?.()?.host;
    let scopeHash = '';
    if (scope) {
      if (scopeMemo && scopeMemo.has(scope)) {
        scopeHash = scopeMemo.get(scope);
      } else {
        scopeHash = hashStr((scope.innerText || '').slice(0, 6000));
        if (scopeMemo) scopeMemo.set(scope, scopeHash);
      }
    }
    const lblCtrl = labelTargetControl(e);
    return [identity(e),role(e) || (customClickable.has(e) ? 'button' : null),name(e),e.value??null,
      (e.checked ?? lblCtrl?.checked ?? null),e.selectedIndex??null,
      e.readOnly??null,e.matches?.(':disabled')??false,e.getAttribute?.('aria-disabled'),
      e.getAttribute?.('aria-expanded'),e.getAttribute?.('aria-checked'),e.getAttribute?.('aria-selected'),
      e.getAttribute?.('href'),scopeHash];
  };
  cache.deepContains = (e, x, y) => {
    const hit = deepElementFromPoint(x, y);
    if (!hit) return false;
    if (deepContains(e, hit)) return true;
    const hitLabel = hit.closest?.('label');
    if (hitLabel && e.labels && [...e.labels].includes(hitLabel)) return true;
    const lblCtrl = labelTargetControl(e);
    if (lblCtrl && deepContains(lblCtrl, hit)) return true;
    return false;
  };
  cache.clickPoint = e => {
    const vr = clippedRect(e);
    if (!vr) return null;
    const pts = [
      [vr.x + vr.w * 0.5, vr.y + vr.h * 0.5],
      [vr.x + vr.w * 0.2, vr.y + vr.h * 0.5],
      [vr.x + vr.w * 0.8, vr.y + vr.h * 0.5],
      [vr.x + vr.w * 0.5, vr.y + vr.h * 0.2],
      [vr.x + vr.w * 0.5, vr.y + vr.h * 0.8],
      [vr.x + vr.w * 0.25, vr.y + vr.h * 0.25],
      [vr.x + vr.w * 0.75, vr.y + vr.h * 0.25],
      [vr.x + vr.w * 0.25, vr.y + vr.h * 0.75],
      [vr.x + vr.w * 0.75, vr.y + vr.h * 0.75],
    ];
    for (const [px, py] of pts) {
      if (px >= 0 && py >= 0 && px < innerWidth && py < innerHeight && cache.deepContains(e, px, py)) {
        return {x: px, y: py};
      }
    }
    return null;
  };
  const actions=[];
  const pushElementAction = (e, isCustom) => {
    if (!safe(e) || !visible(e) || e.matches?.(':disabled') || e.closest?.('[aria-disabled="true"]')) return;
    // Skip <label> if its target control is itself visible & clickable (avoid duplicates).
    if (e.tagName === 'LABEL') {
      const ctrl = labelTargetControl(e);
      if (ctrl && visible(ctrl) && clippedRect(ctrl)) return;
      if (ctrl && (ctrl.matches?.(':disabled') || ctrl.closest?.('[aria-disabled="true"]'))) return;
    }
    // Skip generic tabindex/jsaction containers that wrap real semantic controls (like modal/scroller wrappers).
    if (!isCustom && !e.matches?.(semanticSelector) && e.tagName !== 'LABEL' &&
        e.querySelector?.('button,a[href],input,textarea,select,[role="button"],[role="link"]')) return;
    const vr = clippedRect(e);
    const rname = role(e) || (isCustom ? 'button' : null);
    if (!rname || !vr) return;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) return;
    if (e.hasAttribute?.('tabindex') && !e.matches?.(semanticSelector) && !e.hasAttribute?.('onclick') &&
        !e.hasAttribute?.('aria-haspopup') && !e.hasAttribute?.('aria-expanded') &&
        !e.hasAttribute?.('data-action') && !e.hasAttribute?.('data-href') &&
        !(e.getAttribute?.('jsaction') || '').includes('click') && !isCustom &&
        !name(e)) return;
    const base={node:identity(e),role:rname,label:name(e)||rname,rect:vr};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute?.('aria-'+key);
      if (value!==null && value!==undefined) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    else if (e.tagName === 'LABEL') {
      const ctrl = labelTargetControl(e);
      if (ctrl && ['checkbox','radio'].includes(ctrl.type)) base.checked=String(ctrl.checked);
    }
    collectedEls.add(e);
    if (e.tagName==='SELECT') {
      let optCount = 0;
      for (const o of e.options) {
        if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]')) {
          if (optCount++ >= 40) break;
          actions.push({...base,kind:'select',value:o.value,
            current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
        }
      }
    } else if (rname==='slider') {
      base.min = e.getAttribute?.('aria-valuemin') ?? (e.tagName==='INPUT' && e.min !== '' ? e.min : '0');
      base.max = e.getAttribute?.('aria-valuemax') ?? (e.tagName==='INPUT' && e.max !== '' ? e.max : '100');
      base.step = e.tagName==='INPUT' && e.step ? e.step : '1';
      const cur = e.getAttribute?.('aria-valuenow') ?? e.getAttribute?.('aria-valuetext') ?? ('value' in e ? String(e.value) : '');
      actions.push({...base,kind:'fill',value:String(cur)});
    } else {
      const editable=!e.readOnly && e.getAttribute?.('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? (e.innerText||'').trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  };
  for (const e of allBySelector) pushElementAction(e, false);
  // Discover modern React/Vue/Tailwind/WebComponent custom clickables (cursor: pointer) after real semantic elements
  // so skipped wrapper containers never hide their clickable children.
  const pointerTags = 'div,span,li,article,section,header,nav,tr,td,dt,dd,img,svg,picture,figure,h1,h2,h3,h4,p,a,label,i,b,strong,em';
  const maxViewportArea = innerWidth * innerHeight * 0.65;
  const cursorCache = new WeakMap();
  const getCursor = e => {
    if (!e) return '';
    if (cursorCache.has(e)) return cursorCache.get(e);
    const c = getComputedStyle(e).cursor;
    cursorCache.set(e, c);
    return c;
  };
  let customCount = 0;
  const tryCustomClickable = el => {
    if (customCount >= 140 || collectedEls.has(el)) return;
    const vr = clippedRect(el);
    if (!vr || vr.w < 10 || vr.h < 10 || vr.w * vr.h >= maxViewportArea) return;
    if (!visible(el) || hasCollectedAncestor(el)) return;
    if (getCursor(el) !== 'pointer') return;
    if (el.querySelector?.('button,a[href],input,textarea,select,[role="button"],[role="link"]')) return;
    const lbl = name(el);
    if (!lbl) return;
    customClickable.add(el);
    pushElementAction(el, true);
    customCount++;
  };
  for (const r of roots) {
    if (customCount >= 140) break;
    for (const el of r.querySelectorAll(pointerTags)) {
      if (customCount >= 140) break;
      tryCustomClickable(el);
    }
  }
  for (const el of customTagEls) {
    if (customCount >= 140) break;
    tryCustomClickable(el);
  }
  for (const m of medias) {
    const isAudio = m.tagName === 'AUDIO';
    let rect;
    if (isAudio) {
      const vr = visible(m) ? clippedRect(m) : null;
      if (!vr && !(m.currentSrc || m.src)) continue;
      rect = vr || {x: 0, y: 0, w: 1, h: 1};
    } else {
      if (!visible(m)) continue;
      const vr = clippedRect(m);
      if (!vr || vr.w < 120 || vr.h < 80) continue;
      rect = vr;
    }
    const mid = identity(m);
    const kindLabel = isAudio ? 'audio' : 'video';
    actions.push({node:mid,role:'button',kind:'click',video_op:'toggle_play',
      label:(m.paused ? `Play ${kindLabel}` : `Pause ${kindLabel}`),value:m.paused ? 'paused' : 'playing',rect});
    actions.push({node:mid,role:'button',kind:'click',video_op:'toggle_mute',
      label:(m.muted ? `Unmute ${kindLabel}` : `Mute ${kindLabel}`),value:m.muted ? 'muted' : 'unmuted',rect});
    actions.push({node:mid,role:'slider',kind:'fill',video_op:'volume',min:'0',max:'100',step:'5',
      label:`Set ${kindLabel} volume percent (0 to 100)`,value:Math.round((m.muted ? 0 : m.volume) * 100) + '%',rect});
    const dur = Number.isFinite(m.duration) && m.duration > 0 ? Math.round(m.duration) : 0;
    actions.push({node:mid,role:'slider',kind:'fill',video_op:'seek',min:'0',max:String(dur),step:'5',
      label:`Seek ${kindLabel} (seconds, mm:ss, or +10/-10)`,value:Math.round(m.currentTime) + 's',rect});
    actions.push({node:mid,role:'spinbutton',kind:'fill',video_op:'speed',
      label:`Set ${kindLabel} playback speed (e.g. 1.5)`,value:String(m.playbackRate) + 'x',rect});
  }
  const visibleIframes = [];
  for (const f of iframes) {
    if (!visible(f)) continue;
    const r = f.getBoundingClientRect();
    if (r.width >= 80 && r.height >= 40 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth) {
      visibleIframes.push({src: f.src || '', name: f.name || '', id: f.id || '', rect: {x: r.left, y: r.top, w: r.width, h: r.height}});
    }
  }
  const words=[]; let length=0;
  for (const root of roots) {
    const baseNode = root === document ? document.body : root;
    if (!baseNode) continue;
    const walker = document.createTreeWalker(baseNode, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let node;
    while ((node=walker.nextNode()) && length<6000) {
      const value=node.textContent.trim(), parent=node.parentElement;
      if (!value || !parent || parent.closest?.('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(node); const r=range.getBoundingClientRect();
      if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
        words.push(value); length+=value.length;
      }
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey();
  // Keep dynamic playback time out of marker and semantics so active media does not spuriously fail fresh().
  const semantics=actions.map(({rect,...action})=>action.video_op==='seek' ? {...action, value:''} : action);
  const marker=hashStr(JSON.stringify([performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6],page_key[7]]));
  if (window.__jevFastMarkerOnly) return {marker};
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  const guards={}, scopeMemo=new Map();
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node), scopeMemo);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  // Expose Enter submission when a populated text/search field is focused (handles Enter-only search bars on any site).
  let activeEl = document.activeElement;
  while (activeEl) {
    const sr = getSR(activeEl);
    if (!sr || !sr.activeElement) break;
    activeEl = sr.activeElement;
  }
  if (activeEl && activeEl.isConnected && safe(activeEl) && !activeEl.readOnly && !activeEl.disabled &&
      activeEl.getAttribute?.('aria-readonly') !== 'true' && visible(activeEl)) {
    const ar = role(activeEl);
    const activeVal = ('value' in activeEl ? String(activeEl.value) : (activeEl.isContentEditable ? activeEl.innerText : '')).trim();
    if (activeVal && (['searchbox','textbox'].includes(ar) || (ar==='combobox' && ['INPUT','TEXTAREA'].includes(activeEl.tagName)))) {
      actions.push({id:'press_enter',kind:'press_enter',label:'Press Enter to submit the active field'});
    }
  }
  const canScrollDown = (scrollY + innerHeight < height - 2) ||
    Boolean(innerScroller && innerScroller.scrollTop + innerScroller.clientHeight < innerScroller.scrollHeight - 2);
  const canScrollUp = (scrollY > 0) || Boolean(innerScroller && innerScroller.scrollTop > 0);
  if (canScrollDown) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (canScrollUp) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  const out = {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
  if (visibleIframes.length) out.iframes = visibleIframes;
  return out;
})()