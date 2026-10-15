from __future__ import annotations

NATIVE_UI_AVAILABLE = False


def resolve_native_ui():
    try:
        import uiautomation as automation
    except Exception:
        return None

    def find_element_by_name(target_text: str, app_title: str | None = None):
        target = (target_text or "").strip()
        if not target:
            return None
        root = automation.GetRootControl()
        try:
            iterable = list(root.Descendants())
        except Exception:
            iterable = []
        for element in iterable:
            try:
                name = getattr(element, "Name", "") or ""
            except Exception:
                name = ""
            if isinstance(name, str) and target.lower() in name.lower():
                return element
        return None

    return {"automation": automation, "find_element_by_name": find_element_by_name}


def try_click_element_by_name(target_text: str, app_title: str | None = None) -> bool:
    native_ui = resolve_native_ui()
    if native_ui is None:
        return False

    element = native_ui["find_element_by_name"](target_text, app_title)
    if element is None:
        return False

    try:
        for handler_name in ("Click", "click", "Invoke", "invoke"):
            try:
                handler = getattr(element, handler_name)
            except AttributeError:
                continue
            if callable(handler):
                handler()
                return True
    except Exception:
        return False
    return False
