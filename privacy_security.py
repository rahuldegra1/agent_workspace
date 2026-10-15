import re


SENSITIVE_LABEL_RE = re.compile(
    r"\b(?:password|passwd|passcode|pin|one[ -]?time code|otp|"
    r"api[ _-]?key|secret|access[ _-]?token|refresh[ _-]?token|"
    r"session(?:[ _-]?id|[ _-]?token)?|authorization|bearer|"
    r"cvv|cvc|security code|card number|account number|routing number|"
    r"iban|sort code|social security|\bssn\b)\b",
    re.IGNORECASE,
)
BANKING_LABEL_RE = re.compile(
    r"\b(?:bank|payment|account|routing|iban|sort code|credit card|debit card)\b",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}\b|\bAIza[A-Za-z0-9_-]{20,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]+=*|"
    r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]*?){13,19}\b|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)
LABELED_VALUE_RE = re.compile(
    r"(password|passwd|passcode|pin|one[ -]?time code|otp|api[ _-]?key|"
    r"secret|access[ _-]?token|refresh[ _-]?token|session(?:[ _-]?id|[ _-]?token)?|"
    r"authorization|bearer|cvv|cvc|security code|card number|account number|"
    r"routing number|iban|sort code|social security|ssn)"
    r"(\s*[:=]\s*|\s+)([^\r\n,;]{1,160})",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\w)")


def _rect_from_control(control):
    try:
        bounds = control.BoundingRectangle
        rectangle = (int(bounds.left), int(bounds.top), int(bounds.right), int(bounds.bottom))
        if rectangle[2] > rectangle[0] and rectangle[3] > rectangle[1]:
            return rectangle
    except Exception:
        pass
    return None


def get_ui_protected_rectangles() -> list[tuple[int, int, int, int]]:
    """Return visible password-control and notification rectangles from UIA."""
    try:
        import uiautomation

        root = uiautomation.GetRootControl()
        controls = root.Descendants()
    except Exception:
        return []

    rectangles = []
    for control in controls:
        try:
            if getattr(control, "IsPassword", False):
                rectangle = _rect_from_control(control)
                if rectangle:
                    rectangles.append(rectangle)
                continue

            metadata = " ".join(
                str(getattr(control, attribute, "") or "")
                for attribute in ("Name", "ClassName", "AutomationId", "ControlTypeName")
            ).casefold()
            if any(term in metadata for term in ("notification", "toast", "action center")):
                rectangle = _rect_from_control(control)
                if rectangle:
                    rectangles.append(rectangle)
        except Exception:
            continue
    return rectangles


def _ocr_lines(data: dict) -> list[dict]:
    required = ("text", "left", "top", "width", "height")
    if not all(key in data for key in required):
        return []
    lines = {}
    for index, raw_text in enumerate(data["text"]):
        text = str(raw_text or "").strip()
        if not text:
            continue
        try:
            key = tuple(data.get(name, [0] * len(data["text"]))[index] for name in (
                "block_num", "par_num", "line_num"
            ))
            left = int(data["left"][index])
            top = int(data["top"][index])
            right = left + int(data["width"][index])
            bottom = top + int(data["height"][index])
        except (IndexError, TypeError, ValueError):
            continue
        line = lines.setdefault(key, {"text": [], "left": left, "top": top, "right": right, "bottom": bottom})
        line["text"].append(text)
        line["left"] = min(line["left"], left)
        line["top"] = min(line["top"], top)
        line["right"] = max(line["right"], right)
        line["bottom"] = max(line["bottom"], bottom)
    result = []
    for key, line in lines.items():
        line["key"] = key
        line["text"] = " ".join(line["text"])
        result.append(line)
    return sorted(result, key=lambda line: (line["top"], line["left"]))


def redact_screenshot(image, ocr_data: dict, native_rectangles=()):
    """Mask sensitive OCR layout and native UI regions; return image and boxes."""
    from PIL import ImageDraw

    lines = _ocr_lines(ocr_data or {})
    sensitive_lines = [line for line in lines if SENSITIVE_LABEL_RE.search(line["text"])]
    banking_lines = [line for line in lines if BANKING_LABEL_RE.search(line["text"])]
    mask_lines = {
        line["key"]
        for line in lines
        if SECRET_VALUE_RE.search(line["text"]) or PHONE_RE.search(line["text"])
    }

    for line in sensitive_lines:
        mask_lines.add(line["key"])
        line_height = max(18, line["bottom"] - line["top"])
        for candidate in lines:
            if candidate["top"] < line["bottom"]:
                continue
            if candidate["top"] > line["bottom"] + max(72, line_height * 3):
                break
            same_block = candidate["key"][0] == line["key"][0]
            near_field = (
                candidate["left"] <= line["right"] + 360
                and candidate["right"] >= line["left"] - 40
            )
            if same_block and near_field:
                mask_lines.add(candidate["key"])

    for label in banking_lines:
        for candidate in lines:
            if abs(candidate["top"] - label["top"]) <= 320 and re.search(r"\d", candidate["text"]):
                mask_lines.add(candidate["key"])

    rectangles = []
    for line in lines:
        if line["key"] in mask_lines:
            rectangles.append((line["left"] - 5, line["top"] - 3, line["right"] + 5, line["bottom"] + 3))
    rectangles.extend(tuple(map(int, rectangle)) for rectangle in native_rectangles or ())

    sanitized = image.copy()
    draw = ImageDraw.Draw(sanitized)
    image_width, image_height = sanitized.size
    clipped = []
    for left, top, right, bottom in rectangles:
        left = max(0, left)
        top = max(0, top)
        right = min(image_width, right)
        bottom = min(image_height, bottom)
        if right <= left or bottom <= top:
            continue
        draw.rectangle((left, top, right - 1, bottom - 1), fill=(0, 0, 0))
        clipped.append((left, top, right, bottom))
    return sanitized, clipped


def redact_sensitive_text(text: str) -> str:
    safe_text = LABELED_VALUE_RE.sub(lambda match: f"{match.group(1)}: [REDACTED]", str(text or ""))
    safe_text = SECRET_VALUE_RE.sub("[REDACTED]", safe_text)
    safe_text = EMAIL_RE.sub("[REDACTED_EMAIL]", safe_text)
    return PHONE_RE.sub("[REDACTED_PHONE]", safe_text)