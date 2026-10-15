from PIL import ImageDraw
import base64
import io
import json
import re
from pathlib import Path

import pyautogui
import requests

import model_config

import window_manager
from execution_context import ExecutionContext

SUPPORTED_ACTIONS = {
    "open_app_search",
    "open_url",
    "search_web",
    "type",
    "press_key",
    "hotkey",
    "key_sequence",
    "move_mouse",
    "click",
    "click_text",
    "right_click",
    "double_click",
    "drag_to",
    "scroll",
    "focus_window",
    "list_windows",
    "read_screen",
    "find_text",
    "click_image",
    "screenshot",
    "wait",
    "copy",
    "paste",
    "select_all",
}

import traceback

def _extract_json_object(text: str) -> dict:
    if not text or not isinstance(text, str):
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def validate_action_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise ValueError(f"Action plan must be a dict, got {type(plan).__name__}")

    raw_actions = plan.get("actions", [])
    if not isinstance(raw_actions, list):
        raise ValueError("Action plan 'actions' must be a list.")

    valid_actions = []
    for action in raw_actions:
        # Protect against models returning strings instead of dicts: ["click here", "type text"]
        if not isinstance(action, dict):
            continue
        act_name = action.get("action")
        if act_name in SUPPORTED_ACTIONS:
            valid_actions.append(action)

    return {
        "plan": plan.get("plan", ""),
        "actions": valid_actions
    }

def requested_browser(task: str) -> str | None:
    task_lower = task.lower()
    for browser, aliases in window_manager.BROWSER_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", task_lower) for alias in aliases):
            return browser
    return None

def build_prompt(task: str, system_prompt: str, context: ExecutionContext | None = None) -> str:
    details = []
    if context is not None:
        details.append(f"Current user home directory: {Path.home()}")
        details.append(f"Currently tracked app window: {context.active_app_window_title or 'none'}")
    details_text = "\n".join(details)
    return f"{system_prompt}\n\nTask: {task}\n\n{details_text}"

def get_action_plan(task: str, context: ExecutionContext | None = None, model_name: str | None = None):
    # The strict system prompt that enforces JSON structure for all models
    system_prompt = (
        "You are an autonomous visual desktop agent. Return ONLY valid JSON. "
        "Structure exactly like this:\n"
        "{\n"
        "  \"plan\": \"Short summary of actions\",\n"
        "  \"actions\": [\n"
        "    {\"action\": \"open_app_search\", \"app\": \"chrome\"},\n"
        "    {\"action\": \"wait\", \"seconds\": 2},\n"
        "    {\"action\": \"type\", \"text\": \"https://github.com\"},\n"
        "    {\"action\": \"press_key\", \"key\": \"enter\"}\n"
        "  ]\n"
        "}\n"
        "Allowed actions: 'open_app_search' (requires 'app'), 'type' (requires 'text'), "
        "'press_key' (requires 'key'), 'hotkey' (requires 'keys' array), 'click' (requires 'x', 'y' estimated from the red 100px grid), "
        "and 'wait' (requires 'seconds').\n"
        "Keep actions grounded in the current screen. Output ONLY pure JSON, no conversational text."
    )
    prompt = build_prompt(task, system_prompt, context)
    
    image_base64 = None
    if model_name == "llava":
        try:
            screenshot = pyautogui.screenshot()
            draw = ImageDraw.Draw(screenshot)
            width, height = screenshot.size
            for x in range(0, width, 100):
                draw.line([(x, 0), (x, height)], fill=(255, 0, 0), width=1)
                draw.rectangle([(x, 0), (x + 30, 12)], fill="black")
                draw.text((x + 2, 0), str(x), fill="white")
            for y in range(0, height, 100):
                draw.line([(0, y), (width, y)], fill=(255, 0, 0), width=1)
                draw.rectangle([(0, y), (30, y + 12)], fill="black")
                draw.text((2, y), str(y), fill="white")

            img_byte_arr = io.BytesIO()
            screenshot.save(img_byte_arr, format='PNG')
            image_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        except Exception as e:
            print(f" -> Warning: Failed to capture screen for planner: {e}")

    config = model_config.get_active_model_config()
    
    # Safely extract and format the base URL to prevent missing schema errors
    raw_endpoint = getattr(config, "base_url", None)
    if not raw_endpoint:
        raw_endpoint = "http://localhost:11434"
    endpoint = raw_endpoint.rstrip("/")
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
        
    target_model = model_name or getattr(config, "model", "llava")

    payload = {
        "model": target_model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0
        }
    }

    if image_base64 and target_model == "llava":
        payload["images"] = [image_base64]

    url = f"{endpoint}/api/generate"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        raw_json = response.json()
        response_text = raw_json.get("response", "")
        plan_json = _extract_json_object(response_text)
        if not plan_json:
            return {"plan": task, "actions": []}
        try:
            return validate_action_plan(plan_json)
        except ValueError as e:
            print(f" -> Plan validation failed: {e}")
            return {"plan": task, "actions": []}
    except Exception as exc:
        print(f" -> Planner error: {exc}")
        import traceback
        traceback.print_exc()
        return {"plan": task, "actions": []}