"""Local, deterministic Flash/Pro selection; never an additional model request."""

import re
import unicodedata

FLASH = "deepseek-flash"
PRO = "deepseek-v4-pro"
_MODELS = {FLASH, PRO, "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
_COMPLEX = re.compile(
    r"\b(debug|refactor|implement|architecture|algorithm|prove|proof|audit|optimiz\w*|analy[sz]\w*|"
    r"design|code|coding|program\w*|build|develop\w*|investigat\w*|complex|security|"
    r"αναλυσ\w*|σχεδιασ\w*|αρχιτεκτον\w*|αλγοριθμ\w*|αποδει\w*|κωδικ\w*|"
    r"κωδικα|διορθω\w*|υλοποι\w*|ασφαλει\w*|debugging|κωδικας|"
    r"analysi|analise|kodika|kwdika|diorthose|ylopoiise)\b", re.IGNORECASE)
_FOLLOW_UP = re.compile(r"^(continue|go on|proceed|yes|ok|συνεχισε|προχωρα|ναι|sinehise|synexise|proxora)[.!\s]*$", re.IGNORECASE)


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def _normalized(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c)).strip()


def choose_model(model: str, messages: list) -> str:
    if model not in _MODELS:
        return model
    # Pro is text-only. Images anywhere in replay must stay on the vision-capable Flash.
    if any(isinstance(p, dict) and p.get("type") in {"image_url", "image", "input_image"}
           for m in messages if isinstance(m, dict) and isinstance(m.get("content"), list)
           for p in m["content"]):
        return FLASH
    user_texts = [_normalized(_text(m.get("content"))) for m in messages
                  if isinstance(m, dict) and m.get("role") == "user"]
    for text in reversed(user_texts):
        # A short continuation inherits the previous substantive request's route.
        if not text or _FOLLOW_UP.fullmatch(text):
            continue
        return PRO if len(text) >= 900 or "```" in text or _COMPLEX.search(text) else FLASH
    return FLASH
