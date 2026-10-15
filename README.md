# Local PC Assistant

The PC Assistant desktop app runs on Windows, macOS, and Linux. Desktop automation depends on the operating system's permissions, display server, and installed desktop utilities. PyInstaller builds are specific to the operating system where they are created.

## Common setup

1. Install Python 3.10 or newer and [Ollama](https://ollama.com/) for your operating system.
2. Start Ollama and create the local model from this project's `Modelfile`:

   ```sh
   ollama pull qwen2.5-coder:7b
   ollama create pc-agent -f Modelfile
   ```

3. Create a virtual environment and install Python requirements:

   **Windows PowerShell**

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe controller.py
   ```

   **macOS / Linux**

   ```sh
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python controller.py
   ```

   On Linux, use `bash ./start_pc_assistant_xvfb.sh` to run GUI tasks on a virtual display when Xvfb is installed.

## Desktop app with model switching

Run the laptop/desktop app with model switching:

```powershell
py .\desktop_app.py
```

In the app, choose a provider:

- `ollama` for the local model you already run with Ollama
- `openai` for OpenAI models with your API key
- `gemini` for Google Gemini
- `anthropic` for Claude
- `openai_compatible` for custom endpoints or paid provider gateways

The selected provider and model are stored in your home directory under `.pc_assistant/model_config.json`, and environment variables can override them at runtime:

```powershell
$env:PC_ASSISTANT_PROVIDER = "openai"
$env:PC_ASSISTANT_MODEL = "gpt-4o-mini"
$env:PC_ASSISTANT_API_KEY = "your-key"
$env:PC_ASSISTANT_BASE_URL = "https://api.openai.com/v1"
```

This lets the same desktop assistant use a local model or a paid subscription model without changing the automation core.

## Desktop permissions and platform notes

- **Windows:** Run as your normal user. Install Tesseract OCR and ensure `tesseract.exe` is on `PATH`, or install it under `C:\Program Files\Tesseract-OCR`.
- **macOS:** In System Settings → Privacy & Security, allow your terminal or packaged app to use **Accessibility** and **Screen Recording**. App launching uses Launch Services (`open -a`).
- **Linux:** Desktop control currently targets an X11 or XWayland session. Install `wmctrl`, `xdotool`, and `xdg-utils` (which provides `xdg-open`); Wayland compositors may restrict screenshots, window focus, and simulated input. `gtk-launch` is used for desktop-entry launches when available. Install Tesseract (often the `tesseract-ocr` package) for OCR.
- On every platform, the browser opened for an unnamed URL is the system default. A specifically requested browser must be installed locally.
- When opening an app, the controller first looks for a matching app shortcut on the Desktop. If found, it reveals the desktop and double-clicks the shortcut by its OCR-detected label; if OCR cannot identify that label, it opens that exact shortcut through the operating system instead of searching the Start menu.

## Emergency stop and isolated Linux automation

- Press **Ctrl+Alt+Shift+Q** to immediately terminate the assistant and its child processes. The hook requires the permissions of the current desktop session; on macOS, grant Accessibility permission to the app or terminal.
- On Linux, install `xvfb` and run `bash ./start_pc_assistant_xvfb.sh --task "your task"` to run the controller and its launched GUI applications on a separate virtual display. The launcher keeps a hotkey monitor on the normal display so the emergency stop remains available. Desktop applications opened in this mode are not visible on the normal display.
- On Windows, the emergency stop is supported, but general PyAutoGUI actions still use the active interactive desktop. Windows virtual desktops do not provide PyAutoGUI with an independent background input surface; use browser/CDP actions for non-intrusive web automation. Arbitrary GUI apps require a separately configured Windows Sandbox or RDP session for true isolation.

## Privacy and command authorization

- OCR and saved screenshots are sanitized before use: visible password, token, API-key, and banking-form rows are masked, along with password controls and toast/notification regions exposed by Windows UI Automation. OCR text is also scrubbed for common credential, card, SSN, and email patterns.
- `run_command` launches allowlisted executables (`git`, `notepad`, `code`, and `python`/`python3`) directly without a shell. Unknown executables and detected system-storage, registry, network, package-install, or high-risk Git operations require explicit approval; the desktop app prompts in its UI, while terminal sessions require typing `YES`. Missing authorization UI denies the command.

## Hierarchical task execution

- The Director requests milestone goals with action-index ranges and derives conservative milestones if the model omits them. The Actor executes each action; the Critic records action outcomes and compares visual checkpoints.
- Successful milestones become checkpoints in an execution tree. After a failed action, recovery is attempted only when OCR finds an error dialog and a previous successful checkpoint exists. The assistant tries `Esc`, may use `Alt+F4` only for an explicitly titled error window that remains open, and asks for up to two alternative branches using visible text targets only.
- If the screen does not confirm a dialog or no safe alternative is available, execution stops and pending actions are not sent. Recovery is bounded and is not a general rollback of file or system changes already performed.

## Build a standalone app

PyInstaller builds for the operating system where the build runs; it does not make one executable that works on all three operating systems.

- **Windows:** run `powershell -ExecutionPolicy Bypass -File .\build_windows_app.ps1` to build and install the desktop app. `controller.spec` is also available for a separate onedir PyInstaller build. The desktop shortcut and `.cmd` launcher are Windows-only.
- **macOS / Linux:** install PyInstaller in the virtual environment and run `pyinstaller --onefile controller.py`. The native executable will be in `dist/`.

Build the macOS and Linux versions on their respective systems. Keep Ollama and the `pc-agent` model installed separately on each machine.
