from __future__ import annotations

import ctypes
import os
import platform
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

import controller
import model_config

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    ImageFont = None

# Configure CustomTkinter theme globally for a modern look
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class AssistantDesktopApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        if not controller.emergency_stop.start_emergency_stop():
            print(" -> Emergency hotkey unavailable; check OS keyboard-hook permissions")
        
        self.root.title("PC Assistant")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        
        # Safely route the X button to the tray minimizing function
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        self.provider_var = ctk.StringVar(value="ollama")
        self.model_var = ctk.StringVar(value="pc-agent")
        self.api_key_var = ctk.StringVar(value="")
        self.base_url_var = ctk.StringVar(value="")
        self.profile_name_var = ctk.StringVar(value="default")
        self.startup_var = ctk.BooleanVar(value=model_config.get_startup_enabled())
        self.profiles = model_config.load_saved_profiles()

        self.tray_icon = None
        self._build_ui()
        self._load_saved_model()
        self._configure_tray()

        # Initial welcome message in the chat
        self.add_message("Hello! I am your PC Assistant. What would you like me to automate today?", sender="assistant")

    def _build_ui(self):
        # Configure main grid layout (1 row, 2 columns: Sidebar + Chat)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        # ==========================================
        # 1. Sidebar (Settings & Profiles)
        # ==========================================
        sidebar = ctk.CTkFrame(self.root, width=300, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(9, weight=1) 
        
        label_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")

        ctk.CTkLabel(sidebar, text="Settings", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 15), sticky="w")
        
        ctk.CTkLabel(sidebar, text="Provider", font=label_font).grid(row=1, column=0, sticky="w", padx=20, pady=(5, 2))
        provider_box = ctk.CTkComboBox(
            sidebar,
            variable=self.provider_var,
            values=["ollama", "openai", "gemini", "anthropic", "openai_compatible"],
            state="readonly",
            width=260
        )
        provider_box.grid(row=2, column=0, padx=20, pady=(0, 10))

        ctk.CTkLabel(sidebar, text="Model", font=label_font).grid(row=3, column=0, sticky="w", padx=20, pady=(5, 2))
        ctk.CTkEntry(sidebar, textvariable=self.model_var, width=260).grid(row=4, column=0, padx=20, pady=(0, 10))

        ctk.CTkLabel(sidebar, text="API key", font=label_font).grid(row=5, column=0, sticky="w", padx=20, pady=(5, 2))
        ctk.CTkEntry(sidebar, textvariable=self.api_key_var, show="*", width=260).grid(row=6, column=0, padx=20, pady=(0, 10))

        ctk.CTkLabel(sidebar, text="Base URL", font=label_font).grid(row=7, column=0, sticky="w", padx=20, pady=(5, 2))
        ctk.CTkEntry(sidebar, textvariable=self.base_url_var, width=260).grid(row=8, column=0, padx=20, pady=(0, 10))

        # Bottom section of sidebar for Profiles and Startup
        bottom_sidebar = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom_sidebar.grid(row=9, column=0, sticky="s", pady=20)
        
        ctk.CTkLabel(bottom_sidebar, text="Profile name", font=label_font).pack(anchor="w", padx=20, pady=(0, 2))
        ctk.CTkEntry(bottom_sidebar, textvariable=self.profile_name_var, width=260).pack(padx=20, pady=(0, 10))

        btn_frame = ctk.CTkFrame(bottom_sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkButton(btn_frame, text="Save Model", command=self.save_model, width=125).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_frame, text="Save Profile", command=self.save_profile, width=125).pack(side="right", padx=(5, 0))

        ctk.CTkLabel(bottom_sidebar, text="Load Profile", font=label_font).pack(anchor="w", padx=20, pady=(5, 2))
        
        profile_values = [profile.get("name", "default") for profile in self.profiles]
        self.profile_dropdown = ctk.CTkComboBox(
            bottom_sidebar,
            values=profile_values if profile_values else ["default"],
            state="readonly",
            width=260,
            command=lambda choice: self.load_selected_profile(choice)
        )
        self.profile_dropdown.pack(padx=20, pady=(0, 15))

        startup_check = ctk.CTkCheckBox(
            bottom_sidebar,
            text="Start on Windows login",
            variable=self.startup_var,
            command=self.toggle_startup,
            font=label_font
        )
        startup_check.pack(anchor="w", padx=20, pady=(0, 10))

        # ==========================================
        # 2. Main Chat Area
        # ==========================================
        main_area = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.grid_rowconfigure(0, weight=1)
        main_area.grid_columnconfigure(0, weight=1)

        # Chat history scrollable frame
        self.chat_history = ctk.CTkScrollableFrame(main_area, fg_color="transparent")
        self.chat_history.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 10))
        self.chat_history.grid_columnconfigure(0, weight=1)

        # Input box and send button
        input_frame = ctk.CTkFrame(main_area, corner_radius=20, border_width=1, border_color=("gray75", "gray25"))
        input_frame.grid(row=1, column=0, sticky="ew", padx=40, pady=(0, 20))
        input_frame.grid_columnconfigure(0, weight=1)
        input_frame.grid_rowconfigure(0, weight=1)

        self.task_box = ctk.CTkTextbox(
            input_frame, 
            height=50, 
            wrap="word", 
            corner_radius=20, 
            fg_color="transparent", 
            border_width=0, 
            font=ctk.CTkFont(size=14)
        )
        self.task_box.grid(row=0, column=0, sticky="nsew", padx=15, pady=10)
        
        # Keybindings for chat-like input
        self.task_box.bind("<Return>", self._handle_enter_key)
        self.task_box.bind("<Shift-Return>", self._handle_shift_enter)

        self.send_btn = ctk.CTkButton(
            input_frame, 
            text="Send", 
            width=80, 
            height=40, 
            corner_radius=15, 
            font=ctk.CTkFont(weight="bold"), 
            command=self.run_task
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="s")

    def _handle_enter_key(self, event):
        self.run_task()
        return "break" # Prevents default newline on Enter
        
    def _handle_shift_enter(self, event):
        self.task_box.insert("insert", "\n")
        return "break"

    def add_message(self, text: str, sender: str = "user") -> ctk.CTkLabel:
        """Adds a chat bubble to the UI and returns the label so it can be updated."""
        msg_frame = ctk.CTkFrame(self.chat_history, fg_color="transparent")
        msg_frame.grid(column=0, sticky="ew", pady=8, padx=10)
        msg_frame.grid_columnconfigure(0, weight=1)
        msg_frame.grid_columnconfigure(1, weight=1)

        is_user = (sender == "user")
        
        # Color styling mimicking modern conversational UIs
        bubble_color = ("#007AFF", "#0d47a1") if is_user else ("#e5e5ea", "#2c2c2e")
        text_color = ("white", "white") if is_user else ("black", "white")

        bubble = ctk.CTkFrame(msg_frame, corner_radius=18, fg_color=bubble_color)
        
        label = ctk.CTkLabel(
            bubble, 
            text=text, 
            text_color=text_color, 
            justify="left", 
            wraplength=550,
            font=ctk.CTkFont(size=14)
        )
        label.pack(padx=18, pady=12)

        # Align User to the right, Assistant to the left
        if is_user:
            bubble.grid(row=0, column=1, sticky="e")
        else:
            bubble.grid(row=0, column=0, sticky="w")
            
        # Auto-scroll to the bottom of the chat
        self.chat_history.update_idletasks()
        self.chat_history._parent_canvas.yview_moveto(1.0)
        return label

    def run_task(self):
        task = self.task_box.get("1.0", "end-1c").strip()
        if not task:
            return

        # Clear input and display user message
        self.task_box.delete("1.0", "end")
        self.add_message(task, sender="user")
        
        # Display initial assistant status bubble
        status_label = self.add_message("Executing task...", sender="assistant")
        self.root.update_idletasks()

        # Execute in a background thread to prevent UI freezing
        def worker():
            try:
                controller.process_task(task)
                # Update the existing bubble when finished
                self.root.after(0, lambda: status_label.configure(text="Task completed."))
            except Exception as exc:
                self.root.after(0, lambda e=exc: status_label.configure(text=f"Error: {e}"))
            finally:
                self.root.after(0, lambda: self.chat_history._parent_canvas.yview_moveto(1.0))

        threading.Thread(target=worker, daemon=True).start()

    # ==========================================
    # Tray and System Functions (Unchanged)
    # ==========================================
    def _create_tray_icon(self):
        if pystray is None:
            return None

        def action_show():
            self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

        def action_hide():
            self.root.after(0, self.minimize_to_tray)

        def action_exit():
            self.root.after(0, self.quit_application)

        icon = pystray.Icon(
            "PC Assistant",
            icon=self._build_tray_image(),
            title="PC Assistant",
            menu=pystray.Menu(
                pystray.MenuItem("Show", action_show, default=True),
                pystray.MenuItem("Hide", action_hide),
                pystray.MenuItem("Exit", action_exit),
            ),
        )
        return icon

    def _configure_tray(self):
        if pystray is None:
            return
        self.tray_icon = self._create_tray_icon()
        if self.tray_icon:
            self.root.after(100, self._toggle_tray_visibility)

    def _toggle_tray_visibility(self):
        if self.tray_icon is not None:
            self.tray_icon.run_detached()

    def _build_tray_image(self):
        if Image is None or ImageDraw is None:
            return None
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 54, 54), fill="#1d4ed8")
        draw.text((18, 18), "AI", fill="white")
        return image

    def minimize_to_tray(self):
        if self.tray_icon is not None:
            self.root.withdraw()
            return
        self.quit_application()

    def quit_application(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        try:
            self.root.destroy()
        except Exception:
            pass

    def _load_saved_model(self):
        config = model_config.get_active_model_config()
        self.provider_var.set(config.provider)
        self.model_var.set(config.model)
        self.api_key_var.set(config.api_key)
        self.base_url_var.set(config.base_url)
        self.profile_name_var.set("default")
        if self.profile_dropdown is not None:
            values = [profile.get("name", "default") for profile in self.profiles]
            self.profile_dropdown.configure(values=values)
            if values:
                self.profile_dropdown.set(values[0])

    def save_model(self):
        config = model_config.ModelConfig(
            provider=self.provider_var.get(),
            model=self.model_var.get(),
            api_key=self.api_key_var.get(),
            base_url=self.base_url_var.get(),
        )
        model_config.save_model_config(config)

    def save_profile(self):
        config = model_config.ModelConfig(
            provider=self.provider_var.get(),
            model=self.model_var.get(),
            api_key=self.api_key_var.get(),
            base_url=self.base_url_var.get(),
        )
        updated_profiles = model_config.save_named_profile(self.profile_name_var.get(), config)
        self.profiles = updated_profiles
        values = [profile.get("name", "default") for profile in self.profiles]
        self.profile_dropdown.configure(values=values)

    def load_selected_profile(self, choice=None):
        selected = choice if choice else self.profile_dropdown.get()
        if not selected:
            return
        for profile in self.profiles:
            if profile.get("name") == selected:
                config = model_config.ModelConfig.from_dict(profile)
                self.provider_var.set(config.provider)
                self.model_var.set(config.model)
                self.api_key_var.set(config.api_key)
                self.base_url_var.set(config.base_url)
                return

    def toggle_startup(self):
        enabled = bool(self.startup_var.get())
        model_config.set_startup_enabled(enabled)
        if platform.system() == "Windows":
            self._configure_windows_startup(enabled)

    def _configure_windows_startup(self, enabled: bool):
        try:
            import winreg
        except ImportError:
            return
        startup_key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        app_path = os.path.abspath(__file__)
        if enabled:
            winreg.SetValueEx(startup_key, "PC Assistant", 0, winreg.REG_SZ, f'"{app_path}"')
        else:
            try:
                winreg.DeleteValue(startup_key, "PC Assistant")
            except FileNotFoundError:
                pass
        startup_key.Close()

    def _authorize_command(self, command: str, reason: str) -> bool:
        decision = []
        response_ready = threading.Event()

        def show_prompt():
            try:
                decision.append(messagebox.askyesno(
                    "Authorize command",
                    f"{command}\n\nReason: {reason}\n\nAllow this command?",
                    parent=self.root,
                    default="no",
                ))
            except Exception:
                decision.append(False)
            finally:
                response_ready.set()

        try:
            self.root.after(0, show_prompt)
        except Exception:
            return False
        return response_ready.wait(timeout=120) and bool(decision and decision[0])


def acquire_single_instance_lock(lock_name="PC_Assistant_SingleInstance_Mutex"):
    """Prevent multiple instances on Windows, or return True on other OS."""
    if platform.system() == "Windows":
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, lock_name)
        last_error = kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            return None  
        return mutex
    return True


def main():
    mutex = acquire_single_instance_lock()
    if mutex is None:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(
                "PC Assistant",
                "PC Assistant is already running in your system tray.\n\nCheck the icons near your clock.",
            )
            root.destroy()
        except Exception:
            pass
        return

    root = ctk.CTk()
    app = AssistantDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()