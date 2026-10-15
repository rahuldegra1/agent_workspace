from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


VISUAL_ACTIONS = {
    "click", "click_text", "double_click", "right_click", "type",
    "press_key", "hotkey", "key_sequence", "open_app_search", "open_url",
    "search_web", "focus_window", "click_image", "scroll",
}
ERROR_TERMS = re.compile(r"\b(?:error|exception|failed|failure|not responding|unexpected)\b", re.IGNORECASE)
DIALOG_TERMS = re.compile(r"\b(?:dialog|warning|retry|cancel|close|dismiss|unexpected|not responding)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Milestone:
    goal: str
    action_indices: tuple[int, ...]


class Director:
    def decompose(self, task: str, actions: list[dict[str, Any]], proposed=None) -> list[Milestone]:
        milestones = self._validated_proposal(proposed, len(actions))
        if milestones:
            return milestones
        return self._derive_milestones(task, actions)

    @staticmethod
    def _validated_proposal(proposed, action_count: int) -> list[Milestone]:
        if not isinstance(proposed, list):
            return []
        milestones = []
        indices = []
        for item in proposed:
            if not isinstance(item, dict):
                return []
            goal = str(item.get("goal", "")).strip()
            action_indices = item.get("action_indices")
            if not goal or not isinstance(action_indices, list) or not action_indices:
                return []
            if any(type(index) is not int or index < 0 or index >= action_count for index in action_indices):
                return []
            indices.extend(action_indices)
            milestones.append(Milestone(goal, tuple(action_indices)))
        if indices != list(range(action_count)):
            return []
        return milestones

    @staticmethod
    def _derive_milestones(task: str, actions: list[dict[str, Any]]) -> list[Milestone]:
        milestones = []
        pending = []

        def flush():
            if not pending:
                return
            names = [str(actions[index].get("action", "action")).replace("_", " ") for index in pending]
            milestones.append(Milestone(f"{task}: {', '.join(names)}", tuple(pending)))
            pending.clear()

        terminal_actions = {"write_file", "run_command", "open_file", "open_folder", "open_url", "search_web"}
        for index, step in enumerate(actions):
            name = step.get("action")
            if name in {"open_app_search", *terminal_actions}:
                flush()
                pending.append(index)
                flush()
                continue
            pending.append(index)
            if name == "wait" or len(pending) >= 3:
                flush()
        flush()
        return milestones


class Critic:
    @staticmethod
    def evaluate_milestone(actions, results, before=None, after=None) -> str:
        if not actions or len(actions) != len(results) or not all(results):
            return "failed"
        has_visual_actions = any(step.get("action") in VISUAL_ACTIONS for step in actions)
        if has_visual_actions and before is not None and after is not None:
            observed = any(before.get(key) for key in ("hash", "active_title", "ocr_text"))
            unchanged = observed and all(
                before.get(key) == after.get(key)
                for key in ("hash", "active_title", "ocr_text")
            )
            if unchanged:
                return "stalled"
        return "completed"

    @staticmethod
    def is_error_dialog(screen_text: str) -> bool:
        return bool(ERROR_TERMS.search(screen_text or "") and DIALOG_TERMS.search(screen_text or ""))

    @staticmethod
    def can_close_error_window(window_title: str, screen_text: str) -> bool:
        return bool(
            Critic.is_error_dialog(screen_text)
            and re.search(r"\b(?:error|exception|warning|not responding)\b", window_title or "", re.IGNORECASE)
        )


class Actor:
    def __init__(self, executor):
        self._executor = executor

    def execute(self, action: dict[str, Any]):
        return self._executor(action)


class ExecutionTree:
    def __init__(self, milestones: list[Milestone], max_recovery_branches: int = 2):
        self.milestones = milestones
        self.max_recovery_branches = max_recovery_branches
        self.nodes: list[dict[str, Any]] = [{"id": 0, "parent_id": None, "kind": "root", "status": "active"}]
        self.last_successful_checkpoint = 0
        self.recovery_branches: dict[int, int] = {}
        self._milestone_results: dict[int, list[bool]] = {}
        self._pending_recovery_branch: int | None = None

    def record_action(self, milestone_index: int, action: dict[str, Any], succeeded: bool) -> int:
        parent_id = self.last_successful_checkpoint
        node_id = len(self.nodes)
        self.nodes.append({
            "id": node_id,
            "parent_id": parent_id,
            "kind": "action",
            "milestone_index": milestone_index,
            "action": dict(action),
            "status": "completed" if succeeded else "failed",
        })
        self._milestone_results.setdefault(milestone_index, []).append(bool(succeeded))
        return node_id

    def checkpoint(self, milestone_index: int, critic_status: str, state=None) -> int:
        milestone = self.milestones[milestone_index]
        node_id = len(self.nodes)
        self.nodes.append({
            "id": node_id,
            "parent_id": self.last_successful_checkpoint,
            "kind": "checkpoint",
            "milestone_index": milestone_index,
            "goal": milestone.goal,
            "status": critic_status,
            "state": state,
        })
        if critic_status == "completed":
            self.last_successful_checkpoint = node_id
        return node_id

    def add_recovery_branch(self, milestone_index: int, actions: list[dict[str, Any]], state=None) -> int | None:
        used = self.recovery_branches.get(milestone_index, 0)
        if used >= self.max_recovery_branches:
            return None
        self.recovery_branches[milestone_index] = used + 1
        node_id = len(self.nodes)
        self.nodes.append({
            "id": node_id,
            "parent_id": self.last_successful_checkpoint,
            "kind": "recovery",
            "milestone_index": milestone_index,
            "actions": [dict(action) for action in actions],
            "status": "candidate",
            "state": state,
        })
        self._pending_recovery_branch = node_id
        return node_id

    def resolve_recovery_branch(self, status: str) -> None:
        if self._pending_recovery_branch is None:
            return
        self.nodes[self._pending_recovery_branch]["status"] = status
        self._pending_recovery_branch = None

    def recovery_context(self) -> str:
        checkpoint = self.nodes[self.last_successful_checkpoint]
        return str(checkpoint.get("goal", "No successful milestone checkpoint yet."))
