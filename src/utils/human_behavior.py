"""
Human behavior & Computer Use Visual Cursor Engine for AutoBot.

Educational Concept:
Autonomous browser agents operate in visible graphical environments where human observers
must follow step-by-step actions (as seen in Gemini Browser and Computer Use systems):
1. Visual Cursor Overlay:
   Injects an on-screen SVG mouse pointer and live action status badge into the webpage DOM
   using zero-dependency CSS and DOM manipulation.
2. Natural Trajectory Motion:
   Employs Bezier curve path interpolation with ease-in-out acceleration/deceleration,
   simulating human motor movement rather than instant robotic teleports.
3. Tactile Visual Feedback:
   Highlights targeted elements with glowing focus rings and produces expanding ripple
   animations upon click down/up events.
4. Humanized Cadence:
   Randomizes inter-keystroke intervals (40-120ms) and cognitive micro-pauses between navigation steps.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Any, Dict, Optional, Tuple, Union

from playwright.async_api import ElementHandle, Page


CURSOR_OVERLAY_SCRIPT = """
(() => {
  if (window.__geminiCursorInjected) return;
  window.__geminiCursorInjected = true;

  function initCursor() {
    if (document.getElementById("gemini-cursor-container")) return;

    let initX = 220;
    let initY = 160;
    try {
      const saved = sessionStorage.getItem("__geminiLastPos");
      if (saved) {
        const p = JSON.parse(saved);
        if (typeof p.x === "number" && typeof p.y === "number") {
          initX = p.x;
          initY = p.y;
        }
      }
    } catch (e) {}

    const container = document.createElement("div");
    container.id = "gemini-cursor-container";
    container.style.cssText = [
      "position: fixed !important",
      "top: 0 !important",
      "left: 0 !important",
      "width: 100vw !important",
      "height: 100vh !important",
      "pointer-events: none !important",
      "z-index: 2147483647 !important",
      "overflow: hidden !important",
      "margin: 0 !important",
      "padding: 0 !important"
    ].join("; ");

    container.innerHTML = `
      <div id="gemini-cursor-pointer" style="position: absolute !important; top: 0 !important; left: 0 !important; transform: translate3d(${initX}px, ${initY}px, 0) !important; pointer-events: none !important; display: flex !important; align-items: flex-start !important; gap: 8px !important; will-change: transform !important; z-index: 2147483647 !important;">
        <div id="gemini-cursor-icon" style="filter: drop-shadow(0 3px 6px rgba(0,0,0,0.45)) !important; transition: transform 0.1s ease !important;">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="geminiAgentGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#38BDF8"/>
                <stop offset="50%" stop-color="#2563EB"/>
                <stop offset="100%" stop-color="#4F46E5"/>
              </linearGradient>
            </defs>
            <path d="M4 2L24 12.5L14 15L18.5 24.5L14.5 26.5L10 17L4 21.5V2Z" fill="url(#geminiAgentGrad)" stroke="#FFFFFF" stroke-width="1.8" stroke-linejoin="round"/>
          </svg>
        </div>
        <div id="gemini-cursor-badge" style="display: none !important; background: rgba(15, 23, 42, 0.94) !important; color: #F8FAFC !important; backdrop-filter: blur(8px) !important; -webkit-backdrop-filter: blur(8px) !important; border: 1px solid rgba(56, 189, 248, 0.5) !important; border-radius: 9999px !important; padding: 3px 10px !important; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important; font-size: 11px !important; font-weight: 600 !important; letter-spacing: 0.3px !important; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35) !important; white-space: nowrap !important; margin-top: 14px !important; pointer-events: none !important;">
          <span style="color: #38BDF8 !important; margin-right: 4px !important;">✦</span>
          <span id="gemini-cursor-badge-text">AutoBot Agent</span>
        </div>
      </div>
      <div id="gemini-cursor-ripple" style="position: absolute !important; top: 0 !important; left: 0 !important; width: 36px !important; height: 36px !important; border-radius: 50% !important; border: 2.5px solid #38BDF8 !important; background: rgba(56, 189, 248, 0.25) !important; pointer-events: none !important; transform: translate3d(-100px, -100px, 0) scale(0) !important; opacity: 0 !important; z-index: 2147483646 !important;"></div>
      <div id="gemini-cursor-highlight" style="position: absolute !important; pointer-events: none !important; border: 2px solid #38BDF8 !important; background: rgba(56, 189, 248, 0.1) !important; border-radius: 6px !important; display: none !important; box-shadow: 0 0 14px rgba(56, 189, 248, 0.4) !important; transition: all 0.15s ease-out !important; z-index: 2147483645 !important;"></div>
    `;

    try {
      (document.body || document.documentElement).appendChild(container);
    } catch (e) {
      document.documentElement.appendChild(container);
    }

    window.__geminiUpdateCursor = (x, y, text) => {
      const ptr = document.getElementById("gemini-cursor-pointer");
      const badge = document.getElementById("gemini-cursor-badge");
      const badgeText = document.getElementById("gemini-cursor-badge-text");

      const clampedX = Math.max(0, Math.min(window.innerWidth - 8, x));
      const clampedY = Math.max(0, Math.min(window.innerHeight - 8, y));

      try {
        sessionStorage.setItem("__geminiLastPos", JSON.stringify({x: clampedX, y: clampedY}));
      } catch (e) {}

      if (ptr) {
        ptr.style.transform = `translate3d(${clampedX}px, ${clampedY}px, 0)`;
      }
      if (badge && badgeText) {
        if (text && text.trim().length > 0) {
          badgeText.textContent = text;
          badge.style.display = "inline-flex";
        } else {
          badge.style.display = "none";
        }
      }
    };

    window.__geminiClickAnimation = (x, y) => {
      const rip = document.getElementById("gemini-cursor-ripple");
      const icon = document.getElementById("gemini-cursor-icon");

      if (icon) {
        icon.style.transform = "scale(0.85)";
        setTimeout(() => { if (icon) icon.style.transform = "scale(1)"; }, 120);
      }
      if (rip) {
        rip.style.transition = "none";
        rip.style.transform = `translate3d(${x - 18}px, ${y - 18}px, 0) scale(0.2)`;
        rip.style.opacity = "1";
        void rip.offsetWidth;
        rip.style.transition = "transform 0.4s ease-out, opacity 0.4s ease-out";
        rip.style.transform = `translate3d(${x - 18}px, ${y - 18}px, 0) scale(1.8)`;
        rip.style.opacity = "0";
      }
    };

    window.__geminiHighlight = (rect) => {
      const hl = document.getElementById("gemini-cursor-highlight");
      if (hl && rect) {
        hl.style.left = `${Math.max(0, rect.x - 3)}px`;
        hl.style.top = `${Math.max(0, rect.y - 3)}px`;
        hl.style.width = `${rect.width + 6}px`;
        hl.style.height = `${rect.height + 6}px`;
        hl.style.display = "block";
      }
    };

    window.__geminiClearHighlight = () => {
      const hl = document.getElementById("gemini-cursor-highlight");
      if (hl) hl.style.display = "none";
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCursor);
  } else {
    initCursor();
  }
})();
"""


# Page ID to last cursor position tracking
_LAST_CURSOR_POS: Dict[int, Tuple[float, float]] = {}


async def human_delay(min_ms: float = 500, max_ms: float = 2000) -> None:
    """Randomized human delay interval."""
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def ensure_visual_cursor(page: Any) -> None:
    """Ensure visual cursor overlay is injected ONLY if explicitly requested (disabled by default to prevent anti-bot detection)."""
    import os
    if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") != "1":
        return
    try:
        if hasattr(page, "evaluate"):
            await page.evaluate(CURSOR_OVERLAY_SCRIPT)
    except Exception:
        pass


async def update_visual_cursor(
    page: Any,
    x: Optional[float] = None,
    y: Optional[float] = None,
    action_text: Optional[str] = None,
) -> None:
    """Update on-screen visual cursor position and status badge if visual overlay is enabled."""
    import os
    if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") != "1":
        return
    try:
        page_id = id(page)
        curr_x, curr_y = _LAST_CURSOR_POS.get(page_id, (200.0, 150.0))

        if x is not None:
            curr_x = float(x)
        if y is not None:
            curr_y = float(y)

        _LAST_CURSOR_POS[page_id] = (curr_x, curr_y)

        if hasattr(page, "evaluate"):
            await page.evaluate(
                "([x, y, text]) => { if (window.__geminiUpdateCursor) window.__geminiUpdateCursor(x, y, text); }",
                [curr_x, curr_y, action_text],
            )
    except Exception:
        pass


async def smooth_move_cursor(
    page: Any,
    target_x: float,
    target_y: float,
    steps: Optional[int] = None,
    action_text: Optional[str] = None,
) -> None:
    """
    Smoothly move mouse pointer to target coordinates using Bezier curve easing.
    """
    page_id = id(page)
    x0, y0 = _LAST_CURSOR_POS.get(page_id, (200.0, 150.0))
    x1, y1 = float(target_x), float(target_y)

    dist = math.hypot(x1 - x0, y1 - y0)
    if steps is None:
        steps = max(6, min(22, int(dist / 30)))

    # Curvature control point with natural jitter
    cx = (x0 + x1) / 2.0 + random.uniform(-25.0, 25.0)
    cy = (y0 + y1) / 2.0 + random.uniform(-25.0, 25.0)

    try:
        await ensure_visual_cursor(page)
        for i in range(1, steps + 1):
            t = i / float(steps)
            # Cubic ease-in-out
            u = 4.0 * t * t * t if t < 0.5 else 1.0 - math.pow(-2.0 * t + 2.0, 3) / 2.0

            xi = (1.0 - u) ** 2 * x0 + 2.0 * (1.0 - u) * u * cx + u ** 2 * x1
            yi = (1.0 - u) ** 2 * y0 + 2.0 * (1.0 - u) * u * cy + u ** 2 * y1

            if hasattr(page, "mouse") and hasattr(page.mouse, "move"):
                await page.mouse.move(xi, yi)

            import os
            if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") == "1" and hasattr(page, "evaluate"):
                await page.evaluate(
                    "([x, y, text]) => { if (window.__geminiUpdateCursor) window.__geminiUpdateCursor(x, y, text); }",
                    [xi, yi, action_text],
                )

            await asyncio.sleep(0.012)
    except Exception:
        pass

    _LAST_CURSOR_POS[page_id] = (x1, y1)


async def visual_click(
    page: Any,
    element_or_selector: Union[ElementHandle, str, Any],
    action_text: Optional[str] = None,
    delay_after: float = 0.35,
) -> bool:
    """
    Glides on-screen cursor to element, displays action badge, pulses target highlight,
    triggers visual ripple, and clicks the element.
    """
    await ensure_visual_cursor(page)
    try:
        if hasattr(page, "evaluate"):
            await page.evaluate("() => ({ scrollX: window.scrollX || 0, scrollY: window.scrollY || 0 })")
    except Exception:
        pass

    element = None
    if isinstance(element_or_selector, str):
        try:
            if hasattr(page, "wait_for_selector"):
                element = await page.wait_for_selector(element_or_selector, state="visible", timeout=2500)
            elif hasattr(page, "query_selector"):
                element = await page.query_selector(element_or_selector)
        except Exception:
            try:
                if hasattr(page, "query_selector"):
                    element = await page.query_selector(element_or_selector)
            except Exception:
                element = None
    else:
        element = element_or_selector

    if element is None:
        if isinstance(element_or_selector, str) and hasattr(page, "click"):
            try:
                await page.click(element_or_selector)
                return True
            except Exception:
                return False
        return False

    box = None
    try:
        if hasattr(element, "scroll_into_view_if_needed"):
            await element.scroll_into_view_if_needed(timeout=3000)

        if hasattr(element, "bounding_box"):
            b = await element.bounding_box()
            if isinstance(b, dict) and "x" in b and "y" in b:
                box = b
    except Exception:
        box = None

    if box and isinstance(box, dict):
        tx = box["x"] + box["width"] / 2.0 + random.uniform(-2.0, 2.0)
        ty = box["y"] + box["height"] / 2.0 + random.uniform(-2.0, 2.0)

        # Highlight element with glowing focus ring if overlay enabled
        try:
            import os
            if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") == "1" and hasattr(page, "evaluate"):
                await page.evaluate(
                    "([rect]) => { if (window.__geminiHighlight) window.__geminiHighlight(rect); }",
                    [{"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]}],
                )
        except Exception:
            pass

        # Smooth glide cursor to target
        await smooth_move_cursor(page, tx, ty, action_text=action_text or "Clicking element...")
        await asyncio.sleep(random.uniform(0.10, 0.20))

        # Ripple pulse animation if overlay enabled
        try:
            import os
            if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") == "1" and hasattr(page, "evaluate"):
                await page.evaluate(
                    "([x, y]) => { if (window.__geminiClickAnimation) window.__geminiClickAnimation(x, y); }",
                    [tx, ty],
                )
        except Exception:
            pass

        # Perform actual click
        try:
            await element.click()
        except Exception as e:
            err_msg = str(e).lower()
            if "intercept" in err_msg or "timeout" in err_msg or "pointer" in err_msg:
                try:
                    from src.browser.popup_handler import dismiss_sign_in_popup
                    await dismiss_sign_in_popup(page, use_visual_cursor=False)
                    await asyncio.sleep(0.2)
                    await element.click(force=True)
                except Exception:
                    try:
                        if hasattr(element, "evaluate"):
                            await element.evaluate("el => el.click()")
                    except Exception:
                        pass
            else:
                try:
                    if hasattr(page, "mouse") and hasattr(page.mouse, "click"):
                        await page.mouse.click(tx, ty)
                except Exception:
                    pass

        # Clear highlight if overlay enabled
        try:
            import os
            if os.environ.get("AUTOBOT_VISUAL_CURSOR_OVERLAY") == "1" and hasattr(page, "evaluate"):
                await page.evaluate("() => { if (window.__geminiClearHighlight) window.__geminiClearHighlight(); }")
        except Exception:
            pass

        await asyncio.sleep(delay_after)
        return True

    # Fallback when bounding box is unavailable (or mock object in tests)
    try:
        await element.click()
        return True
    except Exception:
        return False


async def visual_type(
    page: Any,
    element_or_selector: Union[ElementHandle, str, Any],
    text: str,
    action_text: Optional[str] = None,
    clear_first: bool = True,
    is_password: bool = False,
) -> None:
    """
    Glides cursor to input field, focuses it, displays live action badge,
    clears existing content if needed, and types characters with realistic human cadence.
    """
    await ensure_visual_cursor(page)

    # Determine safe action label (mask passwords in visual badge)
    if is_password or (action_text and "password" in action_text.lower()):
        action_label = action_text or "Entering password: ••••••••"
    else:
        preview = text[:20] + "..." if len(text) > 20 else text
        action_label = action_text or f"Typing: {preview}"

    await visual_click(page, element_or_selector, action_text=action_label, delay_after=0.15)

    try:
        await update_visual_cursor(page, action_text=action_label)
    except Exception:
        pass

    # Clear pre-filled input text if requested
    if clear_first:
        try:
            if hasattr(page, "keyboard") and hasattr(page.keyboard, "press"):
                await page.keyboard.press("Control+A")
                await asyncio.sleep(0.05)
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.05)
        except Exception:
            pass

    # Realistic typing cadence
    try:
        for char in text:
            if hasattr(page, "keyboard") and hasattr(page.keyboard, "type"):
                await page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.035, 0.095))
    except Exception:
        pass

    await asyncio.sleep(random.uniform(0.12, 0.25))
    try:
        await update_visual_cursor(page, action_text=None)
    except Exception:
        pass


async def visual_scroll(
    page: Any,
    distance: int = 400,
    direction: str = "down",
    target_element_or_selector: Optional[Union[ElementHandle, str, Any]] = None,
    action_text: Optional[str] = None,
) -> None:
    """
    Positions visual cursor over target content area and smoothly scrolls using mouse wheel.
    """
    await ensure_visual_cursor(page)

    action_label = action_text or ("Scanning page content..." if direction == "down" else "Scrolling...")
    try:
        await update_visual_cursor(page, action_text=action_label)
    except Exception:
        pass

    # If target element is given, move cursor over it first
    if target_element_or_selector:
        try:
            elem = None
            if isinstance(target_element_or_selector, str):
                if hasattr(page, "query_selector"):
                    elem = await page.query_selector(target_element_or_selector)
            else:
                elem = target_element_or_selector

            if elem and hasattr(elem, "bounding_box"):
                box = await elem.bounding_box()
                if box and isinstance(box, dict):
                    cx = box["x"] + box["width"] / 2.0
                    cy = box["y"] + min(box["height"] / 2.0, 150.0)
                    await smooth_move_cursor(page, cx, cy, action_text=action_label)
        except Exception:
            pass

    dy = distance if direction == "down" else -distance
    steps = max(2, abs(dy) // 150)
    step_dy = dy // steps

    try:
        for _ in range(steps):
            if hasattr(page, "mouse") and hasattr(page.mouse, "wheel"):
                await page.mouse.wheel(0, step_dy)
            elif hasattr(page, "evaluate"):
                await page.evaluate(f"window.scrollBy({{top: {step_dy}, behavior: 'smooth'}})")
            await human_delay(150, 300)
    except Exception:
        pass

    try:
        await update_visual_cursor(page, action_text=None)
    except Exception:
        pass


async def slow_type(page: Any, selector: str, text: str) -> None:
    """
    Humanized typing wrapper maintaining backward compatibility.
    """
    await visual_type(page, selector, text)


async def random_scroll(page: Any, times: int = 2) -> None:
    """
    Randomized mouse wheel scroll with visual cursor presence.
    """
    for _ in range(times):
        dy = random.randint(300, 500)
        await visual_scroll(page, distance=dy, direction="down", action_text="Reading content...")
        await human_delay(250, 500)
