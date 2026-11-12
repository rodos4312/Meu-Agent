"""Edit strategy routing: which output FORMAT the Coder should use for a model.

This is a format chooser, not four editing engines. Every strategy maps onto an existing
MEU executor (``patch`` replace mode, ``patch`` V4A mode, ``write_file``); see
``meu_coding.safe_execution``. Profiles are plain data, matched by model-id pattern, so new
models are a registry entry rather than code.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from dataclasses import dataclass

from meu_coding.coding_interfaces import EditAction, EditOperation, EditStrategy, StrategyChoice

ALL_STRATEGIES = tuple(EditStrategy)


@dataclass(frozen=True)
class ModelProfile:
    """``patterns`` are case-insensitive fnmatch globs over the model id."""

    name: str
    patterns: tuple[str, ...]
    preferred: EditStrategy
    allowed: tuple[EditStrategy, ...] = ALL_STRATEGIES
    architect_mode: bool = False
    max_context_chars: int = 12_000
    whole_file_max_bytes: int = 0  # small existing files may be rewritten whole; 0 = never

    def matches(self, model_id: str) -> bool:
        lowered = model_id.lower()
        return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in self.patterns)


# Search/replace is the safe default: every edit is anchored on exact existing text and
# MEU's ``patch`` replace mode refuses ambiguous or missing anchors.
SAFE_DEFAULT = ModelProfile(
    name="safe-default",
    patterns=(),
    preferred=EditStrategy.SEARCH_REPLACE,
    allowed=(EditStrategy.SEARCH_REPLACE, EditStrategy.WHOLE_FILE),
    max_context_chars=8_000,
)

DEFAULT_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        name="deepseek-pro",
        patterns=("deepseek-pro*", "*deepseek*pro*", "deepseek-reasoner*", "*deepseek-r1*"),
        preferred=EditStrategy.V4A_PATCH,
        architect_mode=True,
        max_context_chars=24_000,
        whole_file_max_bytes=3_000,
    ),
    ModelProfile(
        name="deepseek-flash",
        patterns=("deepseek-flash*", "*deepseek*flash*", "deepseek-chat*"),
        preferred=EditStrategy.SEARCH_REPLACE,
        allowed=(EditStrategy.SEARCH_REPLACE, EditStrategy.WHOLE_FILE, EditStrategy.V4A_PATCH),
        max_context_chars=8_000,
        whole_file_max_bytes=1_500,
    ),
)


@dataclass(frozen=True)
class EditHint:
    """What the router knows about one edit before it is written."""

    new_file: bool = False
    file_bytes: int = 0  # size of the largest existing file being edited; 0 = unknown


class EditStrategyRouter:
    def __init__(self, profiles: Iterable[ModelProfile] = DEFAULT_PROFILES,
                 default: ModelProfile = SAFE_DEFAULT) -> None:
        self.profiles = list(profiles)
        self.default = default

    def register(self, profile: ModelProfile) -> None:
        """Later registrations win over earlier ones for the same model id."""
        self.profiles.insert(0, profile)

    def profile_for(self, model_id: str) -> ModelProfile:
        if model_id:
            for profile in self.profiles:
                if profile.matches(model_id):
                    return profile
        return self.default

    def select(self, model_id: str, hint: EditHint = EditHint(),
               requested: EditStrategy | None = None) -> StrategyChoice:
        """Deterministic: the same model id, hint and request always give the same choice."""
        profile = self.profile_for(model_id)
        if requested is not None:
            if requested in profile.allowed:
                return StrategyChoice(requested, profile.name, "requested strategy")
            fallback = self._preferred(profile)
            return StrategyChoice(fallback, profile.name,
                                  f"requested {requested.value} is not allowed for {profile.name}")
        if hint.new_file and EditStrategy.WHOLE_FILE in profile.allowed:
            return StrategyChoice(EditStrategy.WHOLE_FILE, profile.name, "new file")
        if (0 < hint.file_bytes <= profile.whole_file_max_bytes
                and EditStrategy.WHOLE_FILE in profile.allowed):
            return StrategyChoice(EditStrategy.WHOLE_FILE, profile.name,
                                  f"small file ({hint.file_bytes} bytes)")
        return StrategyChoice(self._preferred(profile), profile.name, f"{profile.name} preference")

    @staticmethod
    def _preferred(profile: ModelProfile) -> EditStrategy:
        if profile.preferred in profile.allowed:
            return profile.preferred
        return profile.allowed[0] if profile.allowed else EditStrategy.SEARCH_REPLACE


# ── payload structure (formats only; MEU's executors do the real validation) ──

_V4A_HEADER = re.compile(r"^\*\*\*\s*(Update|Add|Delete)\s+File:\s*(.+?)\s*$", re.MULTILINE)
_V4A_MOVE = re.compile(r"^\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+?)\s*$", re.MULTILINE)
_V4A_BEGIN = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$", re.MULTILINE)
_V4A_END = re.compile(r"^\*\*\*\s*End\s+Patch\s*$", re.MULTILINE)
_DIFF_FILE = re.compile(r"^(?:---|\+\+\+)\s+(\S+)", re.MULTILINE)
_DIFF_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


def _strip_diff_prefix(path: str) -> str | None:
    if path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def touched_paths(op: EditOperation) -> tuple[str, ...]:
    """Every path an operation would touch, including paths named INSIDE a patch payload
    (a patch for ``a.py`` may carry headers for other files; review must see those)."""
    paths = [op.path]
    if op.patch and op.strategy == EditStrategy.V4A_PATCH:
        paths += [m.group(2) for m in _V4A_HEADER.finditer(op.patch)]
        paths += [p for m in _V4A_MOVE.finditer(op.patch) for p in m.groups()]
    elif op.patch and op.strategy == EditStrategy.UNIFIED_DIFF:
        paths += [p for m in _DIFF_FILE.finditer(op.patch) if (p := _strip_diff_prefix(m.group(1)))]
    return tuple(dict.fromkeys(p.strip() for p in paths))


def _v4a_errors(op: EditOperation) -> list[str]:
    patch = op.patch or ""
    errors = []
    if not _V4A_BEGIN.search(patch) or not _V4A_END.search(patch):
        errors.append(f"{op.path}: V4A patch needs '*** Begin Patch' and '*** End Patch' lines")
    if not (_V4A_HEADER.search(patch) or _V4A_MOVE.search(patch)):
        errors.append(f"{op.path}: V4A patch names no file")
    return errors


def _unified_errors(op: EditOperation) -> list[str]:
    patch = op.patch or ""
    if not _DIFF_FILE.search(patch) or not _DIFF_HUNK.search(patch):
        return [f"{op.path}: unified diff needs ---/+++ headers and at least one @@ hunk"]
    return []


def _search_replace_errors(op: EditOperation) -> list[str]:
    if not op.search:
        return [f"{op.path}: search/replace needs a non-empty search block"]
    if op.replace is None:
        return [f"{op.path}: search/replace needs a replace block"]
    if op.search == op.replace:
        return [f"{op.path}: search and replace blocks are identical"]
    return []


def _whole_file_errors(op: EditOperation) -> list[str]:
    return [] if op.content is not None else [f"{op.path}: whole-file edit needs content"]


_PAYLOAD_FIELDS = {
    EditStrategy.SEARCH_REPLACE: ("search", "replace"),
    EditStrategy.WHOLE_FILE: ("content",),
    EditStrategy.V4A_PATCH: ("patch",),
    EditStrategy.UNIFIED_DIFF: ("patch",),
}
_VALIDATORS = {
    EditStrategy.SEARCH_REPLACE: _search_replace_errors,
    EditStrategy.WHOLE_FILE: _whole_file_errors,
    EditStrategy.V4A_PATCH: _v4a_errors,
    EditStrategy.UNIFIED_DIFF: _unified_errors,
}


def format_errors(op: EditOperation) -> list[str]:
    """Structural problems with one operation's payload."""
    if op.action == EditAction.DELETE:
        return []
    errors = list(_VALIDATORS[op.strategy](op))
    expected = set(_PAYLOAD_FIELDS[op.strategy])
    stray = [f for f in ("search", "replace", "content", "patch")
             if f not in expected and getattr(op, f) is not None]
    if stray:
        errors.append(f"{op.path}: {op.strategy.value} edit carries unrelated fields {stray}")
    return errors
