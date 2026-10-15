import platform
import re
import shutil
import subprocess
import time

import pyautogui

from execution_context import ExecutionContext

BROWSER_ALIASES = {
    "brave": ("brave",),
    "chrome": ("google chrome", "chrome"),
    "edge": ("microsoft edge", "edge"),
    "firefox": ("mozilla firefox", "firefox"),
    "opera": ("opera gx", "opera"),
    "vivaldi": ("vivaldi",),
    "chromium": ("chromium",),
}

EXECUTION_CONTEXT = ExecutionContext()
ACTIVE_APP_WINDOW = EXECUTION_CONTEXT.active_app_window
ACTIVE_APP_CONTEXT_REQUIRED = EXECUTION_CONTEXT.active_app_context_required


def _sync_execution_context():
    global ACTIVE_APP_WINDOW, ACTIVE_APP_CONTEXT_REQUIRED
    ACTIVE_APP_WINDOW = EXECUTION_CONTEXT.active_app_window
    ACTIVE_APP_CONTEXT_REQUIRED = EXECUTION_CONTEXT.active_app_context_required


class DesktopWindow:
    def __init__(self, title: str, handle: int, activate):
        self.title = title
        self._hWnd = handle
        self.activate = activate


def _linux_window_list():
    wmctrl = shutil.which("wmctrl")
    if not wmctrl:
        raise RuntimeError("Window management on Linux requires wmctrl (X11/XWayland).")
    result = subprocess.run([wmctrl, "-l"], check=True, capture_output=True, text=True)
    windows = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        handle = int(parts[0], 16)
        title = parts[3]

        def activate(window_id=parts[0]):
            subprocess.run([wmctrl, "-ia", window_id], check=True)

        windows.append(DesktopWindow(title, handle, activate))
    return windows


def get_all_windows():
    if platform.system() == "Linux":
        return _linux_window_list()
    
    try:
        import pygetwindow as gw
    except ImportError:
        raise RuntimeError(f"Window management is unavailable on {platform.system()}.")
        
    return gw.getAllWindows()


def get_active_window():
    if platform.system() == "Linux":
        xdotool = shutil.which("xdotool")
        if not xdotool:
            raise RuntimeError("Active-window detection on Linux requires xdotool (X11/XWayland).")
        result = subprocess.run([xdotool, "getactivewindow"], check=True, capture_output=True, text=True)
        window_id = result.stdout.strip()
        title_result = subprocess.run([xdotool, "getwindowname", window_id], check=True, capture_output=True, text=True)
        handle = int(window_id)
        title = title_result.stdout.strip()
        wmctrl = shutil.which("wmctrl")

        def activate():
            if wmctrl:
                subprocess.run([wmctrl, "-ia", hex(handle)], check=True)
            else:
                subprocess.run([xdotool, "windowactivate", "--sync", str(handle)], check=True)

        return DesktopWindow(title, handle, activate)
        
    try:
        import pygetwindow as gw
    except ImportError:
        raise RuntimeError(f"Window management is unavailable on {platform.system()}.")
        
    return gw.getActiveWindow()


def platform_hotkey(*keys: str):
    normalized_keys = list(keys)
    if platform.system() == "Darwin":
        normalized_keys = [
            "command" if key.lower() in {"ctrl", "control", "win"} else key
            for key in normalized_keys
        ]
    elif platform.system() == "Linux":
        normalized_keys = [
            "win" if key.lower() == "super" else key
            for key in normalized_keys
        ]
    pyautogui.hotkey(*normalized_keys)


def requested_browser(task: str) -> str | None:
    task_lower = task.lower()
    for browser, aliases in BROWSER_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", task_lower) for alias in aliases):
            return browser
    return None


def focus_window_by_title(window_title: str):
    for win in get_all_windows():
        if window_title.lower() in win.title.lower():
            win.activate()
            time.sleep(0.5)
            return True
    return False


def find_app_window(app_name: str):
    normalize = lambda value: " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    normalized_app = normalize(app_name)
    browser = requested_browser(app_name)
    aliases = BROWSER_ALIASES.get(browser, (normalized_app,))
    normalized_aliases = tuple(normalize(alias) for alias in aliases)
    for window in get_all_windows():
        normalized_title = normalize(window.title)
        if normalized_title and any(
            alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_title)
            for alias in normalized_aliases
        ):
            return window
    return None


def remember_active_app_window():
    global ACTIVE_APP_WINDOW, ACTIVE_APP_CONTEXT_REQUIRED
    try:
        EXECUTION_CONTEXT.active_app_window = get_active_window()
    except Exception:
        EXECUTION_CONTEXT.active_app_window = None
    EXECUTION_CONTEXT.active_app_context_required = True
    _sync_execution_context()
    if ACTIVE_APP_WINDOW is None:
        return None
    return ACTIVE_APP_WINDOW


def wait_for_app_window(app_name: str, timeout: float = 12.0) -> bool:
    global ACTIVE_APP_WINDOW, ACTIVE_APP_CONTEXT_REQUIRED
    deadline = time.monotonic() + timeout
    EXECUTION_CONTEXT.active_app_context_required = True
    ACTIVE_APP_CONTEXT_REQUIRED = True

    while time.monotonic() < deadline:
        try:
            window = find_app_window(app_name)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            EXECUTION_CONTEXT.active_app_window = None
            ACTIVE_APP_WINDOW = None
            return False

        if window and window.title:
            try:
                window.activate()
                EXECUTION_CONTEXT.active_app_window = window
                ACTIVE_APP_WINDOW = window
                return True
            except Exception:
                pass

        time.sleep(0.25)

    EXECUTION_CONTEXT.active_app_window = None
    ACTIVE_APP_WINDOW = None
    return False


def focus_active_app_window() -> bool:
    required = EXECUTION_CONTEXT.active_app_context_required or ACTIVE_APP_CONTEXT_REQUIRED
    target_window = EXECUTION_CONTEXT.active_app_window if EXECUTION_CONTEXT.active_app_window is not None else ACTIVE_APP_WINDOW
    if not required:
        return True
    if target_window is None:
        return False

    try:
        target_window.activate()
        time.sleep(0.15)
        current_window = get_active_window()
        if current_window:
            current_handle = getattr(current_window, "_hWnd", None)
            target_handle = getattr(target_window, "_hWnd", None)
            if current_handle is not None and current_handle == target_handle:
                return True
            if (
                current_handle is None
                and target_handle is None
                and current_window.title == target_window.title
            ):
                return True
    except Exception:
        return False

    return False
