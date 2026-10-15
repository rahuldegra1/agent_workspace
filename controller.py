import argparse
import ctypes
import hashlib
import platform
import re
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import pyautogui
import requests

try:
    import pyperclip
except ImportError:
    pyperclip = None

import actor_critic
import agent_orchestrator
import app_launcher
import app_planner
import emergency_stop
import model_config
import privacy_security
import ui_automation
import window_manager
from execution_context import ExecutionContext
import router_agent
import model_manager

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

if pytesseract is not None and platform.system() == "Windows":
    system_tesseract = shutil.which("tesseract")
    if system_tesseract:
        pytesseract.pytesseract.tesseract_cmd = system_tesseract

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

def enable_windows_dpi_awareness():
    if platform.system() != "Windows":
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        return False

def copy_to_clipboard(text: str) -> bool:
    payload = str(text or "")
    if pyperclip is not None:
        try:
            pyperclip.copy(payload)
            return True
        except Exception:
            pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(payload)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False

def paste_from_clipboard() -> bool:
    try:
        window_manager.platform_hotkey("ctrl", "v")
        return True
    except Exception:
        return False

def type_text_with_clipboard(text: str) -> bool:
    if not text:
        return False
    if copy_to_clipboard(text):
        try:
            return paste_from_clipboard()
        except Exception:
            pass
    pyautogui.write(text, interval=0.02)
    return True

def perceptual_difference(before, after):
    if before is None or after is None:
        return 1.0
    try:
        before_gray = before.convert("L").resize((64, 64))
        after_gray = after.convert("L").resize((64, 64))
        before_pixels = list(before_gray.getdata())
        after_pixels = list(after_gray.getdata())
        diff = sum(abs(l - r) for l, r in zip(before_pixels, after_pixels))
        return diff / (len(before_pixels) * 255)
    except Exception:
        return 1.0

def verify_scroll_movement(by_amount: int = 0):
    if int(by_amount) == 0:
        return False
    before = pyautogui.screenshot()
    pyautogui.scroll(int(by_amount))
    time.sleep(0.2)
    after = pyautogui.screenshot()
    if perceptual_difference(before, after) <= 0.001:
        return False
    return True

enable_windows_dpi_awareness()

APP_FOCUS_ACTIONS = {
    "type", "press_key", "hotkey", "key_sequence", "move_mouse", "click",
    "click_text", "right_click", "double_click", "drag_to", "scroll",
    "click_image", "read_screen", "find_text", "copy", "paste", "select_all",
}

def is_browser_app(app_name: str) -> bool:
    normalized = app_name.lower()
    return any(b in normalized for b in ["chrome", "brave", "firefox", "browser"])

def execute_action(step: dict):
    action = step.get("action")
    if action is None:
        return False

    try:
        if action in APP_FOCUS_ACTIONS or (action in {"open_url", "search_web"} and step.get("browser")):
            if not window_manager.focus_active_app_window():
                return False

        if action == "open_app_search":
            app_name = str(step.get("app", "")).strip()
            if not app_name:
                return False
            try:
                existing_window = window_manager.find_app_window(app_name)
            except Exception:
                existing_window = None

            if existing_window:
                existing_window.activate()
                window_manager.ACTIVE_APP_WINDOW = existing_window
                window_manager.ACTIVE_APP_CONTEXT_REQUIRED = True
                return True

            app_launcher.launch_app(
                app_name,
                find_desktop_shortcut_fn=app_launcher.find_desktop_shortcut,
                launch_from_desktop_fn=app_launcher.launch_from_desktop,
                show_desktop_fn=lambda: app_launcher.show_desktop(platform_hotkey_fn=window_manager.platform_hotkey)
            )
            window_manager.wait_for_app_window(app_name)

        elif action == "search_web":
            query = str(step.get("query", "")).strip()
            url = "https://www.google.com/search?q=" + quote_plus(query)
            if window_manager.ACTIVE_APP_WINDOW and is_browser_app(window_manager.ACTIVE_APP_WINDOW.title):
                window_manager.platform_hotkey("ctrl", "l")
                pyautogui.write(url, interval=0.01)
                pyautogui.press("enter")
            else:
                webbrowser.open(url)
            time.sleep(1.5)
            window_manager.remember_active_app_window()

        elif action == "open_url":
            url = str(step.get("url", "")).strip()
            if window_manager.ACTIVE_APP_WINDOW and is_browser_app(window_manager.ACTIVE_APP_WINDOW.title):
                window_manager.platform_hotkey("ctrl", "l")
                pyautogui.write(url, interval=0.01)
                pyautogui.press("enter")
            else:
                webbrowser.open(url)
            time.sleep(1.5)
            window_manager.remember_active_app_window()

        elif action == "type":
            text = str(step.get("text", ""))
            return actor_critic.verify_action_result(step, lambda: type_text_with_clipboard(text))

        elif action == "press_key":
            pyautogui.press(step.get("key"))

        elif action == "hotkey":
            window_manager.platform_hotkey(*step.get("keys", []))

        elif action == "key_sequence":
            for key in step.get("keys", []):
                pyautogui.press(key)
                time.sleep(0.05)

        elif action == "move_mouse":
            pyautogui.moveTo(int(step.get("x", 0)), int(step.get("y", 0)), duration=0.3)

        elif action == "click":
            x, y, button = step.get("x"), step.get("y"), step.get("button", "left")
            def _run_click():
                if x is not None and y is not None:
                    pyautogui.click(x=int(x), y=int(y), button=str(button))
                else:
                    pyautogui.click(button=str(button))
                return True
            return actor_critic.verify_action_result(step, _run_click)

        elif action == "right_click":
            x, y = step.get("x"), step.get("y")
            pyautogui.rightClick(x=int(x), y=int(y)) if x is not None and y is not None else pyautogui.rightClick()

        elif action == "double_click":
            x, y = step.get("x"), step.get("y")
            pyautogui.doubleClick(x=int(x), y=int(y)) if x is not None and y is not None else pyautogui.doubleClick()

        elif action == "drag_to":
            pyautogui.dragTo(int(step.get("x", 0)), int(step.get("y", 0)), duration=0.4)

        elif action == "scroll":
            return verify_scroll_movement(int(step.get("amount", 0)))

        elif action == "focus_window":
            if window_manager.focus_window_by_title(str(step.get("title", "")).strip()):
                window_manager.remember_active_app_window()
            else:
                window_manager.ACTIVE_APP_WINDOW = None
                window_manager.ACTIVE_APP_CONTEXT_REQUIRED = True
                return False

        elif action == "copy":
            window_manager.platform_hotkey("ctrl", "c")

        elif action == "paste":
            window_manager.platform_hotkey("ctrl", "v")

        elif action == "select_all":
            window_manager.platform_hotkey("ctrl", "a")

        elif action == "wait":
            time.sleep(float(step.get("seconds", 1)))

        else:
            return False

    except Exception as exc:
        print(f"[Error] Action '{action}' failed: {exc}")
        return False
    return True


def process_task(task: str):
    if not task or task.lower() in {"exit", "quit", "q"}:
        raise KeyboardInterrupt

    print(f"\n[Task Initiated]: {task}")
    
    # 1. Obtain multi-step routed sequence
    routing_plan = router_agent.get_routing_plan(task)
    if not routing_plan:
        print(" -> Routing failed or returned empty plan. Falling back to single-step execution.")
        routing_plan = [{"step": 1, "model": "llava", "instruction": task}]

    context = ExecutionContext()

    # 2. Sequential execution with memory hygiene
    for item in routing_plan:
        step_num = item.get("step", 1)
        assigned_model = item.get("model", "llava")
        instruction = item.get("instruction", "")

        print(f"\n--- [Pipeline Stage {step_num}] Assigned Model: {assigned_model} ---")
        print(f"Instruction: {instruction}")

        # Generate action plan with the chosen model
        plan_data = app_planner.get_action_plan(instruction, context=context, model_name=assigned_model)
        actions = plan_data.get("actions", [])

        if not actions:
            print(f" -> No executable actions generated for stage {step_num}.")
        else:
            print(f" -> Plan: {plan_data.get('plan', 'Direct execution')}")
            for index, action in enumerate(actions):
                print(f"[{index + 1}/{len(actions)}] Executing: {action.get('action')}")
                succeeded = execute_action(action)
                if not succeeded:
                    print(f" -> Execution stopped on failed action: {action}")
                    break

        # 3. Clean VRAM after heavy model execution (ignore the lightweight router)
        if assigned_model != "qwen2.5:0.5b":
            model_manager.unload_model(assigned_model)

    print("\nEntire pipeline completed successfully.")

def main():
    parser = argparse.ArgumentParser(description="Local PC assistant")
    parser.add_argument("--task", help="Run a single prompt")
    args = parser.parse_args()

    if not emergency_stop.start_emergency_stop():
        print(" -> Emergency hotkey unavailable; check OS keyboard-hook permissions")

    print("=" * 70)
    print(" Local Visual PC Controller Ready")
    print("=" * 70)

    if args.task:
        process_task(args.task)
        return

    while True:
        try:
            task = input("\nEnter prompt: ").strip()
            if task:
                process_task(task)
        except (KeyboardInterrupt, EOFError):
            print("\nInterrupted by user.")
            break

if __name__ == "__main__":
    main()