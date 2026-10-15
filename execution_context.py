from dataclasses import dataclass
from typing import Any


@dataclass
class ExecutionContext:
    active_app_window: Any = None
    active_app_context_required: bool = False

    @property
    def active_app_window_title(self) -> str:
        return getattr(self.active_app_window, "title", "")

    def update_window(self, app_window: Any) -> None:
        self.active_app_window = app_window
        self.active_app_context_required = True


class Agent:
    """Small runtime wrapper that keeps execution state in one object instead of globals."""

    def __init__(self, context: ExecutionContext | None = None):
        self.context = context or ExecutionContext()

    @property
    def active_app_window(self) -> Any:
        return self.context.active_app_window

    @active_app_window.setter
    def active_app_window(self, value: Any) -> None:
        self.context.update_window(value)

    @property
    def active_app_window_title(self) -> str:
        return self.context.active_app_window_title

    def mark_app_context_required(self, required: bool = True) -> None:
        self.context.active_app_context_required = required

    def sync_window(self, app_window: Any) -> None:
        self.context.update_window(app_window)
