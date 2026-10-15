import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

import pyautogui

import app_planner


def _normalize_shortcut_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    words = normalized.split()
    ignored_words = {
        "a", "an", "app", "application", "browser", "desktop",
        "launch", "open", "program", "software", "start", "the",
    }
    return " ".join(word for word in words if word not in ignored_words)


def find_desktop_shortcut(app_name: str):
    system = platform.system()
    if system == "Windows":
        desktop_paths = [
            Path.home() / "Desktop",
            Path(os.environ["OneDrive"]) / "Desktop" if os.environ.get("OneDrive") else None,
            Path(os.environ["PUBLIC"]) / "Desktop" if os.environ.get("PUBLIC") else Path(r"C:\Users\Public\Desktop"),
        ]
        valid_suffixes = {".lnk", ".url", ".exe", ".appref-ms"}
    elif system in {"Darwin", "Linux"}:
        desktop_paths = [Path.home() / "Desktop"]
        valid_suffixes = {".app"} if system == "Darwin" else {".desktop"}
    else:
        return None

    normalized_app = _normalize_shortcut_name(app_name)
    if not normalized_app:
        return None
    browser = app_planner.requested_browser(app_name)
    aliases = {
        "brave": ("brave",),
        "chrome": ("google chrome", "chrome"),
        "edge": ("microsoft edge", "edge"),
        "firefox": ("mozilla firefox", "firefox"),
        "opera": ("opera gx", "opera"),
        "vivaldi": ("vivaldi",),
        "chromium": ("chromium",),
    }.get(browser, ())
    requested_names = {_normalize_shortcut_name(name) for name in (app_name, *aliases)}
    requested_names.discard("")
    requested_compact = {name.replace(" ", "") for name in requested_names}
    requested_words = set(normalized_app.split())

    matches = {}
    for desktop_path in desktop_paths:
        if desktop_path is None or not desktop_path.is_dir():
            continue
        try:
            entries = sorted(desktop_path.iterdir(), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            print(f" -> Cannot inspect desktop shortcuts in '{desktop_path}': {exc}")
            continue
        for entry in entries:
            if not entry.is_file() and entry.suffix.casefold() not in valid_suffixes:
                continue
            if entry.suffix.casefold() not in valid_suffixes:
                continue
            entry_name = _normalize_shortcut_name(entry.stem)
            if not entry_name:
                continue
            entry_words = set(entry_name.split())
            exact_match = entry_name in requested_names
            compact_match = entry_name.replace(" ", "") in requested_compact
            token_match = requested_words <= entry_words or entry_words <= requested_words
            if exact_match or compact_match or token_match:
                score = (
                    3 if exact_match else 2 if compact_match else 1,
                    len(requested_words & entry_words),
                    -abs(len(requested_words) - len(entry_words)),
                )
                current = matches.get(entry_name)
                if current is None or score > current[0]:
                    matches[entry_name] = (score, entry)

    if not matches:
        return None
    best_score = max(match[0] for match in matches.values())
    best_matches = {entry for score, entry in matches.values() if score == best_score}
    if len(best_matches) != 1:
        print(f" -> Multiple desktop shortcuts match '{app_name}'; not guessing")
        return None
    return best_matches.pop()


def show_desktop(platform_hotkey_fn=None):
    system = platform.system()
    hotkey_fn = platform_hotkey_fn or (lambda *keys: pyautogui.hotkey(*keys))
    if system == "Windows":
        hotkey_fn("win", "d")
    elif system == "Darwin":
        hotkey_fn("fn", "f11")
    elif system == "Linux":
        hotkey_fn("win", "d")
    else:
        raise RuntimeError(f"Showing the desktop is unsupported on {system}.")
    time.sleep(0.8)


def launch_from_desktop(
    shortcut,
    app_name: str,
    click_text_on_screen_fn=None,
    show_desktop_fn=None,
) -> bool:
    print(f" -> Looking for desktop shortcut: {shortcut.name}")
    show_desktop_fn = show_desktop_fn or show_desktop
    show_desktop_fn()
    visible_label = shortcut.stem
    if click_text_on_screen_fn and click_text_on_screen_fn(visible_label, clicks=2):
        print(f" -> Opened '{app_name}' from its desktop shortcut")
        return True
    print(
        f" -> Desktop shortcut label '{visible_label}' was not readable; opening the exact matching desktop shortcut directly"
    )
    try:
        if platform.system() == "Windows":
            os.startfile(str(shortcut))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(shortcut)])
        elif platform.system() == "Linux":
            gtk_launch = shutil.which("gtk-launch")
            if not gtk_launch:
                raise RuntimeError("Launching a Linux desktop shortcut requires gtk-launch.")
            subprocess.Popen([gtk_launch, shortcut.stem])
        else:
            raise RuntimeError(f"Launching desktop shortcuts is unsupported on {platform.system()}.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f" -> Could not open desktop shortcut '{shortcut}': {exc}")
        return False
    print(f" -> Opened '{app_name}' from the matching desktop shortcut")
    return True


def launch_app(
    app_name: str,
    click_text_on_screen_fn=None,
    find_desktop_shortcut_fn=None,
    launch_from_desktop_fn=None,
    show_desktop_fn=None,
):
    system = platform.system()
    find_shortcut = find_desktop_shortcut_fn or find_desktop_shortcut
    launch_shortcut = launch_from_desktop_fn or launch_from_desktop
    desktop_shortcut = find_shortcut(app_name)
    if desktop_shortcut is not None:
        if launch_shortcut is launch_from_desktop:
            shortcut_opened = launch_shortcut(
                desktop_shortcut,
                app_name,
                click_text_on_screen_fn=click_text_on_screen_fn,
                show_desktop_fn=show_desktop_fn,
            )
        else:
            shortcut_opened = launch_shortcut(desktop_shortcut, app_name)
        if shortcut_opened:
            return
    if system == "Darwin":
        subprocess.Popen(["open", "-a", app_name])
        return
    if system == "Linux":
        app_commands = {
            "brave": "brave-browser",
            "chrome": "google-chrome",
            "edge": "microsoft-edge",
            "firefox": "firefox",
            "chromium": "chromium",
            "code": "code",
            "visual studio code": "code",
        }
        executable = app_commands.get(app_name.lower(), app_name)
        command_path = shutil.which(executable)
        if command_path:
            subprocess.Popen([command_path])
            return
        gtk_launch = shutil.which("gtk-launch")
        if gtk_launch:
            try:
                subprocess.run([gtk_launch, app_name], check=True, capture_output=True, text=True, timeout=5)
                return
            except (OSError, subprocess.SubprocessError):
                pass
        pyautogui.hotkey("win")
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.04)
        time.sleep(0.4)
        pyautogui.press("enter")
        return
    if system == "Windows":
        pyautogui.hotkey("win")
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.04)
        time.sleep(0.4)
        pyautogui.press("enter")
        return
    raise RuntimeError(f"Launching apps is unsupported on {system}.")
