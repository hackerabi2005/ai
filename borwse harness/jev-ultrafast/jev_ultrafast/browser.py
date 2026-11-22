"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = (
    f"(() => {{ window.__jevFastMarkerOnly=1; try {{ const state={READ_STATE}; "
    "return state?.marker ?? null; } finally { delete window.__jevFastMarkerOnly; } })()"
)
_FRAME_NODE_RE = re.compile(r"^(f\d+):(\d+)$")
_ISO_TEMPORAL_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$|^\d{2}:\d{2}(?::\d{2})?$")
_TAIL_CONTROL_KINDS = frozenset({"scroll", "wait", "press_enter"})

# Record closed & open ShadowRoots cleanly without altering attachShadow(opts.mode) behavior for page scripts.
_CLOSED_SHADOW_INIT_JS = """(() => {
  if (window.__jevShadowRoots) return;
  const map = new WeakMap();
  window.__jevShadowRoots = map;
  const orig = Element.prototype.attachShadow;
  if (typeof orig === 'function') {
    Element.prototype.attachShadow = function(init) {
      const root = orig.call(this, init);
      try { map.set(this, root); } catch {}
      return root;
    };
  }
})();"""
_CONTROL_SELECTOR = (
    'button,[role="button"],[role="switch"],[role="menuitem"],'
    '[role="menuitemradio"],[role="menuitemcheckbox"]'
)

class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


_VIDEO_HOVER_JS = """(() => {
  const getSR = e => e.shadowRoot || window.__jevShadowRoots?.get(e);
  const roots = [document], seen = new Set([document]);
  for (const r of roots) {
    for (const el of r.querySelectorAll('*')) {
      const sr = getSR(el);
      if (sr && !seen.has(sr)) { seen.add(sr); roots.push(sr); }
    }
  }
  const hiddenAnc = e => {
    for (let c = e; c; c = c.parentElement || c.getRootNode?.()?.host || null)
      if (c.nodeType === 1 && (c.getAttribute?.('aria-hidden') === 'true' || c.hasAttribute?.('inert'))) return true;
    return false;
  };
  const vis = e => e && !hiddenAnc(e) && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const deepContains = (container, node) => {
    for (let c = node; c; c = c.parentNode || c.host || null) if (c === container) return true;
    return false;
  };
  const deepPoint = (x, y) => {
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
  let bestVideo = null, bestArea = 0, bestBox = null;
  for (const r of roots) {
    for (const v of r.querySelectorAll('video')) {
      if (!vis(v)) continue;
      const rect = v.getBoundingClientRect();
      const w = Math.min(rect.right, innerWidth) - Math.max(rect.left, 0);
      const h = Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0);
      if (w >= 120 && h >= 80 && w * h > bestArea) {
        bestArea = w * h; bestVideo = v; bestBox = rect;
      }
    }
  }
  if (bestVideo && bestBox) {
    let playerRoot = bestVideo;
    for (
      let cur = bestVideo.parentElement || bestVideo.getRootNode?.()?.host;
      cur && cur !== document.body;
      cur = cur.parentElement || cur.getRootNode?.()?.host
    ) {
      const pr = cur.getBoundingClientRect?.();
      const maxW = Math.max(bestBox.width * 1.35 + 80, bestBox.width);
      const maxH = Math.max(bestBox.height * 1.45, bestBox.height + 140);
      if (!pr || pr.width > maxW || pr.height > maxH) break;
      playerRoot = cur;
    }
    const playerRoots = [playerRoot];
    for (const pr of playerRoots) {
      for (const el of pr.querySelectorAll?.('*') || []) {
        const sr = getSR(el);
        if (sr && !playerRoots.includes(sr)) playerRoots.push(sr);
      }
      const prSr = getSR(pr);
      if (prSr && !playerRoots.includes(prSr)) playerRoots.push(prSr);
    }
    let visibleControls = 0;
    const menuSel = '[aria-expanded="true"],[role="menu"],'
      + '[role="menuitem"],[role="menuitemradio"],[role="menuitemcheckbox"]';
    for (const pr of playerRoots) {
      for (const el of pr.querySelectorAll?.(menuSel) || []) {
        if (vis(el)) return {hover: null, menuOpen: true, controls: 0};
      }
      for (const btn of pr.querySelectorAll?.('""" + _CONTROL_SELECTOR + """') || []) {
        if (vis(btn)) visibleControls += 1;
      }
    }
    if (visibleControls > 0) return {hover: null, menuOpen: false, controls: visibleControls};
    const visW = Math.min(bestBox.right, innerWidth) - Math.max(bestBox.left, 0);
    const visH = Math.min(bestBox.bottom, innerHeight) - Math.max(bestBox.top, 0);
    const hx = Math.max(1, Math.min(innerWidth - 2, Math.round(Math.max(bestBox.left, 0) + visW * 0.25)));
    const hy = Math.max(1, Math.min(innerHeight - 2, Math.round(Math.max(bestBox.top, 0) + visH * 0.5)));
    const hit = deepPoint(hx, hy);
    if (hit && !deepContains(playerRoot, hit)) return {hover: null, menuOpen: true, controls: 0};
    return {hover: [hx, hy], menuOpen: false, controls: 0};
  }
  const iframeSel = [
    'iframe[src*="youtube"]', 'iframe[src*="youtu.be"]', 'iframe[src*="vimeo"]',
    'iframe[src*="twitch"]', 'iframe[src*="dailymotion"]', 'iframe[src*="player"]', 'iframe[allow*="fullscreen"]',
  ].join(',');
  for (const r of roots) {
    for (const f of r.querySelectorAll(iframeSel)) {
      if (!vis(f)) continue;
      const rect = f.getBoundingClientRect();
      const w = Math.min(rect.right, innerWidth) - Math.max(rect.left, 0);
      const h = Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0);
      if (w >= 160 && h >= 90) {
        return {
          hover: [
            Math.max(1, Math.min(innerWidth - 2, Math.round(Math.max(rect.left, 0) + w * 0.25))),
            Math.max(1, Math.min(innerHeight - 2, Math.round(Math.max(rect.top, 0) + h * 0.5))),
          ],
          menuOpen: false,
          controls: 0,
        };
      }
    }
  }
  return {hover: null, menuOpen: false, controls: 0};
})()"""


def _eval_with_frame(session_id, ref, expression, *, await_promise=False):
    sid = (ref or {}).get("session_id") or session_id
    fid = (ref or {}).get("frame_id") if ref else None
    params = {"expression": expression, "returnByValue": True}
    if await_promise:
        params["awaitPromise"] = True
    if fid and not (ref or {}).get("session_id"):
        ctx_id = ref.get("context_id")
        if ctx_id is None:
            # Named world keeps window.__jevFast alive across observe/fresh/act and avoids re-creating worlds.
            world = cdp(
                "Page.createIsolatedWorld",
                session_id=session_id,
                frameId=fid,
                worldName="__jevFast",
                grantUniversalAccess=True,
            )
            ctx_id = world["executionContextId"]
            ref["context_id"] = ctx_id
        params["contextId"] = ctx_id
    try:
        resp = cdp("Runtime.evaluate", session_id=sid, **params)
    except RuntimeError:
        if ref and "context_id" in ref:
            ref.pop("context_id", None)
        raise
    if resp.get("exceptionDetails"):
        raise StalePage("Document changed during evaluation")
    return resp.get("result", {}).get("value")


def _parse_node_ref(node):
    if type(node) is int:
        return None, node
    if isinstance(node, str):
        m = _FRAME_NODE_RE.fullmatch(node)
        if m:
            return m.group(1), int(m.group(2))
    raise ValueError("Invalid observed node")


def _parse_numeric_target(text, *, cur=0.0, min_v=0.0, max_v=100.0):
    raw = str(text or "").strip().lower()
    span = max_v - min_v
    if raw in {"mute", "off", "min", "minimum", "start", "beginning"}:
        val = min_v
    elif raw in {"max", "maximum", "full", "end"}:
        val = max_v
    elif raw in {"half", "middle", "mid"}:
        val = min_v + 0.5 * span
    elif raw == "normal":
        val = 1.0 if min_v <= 1.0 <= max_v else min_v + 0.5 * span
    else:
        mmss = re.fullmatch(r"([+-]?)(\d+):([0-5]?\d)", raw)
        if mmss:
            secs = int(mmss.group(2)) * 60 + int(mmss.group(3))
            val = cur + (-secs if mmss.group(1) == "-" else secs) if mmss.group(1) else float(secs)
        else:
            m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(%?)", raw)
            if not m:
                raise ValueError(f"Unsupported slider/numeric value: {text!r}")
            num = float(m.group(1))
            is_pct = m.group(2) == "%"
            is_rel = m.group(1).startswith(("+", "-"))
            if is_pct and max_v != 100.0 and not is_rel:
                val = min_v + (num / 100.0) * span
            elif is_rel:
                val = cur + ((num / 100.0) * span if is_pct else num)
            else:
                val = num
    clamped = min(max_v, max(min_v, val))
    ratio = (clamped - min_v) / span if span > 0 else 0.0
    return clamped, min(1.0, max(0.0, ratio))


class Browser:
    def __init__(self, url, *, background=True, wait_ready=True, target_id=None):
        ensure_daemon()
        self._background = background
        self._followed_targets = set()
        if target_id:
            self.target = target_id
            if not background:
                cdp("Target.activateTarget", targetId=self.target)
            self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
            self.call("Emulation.setFocusEmulationEnabled", enabled=True)
            self._install_shadow_hook()
            return
        initial_url = url if not wait_ready else "about:blank"
        self.target = cdp("Target.createTarget", url=initial_url, background=background)["targetId"]
        if not background:
            cdp("Target.activateTarget", targetId=self.target)
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self._install_shadow_hook()
        if not wait_ready:
            return
        self.call("Page.navigate", url=url, _response_timeout=20.0)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                state = self.evaluate("[document.readyState, location.href]")
            except StalePage:
                state = None
            if (
                isinstance(state, list)
                and len(state) == 2
                and state[0] in {"interactive", "complete"}
                and (url == "about:blank" or state[1] != "about:blank")
            ):
                break
            time.sleep(0.02)

    def _install_shadow_hook(self):
        try:
            self.call("Page.enable")
            self.call("Page.addScriptToEvaluateOnNewDocument", source=_CLOSED_SHADOW_INIT_JS)
        except Exception:
            pass

    def switch_to_target(self, target_id, *, activate=True):
        """Attach this Browser handle to an existing Chrome tab target."""
        self._frame_refs = {}
        if getattr(self, "_frame_sessions", None):
            self._frame_sessions.clear()
        self._player_menu_open = False
        self._last_click_was_player = False
        self._last_page_has_media = True
        old_session = getattr(self, "session", None)
        if old_session:
            try:
                cdp("Target.detachFromTarget", sessionId=old_session)
            except Exception:
                pass
        self.target = target_id
        if activate:
            cdp("Target.activateTarget", targetId=target_id)
        self.session = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self._install_shadow_hook()

    def _wake_player_controls(self, *, force=False):
        """Hover inside a visible video/iframe player when controls are hidden and no menu is open."""
        if not getattr(self, "session", None):
            return
        if not force and getattr(self, "_player_menu_open", False):
            return
        try:
            state = self.evaluate(_VIDEO_HOVER_JS)
        except (StalePage, RuntimeError):
            return
        if isinstance(state, list) and len(state) == 2:
            pt, menu_open = state, False
            self._last_page_has_media = True
        elif isinstance(state, dict):
            pt = state.get("hover")
            menu_open = bool(state.get("menuOpen"))
            controls = int(state.get("controls") or 0)
            self._last_page_has_media = bool(pt or menu_open or controls > 0)
            if not menu_open and getattr(self, "_last_click_was_player", False):
                prev_cnt = getattr(self, "_last_player_controls_count", 0)
                if controls > prev_cnt:
                    menu_open = True
                self._last_player_controls_count = controls
            else:
                self._last_player_controls_count = controls
        else:
            self._last_page_has_media = False
            return
        self._player_menu_open = menu_open
        if menu_open or not isinstance(pt, list) or len(pt) != 2:
            return
        nudge = getattr(self, "_hover_nudge", 0) & 1
        self._hover_nudge = nudge ^ 1
        self.call(
            "Input.dispatchMouseEvent",
            type="mouseMoved",
            x=pt[0] + nudge,
            y=pt[1],
            pointerType="mouse",
        )
        time.sleep(0.04)

    def _eval_in_frame(self, ref, expression, *, await_promise=False):
        return _eval_with_frame(self.session, ref, expression, await_promise=await_promise)

    def _frame_offsets(self, iframes_meta):
        offsets = {}
        try:
            tree = self.call("Page.getFrameTree").get("frameTree", {})
        except RuntimeError:
            return [], offsets
        root_id = (tree.get("frame") or {}).get("id")
        frames = []

        def walk(node):
            fr = node.get("frame") or {}
            fid = fr.get("id")
            if fid and fid != root_id:
                frames.append(fr)
            for child in node.get("childFrames") or ():
                walk(child)

        walk(tree)
        if not frames:
            return [], offsets
        if not getattr(self, "_dom_enabled", False):
            try:
                self.call("DOM.enable")
                self._dom_enabled = True
            except RuntimeError:
                self._dom_enabled = False
        for fr in frames[:8]:
            fid = fr["id"]
            if getattr(self, "_dom_enabled", False):
                try:
                    owner = self.call("DOM.getFrameOwner", frameId=fid)
                    box = self.call("DOM.getBoxModel", backendNodeId=owner["backendNodeId"])
                    content = box["model"]["content"]
                    offsets[fid] = (float(content[0]), float(content[1]))
                    continue
                except (RuntimeError, KeyError):
                    pass
            f_url, f_name = fr.get("url") or "", fr.get("name") or ""
            for item in iframes_meta:
                if (f_url and item.get("src") == f_url) or (f_name and item.get("name") == f_name):
                    r = item["rect"]
                    offsets[fid] = (float(r["x"]), float(r["y"]))
                    break
        return frames[:8], offsets

    def _attach_oopif_sessions(self):
        try:
            targets = cdp("Target.getTargets").get("targetInfos", [])
        except RuntimeError:
            return {}
        sessions = getattr(self, "_frame_sessions", None)
        if sessions is None:
            sessions = {}
            self._frame_sessions = sessions
        by_url = {}
        live_tids = set()
        for t in targets:
            if t.get("type") != "iframe":
                continue
            tid, url = t["targetId"], t.get("url") or ""
            live_tids.add(tid)
            if tid not in sessions:
                try:
                    sessions[tid] = cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
                except RuntimeError:
                    continue
            by_url.setdefault(url, []).append(sessions[tid])
        for dead in [tid for tid in sessions if tid not in live_tids]:
            sessions.pop(dead, None)
        return by_url

    def _observe_child_frames(self, page, iframes_meta):
        frames, offsets = self._frame_offsets(iframes_meta)
        if not frames:
            return page
        oopifs = self._attach_oopif_sessions()
        frame_refs = {}
        frame_page_keys = {}
        tail_controls = [a for a in page["actions"] if a["kind"] in _TAIL_CONTROL_KINDS]
        merged_actions = [a for a in page["actions"] if a["kind"] not in _TAIL_CONTROL_KINDS]
        extra_text = []

        for idx, fr in enumerate(frames, start=1):
            fid = fr["id"]
            f_url = fr.get("url") or ""
            if not f_url or f_url in {"about:blank", "javascript:false"}:
                continue
            ox, oy = offsets.get(fid, (0.0, 0.0))
            if ox >= page.get("w", 1120) or oy >= page.get("h", 780):
                continue
            oo_list = oopifs.get(f_url) or []
            oo_sid = oo_list.pop(0) if oo_list else None
            ref = {"session_id": oo_sid, "frame_id": None if oo_sid else fid, "ox": ox, "oy": oy}
            try:
                child = self._eval_in_frame(ref, READ_STATE)
            except (StalePage, RuntimeError):
                continue
            if not isinstance(child, dict) or not child.get("actions"):
                continue
            tag = f"f{idx}"
            frame_page_keys[tag] = child.get("page_key")
            c_guards = child.get("guards") or {}
            for a in child["actions"]:
                if a["kind"] in _TAIL_CONTROL_KINDS:
                    continue
                prefixed = f"{tag}:{a['node']}"
                if str(a["node"]) in c_guards:
                    page.setdefault("guards", {})[prefixed] = c_guards[str(a["node"])]
                item = dict(a)
                item["node"] = prefixed
                if "rect" in item:
                    item["rect"] = {
                        **item["rect"],
                        "x": item["rect"]["x"] + ox,
                        "y": item["rect"]["y"] + oy,
                    }
                merged_actions.append(item)
                frame_refs[prefixed] = ref
            if child.get("text"):
                extra_text.append(child["text"])

        self._frame_refs = frame_refs
        if not frame_refs:
            return page
        page["_frame_page_keys"] = frame_page_keys
        page["omitted_actions"] = page.get("omitted_actions", 0) + max(0, len(merged_actions) - 250)
        merged_actions = merged_actions[:250]
        for i, a in enumerate(merged_actions, start=1):
            a["id"] = f"e{i}"
        page["actions"] = merged_actions + tail_controls
        if extra_text:
            combined = "\n".join([page.get("text") or "", *extra_text]).strip()
            page["text"] = combined[:6000]
        page["fingerprint"] = fingerprint(page)
        return page

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # Wait briefly for post-input DOM settles or autocomplete options without capturing video_op.
            if not action.get("video_op") and "node" in action:
                if action.get("kind") == "fill" and action.get("role") == "combobox":
                    ref = getattr(self, "_frame_refs", {}).get(action.get("node"))
                    frame_tag, local_node = _parse_node_ref(action["node"])
                    local_action = {**action, "node": local_node} if frame_tag else action
                    try:
                        self._eval_in_frame(
                            ref,
                            """(action => new Promise(resolve => {
                              const field=window.__jevFast?.nodes.get(action.node);
                              const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                              let frames=0, stopped=false;
                              const finish=()=>{stopped=true;resolve()};
                              setTimeout(finish,autocomplete ? 200 : 25);
                              const ready=()=>{
                                if (stopped) return;
                                const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                                  .split(/\\s+/).filter(Boolean);
                                const doc = document;
                                const roots=ids.length ? ids.map(id=>doc.getElementById(id)).filter(Boolean) : [doc];
                                const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                                const minFrames = autocomplete ? 2 : 1;
                                if (++frames>=minFrames && (!autocomplete || options.some(e=>{
                                  const r=e.getBoundingClientRect();
                                  return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                                    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                                }))) finish();
                                else requestAnimationFrame(ready);
                              };
                              requestAnimationFrame(ready);
                            }))(""" + json.dumps(local_action) + ")",
                            await_promise=True,
                        )
                    except (RuntimeError, StalePage):
                        pass
                else:
                    time.sleep(0.025)
        if getattr(self, "_last_page_has_media", True):
            self._wake_player_controls()
        for attempt in range(10):
            try:
                page = browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
                iframes = page.pop("iframes", None) if isinstance(page, dict) else None
                self._frame_refs = {}
                if iframes and getattr(self, "session", None):
                    page = self._observe_child_frames(page, iframes)
                cur_url = page.get("url") if isinstance(page, dict) else None
                prev_url = getattr(self, "_last_observed_url", None)
                if cur_url and cur_url != prev_url:
                    self._last_observed_url = cur_url
                    if prev_url is not None:
                        self._last_page_has_media = True
                return page
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if attempt < 3 and any(k in msg for k in ("timed out", "navigat", "context")):
                    time.sleep(0.05)
                    continue
                raise
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select", "fill"} and "node" in action:
            node = action["node"]
            try:
                frame_tag, local_node = _parse_node_ref(node)
            except ValueError:
                return False
            if frame_tag is None:
                current = self.evaluate(
                    "(() => { const c=window.__jevFast; "
                    f"return c ? [c.pageKey(),c.guard(c.nodes.get({local_node}))] : null; }})()"
                )
                return current == [page["page_key"], page["guards"].get(str(node))]
            ref = getattr(self, "_frame_refs", {}).get(node)
            if not ref:
                return False
            current = self._eval_in_frame(
                ref,
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({local_node}))] : null; }})()",
            )
            expected_key = (page.get("_frame_page_keys") or {}).get(frame_tag)
            return current == [expected_key, page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def _follow_opened_tab(self, *, expect_popup=False):
        """Follow a target='_blank' or window.open child tab opened by the last click."""
        cur_target = getattr(self, "target", None)
        if not cur_target:
            return False
        followed = getattr(self, "_followed_targets", None)
        if followed is None:
            followed = set()
            self._followed_targets = followed
        deadline = time.monotonic() + (0.18 if expect_popup else 0.0)
        while True:
            try:
                targets = cdp("Target.getTargets").get("targetInfos", [])
            except Exception:
                return False
            for t in targets:
                tid = t.get("targetId")
                if (
                    t.get("type") == "page"
                    and tid
                    and tid != cur_target
                    and tid not in followed
                    and t.get("openerId") == cur_target
                ):
                    followed.add(tid)
                    self.switch_to_target(tid, activate=not getattr(self, "_background", True))
                    # Wait briefly for the newly opened tab to leave about:blank.
                    ready_deadline = time.monotonic() + 8.0
                    while time.monotonic() < ready_deadline:
                        try:
                            st = self.evaluate("[document.readyState, location.href]")
                        except (StalePage, RuntimeError):
                            st = None
                        if (
                            isinstance(st, list)
                            and len(st) == 2
                            and st[0] in {"interactive", "complete"}
                            and st[1] != "about:blank"
                        ):
                            break
                        time.sleep(0.02)
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def act(self, action, page, text=None):
        if (
            action["kind"] in {"click", "select"}
            and not action.get("video_op")
            and getattr(self, "_last_page_has_media", True)
        ):
            self._wake_player_controls()
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        frame = getattr(self, "_frame_refs", {}).get(action.get("node"))
        result = browser_operation(
            {"operation": "act", "session": self.session, "action": action, "text": text, "frame": frame}
        )
        if action["kind"] == "click" and not action.get("video_op"):
            switched = self._follow_opened_tab(expect_popup=bool((result or {}).get("opens_new_tab")))
            if switched:
                self._last_click_was_player = False
                self._player_menu_open = False
                self.after_input = None
                return result
        self._last_click_was_player = action["kind"] == "click" and not action.get("video_op")
        if self._last_click_was_player:
            self._last_page_has_media = True
        else:
            self._player_menu_open = False
        self.after_input = action if action["kind"] not in {"wait", "scroll", "press_enter"} else None
        return result

    def close(self):
        self._frame_refs = {}
        if getattr(self, "_frame_sessions", None):
            self._frame_sessions.clear()
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _dispatch_click(call, x, y):
    for event in ("mousePressed", "mouseReleased"):
        call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)


def _dispatch_drag(call, sx, sy, ex, ey, steps=4):
    call("Input.dispatchMouseEvent", type="mousePressed", x=sx, y=sy, button="left", clickCount=1)
    for i in range(1, steps + 1):
        t = i / steps
        call("Input.dispatchMouseEvent", type="mouseMoved", x=sx + (ex - sx) * t, y=sy + (ey - sy) * t, button="left")
    call("Input.dispatchMouseEvent", type="mouseReleased", x=ex, y=ey, button="left", clickCount=1)


def _execute_video_op(evaluate_fn, call_top_fn, local_node, video_op, text, ox=0.0, oy=0.0):
    meta = evaluate_fn(
        f"""(() => {{
          const v = window.__jevFast?.nodes.get({local_node});
          const visCfg = {{checkOpacity:true,checkVisibilityCSS:true}};
          if (!v?.isConnected || (v.tagName !== 'VIDEO' && v.tagName !== 'AUDIO')) return null;
          const isAudio = v.tagName === 'AUDIO';
          if (!isAudio && !v.checkVisibility(visCfg)) return null;
          const r = v.getBoundingClientRect();
          if (!isAudio && (!r.width || !r.height)) return null;
          return {{
            paused: Boolean(v.paused),
            muted: Boolean(v.muted),
            volume: Number.isFinite(v.volume) ? v.volume : 1,
            currentTime: Number.isFinite(v.currentTime) ? v.currentTime : 0,
            duration: Number.isFinite(v.duration) ? v.duration : 0,
            playbackRate: Number.isFinite(v.playbackRate) ? v.playbackRate : 1,
            x: Math.max(1, Math.min(innerWidth - 1, r.x + r.width / 2)),
            y: Math.max(1, Math.min(innerHeight - 1, r.y + r.height / 2)),
          }};
        }})()"""
    )
    if meta is None:
        raise StalePage("Video element is no longer visible. Observe again.")
    if video_op == "toggle_play":
        if meta["paused"]:
            played = evaluate_fn(
                f"(() => {{ const v = window.__jevFast?.nodes.get({local_node}); "
                "return v ? Promise.resolve(v.play()).then(() => true, () => false) : false; })()",
                await_promise=True,
            )
            if not played:
                _dispatch_click(call_top_fn, meta["x"] + ox, meta["y"] + oy)
        else:
            evaluate_fn(f"window.__jevFast?.nodes.get({local_node})?.pause()")
    elif video_op == "toggle_mute":
        evaluate_fn(
            f"(() => {{ const v = window.__jevFast?.nodes.get({local_node}); "
            "if (!v) return; v.muted = !v.muted; if (!v.muted && v.volume === 0) v.volume = 0.5; })()"
        )
    elif video_op == "volume":
        pct, _ = _parse_numeric_target(text, cur=meta["volume"] * 100.0, min_v=0.0, max_v=100.0)
        vol = round(pct / 100.0, 3)
        evaluate_fn(
            f"(() => {{ const v = window.__jevFast?.nodes.get({local_node}); "
            f"if (!v) return; v.volume = {vol}; v.muted = {str(vol <= 0.0).lower()}; }})()"
        )
    elif video_op == "seek":
        max_dur = meta["duration"] if meta["duration"] > 0 else max(meta["currentTime"] + 300.0, 300.0)
        sec, _ = _parse_numeric_target(text, cur=meta["currentTime"], min_v=0.0, max_v=max_dur)
        evaluate_fn(
            f"(() => {{ const v = window.__jevFast?.nodes.get({local_node}); if (v) v.currentTime = {sec:.3f}; }})()"
        )
    elif video_op == "speed":
        rate, _ = _parse_numeric_target(text, cur=meta["playbackRate"], min_v=0.25, max_v=4.0)
        evaluate_fn(
            f"(() => {{ const v = window.__jevFast?.nodes.get({local_node}); if (v) v.playbackRate = {rate:.2f}; }})()"
        )
    else:
        raise ValueError(f"Unsupported video operation: {video_op!r}")


def _execute_slider_op(evaluate_fn, call_top_fn, local_node, info, text, ox=0.0, oy=0.0):
    min_v = float(info.get("min", 0.0))
    max_v = float(info.get("max", 100.0))
    if max_v <= min_v:
        max_v = min_v + 100.0
    cur = float(info.get("cur", min_v))
    step = max(float(info.get("step", 1.0)), 1e-6)
    target_val, target_ratio = _parse_numeric_target(text, cur=cur, min_v=min_v, max_v=max_v)

    if info.get("tag") == "INPUT" and info.get("input_type") == "range":
        evaluate_fn(
            f"""(() => {{
              const e = window.__jevFast?.nodes.get({local_node});
              if (!e) return null;
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
              if (setter) setter.call(e, {json.dumps(str(target_val))});
              else e.value = {json.dumps(str(target_val))};
              e.dispatchEvent(new Event('input', {{bubbles: true}}));
              e.dispatchEvent(new Event('change', {{bubbles: true}}));
              return parseFloat(e.value);
            }})()"""
        )
        return

    evaluate_fn(f"window.__jevFast?.nodes.get({local_node})?.focus?.()")
    if info.get("has_aria_now") and abs(target_val - cur) > step * 0.55:
        if target_val == min_v or target_val == max_v:
            key, code, vk = ("Home", "Home", 36) if target_val == min_v else ("End", "End", 35)
            call_top_fn("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk)
            call_top_fn("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)
            after = evaluate_fn(f"parseFloat(window.__jevFast?.nodes.get({local_node})?.getAttribute('aria-valuenow'))")
            if isinstance(after, (int, float)) and abs(after - target_val) <= step * 0.55:
                return
        prev_now = cur
        moved = False
        for i in range(25):
            if abs(target_val - prev_now) <= step * 0.55:
                return
            right = target_val > prev_now
            key, code, vk = ("ArrowRight", "ArrowRight", 39) if right else ("ArrowLeft", "ArrowLeft", 37)
            call_top_fn("Input.dispatchKeyEvent", type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk)
            call_top_fn("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk)
            after = evaluate_fn(f"parseFloat(window.__jevFast?.nodes.get({local_node})?.getAttribute('aria-valuenow'))")
            if not isinstance(after, (int, float)) or math.isnan(after):
                break
            if after != prev_now:
                moved = True
                prev_now = after
            elif i >= 1 and not moved:
                break
        if moved and abs(target_val - prev_now) <= step * 0.55:
            return

    r = info["rect"]
    span = max_v - min_v
    cur_ratio = min(1.0, max(0.0, (cur - min_v) / span)) if span > 0 else 0.5
    cy = oy + r["y"] + r["h"] / 2.0
    sx = ox + r["x"] + max(1.0, min(max(1.0, r["w"] - 1.0), cur_ratio * r["w"]))
    ex = ox + r["x"] + max(1.0, min(max(1.0, r["w"] - 1.0), target_ratio * r["w"]))
    _dispatch_drag(call_top_fn, sx, cy, ex, cy)


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]
    frame = request.get("frame") or {}
    ox = float(frame.get("ox") or 0.0)
    oy = float(frame.get("oy") or 0.0)

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression, *, await_promise=False):
        try:
            return _eval_with_frame(session, frame, expression, await_promise=await_promise)
        except StalePage:
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.") from None
            raise

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "press_enter":
            call(
                "Input.dispatchKeyEvent",
                type="rawKeyDown",
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                nativeVirtualKeyCode=13,
            )
            call("Input.dispatchKeyEvent", type="char", text="\r", unmodifiedText="\r")
            call(
                "Input.dispatchKeyEvent",
                type="keyUp",
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                nativeVirtualKeyCode=13,
            )
            return {"executed": action["id"]}
        if kind == "scroll":
            delta = int(action["delta"])
            scrolled = evaluate(
                f"""((dy) => {{
                  const before = scrollY;
                  scrollBy({{top: dy, behavior: 'instant'}});
                  if (scrollY !== before) return true;
                  const roots = [document], seen = new Set([document]);
                  const getSR = e => e.shadowRoot || window.__jevShadowRoots?.get(e);
                  for (const r of roots) {{
                    for (const el of r.querySelectorAll('*')) {{
                      const sr = getSR(el);
                      if (sr && !seen.has(sr)) {{
                        seen.add(sr); roots.push(sr);
                      }}
                    }}
                  }}
                  let best = null, bestArea = 0;
                  for (const r of roots) {{
                    for (const el of r.querySelectorAll('*')) {{
                      if (el === document.documentElement || el === document.body) continue;
                      if (el.scrollHeight <= el.clientHeight + 20 || el.clientHeight < 120) continue;
                      const ov = getComputedStyle(el).overflowY;
                      if (ov !== 'auto' && ov !== 'scroll' && ov !== 'overlay') continue;
                      const rc = el.getBoundingClientRect();
                      const w = Math.min(rc.right, innerWidth) - Math.max(rc.left, 0);
                      const h = Math.min(rc.bottom, innerHeight) - Math.max(rc.top, 0);
                      if (w >= 120 && h >= 120 && w * h > bestArea) {{ bestArea = w * h; best = el; }}
                    }}
                  }}
                  if (best) {{
                    const b2 = best.scrollTop;
                    best.scrollBy({{top: dy, behavior: 'instant'}});
                    if (best.scrollTop !== b2) return true;
                  }}
                  return false;
                }})({delta})"""
            )
            if scrolled is not True:
                call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=delta)
        elif kind != "wait":
            _, local_node = _parse_node_ref(action["node"])
            local_action = {**action, "node": local_node} if local_node != action["node"] else action
            if action.get("video_op"):
                _execute_video_op(evaluate, call, local_node, action["video_op"], request.get("text"), ox, oy)
                return {"executed": action["id"]}
            if kind == "fill" and action.get("role") == "slider":
                slider_info = evaluate(f"""(() => {{
                  const e = window.__jevFast?.nodes.get({local_node});
                  if (!e?.isConnected || e.matches?.(':disabled') || e.closest?.('[aria-disabled="true"],[inert]') ||
                      !e.checkVisibility({{checkOpacity:true,checkVisibilityCSS:true}})) return null;
                  const r = e.getBoundingClientRect();
                  if (!r.width || !r.height) return null;
                  const minAttr = e.getAttribute?.('aria-valuemin');
                  const maxAttr = e.getAttribute?.('aria-valuemax');
                  const minV = parseFloat(minAttr ?? (e.tagName === 'INPUT' && e.min !== '' ? e.min : '0'));
                  const maxV = parseFloat(maxAttr ?? (e.tagName === 'INPUT' && e.max !== '' ? e.max : '100'));
                  const stepV = parseFloat(e.tagName === 'INPUT' && e.step ? e.step : '1');
                  const rawNow = e.getAttribute?.('aria-valuenow');
                  const hasNow = rawNow !== null && rawNow !== undefined && !Number.isNaN(parseFloat(rawNow));
                  const valNum = 'value' in e ? parseFloat(e.value) : Number.NaN;
                  const curV = hasNow ? parseFloat(rawNow) : (!Number.isNaN(valNum) ? valNum : minV);
                  return {{
                    tag: e.tagName,
                    input_type: e.type || '',
                    has_aria_now: hasNow,
                    cur: Number.isFinite(curV) ? curV : 0,
                    min: Number.isFinite(minV) ? minV : 0,
                    max: Number.isFinite(maxV) ? maxV : 100,
                    step: Number.isFinite(stepV) && stepV > 0 ? stepV : 1,
                    rect: {{x: r.x, y: r.y, w: r.width, h: r.height}},
                  }};
                }})()""")
                if slider_info is None:
                    raise StalePage("Target changed or is covered. Observe again.")
                _execute_slider_op(evaluate, call, local_node, slider_info, request.get("text"), ox, oy)
                return {"executed": action["id"]}
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            fill_text = request.get("text") if kind == "fill" else None
            iso_fill = bool(isinstance(fill_text, str) and _ISO_TEMPORAL_RE.match(fill_text.strip()))
            target = evaluate("""((action, fillText, isoFill) => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches?.(':disabled') || e.closest?.('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute?.('aria-readonly')==='true')) return null;
              let pt = window.__jevFast?.clickPoint?.(e);
              if (!pt) {
                const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
                if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
                const deepContains = window.__jevFast?.deepContains;
                const hitOk = deepContains ? deepContains(e, x, y) : e.contains(document.elementFromPoint(x, y));
                if (!hitOk) return null;
                pt = {x, y};
              }
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              } else if (action.kind==='fill' && isoFill && e.tagName==='INPUT' &&
                  ['date','time','datetime-local','month','week'].includes(e.type)) {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(e, fillText.trim());
                else e.value = fillText.trim();
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                return {...pt, native_filled: true};
              }
              const opensNewTab = action.kind==='click' && Boolean(e.closest?.('a[target="_blank"]'));
              return opensNewTab ? {...pt, opens_new_tab: true} : pt;
            })(""" + json.dumps(local_action) + "," + json.dumps(fill_text) + "," + json.dumps(iso_fill) + ")")
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select" and not target.get("native_filled"):
                x, y = target["x"] + ox, target["y"] + oy
                _dispatch_click(call, x, y)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
            if target.get("opens_new_tab"):
                return {"executed": action["id"], "opens_new_tab": True}
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
