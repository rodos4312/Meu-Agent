"""Local Flash/Pro selection, shared task classification and no extra model call."""
from agent.model_routing_policy import complex_work, has_images

FLASH = "deepseek-flash"
PRO = "deepseek-v4-pro"
_MODELS = {FLASH, PRO, "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}


def choose_model(model: str, messages: list) -> str:
    if model not in _MODELS:
        return model
    if has_images(messages):
        return FLASH
    return PRO if complex_work(messages) else FLASH
