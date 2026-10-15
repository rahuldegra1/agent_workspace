import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pyautogui


ALLOWED_COMMANDS = {"git", "notepad", "code", "python", "python3"}
SYSTEM_MODIFICATION_RE = re.compile(
    r"(?i)(?:\b(?:diskpart|format|mountvol|bcdedit|reg|regedit|netsh|route|"
    r"ipconfig|ifconfig|nmcli|iptables|ip6tables|Set-NetIPInterface|"
    r"New-NetIPAddress|Remove-NetIPAddress)\b|"
    r"\bHK(?:LM|CU|CR|U|CC)\b|\bHKEY_(?:LOCAL_MACHINE|CURRENT_USER|"
    r"CLASSES_ROOT|USERS|CURRENT_CONFIG)\b|\\\\\.\\PhysicalDrive\d*)"
)
RISKY_PYTHON_RE = re.compile(
    r"(?i)\b(?:winreg|ctypes(?:\.windll)?|subprocess(?:\.(?:run|Popen|call))?|"
    r"os\.system|socket|netsh|diskpart|reg(?:edit)?|win32api)\b"
)
_COMMAND_AUTHORIZER = None


def set_command_authorizer(callback) -> None:
    global _COMMAND_AUTHORIZER
    _COMMAND_AUTHORIZER = callback


def _command_name(executable: str) -> str:
    name = Path(str(executable).replace("\\", "/")).name.casefold()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def command_authorization_reason(arguments: list[str]) -> str | None:
    if not arguments:
        return "The command is empty."
    executable = _command_name(arguments[0])
    joined_arguments = " ".join(str(argument) for argument in arguments[1:])
    if executable not in ALLOWED_COMMANDS:
        return f"'{executable}' is not in the permitted executable list."

    if "/" in arguments[0] or "\\" in arguments[0]:
        trusted_path = shutil.which(executable)
        try:
            requested_path = Path(arguments[0]).resolve()
            allowed_path = Path(trusted_path).resolve() if trusted_path else None
        except OSError:
            requested_path = None
            allowed_path = None
        if allowed_path is None or requested_path != allowed_path:
            return "The executable path does not match the trusted allowlisted binary."

    if SYSTEM_MODIFICATION_RE.search(joined_arguments):
        return "The command appears to modify system storage, registry, or network settings."

    if executable in {"python", "python3"}:
        if len(arguments) > 1 and arguments[1] == "-c":
            return "Inline Python can perform arbitrary system actions."
        if len(arguments) > 1 and arguments[1] == "-m":
            return "Python module execution can perform arbitrary system actions."
        if len(arguments) > 3 and arguments[1:3] == ["-m", "pip"] and any(
            argument.casefold() in {"install", "uninstall"} for argument in arguments[3:]
        ):
            return "This Python command changes installed packages."
        if len(arguments) > 1 and Path(arguments[1]).suffix.casefold() == ".py":
            try:
                script_text = Path(arguments[1]).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return "The Python script could not be inspected."
            if RISKY_PYTHON_RE.search(script_text):
                return "The Python script references system, process, or network control APIs."

    if executable == "git" and len(arguments) > 1:
        git_arguments = [argument.casefold() for argument in arguments[1:]]
        if "--system" in git_arguments or (
            "clean" in git_arguments and any(argument.startswith("-f") for argument in git_arguments)
        ) or ("reset" in git_arguments and "--hard" in git_arguments):
            return "This Git command changes system configuration or forcibly deletes files."
    return None


def request_command_authorization(command: str, reason: str) -> bool:
    message = (
        f"Authorization required:\n\n{command}\n\nReason: {reason}\n\n"
        "Allow this command?"
    )
    if callable(_COMMAND_AUTHORIZER):
        try:
            return bool(_COMMAND_AUTHORIZER(command, reason))
        except Exception:
            return False

    if sys.stdin is not None and getattr(sys.stdin, "isatty", lambda: False)():
        try:
            return input(f"{message}\nType YES to authorize: ").strip() == "YES"
        except (EOFError, OSError, RuntimeError):
            return False

    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        allowed = messagebox.askyesno("Authorize command", message, parent=root, default="no")
        root.destroy()
        return bool(allowed)
    except Exception:
        return False


def open_path(path: str):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    elif system == "Linux":
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("Opening files on Linux requires xdg-open.")
        subprocess.Popen([opener, path])
    else:
        raise RuntimeError(f"Opening files is unsupported on {system}.")


def read_file_text(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception as exc:
        print(f"[Warning] Could not read file '{file_path}': {exc}")
        return ""


def write_file_text(file_path: str, content: str):
    try:
        parent = Path(file_path).parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f" -> Wrote file: {file_path}")
        return True
    except Exception as exc:
        print(f"[Warning] Could not write file '{file_path}': {exc}")
        return False


def _prepare_command_args(command: str):
    if not command or not command.strip():
        raise ValueError("Missing command")

    system = platform.system()
    arguments = shlex.split(command, posix=system != "Windows")
    if system == "Windows":
        arguments = [
            argument[1:-1]
            if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in "\"'"
            else argument
            for argument in arguments
        ]
    if not arguments:
        raise ValueError("Missing command")
    return arguments
