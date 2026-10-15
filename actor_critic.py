from __future__ import annotations

import hashlib
import time
from typing import Any

import pyautogui

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover
    gw = None


def capture_screen_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "hash": "",
        "active_title": "",
        "ocr_text": "",
    }
    try:
        screenshot = pyautogui.screenshot()
        state["hash"] = hashlib.sha256(screenshot.tobytes()).hexdigest()
    except Exception:
        state["hash"] = "unavailable"

    try:
        if gw is not None:
            active = gw.getActiveWindow()
            if active is not None:
                state["active_title"] = getattr(active, "title", "") or ""
    except Exception:
        state["active_title"] = ""

    try:
        import pytesseract
        from PIL import Image

        if pytesseract is not None and Image is not None:
            state["ocr_text"] = pytesseract.image_to_string(pyautogui.screenshot()).strip()
    except Exception:
        state["ocr_text"] = ""

    return state


def evaluate_action_effect(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"stalled": False, "reason": "No verification state"}

    before_hash = str(before.get("hash", ""))
    after_hash = str(after.get("hash", ""))
    before_title = str(before.get("active_title", "")).strip().lower()
    after_title = str(after.get("active_title", "")).strip().lower()
    before_text = str(before.get("ocr_text", "")).strip().lower()
    after_text = str(after.get("ocr_text", "")).strip().lower()

    same_hash = before_hash and before_hash == after_hash
    same_window = before_title == after_title
    same_text = before_text == after_text

    if same_hash and same_window and same_text:
        return {"stalled": True, "reason": "Action Stalling Error"}

    return {"stalled": False, "reason": "Verified"}


def verify_action_result(step: dict[str, Any], action_callback):
    action = str(step.get("action", "")).strip()
    if not action:
        return False

    if action not in {
        "click_text",
        "click",
        "double_click",
        "press_key",
        "hotkey",
        "type",
        "key_sequence",
        "open_app_search",
        "focus_window",
        "run_command",
        "click_image",
        "open_url",
        "search_web",
    }:
        return action_callback()

    before = capture_screen_state()
    result = action_callback()
    if not result:
        return False

    time.sleep(0.5)
    after = capture_screen_state()
    verdict = evaluate_action_effect(before, after)
    if verdict["stalled"]:
        print(f"[Verification] {verdict['reason']}: the action produced no visible change.")
        return False
    return True
