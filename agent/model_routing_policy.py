"""Local task classification and an explicitly selected, provider-bound model pair."""
import re
import unicodedata

_COMPLEX = re.compile(
    r"\b(debug|refactor|implement|architecture|algorithm|prove|proof|audit|optimiz\w*|analy[sz]\w*|"
    r"design|code|coding|program\w*|build|develop\w*|investigat\w*|complex|security|apk|android|application|"
    r"αναλυσ\w*|σχεδιασ\w*|αρχιτεκτον\w*|αλγοριθμ\w*|αποδει\w*|κωδικ\w*|εφαρμογ\w*|"
    r"διορθω\w*|υλοποι\w*|ασφαλει\w*|debugging|analysi|analise|kodika|kwdika|diorthose|ylopoiise|efarmog\w*)\b", re.IGNORECASE)
_FOLLOW_UP = re.compile(r"^(continue|go on|proceed|yes|ok|συνεχισε|προχωρα|ναι|sinehise|synexise|proxora)[.!\s]*$", re.IGNORECASE)


def has_images(messages):
    return any(isinstance(part, dict) and part.get("type") in {"image_url", "image", "input_image"}
               for message in messages if isinstance(message, dict) and isinstance(message.get("content"), list)
               for part in message["content"])


def complex_work(messages):
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
        if not isinstance(content, str):
            continue
        text = "".join(c for c in unicodedata.normalize("NFD", content.casefold()) if not unicodedata.combining(c)).strip()
        if text and not _FOLLOW_UP.fullmatch(text):
            return len(text) >= 900 or "```" in text or bool(_COMPLEX.search(text))
    return False


def selected_pair(policy, provider):
    if not isinstance(policy, dict) or policy.get("provider") != provider:
        return None
    pair = tuple(policy.get(key) for key in ("routine", "complex"))
    if not all(isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{1,199}", model) for model in pair):
        return None
    return pair


def choose_from_pair(policy, provider, messages):
    pair = selected_pair(policy, provider)
    if pair is None:
        return None
    if has_images(messages):
        from agent.models_dev import get_model_capabilities
        unknown = []
        for model in pair:
            capabilities = get_model_capabilities(provider, model)
            supports = capabilities.supports_vision if capabilities is not None else None
            if supports is True:
                return model
            if supports is None:
                unknown.append(model)
        if unknown:
            return unknown[-1]
        raise ValueError("Neither selected Auto model supports images; choose a compatible model within this provider.")
    return pair[1 if complex_work(messages) else 0]
