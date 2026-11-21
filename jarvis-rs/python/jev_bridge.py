"""JSON-lines bridge driving jev_ultrafast.Agent step-by-step from stdin/stdout."""

from __future__ import annotations

from difflib import SequenceMatcher
import inspect
import json
import os
import re
import sys
import threading
import time
from typing import Any, TextIO

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp
from jev_ultrafast.agent import Agent
from jev_ultrafast.browser import StalePage
from jev_ultrafast.model import CLIENT as JEV_HTTP_CLIENT
from jev_ultrafast.model import DEFAULT_JEV_URL, action_space


def page_summary(page: dict[str, Any]) -> dict[str, Any]:
    """Return bounded visible page context for the Rust broker and voice narrator."""
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": (page.get("text") or "")[:6000],
        "fingerprint": page.get("fingerprint", ""),
    }


def classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "api_key" in msg or "credential" in msg:
        return "missing_key"
    if "budget" in msg:
        return "budget_exceeded"
    if isinstance(exc, (ConnectionError, EOFError)) or any(
        k in msg
        for k in (
            "allow",
            "devtools",
            "chrome",
            "daemon",
            "target",
            "closed",
            "websocket",
            "session",
            "detached",
            "broken pipe",
            "connection",
        )
    ):
        return "chrome_not_ready"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return "browser_error"


def _is_dead_session_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "session with given id not found",
            "no target with given id",
            "target closed",
            "inspected target navigated or closed",
            "session closed",
            "detached",
        )
    )


def _is_transient_nav_error(exc: Exception) -> bool:
    if isinstance(exc, StalePage):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("navigated", "execution context", "cannot find context"))


def _wait_for_ready_state(
    browser: Any,
    target_url: str | None = None,
    timeout_s: float = 15.0,
    *,
    prev_origin: Any = None,
    prev_href: str | None = None,
) -> tuple[str, str]:
    fallback = target_url or ""
    same_doc_hash = bool(
        prev_href
        and target_url
        and "#" in target_url
        and target_url.split("#", 1)[0] == prev_href.split("#", 1)[0]
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            state = browser.evaluate("[document.readyState, location.href, document.title, performance.timeOrigin]")
        except Exception as exc:
            if _is_transient_nav_error(exc):
                state = None
            else:
                raise
        if isinstance(state, str) and state in {"interactive", "complete"}:
            return fallback, ""
        if (
            isinstance(state, (list, tuple))
            and len(state) >= 2
            and state[0] in {"interactive", "complete"}
            and (not target_url or target_url == "about:blank" or state[1] != "about:blank")
        ):
            href = str(state[1] or fallback)
            title = str(state[2] or "") if len(state) >= 3 else ""
            origin = state[3] if len(state) >= 4 else None
            # When reusing an existing tab for a new URL, wait until navigation actually commits off the old document.
            if (
                prev_origin is not None
                and not same_doc_hash
                and origin is not None
                and origin == prev_origin
                and (not prev_href or href == prev_href)
            ):
                time.sleep(0.02)
                continue
            return href, title
        time.sleep(0.02)
    return fallback, ""


def _read_lightweight_meta(browser: Any, fallback_url: str) -> tuple[str, str]:
    try:
        meta = browser.evaluate("[location.href, document.title]")
    except Exception:
        return fallback_url, ""
    if isinstance(meta, (list, tuple)) and len(meta) == 2:
        href = str(meta[0] or fallback_url)
        title = str(meta[1] or "")
        return href, title
    return fallback_url, ""


def _fast_scroll(browser: Any, action: str) -> None:
    """Scroll instantly on window OR the largest visible scrollable container; fall back to CDP mouseWheel."""
    payload = json.dumps(action)
    res = browser.evaluate(
        f"""((action) => {{
          const step = Math.max(700, Math.round(innerHeight * 0.75));
          const dir = action === 'scroll_up' ? -1 : 1;
          const dy = dir * step;
          const tryScroll = (el, isWin) => {{
            const before = isWin ? scrollY : el.scrollTop;
            if (action === 'scroll_top') {{
              if (isWin) scrollTo({{top: 0, behavior: 'instant'}});
              else el.scrollTo({{top: 0, behavior: 'instant'}});
            }} else if (action === 'scroll_bottom') {{
              const maxY = isWin ? Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0) : el.scrollHeight;
              if (isWin) scrollTo({{top: maxY, behavior: 'instant'}});
              else el.scrollTo({{top: maxY, behavior: 'instant'}});
            }} else {{
              if (isWin) scrollBy({{top: dy, behavior: 'instant'}});
              else el.scrollBy({{top: dy, behavior: 'instant'}});
            }}
            const after = isWin ? scrollY : el.scrollTop;
            return after !== before;
          }};
          if (tryScroll(window, true)) return true;
          const roots = [document], seen = new Set([document]);
          const getSR = e => e.shadowRoot || window.__jevShadowRoots?.get(e);
          for (const r of roots) {{
            for (const el of r.querySelectorAll('*')) {{
              const sr = getSR(el);
              if (sr && !seen.has(sr)) {{ seen.add(sr); roots.push(sr); }}
            }}
          }}
          let best = null, bestArea = 0;
          for (const r of roots) {{
            for (const el of r.querySelectorAll('*')) {{
              if (el === document.documentElement || el === document.body) continue;
              if (el.scrollHeight <= el.clientHeight + 20 || el.clientHeight < 120) continue;
              const ov = getComputedStyle(el).overflowY;
              if (ov !== 'auto' && ov !== 'scroll' && ov !== 'overlay') continue;
              const rect = el.getBoundingClientRect();
              const visW = Math.min(rect.right, innerWidth) - Math.max(rect.left, 0);
              const visH = Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0);
              if (visW < 120 || visH < 120) continue;
              const area = visW * visH;
              if (area > bestArea) {{ bestArea = area; best = el; }}
            }}
          }}
          if (best && tryScroll(best, false)) return true;
          return [Math.round(innerWidth / 2), Math.round(innerHeight / 2), action === 'scroll_top' ? -5000 : action === 'scroll_bottom' ? 5000 : dy];
        }})({payload})"""
    )
    if res is True:
        return
    cx, cy, dy = (
        (int(res[0]), int(res[1]), int(res[2]))
        if isinstance(res, (list, tuple)) and len(res) == 3
        else (560, 390, (-1 if action in {"scroll_up", "scroll_top"} else 1) * 700)
    )
    browser.call(
        "Input.dispatchMouseEvent",
        type="mouseWheel",
        x=cx,
        y=cy,
        deltaX=0,
        deltaY=dy,
    )


def _adjust_zoom(browser: Any, action: str) -> str:
    """Adjust page zoom cleanly between 50% and 250% for hands-free readability on any website."""
    pct = browser.evaluate(
        f"""((action) => {{
          const cur = parseFloat(document.documentElement.style.zoom || '1') || 1;
          const next = action === 'zoom_reset' ? 1
            : action === 'zoom_in' ? Math.min(2.5, +(cur + 0.15).toFixed(2))
            : Math.max(0.5, +(cur - 0.15).toFixed(2));
          document.documentElement.style.zoom = next === 1 ? '' : String(next);
          return Math.round(next * 100);
        }})({json.dumps(action)})"""
    )
    if action == "zoom_reset" or pct == 100:
        return "Zoom reset."
    return f"Zoom {pct} percent."


_KEY_SPECS: dict[str, tuple[str, str, int, int]] = {
    "press_escape": ("Escape", "Escape", 27, 0),
    "press_enter": ("Enter", "Enter", 13, 0),
    "press_tab": ("Tab", "Tab", 9, 0),
    "press_ctrl_k": ("k", "KeyK", 75, 2),
    "press_ctrl_f": ("f", "KeyF", 70, 2),
}


def _dispatch_key(browser: Any, action: str) -> None:
    key, code, vk, mods = _KEY_SPECS[action]
    extra = {"modifiers": mods} if mods else {}
    browser.call(
        "Input.dispatchKeyEvent",
        type="rawKeyDown",
        key=key,
        code=code,
        windowsVirtualKeyCode=vk,
        nativeVirtualKeyCode=vk,
        **extra,
    )
    if action == "press_enter":
        browser.call("Input.dispatchKeyEvent", type="char", text="\r", unmodifiedText="\r")
    browser.call(
        "Input.dispatchKeyEvent",
        type="keyUp",
        key=key,
        code=code,
        windowsVirtualKeyCode=vk,
        nativeVirtualKeyCode=vk,
        **extra,
    )


def _close_dialog(browser: Any) -> None:
    """Dismiss an active modal/help dialog/overlay by clicking its Close button (main doc or iframe) or pressing Escape."""
    js = """(() => {
      const roots = [document], seen = new Set([document]);
      const getSR = e => e.shadowRoot || window.__jevShadowRoots?.get(e);
      for (const r of roots) {
        for (const el of r.querySelectorAll('*')) {
          const sr = getSR(el);
          if (sr && !seen.has(sr)) { seen.add(sr); roots.push(sr); }
        }
      }
      const vis = e => e && e.checkVisibility?.({checkOpacity: true, checkVisibilityCSS: true});
      const dialogSel = '[role="dialog"],[aria-modal="true"],dialog[open],[class*="dialog" i],[class*="modal" i],[class*="popup" i],[class*="drawer" i],ytd-popup-container,tp-yt-paper-dialog,.ytp-popup';
      const btnSel = 'button,[role="button"],[aria-label*="close" i],[title*="close" i]';
      const isClose = el => {
        const lbl = ((el.getAttribute?.('aria-label') || el.getAttribute?.('title') || el.innerText || '') + '').trim();
        return /^(?:close|dismiss)(?:\\b|$)/i.test(lbl) || /^×$|^✕$|^x$/i.test(lbl);
      };
      const clickPt = el => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        const x = r.x + r.width / 2, y = r.y + r.height / 2;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;
        return [x, y];
      };
      for (const r of roots) {
        for (const dlg of r.querySelectorAll(dialogSel)) {
          if (!vis(dlg)) continue;
          for (const btn of dlg.querySelectorAll(btnSel)) {
            if (!vis(btn) || !isClose(btn)) continue;
            const pt = clickPt(btn);
            if (pt) return {click: pt};
          }
        }
      }
      for (const r of roots) {
        for (const btn of r.querySelectorAll('button[aria-label*="close" i],[role="button"][aria-label*="close" i]')) {
          if (!vis(btn)) continue;
          const pt = clickPt(btn);
          if (pt) return {click: pt};
        }
      }
      return {click: null};
    })()"""
    res = browser.evaluate(js)
    if isinstance(res, dict) and isinstance(res.get("click"), (list, tuple)) and len(res["click"]) == 2:
        x, y = float(res["click"][0]), float(res["click"][1])
        for ev in ("mousePressed", "mouseReleased"):
            browser.call("Input.dispatchMouseEvent", type=ev, x=x, y=y, button="left", clickCount=1)
        return
    # Also check open help/dialog iframes (e.g., Google/YouTube Help overlay).
    eval_in_frame = getattr(browser, "_eval_in_frame", None)
    if callable(eval_in_frame):
        iframe_js = """(() => {
          const btns = document.querySelectorAll('button,[role="button"],[aria-label*="close" i],[title*="close" i]');
          for (const b of btns) {
            const lbl = ((b.getAttribute?.('aria-label') || b.getAttribute?.('title') || b.innerText || '') + '').trim();
            if (/^(?:close|dismiss)(?:\\b|$)/i.test(lbl) && b.checkVisibility?.({checkOpacity: true, checkVisibilityCSS: true})) {
              b.click();
              return true;
            }
          }
          return false;
        })()"""
        for ref in _collect_iframe_refs(browser):
            try:
                if eval_in_frame(ref, iframe_js) is True:
                    return
            except Exception:
                continue
    _dispatch_key(browser, "press_escape")


def _extract_readable_text(browser: Any) -> str:
    """Extract clean primary article/main text on any website, skipping nav/header/footer chrome."""
    try:
        text = browser.evaluate(
            """(() => {
              const container = document.querySelector('article, main, [role="main"]');
              if (!container) return '';
              const skip = 'nav,header,footer,aside,script,style,noscript,[aria-hidden="true"],[role="navigation"]';
              const parts = [];
              const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const parent = node.parentElement;
                if (!parent || parent.closest(skip)) continue;
                const s = (node.nodeValue || '').replace(/\\s+/g, ' ').trim();
                if (s) parts.push(s);
                if (parts.length > 220) break;
              }
              return parts.join(' ').slice(0, 2000);
            })()"""
        )
    except Exception:
        return ""
    return text.strip() if isinstance(text, str) else ""


_MEDIA_ACTIONS = frozenset({
    "play_video",
    "pause_video",
    "mute_video",
    "unmute_video",
    "volume_up",
    "volume_down",
    "seek_forward",
    "seek_back",
    "skip_ad",
    "fullscreen",
    "open_settings",
    "toggle_captions",
    "speed_up",
    "speed_down",
    "next_track",
    "prev_track",
})


def _parse_media_action(action: str) -> tuple[str, float | None] | None:
    if action in _MEDIA_ACTIONS:
        return action, None
    if action.startswith("volume:"):
        try:
            pct = float(action.split(":", 1)[1])
        except ValueError:
            return None
        return "volume_set", max(0.0, min(100.0, pct))
    if action.startswith("speed:"):
        try:
            rate = float(action.split(":", 1)[1])
        except ValueError:
            return None
        return "speed_set", max(0.25, min(4.0, rate))
    return None


def _media_control_js(op: str, value: float | None) -> str:
    payload = json.dumps({"op": op, "value": value})
    return f"""(({{op, value}}) => {{
      const roots = [document], seen = new Set([document]);
      const getSR = e => e.shadowRoot || window.__jevShadowRoots?.get(e);
      for (const r of roots) {{
        for (const el of r.querySelectorAll('*')) {{
          const sr = getSR(el);
          if (sr && !seen.has(sr)) {{ seen.add(sr); roots.push(sr); }}
        }}
      }}
      const vis = e => e && e.checkVisibility?.({{checkOpacity: true, checkVisibilityCSS: true}});
      const center = (e, ensureInView = false) => {{
        let r = e.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        if (ensureInView && (r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth)) {{
          e.scrollIntoView?.({{block: 'center', inline: 'center', behavior: 'instant'}});
          r = e.getBoundingClientRect();
        }}
        const x = r.x + r.width / 2, y = r.y + r.height / 2;
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;
        return [x, y];
      }};
      const findBtn = (sel, re) => {{
        for (const r of roots) {{
          for (const el of r.querySelectorAll(sel)) {{
            const lbl = ((el.getAttribute?.('aria-label') || el.getAttribute?.('title') || el.innerText || '') + '').trim();
            if (re && !re.test(lbl)) continue;
            const pt = center(el, true);
            if (pt && vis(el)) return pt;
          }}
        }}
        return null;
      }};
      if (op === 'skip_ad') {{
        const sel = '.ytp-skip-ad-button,.ytp-ad-skip-button,.ytp-ad-skip-button-modern,[class*="skip-ad"],[class*="skip" i],button,[role="button"]';
        for (const r of roots) {{
          for (const el of r.querySelectorAll(sel)) {{
            if (!vis(el)) continue;
            const txt = ((el.innerText || el.getAttribute?.('aria-label') || '') + '').trim();
            if (el.matches?.('.ytp-skip-ad-button,.ytp-ad-skip-button,.ytp-ad-skip-button-modern,[class*="skip-ad"]') || /^skip(\\s+(?:ads?|intro|recap))?$/i.test(txt)) {{
              const pt = center(el, true);
              if (pt) return {{ok: true, click: pt}};
            }}
          }}
        }}
        return {{ok: false, reason: 'no_skip_button'}};
      }}
      if (op === 'next_track' || op === 'prev_track') {{
        const sel = op === 'next_track'
          ? '.ytp-next-button,button[aria-label*="next" i],[role="button"][aria-label*="next" i],a[aria-label*="next" i],button[title*="next" i]'
          : '.ytp-prev-button,button[aria-label*="previous" i],[role="button"][aria-label*="previous" i],button[title*="previous" i]';
        const pt = findBtn(sel, null);
        if (pt) return {{ok: true, click: pt}};
        return {{ok: false, reason: 'control_not_found'}};
      }}
      if (op === 'open_settings' || op === 'toggle_captions') {{
        const sel = op === 'open_settings'
          ? '.ytp-settings-button,button[aria-label*="settings" i],[role="button"][aria-label*="settings" i],button[title*="settings" i],button[aria-label*="quality" i]'
          : '.ytp-subtitles-button,button[aria-label*="caption" i],button[aria-label*="subtitle" i],[role="button"][aria-label*="caption" i],[role="button"][aria-label*="subtitle" i]';
        const pt = findBtn(sel, null);
        if (pt) return {{ok: true, click: pt}};
        let bestV = null, bestA = 0;
        for (const r of roots) {{
          for (const v of r.querySelectorAll('video')) {{
            const rect = v.getBoundingClientRect();
            const a = Math.max(0, rect.width) * Math.max(0, rect.height);
            if (a > bestA) {{ bestA = a; bestV = v; }}
          }}
        }}
        if (bestV) {{
          const ptV = center(bestV, true);
          if (ptV) return {{ok: false, hover: ptV}};
        }}
        return {{ok: false, reason: 'control_not_found'}};
      }}
      if (op === 'fullscreen') {{
        if (document.fullscreenElement) {{
          document.exitFullscreen?.().catch?.(() => {{}});
          return {{ok: true}};
        }}
        const sel = '.ytp-fullscreen-button,button[aria-label*="full screen" i],button[aria-label*="fullscreen" i],button[title*="full screen" i]';
        const pt = findBtn(sel, null);
        if (pt) return {{ok: true, click: pt}};
      }}
      // Prefer YouTube's #movie_player API when present so UI slider/icons stay synced with audio.
      const mp = document.getElementById('movie_player');
      if (mp && typeof mp.setVolume === 'function' && typeof mp.getVolume === 'function') {{
        if (op === 'pause_video' && typeof mp.pauseVideo === 'function') {{ mp.pauseVideo(); return {{ok: true, via: 'yt'}}; }}
        if (op === 'play_video' && typeof mp.playVideo === 'function') {{ mp.playVideo(); return {{ok: true, via: 'yt'}}; }}
        if (op === 'mute_video' && typeof mp.mute === 'function') {{ mp.mute(); return {{ok: true, via: 'yt'}}; }}
        if (op === 'unmute_video' && typeof mp.unMute === 'function') {{
          mp.unMute();
          if (mp.getVolume() === 0) mp.setVolume(50);
          return {{ok: true, via: 'yt'}};
        }}
        if (op === 'volume_up') {{
          mp.unMute?.();
          const next = Math.min(100, Math.round(mp.getVolume() + 15));
          mp.setVolume(next);
          return {{ok: true, via: 'yt', volume: next}};
        }}
        if (op === 'volume_down') {{
          const next = Math.max(0, Math.round(mp.getVolume() - 15));
          mp.setVolume(next);
          if (next === 0) mp.mute?.();
          return {{ok: true, via: 'yt', volume: next}};
        }}
        if (op === 'volume_set') {{
          const next = Math.max(0, Math.min(100, Math.round(Number(value || 0))));
          if (next > 0) mp.unMute?.();
          mp.setVolume(next);
          if (next === 0) mp.mute?.();
          return {{ok: true, via: 'yt', volume: next}};
        }}
        if ((op === 'seek_forward' || op === 'seek_back') && typeof mp.getCurrentTime === 'function' && typeof mp.seekTo === 'function') {{
          const cur = Number(mp.getCurrentTime() || 0);
          const dur = Number(mp.getDuration?.() || 0);
          const delta = op === 'seek_forward' ? 10 : -10;
          const next = Math.max(0, dur > 0 ? Math.min(dur, cur + delta) : cur + delta);
          mp.seekTo(next, true);
          return {{ok: true, via: 'yt', time: next}};
        }}
        if ((op === 'speed_set' || op === 'speed_up' || op === 'speed_down') && typeof mp.setPlaybackRate === 'function') {{
          const cur = Number(mp.getPlaybackRate?.() || 1);
          const next = op === 'speed_set' ? Number(value || 1)
            : op === 'speed_up' ? Math.min(2.0, +(cur + 0.25).toFixed(2))
            : Math.max(0.25, +(cur - 0.25).toFixed(2));
          mp.setPlaybackRate(next);
          return {{ok: true, via: 'yt', speed: next}};
        }}
      }}
      // Universal HTML5 <video> and <audio> across all websites (podcasts, Spotify, Vimeo, Twitch, news, courses).
      let best = null, bestScore = -1;
      for (const r of roots) {{
        for (const m of r.querySelectorAll('video, audio')) {{
          const isAudio = m.tagName === 'AUDIO';
          const rect = m.getBoundingClientRect();
          const area = Math.max(0, rect.width) * Math.max(0, rect.height);
          const playing = !m.paused && !m.ended;
          const score = (playing ? 2e9 : 0) + (vis(m) ? 1e9 : 0) + (m.readyState > 0 ? 1e6 : 0) + (isAudio && (m.currentSrc || m.src) ? 5e5 : 0) + area;
          if (score > bestScore) {{ bestScore = score; best = m; }}
        }}
      }}
      if (best) {{
        if (op === 'fullscreen') {{
          best.requestFullscreen?.().catch?.(() => {{}});
          return {{ok: true}};
        }}
        if (op === 'pause_video') {{ best.pause(); return {{ok: true}}; }}
        if (op === 'play_video') {{
          if (best.paused) {{
            try {{ const p = best.play?.(); if (p?.catch) p.catch(() => {{}}); }} catch {{}}
            if (best.paused) {{
              const pt = center(best, true);
              if (pt) return {{ok: true, click: pt}};
            }}
          }}
          return {{ok: true}};
        }}
        if (op === 'mute_video') {{ best.muted = true; return {{ok: true}}; }}
        if (op === 'unmute_video') {{ best.muted = false; if (best.volume === 0) best.volume = 0.5; return {{ok: true}}; }}
        if (op === 'volume_up') {{ best.muted = false; best.volume = Math.min(1, +(best.volume + 0.15).toFixed(2)); return {{ok: true}}; }}
        if (op === 'volume_down') {{
          best.volume = Math.max(0, +(best.volume - 0.15).toFixed(2));
          if (best.volume === 0) best.muted = true;
          return {{ok: true}};
        }}
        if (op === 'volume_set') {{
          const vol = Math.max(0, Math.min(1, +(Number(value || 0) / 100).toFixed(2)));
          best.volume = vol;
          best.muted = vol <= 0;
          return {{ok: true}};
        }}
        if (op === 'seek_forward') {{
          const maxT = Number.isFinite(best.duration) && best.duration > 0 ? best.duration : best.currentTime + 10;
          best.currentTime = Math.min(maxT, best.currentTime + 10);
          return {{ok: true}};
        }}
        if (op === 'seek_back') {{ best.currentTime = Math.max(0, best.currentTime - 10); return {{ok: true}}; }}
        if (op === 'speed_set' || op === 'speed_up' || op === 'speed_down') {{
          const cur = Number(best.playbackRate || 1);
          const next = op === 'speed_set' ? Math.max(0.25, Math.min(4.0, Number(value || 1)))
            : op === 'speed_up' ? Math.min(4.0, +(cur + 0.25).toFixed(2))
            : Math.max(0.25, +(cur - 0.25).toFixed(2));
          best.playbackRate = next;
          return {{ok: true, speed: next}};
        }}
      }}
      // Accessible button fallback for custom WebAudio/DRM players (Spotify, SoundCloud, Netflix, Twitch, podcasts).
      const btnMap = {{
        pause_video: ['button,[role="button"]', /^(?:pause|stop)(?:\\b|$)/i],
        play_video: ['button,[role="button"]', /^(?:play|resume)(?:\\b|$)/i],
        mute_video: ['button,[role="button"]', /^mute(?:\\b|$)/i],
        unmute_video: ['button,[role="button"]', /^unmute(?:\\b|$)/i],
      }};
      if (btnMap[op]) {{
        const [sel, re] = btnMap[op];
        const pt = findBtn(sel, re);
        if (pt) return {{ok: true, click: pt}};
      }}
      return {{ok: false, reason: 'no_video'}};
    }})({payload})"""


def _collect_iframe_refs(browser: Any) -> list[dict[str, Any]]:
    """Collect accessible child iframe refs (same-process and attached OOPIFs) for universal media/dialog fallback."""
    refs: list[dict[str, Any]] = []
    if not getattr(browser, "session", None):
        return refs
    try:
        tree = browser.call("Page.getFrameTree").get("frameTree", {})
    except Exception:
        return refs
    if not isinstance(tree, dict):
        return refs
    raw_oopifs = getattr(browser, "_attach_oopif_sessions", dict)()
    oopifs: dict[str, list[str]] = {}
    if isinstance(raw_oopifs, dict):
        for k, v in raw_oopifs.items():
            if isinstance(v, list):
                oopifs[k] = list(v)
            elif isinstance(v, str):
                oopifs[k] = [v]
    main_id = (tree.get("frame") or {}).get("id")
    child_frames = tree.get("childFrames")
    stack = list(child_frames) if isinstance(child_frames, list) else []
    while stack and len(refs) < 12:
        node = stack.pop(0)
        fr = node.get("frame") or {}
        fid = fr.get("id")
        f_url = str(fr.get("url") or "")
        if fid and fid != main_id and f_url not in {"about:blank", "javascript:false"}:
            oo_list = oopifs.get(f_url) or oopifs.get(fid) or []
            oo_sid = oo_list.pop(0) if oo_list else None
            refs.append({"frame_id": None, "session_id": oo_sid} if oo_sid else {"frame_id": fid})
        stack.extend(node.get("childFrames") or [])
    return refs


def _run_media_control(browser: Any, op: str, value: float | None = None) -> dict[str, Any]:
    """Execute direct 1-shot media/player control across main doc, Shadow DOM, and iframes."""
    js = _media_control_js(op, value)
    res = browser.evaluate(js)
    if isinstance(res, dict) and isinstance(res.get("hover"), (list, tuple)) and len(res["hover"]) == 2:
        hx, hy = float(res["hover"][0]), float(res["hover"][1])
        browser.call("Input.dispatchMouseEvent", type="mouseMoved", x=hx, y=hy, pointerType="mouse")
        time.sleep(0.18)
        res = browser.evaluate(js)
    if isinstance(res, dict) and isinstance(res.get("click"), (list, tuple)) and len(res["click"]) == 2:
        x, y = float(res["click"][0]), float(res["click"][1])
        for ev in ("mousePressed", "mouseReleased"):
            browser.call("Input.dispatchMouseEvent", type=ev, x=x, y=y, button="left", clickCount=1)
        return res
    if isinstance(res, dict) and res.get("ok"):
        return res
    # Fallback: check embedded same-process / OOPIF iframes (Vimeo, YouTube, Twitch, podcast embeds on any site).
    eval_in_frame = getattr(browser, "_eval_in_frame", None)
    if callable(eval_in_frame):
        for ref in _collect_iframe_refs(browser):
            try:
                fres = eval_in_frame(ref, js)
            except Exception:
                continue
            if isinstance(fres, dict) and fres.get("ok"):
                return fres
    return res if isinstance(res, dict) else {"ok": True}


def _prewarm_jev_http_async() -> None:
    def _warm() -> None:
        try:
            base = DEFAULT_JEV_URL.split("/v1/", 1)[0]
            JEV_HTTP_CLIENT.head(base, timeout=3.0)
        except Exception:
            pass

    threading.Thread(target=_warm, name="jev-http-prewarm", daemon=True).start()


def _list_page_targets(*, prefer_real: bool = True) -> list[dict[str, Any]]:
    """Return user-browsable Chrome page targets via CDP."""
    raw = cdp("Target.getTargets").get("targetInfos", [])
    pages = [
        t
        for t in raw
        if t.get("type") == "page"
        and not str(t.get("url") or "").startswith(("devtools://", "chrome-extension://", "chrome-untrusted://"))
    ]
    if prefer_real:
        real = [t for t in pages if str(t.get("url") or "") not in {"", "about:blank"}]
        if real:
            return real
    return pages


_TAB_LABEL_CLEAN_RE = re.compile(r"[^A-Za-z0-9 '\-,.&:]+")


def _short_tab_label(url: str, title: str) -> str:
    clean_title = _TAB_LABEL_CLEAN_RE.sub(" ", (title or ""))
    clean_title = " ".join(clean_title.split()).strip(" .-,:&")
    if len(clean_title) >= 2:
        return clean_title[:50].rstrip(" .-,:&")
    if "://" in url:
        host = url.split("://", 1)[1].split("/", 1)[0]
        return host.removeprefix("www.") or "the tab"
    return "the tab"


_CLICK_NOISE_RE = re.compile(r"[^a-z0-9]+")
_CLICK_UI_SUFFIX_RE = re.compile(
    r"\s+(?:button|btn|link|tab|icon|menu|option|checkbox|radio|toggle|switch|box|field|card|item|video|result)$"
)


def _norm_click_text(s: str) -> str:
    return _CLICK_NOISE_RE.sub(" ", (s or "").lower()).strip()


def _match_clickable_action(actions: list[dict[str, Any]], target: str) -> tuple[dict[str, Any], float] | None:
    """Match a spoken target against all observed clickable/selectable actions on the page."""
    raw_q = _norm_click_text(target)
    if not raw_q:
        return None
    stripped_q = _CLICK_UI_SUFFIX_RE.sub("", raw_q).strip() or raw_q
    queries = (raw_q, stripped_q) if stripped_q != raw_q else (raw_q,)

    scored: list[tuple[float, int, str, dict[str, Any]]] = []
    for act in actions:
        kind = act.get("kind")
        if kind not in {"click", "select"} or act.get("video_op"):
            continue
        raw_label = str(act.get("label") or "")
        if not raw_label or raw_label.startswith("Open ") and act.get("role") in {"textbox", "searchbox", "spinbutton"}:
            continue
        variants = [_norm_click_text(raw_label)]
        if kind == "select" and "→" in raw_label:
            variants.append(_norm_click_text(raw_label.split("→", 1)[1]))

        best_local = 0.0
        best_len = 9999
        for lbl in variants:
            if not lbl:
                continue
            for q in queries:
                if lbl == q:
                    score = 1.0
                elif lbl.startswith(q + " ") or (len(lbl) >= 3 and q.startswith(lbl + " ")):
                    score = 0.92
                elif f" {q} " in f" {lbl} ":
                    score = 0.87
                elif len(q) >= 4:
                    ratio = SequenceMatcher(None, q, lbl).ratio()
                    score = ratio if ratio >= 0.82 else 0.0
                else:
                    score = 0.0
                if score > best_local or (score == best_local and len(lbl) < best_len):
                    best_local = score
                    best_len = len(lbl)
        if best_local >= 0.84:
            scored.append((best_local, -best_len, raw_label, act))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_score, _, top_label, top_act = scored[0]
    if len(scored) > 1 and top_score < 0.99:
        second_score, _, second_label, _ = scored[1]
        if second_label.lower() != top_label.lower() and (top_score - second_score) < 0.05:
            return None
    return top_act, top_score


def _reset_browser_media_state(browser: Any) -> None:
    """Ensure the next observe() after a navigation re-checks video/iframe player controls."""
    if browser is None:
        return
    browser._last_page_has_media = True
    browser._player_menu_open = False
    browser._last_click_was_player = False


def _invalidate_page_cache(agent: Any) -> dict[str, Any]:
    page = dict(agent.state.get("page") or {})
    page["marker"] = None
    page["fingerprint"] = ""
    agent.state["page"] = page
    agent.state["decision"] = None
    if agent.state.get("status") == "predicted":
        agent.state["status"] = "ready"
    return page


def _detach_browser_session(agent: Any) -> None:
    """Detach CDP session without closing the Chrome tab."""
    browser = getattr(agent, "browser", None)
    if browser is None:
        return
    sid = getattr(browser, "session", None)
    if sid:
        try:
            cdp("Target.detachFromTarget", sessionId=sid)
        except Exception:
            pass
        browser.session = None
    browser.target = None


class BridgeSession:
    """Owns at most one jev_ultrafast Agent tab and handles JSON-lines commands."""

    def __init__(self, *, agent_cls: Any = Agent, default_background: bool = False) -> None:
        self._agent_cls = agent_cls
        self._default_background = default_background
        self.agent: Any = None
        self._pending_nav_url: str | None = None
        self._owns_tab: bool = False

    def close_agent(self) -> None:
        self._pending_nav_url = None
        if self.agent is not None:
            agent = self.agent
            owns = self._owns_tab
            self.agent = None
            self._owns_tab = False
            if self._agent_cls is Agent and getattr(agent.browser, "target", None):
                try:
                    other_tabs = [
                        t
                        for t in _list_page_targets(prefer_real=False)
                        if t.get("targetId") != agent.browser.target
                    ]
                except Exception:
                    other_tabs = []
                # Never close the user's pre-existing tab or Chrome's last remaining tab.
                if not owns or not other_tabs:
                    _detach_browser_session(agent)
                    return
            try:
                agent.close()
            except Exception:
                pass

    def _try_attach_existing_tab(self) -> Any | None:
        """Attach to an existing Chrome tab when no Jarvis-opened tab is active."""
        if self._agent_cls is not Agent:
            return None
        try:
            ensure_daemon()
            tabs = _list_page_targets(prefer_real=True)
            if not tabs:
                return None
            chosen = tabs[-1]
            tid = chosen["targetId"]
            url = str(chosen.get("url") or "about:blank")
            title = str(chosen.get("title") or "")
            self.agent = self._agent_cls(
                url,
                "Active browser tab",
                background=self._default_background,
                observe=False,
                target_id=tid,
            )
            self._owns_tab = False
            self.agent.state["page"]["url"] = url
            self.agent.state["page"]["title"] = title
            return self.agent
        except Exception:
            return None

    def handle(self, req: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Execute one command and return (response_dict, should_exit)."""
        cmd = req.get("cmd")
        try:
            if cmd == "ping":
                return {"ok": True, "pid": os.getpid()}, False
            if cmd == "warm_browser":
                ensure_daemon()
                _prewarm_jev_http_async()
                return {"ok": True}, False
            if cmd == "open":
                return self._open(req), False
            if cmd == "predict":
                return self._predict(), False
            if cmd == "act":
                return self._act(req), False
            if cmd == "cancel":
                return self._cancel(), False
            if cmd == "read_page":
                return self._read_page(), False
            if cmd == "match_click":
                return self._match_click(req), False
            if cmd == "control":
                return self._control(req), False
            if cmd == "close":
                self.close_agent()
                return {"ok": True}, True
            return {"ok": False, "code": "unknown_command", "error": f"Unknown command: {cmd!r}"}, False
        except Exception as exc:
            code = classify_error(exc)
            print(f"jev_bridge: cmd={cmd!r} failed ({code}): {exc}", file=sys.stderr, flush=True)
            if code == "chrome_not_ready":
                self.close_agent()
            return {"ok": False, "code": code, "error": str(exc)}, False

    def _require_agent(self) -> Any:
        if self.agent is None:
            attached = self._try_attach_existing_tab()
            if attached is not None:
                return attached
            raise ValueError("No browser tab is open; start a browser task first.")
        return self.agent

    def _open(self, req: dict[str, Any]) -> dict[str, Any]:
        goal = str(req.get("goal", "")).strip()
        if not goal:
            raise ValueError("Supply a non-empty goal.")
        url = req.get("url")
        url = str(url).strip() if isinstance(url, str) and url.strip() else None
        background = bool(req.get("background", self._default_background))
        skip_observe = bool(req.get("skip_observe", False))
        new_tab = bool(req.get("new_tab", False))

        if new_tab and self.agent is not None:
            # Detach CDP session cleanly without closing the prior Chrome tab, then open a fresh tab.
            if self._agent_cls is Agent:
                _detach_browser_session(self.agent)
            self.agent = None
            self._owns_tab = False

        if self.agent is None and not url and not new_tab:
            self._try_attach_existing_tab()

        if self.agent is not None:
            try:
                ready_meta: tuple[str, str] | None = None
                if url:
                    prev_origin, prev_href = None, None
                    try:
                        prev = self.agent.browser.evaluate("[performance.timeOrigin, location.href]")
                        if isinstance(prev, (list, tuple)) and len(prev) == 2:
                            prev_origin, prev_href = prev[0], str(prev[1] or "")
                    except Exception:
                        pass
                    self.agent.browser.call("Page.navigate", url=url, _response_timeout=20.0)
                    _reset_browser_media_state(self.agent.browser)
                    # Direct opens/searches don't need full interactive DOM before returning; Chrome paints immediately.
                    ready_meta = _wait_for_ready_state(
                        self.agent.browser,
                        target_url=url,
                        timeout_s=0.35 if skip_observe else 15.0,
                        prev_origin=prev_origin,
                        prev_href=prev_href,
                    )
                    self._pending_nav_url = url if skip_observe else None
                elif not skip_observe:
                    _wait_for_ready_state(self.agent.browser, target_url=self._pending_nav_url, timeout_s=10.0)
                    self._pending_nav_url = None
                self.agent.pending_text = None
                if skip_observe:
                    if ready_meta is not None:
                        href, title = ready_meta
                    else:
                        fallback = url or (self.agent.state.get("page") or {}).get("url", "")
                        href, title = _read_lightweight_meta(self.agent.browser, fallback)
                    page = {
                        "url": href,
                        "title": title,
                        "text": "",
                        "actions": [],
                        "fingerprint": "",
                        "marker": None,
                    }
                else:
                    try:
                        page = self.agent.browser.observe(screenshot=self.agent.screenshots)
                    except Exception as exc:
                        if not _is_transient_nav_error(exc):
                            raise
                        _wait_for_ready_state(self.agent.browser, target_url=url, timeout_s=8.0)
                        page = self.agent.browser.observe(screenshot=self.agent.screenshots)
                self.agent.state.update(
                    goal=goal,
                    plan=[goal],
                    plan_index=0,
                    page=page,
                    decision=None,
                    history=[],
                    status="ready",
                    decisions=[],
                    text_calls=[],
                    elapsed_ms=0,
                    started_at=None,
                )
                return {"ok": True, "status": "ready", "page": page_summary(page)}
            except Exception:
                self.close_agent()

        target_url = url or "https://www.google.com"
        init_params = inspect.signature(self._agent_cls.__init__).parameters
        if skip_observe and "observe" in init_params:
            self.agent = self._agent_cls(target_url, goal, background=background, observe=False)
            self._owns_tab = True
            self._pending_nav_url = target_url
            self.agent.state["page"]["url"] = target_url
            self.agent.state["page"]["title"] = ""
        else:
            self._pending_nav_url = None
            self.agent = self._agent_cls(target_url, goal, background=background)
            self._owns_tab = True
        return {
            "ok": True,
            "status": self.agent.state["status"],
            "page": page_summary(self.agent.state["page"]),
        }

    def _predict(self) -> dict[str, Any]:
        agent = self._require_agent()
        agent.command("predict", {})
        decision = agent.state["decision"]
        page = agent.state["page"]
        selected = decision["choice"]
        if selected in {"DONE", "BLOCKED"}:
            kind = selected.lower()
            action_label = selected
            role = None
        else:
            action = next(a for a in page["actions"] if a["id"] == selected)
            kind = action["kind"]
            action_label = action["label"]
            role = action.get("role")
        return {
            "ok": True,
            "status": agent.state["status"],
            "choice": selected,
            "operation": decision["operation"],
            "kind": kind,
            "action_label": action_label,
            "role": role,
            "target": decision.get("target"),
            "confidence": decision["confidence"],
            "fingerprint": page["fingerprint"],
            "history_len": len(agent.state["history"]),
            "decision_count": len(agent.state["decisions"]),
            "page": page_summary(page),
        }

    def _act(self, req: dict[str, Any]) -> dict[str, Any]:
        agent = self._require_agent()
        fingerprint = req.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("act requires a non-empty fingerprint.")
        prev_history_len = len(agent.state["history"])
        try:
            snap = agent.command("act", {"fingerprint": fingerprint})
            executed = len(snap["history"]) > prev_history_len
            return {
                "ok": True,
                "stale": False,
                "executed": executed,
                "status": snap["status"],
                "history_len": len(snap["history"]),
                "decision_count": len(snap["decisions"]),
                "page": page_summary(snap["page"]),
                "last_action": snap["history"][-1] if snap["history"] else None,
            }
        except StalePage:
            executed = len(agent.state["history"]) > prev_history_len
            agent.state["decision"] = None
            agent.state["status"] = "ready"
            agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)
            return {
                "ok": True,
                "stale": True,
                "executed": executed,
                "status": "ready",
                "history_len": len(agent.state["history"]),
                "decision_count": len(agent.state["decisions"]),
                "page": page_summary(agent.state["page"]),
                "last_action": agent.state["history"][-1] if executed else None,
            }
        except ValueError as exc:
            if "Observe and choose before acting" in str(exc):
                executed = len(agent.state["history"]) > prev_history_len
                agent.state["decision"] = None
                agent.state["status"] = "ready"
                agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)
                return {
                    "ok": True,
                    "stale": True,
                    "executed": executed,
                    "status": "ready",
                    "history_len": len(agent.state["history"]),
                    "decision_count": len(agent.state["decisions"]),
                    "page": page_summary(agent.state["page"]),
                    "last_action": agent.state["history"][-1] if executed else None,
                }
            if "Text helper returned no valid field value" in str(exc):
                agent.state["decision"] = None
                agent.state["status"] = "blocked"
                return {
                    "ok": True,
                    "stale": False,
                    "executed": False,
                    "status": "blocked",
                    "history_len": len(agent.state["history"]),
                    "decision_count": len(agent.state["decisions"]),
                    "page": page_summary(agent.state["page"]),
                    "last_action": None,
                }
            raise

    def _cancel(self) -> dict[str, Any]:
        if self.agent is None:
            return {"ok": True, "page": None}
        self.agent.state["decision"] = None
        if self.agent.state.get("status") == "predicted":
            self.agent.state["status"] = "ready"
        return {"ok": True, "page": page_summary(self.agent.state["page"])}

    def _read_page(self) -> dict[str, Any]:
        for attempt in range(2):
            try:
                agent = self._require_agent()
                _wait_for_ready_state(agent.browser, target_url=self._pending_nav_url, timeout_s=10.0)
                self._pending_nav_url = None
                old_fp = agent.state["page"].get("fingerprint")
                try:
                    page = agent.browser.observe(screenshot=False)
                except Exception as exc:
                    if not _is_transient_nav_error(exc):
                        raise
                    _wait_for_ready_state(agent.browser, timeout_s=5.0)
                    page = agent.browser.observe(screenshot=False)
                agent.state["page"] = page
                if page.get("fingerprint") != old_fp and agent.state.get("decision") is not None:
                    agent.state["decision"] = None
                    agent.state["status"] = "ready"
                elements, _, _ = action_space(page.get("actions", []))
                summary = page_summary(page)
                readable = _extract_readable_text(agent.browser)
                if len(readable) >= 60:
                    summary["text"] = readable
                return {
                    "ok": True,
                    "page": summary,
                    "elements": elements[:60],
                    "omitted_elements": max(0, len(elements) - 60),
                }
            except Exception as exc:
                if attempt == 0 and _is_dead_session_error(exc) and self._agent_cls is Agent:
                    self.agent = None
                    self._owns_tab = False
                    if self._try_attach_existing_tab() is not None:
                        continue
                raise
        raise RuntimeError("read_page retry exhausted")

    def _match_click(self, req: dict[str, Any]) -> dict[str, Any]:
        target = str(req.get("target", "")).strip()
        if not target:
            raise ValueError("match_click requires a non-empty target.")
        for attempt in range(2):
            try:
                agent = self._require_agent()
                _wait_for_ready_state(agent.browser, target_url=self._pending_nav_url, timeout_s=10.0)
                self._pending_nav_url = None
                try:
                    page = agent.browser.observe(screenshot=False)
                except Exception as exc:
                    if not _is_transient_nav_error(exc):
                        raise
                    _wait_for_ready_state(agent.browser, timeout_s=5.0)
                    page = agent.browser.observe(screenshot=False)
                agent.state["page"] = page
                agent._observed_at = time.perf_counter()
                matched = _match_clickable_action(page.get("actions", []), target)
                if matched is None:
                    agent.state["decision"] = None
                    if agent.state.get("status") == "predicted":
                        agent.state["status"] = "ready"
                    return {"ok": True, "matched": False, "page": page_summary(page)}
                action, score = matched
                selected = action["id"]
                op = "SELECT" if action["kind"] == "select" else "CLICK"
                # Direct voice clicks are standalone single-step actions; never exhaust the 60-step loop budget.
                agent.state["history"] = []
                agent.state["decisions"] = []
                agent.state["started_at"] = time.perf_counter()
                agent.state["decision"] = {
                    "choice": selected,
                    "operation": op,
                    "target": selected,
                    "confidence": round(score, 3),
                    "probabilities": {selected: 1.0},
                    "latency_ms": 0,
                    "usage": {},
                }
                agent.state["status"] = "predicted"
                return {
                    "ok": True,
                    "matched": True,
                    "choice": selected,
                    "kind": action["kind"],
                    "action_label": action["label"],
                    "fingerprint": page["fingerprint"],
                    "page": page_summary(page),
                }
            except Exception as exc:
                if attempt == 0 and _is_dead_session_error(exc) and self._agent_cls is Agent:
                    self.agent = None
                    self._owns_tab = False
                    if self._try_attach_existing_tab() is not None:
                        continue
                raise
        raise RuntimeError("match_click retry exhausted")

    def _switch_tab(self, agent: Any, action: str) -> dict[str, Any]:
        tabs = _list_page_targets(prefer_real=True)
        if not tabs:
            raise ValueError("No browser tab is open; start a browser task first.")
        cur_id = getattr(agent.browser, "target", None)
        cur_idx = next((i for i, t in enumerate(tabs) if t.get("targetId") == cur_id), 0)
        if action == "switch_tab_next":
            if len(tabs) <= 1:
                return {"ok": True, "action": action, "page": page_summary(agent.state["page"]), "message": "Only one tab is open."}
            chosen = tabs[(cur_idx + 1) % len(tabs)]
        elif action == "switch_tab_prev":
            if len(tabs) <= 1:
                return {"ok": True, "action": action, "page": page_summary(agent.state["page"]), "message": "Only one tab is open."}
            chosen = tabs[(cur_idx - 1) % len(tabs)]
        else:
            query = action.split(":", 1)[1].strip().lower()
            matches = [
                t
                for t in tabs
                if query in f"{t.get('title', '')} {t.get('url', '')}".lower()
            ]
            non_current = [t for t in matches if t.get("targetId") != cur_id]
            chosen = (non_current or matches or [None])[0]
            if chosen is None:
                return {
                    "ok": True,
                    "action": action,
                    "page": page_summary(agent.state["page"]),
                    "message": f"No open tab matched {query}.",
                }
        agent.browser.switch_to_target(chosen["targetId"], activate=not self._default_background)
        href, title = _read_lightweight_meta(agent.browser, str(chosen.get("url") or ""))
        title = title or str(chosen.get("title") or "")
        page = _invalidate_page_cache(agent)
        page["url"] = href
        page["title"] = title
        agent.state["page"] = page
        return {
            "ok": True,
            "action": action,
            "page": page_summary(page),
            "message": f"Switched to {_short_tab_label(href, title)}.",
        }

    def _control(self, req: dict[str, Any]) -> dict[str, Any]:
        action_name = str(req.get("action", "")).strip().lower()
        for attempt in range(2):
            try:
                return self._control_once(req)
            except Exception as exc:
                already_closed = (
                    action_name == "close_tab"
                    and self.agent is not None
                    and getattr(self.agent.browser, "target", None) is None
                )
                if attempt == 0 and not already_closed and _is_dead_session_error(exc) and self._agent_cls is Agent:
                    self.agent = None
                    self._owns_tab = False
                    if self._try_attach_existing_tab() is not None:
                        continue
                if attempt == 0 and not already_closed and _is_transient_nav_error(exc) and self.agent is not None:
                    _wait_for_ready_state(self.agent.browser, timeout_s=5.0)
                    continue
                raise
        raise RuntimeError("Control retry exhausted")

    def _control_once(self, req: dict[str, Any]) -> dict[str, Any]:
        agent = self._require_agent()
        action = str(req.get("action", "")).strip().lower()
        if action == "close_tab":
            if self._agent_cls is Agent and getattr(agent.browser, "target", None):
                old_target = agent.browser.target
                all_tabs = _list_page_targets(prefer_real=False)
                other_tabs = [t for t in all_tabs if t.get("targetId") != old_target]
                if not other_tabs:
                    # Never close the last Chrome tab (that exits Chrome and drops remote debugging).
                    agent.browser.call("Page.navigate", url="https://www.google.com", _response_timeout=20.0)
                    _reset_browser_media_state(agent.browser)
                    self._pending_nav_url = "https://www.google.com"
                    page = _invalidate_page_cache(agent)
                    page["url"] = "https://www.google.com"
                    page["title"] = "Google"
                    agent.state["page"] = page
                    return {
                        "ok": True,
                        "action": action,
                        "closed": True,
                        "page": page_summary(page),
                        "message": "Closed the page and kept Chrome open.",
                    }
                try:
                    cdp("Target.closeTarget", targetId=old_target)
                except Exception:
                    pass
                agent.browser.target = None
                real_remaining = [t for t in other_tabs if str(t.get("url") or "") not in {"", "about:blank"}]
                fallback_remaining = [t for t in other_tabs if t not in real_remaining]
                candidates = list(reversed(real_remaining)) + list(reversed(fallback_remaining))
                switched_tab: dict[str, Any] | None = None
                for cand in candidates:
                    try:
                        agent.browser.switch_to_target(cand["targetId"], activate=not self._default_background)
                        switched_tab = cand
                        break
                    except Exception:
                        continue
                if switched_tab is None:
                    _detach_browser_session(agent)
                    self.agent = None
                    self._owns_tab = False
                    return {"ok": True, "action": action, "closed": True, "message": "Closed the tab."}
                href, title = _read_lightweight_meta(agent.browser, str(switched_tab.get("url") or ""))
                title = title or str(switched_tab.get("title") or "")
                page = _invalidate_page_cache(agent)
                page["url"] = href
                page["title"] = title
                agent.state["page"] = page
                return {
                    "ok": True,
                    "action": action,
                    "closed": True,
                    "page": page_summary(page),
                    "message": f"Closed the tab. Now on {_short_tab_label(href, title)}.",
                }
            self.close_agent()
            return {"ok": True, "action": action, "closed": True}
        if action == "list_tabs":
            if self._agent_cls is Agent:
                tabs = _list_page_targets(prefer_real=False)
                labels = [_short_tab_label(str(t.get("url") or ""), str(t.get("title") or "")) for t in tabs]
            else:
                pg = agent.state.get("page") or {}
                labels = [_short_tab_label(str(pg.get("url") or ""), str(pg.get("title") or ""))]
            n = len(labels)
            if n == 0:
                msg = "No tabs are open."
            elif n == 1:
                msg = f"1 tab open: {labels[0]}."
            else:
                shown = labels[:4]
                joined = ", ".join(shown[:-1]) + f", and {shown[-1]}"
                extra = f", plus {n - 4} more" if n > 4 else ""
                msg = f"{n} tabs open: {joined}{extra}."
            return {"ok": True, "action": action, "page": page_summary(agent.state["page"]), "message": msg}
        if action == "close_dialog":
            _close_dialog(agent.browser)
            page = _invalidate_page_cache(agent)
            return {"ok": True, "action": action, "page": page_summary(page)}
        if action in {"switch_tab_next", "switch_tab_prev"} or action.startswith("switch_tab:"):
            return self._switch_tab(agent, action)
        if action == "back":
            agent.browser.evaluate("history.back()")
            _reset_browser_media_state(agent.browser)
            time.sleep(0.25)
            _wait_for_ready_state(agent.browser, timeout_s=5.0)
        elif action == "forward":
            agent.browser.evaluate("history.forward()")
            _reset_browser_media_state(agent.browser)
            time.sleep(0.25)
            _wait_for_ready_state(agent.browser, timeout_s=5.0)
        elif action == "reload":
            agent.browser.call("Page.reload", _response_timeout=20.0)
            _reset_browser_media_state(agent.browser)
            _wait_for_ready_state(agent.browser, timeout_s=15.0)
        elif action in {"scroll_down", "scroll_up", "scroll_top", "scroll_bottom"}:
            _fast_scroll(agent.browser, action)
            page = _invalidate_page_cache(agent)
            return {"ok": True, "action": action, "page": page_summary(page)}
        elif action in {"zoom_in", "zoom_out", "zoom_reset"}:
            msg = _adjust_zoom(agent.browser, action)
            page = _invalidate_page_cache(agent)
            return {"ok": True, "action": action, "page": page_summary(page), "message": msg}
        elif action in _KEY_SPECS:
            _dispatch_key(agent.browser, action)
            page = _invalidate_page_cache(agent)
            return {"ok": True, "action": action, "page": page_summary(page)}
        elif (media := _parse_media_action(action)) is not None:
            op, val = media
            res = _run_media_control(agent.browser, op, val)
            msg: str | None = None
            if not res.get("ok", True):
                print(f"jev_bridge: media control {action} -> {res}", file=sys.stderr, flush=True)
                reason = res.get("reason")
                if reason == "no_skip_button":
                    msg = "No skip button found."
                elif reason == "no_video":
                    msg = "No media found on this page."
                elif reason == "control_not_found":
                    msg = "That control isn't on this page."
            elif op in {"speed_set", "speed_up", "speed_down"} and "speed" in res:
                msg = f"Speed {float(res['speed']):g}x."
            page = _invalidate_page_cache(agent)
            out: dict[str, Any] = {"ok": True, "action": action, "page": page_summary(page)}
            if msg:
                out["message"] = msg
            return out
        else:
            raise ValueError(f"Unsupported browser control action: {action!r}")

        try:
            page = agent.browser.observe(screenshot=False)
        except Exception as exc:
            if not _is_transient_nav_error(exc):
                raise
            _wait_for_ready_state(agent.browser, timeout_s=5.0)
            page = agent.browser.observe(screenshot=False)
        agent.state["page"] = page
        agent.state["decision"] = None
        if agent.state.get("status") == "predicted":
            agent.state["status"] = "ready"
        return {"ok": True, "action": action, "page": page_summary(page)}


def serve_stdio(stdin: TextIO, stdout: TextIO, *, default_background: bool = False) -> None:
    session = BridgeSession(default_background=default_background)
    try:
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            req_id: Any = None
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("Request must be a JSON object")
                req_id = req.get("id")
                resp, should_exit = session.handle(req)
            except Exception as exc:
                resp = {"ok": False, "code": "invalid_json", "error": str(exc)}
                should_exit = False
            resp["id"] = req_id
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
            if should_exit:
                break
    finally:
        session.close_agent()


def main() -> None:
    real_stdout = sys.stdout
    # Keep library prints off stdout so the JSON-lines stream stays uncorrupted.
    sys.stdout = sys.stderr
    background = os.environ.get("JARVIS_BROWSER_BACKGROUND", "0") == "1"
    serve_stdio(sys.stdin, real_stdout, default_background=background)


if __name__ == "__main__":
    main()
