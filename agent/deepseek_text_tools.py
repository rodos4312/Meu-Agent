"""Guard against a DeepSeek tool-call format leaking into tool-free answers."""

import re


_MARKER = r"[ \t]*(?:[|｜][ \t]*){1,2}DSML[ \t]*(?:[|｜][ \t]*){1,2}"
_TEXT_TOOL_CALLS = re.compile(
    rf"<{_MARKER}(?P<tag>calls|function_calls)[ \t]*>.*?"
    rf"(?:</{_MARKER}(?P=tag)[ \t]*>|\Z)",
    re.DOTALL,
)


def is_tool_free_deepseek(agent) -> bool:
    return getattr(agent, "provider", None) == "deepseek" and getattr(agent, "tools", None) == []


def clean_text_tool_calls(content: str) -> str:
    answer, blocks = _TEXT_TOOL_CALLS.subn("", content)
    if not blocks:
        return content
    return answer.strip() or "I couldn't look that up because tools are unavailable in this chat."
