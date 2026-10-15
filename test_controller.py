import pytest

import actor_critic
import agent_orchestrator
import app_planner
import controller
import emergency_stop
import model_config
import privacy_security
import ui_automation


def test_action_verifier_flags_stalled_ui_action():
    before = {"ocr_text": "Save", "active_title": "Notepad", "hash": "abc"}
    after = {"ocr_text": "Save", "active_title": "Notepad", "hash": "abc"}

    result = actor_critic.evaluate_action_effect(before, after)

    assert result["stalled"] is True
    assert result["reason"] == "Action Stalling Error"


def test_director_validates_milestone_action_indices_and_falls_back():
    director = agent_orchestrator.Director()
    actions = [{"action": "open_app_search"}, {"action": "type"}]

    proposed = director.decompose(
        "write a note",
        actions,
        [{"goal": "Open editor", "action_indices": [0]}, {"goal": "Write note", "action_indices": [1]}],
    )
    fallback = director.decompose(
        "write a note",
        actions,
        [{"goal": "invalid", "action_indices": [1]}],
    )

    assert [item.goal for item in proposed] == ["Open editor", "Write note"]
    assert [index for item in fallback for index in item.action_indices] == [0, 1]


def test_execution_tree_keeps_last_successful_checkpoint_and_bounds_recovery():
    milestones = [agent_orchestrator.Milestone("Open editor", (0,))]
    tree = agent_orchestrator.ExecutionTree(milestones, max_recovery_branches=1)

    tree.record_action(0, {"action": "open_app_search"}, True)
    checkpoint = tree.checkpoint(0, "completed", {"active_title": "Notepad"})
    first_branch = tree.add_recovery_branch(0, [{"action": "press_key", "key": "esc"}])
    second_branch = tree.add_recovery_branch(0, [{"action": "press_key", "key": "esc"}])

    assert tree.last_successful_checkpoint == checkpoint
    assert first_branch is not None
    assert second_branch is None


def test_critic_recognizes_error_dialogs_conservatively():
    assert agent_orchestrator.Critic.is_error_dialog("Error dialog: retry or cancel")
    assert not agent_orchestrator.Critic.is_error_dialog("The report contains an error code")
    assert agent_orchestrator.Critic.can_close_error_window(
        "Application Error",
        "An exception occurred. Close or Retry.",
    )


def test_process_task_creates_successful_milestone_checkpoints(monkeypatch):
    trees = []
    original_tree = agent_orchestrator.ExecutionTree

    def make_tree(milestones):
        tree = original_tree(milestones)
        trees.append(tree)
        return tree

    monkeypatch.setattr(controller.agent_orchestrator, "ExecutionTree", make_tree)
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {"plan": "Do two steps", "actions": [
            {"action": "wait", "seconds": 0},
            {"action": "wait", "seconds": 0},
        ]},
    )
    monkeypatch.setattr(controller, "execute_action", lambda _step: True)

    controller.process_task("complete two steps")

    checkpoints = [node for node in trees[0].nodes if node["kind"] == "checkpoint"]
    assert len(checkpoints) == 2
    assert all(node["status"] == "completed" for node in checkpoints)


def test_recovered_final_action_becomes_a_successful_checkpoint(monkeypatch):
    trees = []
    original_tree = agent_orchestrator.ExecutionTree
    outcomes = iter([True, False, True])
    states = iter([
        {"hash": "before", "active_title": "Editor", "ocr_text": ""},
        {"hash": "after", "active_title": "Editor", "ocr_text": ""},
    ])

    def make_tree(milestones):
        tree = original_tree(milestones)
        trees.append(tree)
        return tree

    def recover(_task, _milestone, tree, _failed_action, _completed):
        alternatives = [{"action": "wait", "seconds": 0}]
        tree.add_recovery_branch(1, alternatives)
        return alternatives

    monkeypatch.setattr(controller.agent_orchestrator, "ExecutionTree", make_tree)
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {"plan": "Open and edit", "actions": [
            {"action": "wait", "seconds": 0},
            {"action": "type", "text": "continue"},
        ]},
    )
    monkeypatch.setattr(controller, "execute_action", lambda _step: next(outcomes))
    monkeypatch.setattr(controller, "recover_error_dialog", recover)
    monkeypatch.setattr(controller, "capture_orchestration_state", lambda: next(states))

    controller.process_task("continue editing")

    final_checkpoint = [node for node in trees[0].nodes if node["kind"] == "checkpoint"][-1]
    assert final_checkpoint["milestone_index"] == 1
    assert final_checkpoint["status"] == "completed"


def test_recovery_dismisses_error_dialog_and_selects_visible_alternative(monkeypatch):
    milestone = agent_orchestrator.Milestone("Open project", (0,))
    tree = agent_orchestrator.ExecutionTree([milestone])
    tree.checkpoint(0, "completed", {"active_title": "Editor"})
    keypresses = []
    screens = iter(["Error dialog: Retry or Cancel", "Continue"])
    monkeypatch.setattr(controller, "capture_orchestration_state", lambda: {"active_title": "Editor"})
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: next(screens))
    monkeypatch.setattr(controller.pyautogui, "press", lambda key: keypresses.append(key))
    monkeypatch.setattr(controller.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda prompt: {
            "actions": [{"action": "click_text", "text": "Continue"}],
        },
    )

    alternatives = controller.recover_error_dialog(
        "Open project",
        milestone,
        tree,
        {"action": "click_text", "text": "Open"},
        [],
    )

    assert keypresses == ["esc"]
    assert alternatives == [{"action": "click_text", "text": "Continue"}]
    assert any(node["kind"] == "recovery" for node in tree.nodes)
    assert tree.nodes[-1]["status"] == "candidate"

    tree.resolve_recovery_branch("completed")

    assert tree.nodes[-1]["status"] == "completed"


def test_ui_automation_uses_native_click_when_available(monkeypatch):
    calls = []

    class FakeElement:
        def click(self):
            calls.append("clicked")

    fake_native = {"find_element_by_name": lambda *_args, **_kwargs: FakeElement()}
    monkeypatch.setattr(ui_automation, "NATIVE_UI_AVAILABLE", True)
    monkeypatch.setattr(ui_automation, "resolve_native_ui", lambda: fake_native)

    result = ui_automation.try_click_element_by_name("Save")

    assert result is True
    assert calls == ["clicked"]


def test_type_action_uses_clipboard_injection(monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "copy_to_clipboard", lambda text: calls.append(("copy", text)) or True)
    monkeypatch.setattr(controller, "paste_from_clipboard", lambda: calls.append(("paste", "v")) or True)
    monkeypatch.setattr(controller, "platform_hotkey", lambda *keys: calls.append(("hotkey", keys)))

    result = controller.type_text_with_clipboard("Hello\nWorld")

    assert result is True
    assert calls[0] == ("copy", "Hello\nWorld")
    assert calls[1] == ("paste", "v")


def test_window_dpi_awareness_calls_windows_api(monkeypatch):
    calls = []

    class FakeWindll:
        class shcore:
            @staticmethod
            def SetProcessDpiAwareness(level):
                calls.append(level)

    monkeypatch.setattr(controller, "ctypes", type("C", (), {"windll": FakeWindll, "byref": lambda value: value}))
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")

    controller.enable_windows_dpi_awareness()

    assert calls == [2]


def test_scroll_verification_detects_stalled_scroll(monkeypatch):
    class FakeImage:
        def __init__(self, payload):
            self.payload = payload

    fake_before = FakeImage("same")
    fake_after = FakeImage("same")
    monkeypatch.setattr(controller, "capture_scroll_state", lambda: (fake_before, fake_after))
    monkeypatch.setattr(controller, "perceptual_difference", lambda _a, _b: 0)

    result = controller.verify_scroll_movement()

    assert result is False


def test_prompt_for_task_handles_lost_stdin(monkeypatch, capsys):
    def fake_input(_prompt):
        raise RuntimeError("lost sys.stdin")

    monkeypatch.setattr("builtins.input", fake_input)

    with pytest.raises(SystemExit) as exc:
        controller.prompt_for_task()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "No interactive console is available" in captured.out


def test_execute_action_does_not_pause_for_risk_confirmation(monkeypatch, capsys):
    clipboard_calls = []
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", False)
    monkeypatch.setattr(controller, "copy_to_clipboard", lambda text: clipboard_calls.append(("copy", text)) or True)
    monkeypatch.setattr(controller, "paste_from_clipboard", lambda: clipboard_calls.append(("paste", "v")) or True)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Actions should not prompt for confirmation")
        ),
    )

    controller.execute_action({"action": "type", "text": "continue"})

    assert clipboard_calls[0] == ("copy", "continue")
    assert clipboard_calls[1] == ("paste", "v")
    output = capsys.readouterr().out
    assert "Risky action detected" not in output
    assert "Proceed?" not in output


def test_platform_hotkey_maps_common_modifiers_on_macos(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(controller.pyautogui, "hotkey", lambda *keys: calls.append(keys))

    controller.platform_hotkey("ctrl", "l")

    assert calls == [("command", "l")]


def test_emergency_stop_starts_daemon_global_hotkey(monkeypatch):
    calls = []

    class FakeListener:
        daemon = False

        def __init__(self, hotkeys):
            calls.append(hotkeys)

        def start(self):
            calls.append("started")

        def is_alive(self):
            return False

    monkeypatch.setattr(emergency_stop, "GlobalHotKeys", FakeListener)
    monkeypatch.setattr(emergency_stop, "_listener", None)

    assert emergency_stop.start_emergency_stop() is True
    assert calls[0].keys() == {"<ctrl>+<alt>+<shift>+q"}
    assert calls[1] == "started"


def test_emergency_abort_kills_child_processes_and_exits(monkeypatch):
    killed = []

    class FakeChild:
        def kill(self):
            killed.append("child")

    class FakeProcess:
        def __init__(self, _pid):
            pass

        def children(self, recursive):
            assert recursive is True
            return [FakeChild()]

        def kill(self):
            killed.append("root")

    class FakePsutil:
        Error = OSError
        Process = FakeProcess

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(emergency_stop, "psutil", FakePsutil)
    monkeypatch.setattr(emergency_stop.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc:
        emergency_stop.abort_process_tree(123)

    assert killed == ["child", "root"]
    assert exc.value.code == 1


def test_launch_browser_with_cdp_starts_debug_port(monkeypatch):
    calls = []

    readiness = iter([False, True])
    monkeypatch.setattr(controller, "browser_port_ready", lambda port=9222: next(readiness))

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(controller.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(controller.shutil, "which", lambda name: r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")

    result = controller.launch_browser_with_cdp("chrome")

    assert result is True
    assert calls
    assert any("--remote-debugging-port=9222" in arg for arg in calls[0][0])


def test_execute_action_uses_browser_cdp_bridge_for_url(monkeypatch):
    calls = []

    monkeypatch.setattr(controller, "launch_browser_with_cdp", lambda browser: calls.append(("launch", browser)) or True)
    monkeypatch.setattr(controller, "run_browser_cdp_action", lambda browser, action, target: calls.append(("cdp", browser, action, target)) or True)
    monkeypatch.setattr(controller, "focus_active_app_window", lambda: True)

    result = controller.execute_action({"action": "open_url", "url": "https://example.com", "browser": "chrome"})

    assert result is True
    assert calls == [("cdp", "chrome", "open_url", "https://example.com")]


def test_run_command_uses_argument_list_without_shell(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(controller.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(controller, "remember_active_app_window", lambda: None)

    controller.execute_action({"action": "run_command", "command": 'notepad "hello & world.txt"'})

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["notepad", "hello & world.txt"]
    assert kwargs.get("shell") is None


def test_command_authorization_required_for_unknown_and_system_commands(tmp_path):
    assert controller.system_actions.command_authorization_reason(["curl", "https://example.com"])
    assert controller.system_actions.command_authorization_reason(["python", "-c", "import winreg"])
    assert controller.system_actions.command_authorization_reason(["python", "-m", "http.server"])
    assert controller.system_actions.command_authorization_reason(["git", "config", "--system", "user.name", "x"])
    assert controller.system_actions.command_authorization_reason(["python", "missing.py"])
    safe_script = tmp_path / "safe_script.py"
    safe_script.write_text("print('hello')\n", encoding="utf-8")
    assert controller.system_actions.command_authorization_reason(["python", str(safe_script)]) is None


def test_python_script_using_registry_api_requires_authorization(tmp_path):
    script = tmp_path / "change_settings.py"
    script.write_text("import winreg\n", encoding="utf-8")

    reason = controller.system_actions.command_authorization_reason(["python", str(script)])

    assert reason is not None


def test_sensitive_ocr_text_scrubs_tokens_contact_details_and_card_data():
    text = "access token: abc123; user@example.com; 555-123-4567; card 4111 1111 1111 1111"

    safe_text = privacy_security.redact_sensitive_text(text)

    assert "abc123" not in safe_text
    assert "user@example.com" not in safe_text
    assert "555-123-4567" not in safe_text
    assert "4111 1111 1111 1111" not in safe_text


def test_unknown_command_is_not_started_when_authorization_is_denied(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(controller.system_actions, "request_command_authorization", lambda *_args: False)

    result = controller.execute_action({"action": "run_command", "command": "curl https://example.com"})

    assert result is False
    assert calls == []


def test_read_screen_redacts_before_ocr_and_saves_sanitized_image(monkeypatch, tmp_path):
    from PIL import Image

    image = Image.new("RGB", (220, 40), "white")
    ocr_data = {
        "text": ["API", "key", "sk-abcdefgh12345678"],
        "left": [5, 35, 100], "top": [10, 10, 10],
        "width": [25, 35, 110], "height": [14, 14, 14],
        "block_num": [1, 1, 1], "par_num": [1, 1, 1], "line_num": [1, 1, 1],
    }
    ocr_inputs = []

    monkeypatch.setattr(controller.pyautogui, "screenshot", lambda: image.copy())
    monkeypatch.setattr(controller.privacy_security, "get_ui_protected_rectangles", lambda: [])
    monkeypatch.setattr(controller.pytesseract, "image_to_data", lambda *_args, **_kwargs: ocr_data)

    def fake_image_to_string(safe_image):
        ocr_inputs.append(safe_image.getpixel((110, 15)))
        return "API key: sk-abcdefgh12345678"

    monkeypatch.setattr(controller.pytesseract, "image_to_string", fake_image_to_string)
    output_path = tmp_path / "sanitized.png"

    result = controller.read_screen_text(path=str(output_path))

    assert ocr_inputs == [(0, 0, 0)]
    assert "sk-abcdefgh12345678" not in result
    assert Image.open(output_path).getpixel((110, 15)) == (0, 0, 0)


def test_screenshot_action_uses_sanitized_capture(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(controller, "capture_sanitized_screenshot", lambda path: saved.append(path))
    monkeypatch.setattr(controller, "ensure_dir", lambda _path: None)

    result = controller.execute_action({"action": "screenshot", "path": str(tmp_path / "screen.png")})

    assert result is True
    assert saved == [str(tmp_path / "screen.png")]


def test_screenshot_redaction_masks_password_and_banking_fields():
    from PIL import Image
    from privacy_security import redact_screenshot

    image = Image.new("RGB", (240, 90), "white")
    data = {
        "text": ["Password", "hunter2", "Card", "number", "4111111111111111"],
        "left": [10, 100, 10, 45, 120],
        "top": [10, 10, 50, 50, 50],
        "width": [70, 60, 30, 60, 110],
        "height": [16, 16, 16, 16, 16],
        "block_num": [1, 1, 2, 2, 2],
        "par_num": [1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 1, 1],
        "conf": [95, 95, 95, 95, 95],
    }

    sanitized, rectangles = redact_screenshot(image, data)

    assert rectangles
    assert sanitized.getpixel((110, 18)) == (0, 0, 0)
    assert sanitized.getpixel((150, 58)) == (0, 0, 0)


def test_native_password_and_notification_bounds_are_protected(monkeypatch):
    import sys
    from types import SimpleNamespace

    class Control:
        def __init__(self, password=False, name="", class_name=""):
            self.IsPassword = password
            self.Name = name
            self.ClassName = class_name
            self.AutomationId = ""
            self.ControlTypeName = "Control"
            self.BoundingRectangle = SimpleNamespace(left=1, top=2, right=30, bottom=40)

    controls = [Control(password=True), Control(name="", class_name="ToastNotification")]
    fake_uia = SimpleNamespace(GetRootControl=lambda: SimpleNamespace(Descendants=lambda: controls))
    monkeypatch.setitem(sys.modules, "uiautomation", fake_uia)

    rectangles = privacy_security.get_ui_protected_rectangles()

    assert rectangles == [(1, 2, 30, 40), (1, 2, 30, 40)]


def test_screenshot_layout_masks_phone_number_pii():
    from PIL import Image

    image = Image.new("RGB", (240, 40), "white")
    data = {
        "text": ["555-123-4567"],
        "left": [20], "top": [10], "width": [130], "height": [18],
        "block_num": [1], "par_num": [1], "line_num": [1],
    }

    sanitized, rectangles = privacy_security.redact_screenshot(image, data)

    assert rectangles
    assert sanitized.getpixel((80, 18)) == (0, 0, 0)


def test_action_planner_receives_current_operating_system(monkeypatch):
    requests = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "response": '{"plan":"open app","actions":[{"action":"wait","seconds":1}]}'
            }

    monkeypatch.setattr(
        controller.requests,
        "post",
        lambda _url, **kwargs: (requests.append(kwargs) or Response()),
    )
    monkeypatch.setattr(controller.platform, "system", lambda: "Darwin")

    controller.get_action_plan("open Notes")

    assert "Current operating system: Darwin" in requests[0]["json"]["prompt"]


def test_action_planner_receives_real_file_and_active_app_context(monkeypatch, tmp_path):
    requests = []
    active_window = type("Window", (), {"title": "Notepad"})()

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "response": '{"plan":"continue","actions":[{"action":"wait","seconds":1}]}'
            }

    monkeypatch.setattr(
        controller.requests,
        "post",
        lambda _url, **kwargs: (requests.append(kwargs) or Response()),
    )
    monkeypatch.setattr(controller.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", active_window)
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", True)

    controller.get_action_plan("save current file")

    prompt = requests[0]["json"]["prompt"]
    assert f"Current user home directory: {tmp_path}" in prompt
    assert "Currently tracked app window: Notepad" in prompt
    assert "C:/Users/name" in prompt
    assert "complete source in one 'write_file' action" in prompt
    assert "Preserve the exact filename and extension" in prompt
    assert "valid Rust source to" in prompt


def test_generate_source_code_returns_plain_rust_from_local_model(monkeypatch):
    requests = []
    source = 'fn main() {\n    println!("Calculator");\n}'

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": f"```rust\n{source}\n```"}

    monkeypatch.setattr(
        controller.requests,
        "post",
        lambda url, **kwargs: (requests.append((url, kwargs)) or Response()),
    )

    generated = controller.generate_source_code(
        "Create a Rust greeting program and save it as greeting.rust",
        r"C:\Users\rahul\Documents\calculator.rust",
    )

    assert generated == source + "\n"
    assert "complete, useful, syntactically valid Rust" in requests[0][1]["json"]["prompt"]
    assert "calculator.rust" in requests[0][1]["json"]["prompt"]


def test_python_source_generation_rejects_invalid_code(monkeypatch, capsys):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "def broken("}

    monkeypatch.setattr(controller.requests, "post", lambda *_args, **_kwargs: Response())

    assert controller.generate_source_code(
        "Create a Python script",
        "script.py",
    ) is None
    assert "invalid Python syntax" in capsys.readouterr().out


def test_rust_calculator_source_is_complete_and_handles_bad_input():
    source = controller.rust_calculator_source()

    assert "fn main()" in source
    assert all(operation in source for operation in ['"+"', '"-"', '"*"', '"/"'])
    assert "Invalid first number." in source
    assert "Cannot divide by zero." in source
    assert ".unwrap()" not in source


def test_code_file_plan_uses_generated_source_and_exact_requested_path(
    monkeypatch,
    tmp_path,
):
    requested_path = "C:/Users/actual-user/Documents/calculator.rust"
    source = controller.rust_calculator_source()

    monkeypatch.setattr(controller.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {
            "plan": "Create a Rust calculator",
            "actions": [
                {"action": "open_app_search", "app": "Notepad"},
                {"action": "wait", "seconds": 2},
                {
                    "action": "write_file",
                    "path": requested_path,
                    "content": 'fn main() {}',
                },
            ],
        },
    )
    monkeypatch.setattr(
        controller,
        "generate_source_code",
        lambda _task, _path: source,
    )
    opened = []
    app_window = type("Window", (), {"title": "Untitled - Notepad"})()
    monkeypatch.setattr(controller, "find_app_window", lambda _app: None)
    monkeypatch.setattr(controller, "launch_app", lambda _app: None)
    monkeypatch.setattr(
        controller,
        "wait_for_app_window",
        lambda _app: (
            monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", app_window) or True
        ),
    )
    monkeypatch.setattr(
        controller,
        "open_file_in_app",
        lambda path, app: opened.append((path, app)) or True,
    )
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(controller, "remember_active_app_window", lambda: None)

    controller.process_task(
        "Create a Rust calculator and save it as calculator.rust"
    )

    output_file = tmp_path / "Documents" / "calculator.rust"
    assert output_file.read_text(encoding="utf-8") == source
    assert output_file.name == "calculator.rust"
    assert opened == [(str(output_file), "Notepad")]


def test_windows_opens_created_file_in_notepad(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        controller.subprocess,
        "Popen",
        lambda args: calls.append(args),
    )
    monkeypatch.setattr(
        controller,
        "wait_for_app_window",
        lambda app: calls.append(("wait", app)) or True,
    )

    assert controller.open_file_in_app(
        r"C:\Users\rahul\Documents\calculator.py",
        "Notepad",
    )
    assert calls == [
        ["notepad.exe", r"C:\Users\rahul\Documents\calculator.py"],
        ("wait", "notepad"),
    ]


@pytest.mark.parametrize(
    ("task", "filename"),
    [
        ("now save that file as calculator.rust", "calculator.rust"),
        ("Save this document as 'hello_world.py'", "hello_world.py"),
    ],
)
def test_requested_save_as_filename(task, filename):
    assert controller.requested_save_as_filename(task) == filename


@pytest.mark.parametrize(
    ("task", "contact_name"),
    [
        ("open whatsapp and video call rinku jiji", "rinku jiji"),
        ("call rinku jiji through whatsapp", "rinku jiji"),
        ("call rinku jiji on whatsapp", "rinku jiji"),
        ("call rinku jiji via whatsapp", "rinku jiji"),
    ],
)
def test_whatsapp_call_intent_extracts_contact_name(task, contact_name):
    assert controller.is_whatsapp_call_request(task)
    assert controller.whatsapp_contact_from_task(task) == contact_name


def test_whatsapp_contact_result_must_be_a_standalone_ocr_line():
    assert controller.whatsapp_contact_result_visible(
        "Search: Rinku Jiji\nRinku Jiji",
        "rinku jiji",
    )
    assert not controller.whatsapp_contact_result_visible(
        "Search: Rinku Jiji",
        "rinku jiji",
    )


def test_exact_filename_check_rejects_appended_txt_extension():
    assert controller.screen_contains_exact_filename(
        "calculator.rust - Notepad",
        "calculator.rust",
    )
    assert not controller.screen_contains_exact_filename(
        "calculator.rust.txt - Notepad",
        "calculator.rust",
    )


def test_save_as_uses_visible_dialog_and_verifies_saved_filename(
    monkeypatch,
    capsys,
):
    hotkeys = []
    typed = []
    pressed = []
    screens = iter(
        [
            "Save As\nFile name:\nSave as type:\nSave\nCancel",
            'File name: "calculator.rust"\nSave as type:\nSave\nCancel',
            "calculator.rust - Notepad\nprint('calculator ready')",
        ]
    )
    active_window = type("Window", (), {"title": "Untitled - Notepad"})()
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", active_window)
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", True)
    monkeypatch.setattr(controller, "focus_active_app_window", lambda: True)
    monkeypatch.setattr(
        controller,
        "platform_hotkey",
        lambda *keys: hotkeys.append(keys),
    )
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        controller,
        "read_screen_text",
        lambda **_kwargs: next(screens),
    )
    monkeypatch.setattr(
        controller.pyautogui,
        "write",
        lambda text, **_kwargs: typed.append(text),
    )
    monkeypatch.setattr(
        controller.pyautogui,
        "press",
        lambda key: pressed.append(key),
    )
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Save As should use the active document, not invented paths")
        ),
    )

    controller.process_task("now save that file as calculator.rust")

    assert hotkeys == [("ctrl", "shift", "s"), ("ctrl", "a")]
    assert typed == ['"calculator.rust"']
    assert pressed == ["enter"]
    assert "Document window confirms the filename: calculator.rust" in capsys.readouterr().out


def test_save_as_does_not_type_without_visible_filename_field(monkeypatch, capsys):
    typed = []
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", object())
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", True)
    monkeypatch.setattr(controller, "focus_active_app_window", lambda: True)
    monkeypatch.setattr(controller, "platform_hotkey", lambda *_keys: None)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: "Notepad")
    monkeypatch.setattr(
        controller.pyautogui,
        "write",
        lambda text, **_kwargs: typed.append(text),
    )

    controller.process_task("save that file as calculator.rust")

    assert typed == []
    assert "filename field was not found" in capsys.readouterr().out


def test_failed_file_action_stops_later_actions(monkeypatch, capsys):
    hotkeys = []
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {
            "plan": "Open a file and copy its content",
            "actions": [
                {
                    "action": "open_file",
                    "path": "C:/Users/name/Documents/file.txt",
                },
                {"action": "select_all"},
                {"action": "copy"},
            ],
        },
    )
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", False)
    monkeypatch.setattr(
        controller,
        "platform_hotkey",
        lambda *keys: hotkeys.append(keys),
    )

    controller.process_task("open and copy the example file")

    assert hotkeys == []
    output = capsys.readouterr().out
    assert "File does not exist; refusing to open" in output
    assert "Later actions were not sent" in output


def test_failed_file_write_stops_later_actions(monkeypatch, capsys):
    later_actions = []
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {
            "plan": "Write a file and open it",
            "actions": [
                {
                    "action": "write_file",
                    "path": "C:/Users/name/Documents/calculator.rust",
                    "content": "code",
                },
                {"action": "type", "text": "should not be typed"},
            ],
        },
    )
    monkeypatch.setattr(controller, "ACTIVE_APP_CONTEXT_REQUIRED", False)
    monkeypatch.setattr(controller, "write_file_text", lambda *_args: False)
    monkeypatch.setattr(
        controller.pyautogui,
        "write",
        lambda text, **_kwargs: later_actions.append(text),
    )

    controller.process_task(
        "Create a Rust calculator and save as calculator.rust"
    )

    assert later_actions == []
    assert "Later actions were not sent" in capsys.readouterr().out


def test_open_path_uses_native_macos_opener(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        controller.subprocess,
        "Popen",
        lambda args: calls.append(args),
    )

    controller.open_path("/tmp/document.txt")

    assert calls == [["open", "/tmp/document.txt"]]


def test_finds_matching_windows_desktop_shortcut(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shortcut = desktop / "Brave.lnk"
    shortcut.touch()
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))

    assert controller.find_desktop_shortcut("brave") == shortcut


@pytest.mark.parametrize(
    ("requested_name", "shortcut_name"),
    [
        ("Brave browser", "Brave.lnk"),
        ("open WhatsApp app", "WhatsApp.lnk"),
        ("AB Download Manager", "AB Download Manager.lnk"),
        ("Blender 5.2", "Blender 5.2.lnk"),
        ("WinMemoryCleaner", "WinMemoryCleaner.exe"),
    ],
)
def test_finds_any_matching_desktop_app_shortcut(
    monkeypatch,
    tmp_path,
    requested_name,
    shortcut_name,
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shortcut = desktop / shortcut_name
    shortcut.touch()
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))

    assert controller.find_desktop_shortcut(requested_name) == shortcut


def test_ambiguous_shortcut_match_does_not_choose_random_app(
    monkeypatch,
    tmp_path,
    capsys,
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "Visual Studio Code.lnk").touch()
    (desktop / "Visual Studio Community.lnk").touch()
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))

    assert controller.find_desktop_shortcut("Visual Studio") is None
    assert "Multiple desktop shortcuts match" in capsys.readouterr().out


def test_app_launch_prefers_a_matching_desktop_shortcut(monkeypatch):
    calls = []
    shortcut = controller.Path("Brave.lnk")
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller, "find_desktop_shortcut", lambda _app: shortcut)
    monkeypatch.setattr(
        controller,
        "launch_from_desktop",
        lambda matched, app: calls.append((matched, app)) or True,
    )
    monkeypatch.setattr(
        controller.pyautogui,
        "hotkey",
        lambda *_keys: (_ for _ in ()).throw(
            AssertionError("Start-menu search must not be used when desktop shortcut exists")
        ),
    )

    controller.launch_app("brave")

    assert calls == [(shortcut, "brave")]


def test_desktop_shortcut_ocr_failure_opens_exact_shortcut_without_start_menu(
    monkeypatch,
    capsys,
):
    calls = []
    shortcut = controller.Path("WhatsApp.lnk")
    monkeypatch.setattr(controller.platform, "system", lambda: "Windows")
    monkeypatch.setattr(controller, "show_desktop", lambda: None)
    monkeypatch.setattr(
        controller,
        "click_text_on_screen",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        controller.os,
        "startfile",
        lambda path: calls.append(path),
        raising=False,
    )

    assert controller.launch_from_desktop(shortcut, "WhatsApp") is True
    assert calls == [str(shortcut)]
    assert "opening the exact matching desktop shortcut directly" in capsys.readouterr().out


def test_empty_model_action_list_is_preserved(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": '{"plan":"No safe next step","actions":[]}'}

    monkeypatch.setattr(controller.requests, "post", lambda *_args, **_kwargs: Response())

    assert controller.get_action_plan("continue") == {
        "plan": "No safe next step",
        "actions": [],
    }


def test_validate_action_plan_rejects_unknown_actions():
    with pytest.raises(ValueError):
        app_planner.validate_action_plan({
            "plan": "Bad plan",
            "actions": [{"action": "not_a_real_action", "text": "hi"}],
        })


def test_model_config_prefers_provider_environment_over_defaults(monkeypatch):
    monkeypatch.setenv("PC_ASSISTANT_PROVIDER", "openai")
    monkeypatch.setenv("PC_ASSISTANT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("PC_ASSISTANT_API_KEY", "secret-key")

    config = model_config.get_active_model_config()

    assert config.provider == "openai"
    assert config.model == "gpt-4o-mini"
    assert config.api_key == "secret-key"


def test_model_request_builds_openai_headers(monkeypatch):
    config = model_config.ModelConfig(
        provider="openai",
        model="gpt-4o-mini",
        api_key="token-123",
        base_url="https://api.openai.com/v1",
    )

    payload = model_config.build_provider_request(config, "hello there")

    assert payload["headers"]["Authorization"] == "Bearer token-123"
    assert payload["url"].startswith("https://api.openai.com/v1")


def test_click_text_can_double_click_matching_shortcut(monkeypatch):
    clicked = []
    image_data = {
        "text": ["WhatsApp"],
        "conf": ["95"],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
        "left": [10],
        "top": [20],
        "width": [40],
        "height": [12],
    }
    monkeypatch.setattr(controller.pyautogui, "screenshot", lambda: object())
    monkeypatch.setattr(
        controller.pytesseract,
        "image_to_data",
        lambda *_args, **_kwargs: image_data,
    )
    monkeypatch.setattr(
        controller.pyautogui,
        "doubleClick",
        lambda *args: clicked.append(args),
    )

    assert controller.click_text_on_screen("WhatsApp", clicks=2) is True
    assert clicked == [(30, 26)]


def test_linux_window_list_parses_and_activates_wmctrl_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        controller.shutil,
        "which",
        lambda name: "/usr/bin/wmctrl" if name == "wmctrl" else None,
    )
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda args, **_kwargs: type(
            "Result",
            (),
            {"stdout": "0x01200007  0 1234  Browser - Start Page\n"},
        )(),
    )

    windows = controller.get_all_windows()
    windows[0].activate()

    assert windows[0].title == "Browser - Start Page"


def test_linux_opens_files_using_xdg_open(monkeypatch):
    calls = []
    monkeypatch.setattr(controller.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        controller.shutil,
        "which",
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    )
    monkeypatch.setattr(
        controller.subprocess,
        "Popen",
        lambda args: calls.append(args),
    )

    controller.open_path("/tmp/document.txt")

    assert calls == [["/usr/bin/xdg-open", "/tmp/document.txt"]]


def test_process_task_runs_direct_command(monkeypatch):
    calls = {"task": None}

    def fake_execute_direct_command(task):
        calls["task"] = task
        return True

    monkeypatch.setattr(controller, "execute_direct_command", fake_execute_direct_command)
    controller.process_task("open app notepad")
    assert calls["task"] == "open app notepad"


def test_wait_for_app_window_does_not_capture_an_unrelated_new_window(monkeypatch):
    class Window:
        title = "YouTube - Google Chrome"

        def activate(self):
            raise AssertionError("An unrelated window must not be activated")

    monkeypatch.setattr(controller.gw, "getAllWindows", lambda: [Window()])
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", None)

    assert controller.wait_for_app_window("brave", timeout=0.01) is False
    assert controller.ACTIVE_APP_WINDOW is None


def test_click_text_clicks_ocr_matched_text(monkeypatch):
    clicked = []
    image_data = {
        "text": ["Create", "Project"],
        "conf": ["95", "92"],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
        "left": [10, 45],
        "top": [20, 20],
        "width": [30, 40],
        "height": [12, 12],
    }
    monkeypatch.setattr(controller.pyautogui, "screenshot", lambda: object())
    monkeypatch.setattr(
        controller.pytesseract,
        "image_to_data",
        lambda *_args, **_kwargs: image_data,
    )
    monkeypatch.setattr(controller.pyautogui, "click", lambda *args: clicked.append(args))

    assert controller.click_text_on_screen("Create Project") is True
    assert clicked == [(47, 26)]


def test_named_browser_task_routes_url_to_requested_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller,
        "get_action_plan",
        lambda _task: {
            "plan": "Open YouTube in Brave",
            "actions": [
                {"action": "open_app_search", "app": "chrome"},
                {"action": "open_url", "url": "https://www.youtube.com"},
            ],
        },
    )
    monkeypatch.setattr(
        controller,
        "execute_action",
        lambda step, **_kwargs: calls.append(step),
    )

    controller.process_task("open YouTube in Brave")

    assert calls[0] == {"action": "open_app_search", "app": "brave"}
    assert calls[1] == {
        "action": "open_url",
        "url": "https://www.youtube.com",
        "browser": "brave",
    }


def test_app_task_replans_from_ocr_and_rejects_guessed_coordinates(monkeypatch, capsys):
    calls = []
    plans = iter(
        [
            {
                "plan": "Open CapCut and create a project",
                "actions": [
                    {"action": "open_app_search", "app": "CapCut"},
                    {"action": "wait", "seconds": 2},
                    {"action": "click", "x": 100, "y": 100},
                ],
            },
            {
                "plan": "Click the visible create-project control",
                "actions": [
                    {"action": "click_text", "text": "New project"},
                    {"action": "click", "x": 100, "y": 100},
                ],
            },
            {
                "plan": "No more action is needed",
                "actions": [],
            },
        ]
    )
    app_window = object()

    def fake_execute_action(step, **_kwargs):
        calls.append(step)
        if step.get("action") == "open_app_search":
            monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", app_window)

    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "execute_action", fake_execute_action)
    monkeypatch.setattr(
        controller,
        "read_screen_text",
        lambda **_kwargs: "New project",
    )

    controller.process_task("open CapCut and create a new project")

    assert [call.get("action") for call in calls] == [
        "open_app_search",
        "wait",
        "click_text",
    ]
    output = capsys.readouterr().out
    assert "Refusing ungrounded coordinate action" in output
    assert "requested result has not been confirmed" in output


def test_editor_replan_preserves_pending_code_actions(monkeypatch, capsys):
    code = "print('calculator ready')"
    calls = []
    plans = {
        "plan": "Open Notepad and create a Python calculator",
        "actions": [
            {"action": "open_app_search", "app": "Notepad"},
            {"action": "wait", "seconds": 2},
            {"action": "type", "text": code},
        ],
    }
    app_window = object()

    def fake_execute_action(step, **_kwargs):
        calls.append(step)
        if step.get("action") == "open_app_search":
            monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", app_window)

    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: plans)
    monkeypatch.setattr(
        controller,
        "generate_source_code",
        lambda _task, _path: code + "\n",
    )
    monkeypatch.setattr(controller, "execute_action", fake_execute_action)

    controller.process_task(
        "open notepad with new file and create calculator by using python language"
    )

    assert [call.get("action") for call in calls] == [
        "open_app_search",
        "wait",
        "write_file",
        "open_file",
    ]
    assert calls[2]["content"] == code + "\n"
    assert calls[3]["path"] == calls[2]["path"]
    assert calls[3]["app"] == "Notepad"
    assert "Actions finished" in capsys.readouterr().out


def test_missing_text_target_stops_followup_actions(monkeypatch, capsys):
    calls = []
    plans = iter(
        [
            {
                "plan": "Open WhatsApp and call the contact",
                "actions": [
                    {"action": "open_app_search", "app": "WhatsApp"},
                    {"action": "wait", "seconds": 2},
                    {"action": "click_text", "text": "New Call"},
                    {"action": "type", "text": "Rinku jiji"},
                ],
            },
            {
                "plan": "Find the contact",
                "actions": [
                    {"action": "click_text", "text": "New Call"},
                    {"action": "type", "text": "Rinku jiji"},
                ],
            },
        ]
    )
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", object())
    monkeypatch.setattr(
        controller,
        "execute_action",
        lambda step: calls.append(step) or (
            False if step.get("action") == "click_text" else True
        ),
    )
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: "WhatsApp")

    controller.process_task("open WhatsApp and call Rinku jiji")

    assert [call["action"] for call in calls] == ["open_app_search", "wait"]
    assert "named contact has not been opened" in capsys.readouterr().out


def test_whatsapp_call_guides_an_already_open_app_one_action_at_a_time(
    monkeypatch,
    capsys,
):
    calls = []
    plans = iter(
        [
            {
                "plan": "Call Rinku",
                "actions": [
                    {"action": "wait", "seconds": 2},
                    {"action": "type", "text": "Rinku Jiji"},
                ],
            },
            {
                "plan": "Search for Rinku and call",
                "actions": [{"action": "hotkey", "keys": ["ctrl", "f"]}],
            },
            {
                "plan": "Enter the contact name",
                "actions": [{"action": "type", "text": "Rinku Jiji"}],
            },
            {
                "plan": "Open the exact contact",
                "actions": [{"action": "press_key", "key": "enter"}],
            },
            {
                "plan": "Call the open contact",
                "actions": [{"action": "click_text", "text": "Video Call"}],
            },
        ]
    )
    screens = iter(
        [
            "Chats\nSearch",
            "Search or start a new chat",
            "Search: Rinku Jiji\nRinku Jiji",
            "Rinku Jiji\nVideo Call",
            "Video calling Rinku Jiji\nEnd call",
        ]
    )
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "execute_action", lambda step: calls.append(step) or True)
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: next(screens))
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    controller.process_task("call rinku jiji through whatsapp")

    assert calls == [
        {"action": "wait", "seconds": 2},
        {"action": "hotkey", "keys": ["ctrl", "f"]},
        {"action": "type", "text": "Rinku Jiji"},
        {"action": "click_text", "text": "rinku jiji"},
        {"action": "click_text", "text": "Video Call"},
    ]
    output = capsys.readouterr().out
    assert "Replacing Enter with an exact visible contact selection" in output
    assert "WhatsApp shows the call in progress" in output


def test_whatsapp_call_retries_when_initial_screen_text_is_empty(monkeypatch, capsys):
    calls = []
    plans = iter(
        [
            {
                "plan": "Open WhatsApp and call Rinku",
                "actions": [
                    {"action": "open_app_search", "app": "WhatsApp"},
                    {"action": "wait", "seconds": 2},
                    {"action": "click_text", "text": "Search"},
                ],
            },
            {
                "plan": "Open search",
                "actions": [{"action": "click_text", "text": "Search"}],
            },
            {"plan": "Done", "actions": []},
        ]
    )
    screens = iter(["", "Search", "Search"])
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", object())
    monkeypatch.setattr(
        controller,
        "execute_action",
        lambda step: calls.append(step) or True,
    )
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: next(screens))
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    controller.process_task(
        "open WhatsApp and call Rinku",
    )

    assert [step["action"] for step in calls] == [
        "open_app_search",
        "wait",
        "click_text",
    ]
    assert "retrying after a short wait" in capsys.readouterr().out


def test_whatsapp_call_does_not_type_without_visible_search_field(
    monkeypatch,
    capsys,
):
    calls = []
    plans = iter(
        [
            {
                "plan": "Call Rinku",
                "actions": [
                    {"action": "wait", "seconds": 2},
                    {"action": "type", "text": "Rinku Jiji"},
                ],
            },
            {
                "plan": "Type the contact",
                "actions": [{"action": "type", "text": "Rinku Jiji"}],
            },
        ]
    )
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(
        controller,
        "execute_action",
        lambda step: calls.append(step) or True,
    )
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: "Chats")
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    controller.process_task("call rinku jiji through whatsapp")

    assert calls == [{"action": "wait", "seconds": 2}]
    assert "no WhatsApp search field is visible" in capsys.readouterr().out


def test_whatsapp_call_selects_contact_before_visible_call_control(
    monkeypatch,
    capsys,
):
    calls = []
    screens = iter(
        [
            "Search or start a new chat",
            "Search or start a new chat",
            "Search: Rinku jiji\nRinku jiji",
            "Rinku jiji\nVideo Call",
            "Video calling Rinku jiji\nEnd call",
        ]
    )
    plans = iter(
        [
            {
                "plan": "Open WhatsApp and video call Rinku jiji",
                "actions": [
                    {"action": "open_app_search", "app": "WhatsApp"},
                    {"action": "wait", "seconds": 2},
                    {
                        "action": "click_text",
                        "text": "Search or start a new chat",
                    },
                ],
            },
            {
                "plan": "Search and start the video call",
                "actions": [
                    {"action": "click_text", "text": "Search or start a new chat"},
                    {"action": "type", "text": "Rinku jiji"},
                    {"action": "press_key", "key": "enter"},
                    {"action": "wait", "seconds": 2},
                    {"action": "click_text", "text": "Video Call"},
                ],
            },
            {
                "plan": "Enter the contact name",
                "actions": [{"action": "type", "text": "Rinku jiji"}],
            },
            {
                "plan": "Show the matching contact",
                "actions": [{"action": "press_key", "key": "enter"}],
            },
            {
                "plan": "Call the contact",
                "actions": [{"action": "click_text", "text": "Video Call"}],
            },
        ]
    )
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", object())

    def fake_execute_action(step):
        calls.append(step)
        return True

    monkeypatch.setattr(controller, "execute_action", fake_execute_action)
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: next(screens))

    controller.process_task("open whatsapp and video call rinku jiji")

    assert [call.get("action") for call in calls] == [
        "open_app_search",
        "wait",
        "click_text",
        "type",
        "click_text",
        "click_text",
    ]
    assert calls[-2] == {"action": "click_text", "text": "rinku jiji"}
    assert calls[-1] == {"action": "click_text", "text": "Video Call"}
    output = capsys.readouterr().out
    assert "Replacing Enter with an exact visible contact selection" in output
    assert "WhatsApp shows the call in progress" in output


def test_whatsapp_call_never_clicks_call_before_contact_is_open(
    monkeypatch,
    capsys,
):
    calls = []
    plans = iter(
        [
            {
                "plan": "Open WhatsApp and call Rinku",
                "actions": [
                    {"action": "open_app_search", "app": "WhatsApp"},
                    {"action": "wait", "seconds": 2},
                    {"action": "click_text", "text": "Search"},
                ],
            },
            {
                "plan": "Click the visible video call button",
                "actions": [{"action": "click_text", "text": "Video Call"}],
            },
            {
                "plan": "Now use the visible call control",
                "actions": [{"action": "click_text", "text": "Video Call"}],
            },
        ]
    )
    screens = iter(
        [
            "Search\nRinku\nVideo Call",
            "Rinku\nVideo Call",
            "Calling Rinku\nEnd call",
        ]
    )
    monkeypatch.setattr(controller, "get_action_plan", lambda _prompt: next(plans))
    monkeypatch.setattr(controller, "ACTIVE_APP_WINDOW", object())
    monkeypatch.setattr(
        controller,
        "execute_action",
        lambda step: calls.append(step) or True,
    )
    monkeypatch.setattr(controller, "read_screen_text", lambda **_kwargs: next(screens))

    controller.process_task("open whatsapp and video call Rinku")

    contact_click_index = calls.index({"action": "click_text", "text": "Rinku"})
    call_click_index = calls.index({"action": "click_text", "text": "Video Call"})
    assert contact_click_index < call_click_index
    assert "Selecting the exact visible contact" in capsys.readouterr().out
