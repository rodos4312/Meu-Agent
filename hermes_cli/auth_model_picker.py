"""Interactive model picker used after OAuth login.

Re-exported from ``hermes_cli/auth.py`` (patch targets unchanged); origin helpers are imported
lazily per function so ``hermes_cli.auth.<helper>`` patches still intercept and no cycle forms.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger("hermes_cli.auth")

_CUSTOM_LABEL = "Enter custom model name"
_SKIP_LABEL = "Skip (keep current)"
_CURRENT_SUFFIX = "  ← currently in use"


def _confirm_selection_guards(
    model_id: str, *, provider: str = "", base_url: str = "", api_key: str = "",
    include_kinds: Optional[list[str]] = None,
) -> bool:
    """Prompt before saving a model that trips any selection guard (cost, data-policy, ...).

    Shows one [y/N] confirm listing every warning that fired. Returns True to proceed.
    """
    try:
        from hermes_cli.model_selection_guards import combined_message, selection_warnings
        warnings = selection_warnings(
            model_id, provider=provider, base_url=base_url, api_key=api_key, include_kinds=include_kinds,
        )
    except Exception:
        warnings = []
    if not warnings:
        return True

    print()
    print("=" * 72)
    print(combined_message(warnings))
    print("=" * 72)
    try:
        response = input("Switch anyway? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    return response in {"y", "yes"}


class _ModelPickerRows:
    """Aligned model names, provider prices and optional annotations."""

    def __init__(self, all_models, pricing, *, current_model, notes=None):
        from hermes_cli.models_pricing import _format_price_per_mtok
        self.current_model = current_model
        self.notes = notes or {}
        self.prices = {}
        for model in all_models:
            row = (pricing or {}).get(model)
            if row:
                self.prices[model] = tuple(_format_price_per_mtok(row.get(k, "")) for k in
                                           ("prompt", "completion", "input_cache_read"))
        self.name_width = max((len(m) for m in all_models), default=0) + 2
        self.price_width = max([5] + [len(p) for row in self.prices.values() for p in row])
        self.has_cache = any((pricing or {}).get(m, {}).get("input_cache_read") for m in all_models)

    def segments(self, mid):
        name = f"{mid:<{self.name_width}}" if self.prices else mid
        result = [(name, None)]
        if self.prices:
            prices = self.prices.get(mid, ("", "", ""))
            result.append(("  ".join(f"{p:>{self.price_width}}" for p in prices[:3 if self.has_cache else 2]), None))
        if self.notes.get(mid):
            result.append((f"  · {self.notes[mid]}", "dim"))
        if mid == self.current_model:
            result.append((_CURRENT_SUFFIX, None))
        return result

    def label(self, mid):
        return "".join(text for text, _ in self.segments(mid))

    def description_lines(self):
        if not self.prices:
            return []
        columns = ["In", "Out"] + (["Cache"] if self.has_cache else [])
        return [" " * (5 + self.name_width) + "  ".join(f"{c:>{self.price_width}}" for c in columns) + "  $/Mtok"]

    def menu_title(self, title="Select default model:"):
        return "\n".join([title, *self.description_lines()])


def _picker_order(model_ids: list[str], current_model: str) -> tuple[list[str], dict[int, str], int]:
    """Put the current model first and preserve catalog order for the rest."""
    ordered = list(dict.fromkeys(([current_model] if current_model in model_ids else []) + list(model_ids)))
    return ordered, {}, 0


def _print_numbered_rows(rows: _ModelPickerRows, menu_title: str, ordered: list[str], sections: dict[int, str]) -> int:
    """The no-curses fallback's title, numbered rows (+ custom / skip) and footnote; returns the number width."""
    from hermes_cli.curses_ui import format_radio_item_ansi
    from hermes_cli.colors import Colors, color
    n, _DIM, _RESET = len(ordered), "\033[2m", "\033[0m"
    for line in menu_title.splitlines():
        print(line.replace("★", color("★", Colors.YELLOW), 1) if "★" in line else line)
    num_width = len(str(n + 2))
    for i, mid in enumerate(ordered, 1):
        if (i - 1) in sections:
            print(f"  {_DIM}{sections[i - 1]}{_RESET}")
        print(f"  {i:>{num_width}}. {format_radio_item_ansi(rows.segments(mid))}")
    print(f"  {n + 1:>{num_width}}. {_CUSTOM_LABEL}")
    print(f"  {n + 2:>{num_width}}. {_SKIP_LABEL}")
    return num_width


def _prompt_model_selection(
    model_ids: list[str], current_model: str = "",
    pricing: Optional[dict[str, dict[str, str]]] = None,
    unavailable_models: Optional[list[str]] = None, portal_url: str = "",
    unavailable_message: str = "", confirm_provider: str = "", confirm_base_url: str = "",
    confirm_api_key: str = "",
    notes: Optional[dict[str, str]] = None, title: str = "Select default model:",
) -> Optional[str]:
    """Interactive model picker; current_model listed first. Returns the chosen model ID or None. *title* heads
    the menu (a plugin picking a model for something other than the default says so).

    With *pricing* (``{model_id: {prompt, completion}}``) a compact price column is shown; models in
    *unavailable_models* render grayed out and unselectable with an upgrade link to *portal_url*.
    """
    from hermes_cli.cli_output import line_input
    _unavailable = unavailable_models or []

    def _confirmed_selection(mid: str) -> Optional[str]:
        if not mid:
            return None
        # Cost guard needs a known provider; id-keyed guards (data policy) always run.
        ok = _confirm_selection_guards(
            mid, provider=confirm_provider, base_url=confirm_base_url, api_key=confirm_api_key,
            include_kinds=None if confirm_provider else ["data_policy"],
        )
        return mid if ok else None

    def _custom_selection() -> Optional[str]:
        try:
            custom = line_input("Enter model name: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return _confirmed_selection(custom) if custom else None

    ordered, sections, start = _picker_order(model_ids, current_model)

    rows = _ModelPickerRows(
        ordered + list(_unavailable), pricing, current_model=current_model, notes=notes)
    _DIM = "\033[2m"
    _RESET = "\033[0m"

    menu_title = rows.menu_title(title)
    _upgrade_url = portal_url.rstrip("/")
    n = len(ordered)

    # Try arrow-key menu first, fall back to number input.
    try:
        from hermes_cli.curses_ui import curses_radiolist
        choices = [rows.segments(mid) for mid in ordered] + [_CUSTOM_LABEL, _SKIP_LABEL]

        unavailable_footer = unavailable_message.strip()
        if not unavailable_footer and _unavailable:
            unavailable_footer = f"Provider details: {_upgrade_url}" if _upgrade_url else "Unavailable for this provider"

        # Header/legend/gauges + unavailable block go in the description so they survive the curses clear.
        desc_lines: list[str] = rows.description_lines()
        if _unavailable:
            desc_lines.extend(f"   {rows.label(mid)}" for mid in _unavailable)
            desc_lines.append(f"  ── {unavailable_footer} ──")

        # Search haystack = label + aliases for brand-less wire ids (Kimi `k3` ↔ "kimi"); skip when
        # model_search_text adds nothing beyond the bare id.
        from hermes_cli.model_search import model_search_text
        model_search_labels = []
        for mid in ordered:
            label, haystack = rows.label(mid), model_search_text(mid)
            model_search_labels.append(label if haystack == mid else f"{label} {haystack}")
        model_search_labels += [_CUSTOM_LABEL, _SKIP_LABEL]

        idx = curses_radiolist(
            title,
            choices,
            selected=start,  # cursor on the current model
            cancel_returns=-1,
            description="\n".join(desc_lines) if desc_lines else None,
            searchable=True,
            search_labels=model_search_labels,
            headings=sections or None,
        )
        if idx < 0:
            return None
        print()
        if idx < n:
            return _confirmed_selection(ordered[idx])
        if idx == n:
            return _custom_selection()
        return None
    except (ImportError, NotImplementedError, OSError, subprocess.SubprocessError):
        pass

    # Fallback: numbered list (ANSI colors for sale chrome / usage gauges)
    num_width = _print_numbered_rows(rows, menu_title, ordered, sections)

    if _unavailable:
        unavailable_footer = unavailable_message.strip() or (
            f"Provider details: {_upgrade_url}" if _upgrade_url else "Unavailable for this provider"
        )
        print()
        print(f"  {_DIM}── {unavailable_footer} ──{_RESET}")
        for mid in _unavailable:
            print(f"  {'':>{num_width}}  {_DIM}{rows.label(mid)}{_RESET}")
    print()

    while True:
        try:
            choice = input(f"Choice [1-{n + 2}] (default: skip): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 1 <= idx <= n:
                return _confirmed_selection(ordered[idx - 1])
            if idx == n + 1:
                return _custom_selection()
            if idx == n + 2:
                return None
            print(f"Please enter 1-{n + 2}")
        except ValueError:
            print("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            return None


_model_choice_saves = 0  # bumped per saved pick; `hermes model` reads it to know a pick landed


def model_choice_save_count() -> int:
    return _model_choice_saves


def _save_model_choice(model_id: str) -> None:
    """Save the selected model to config.yaml only — NOT .env, which would stomp in multi-agent setups."""
    global _model_choice_saves
    from hermes_cli.config import save_config, load_config
    _model_choice_saves += 1
    config = load_config()
    # Always use dict format so provider/base_url can be stored alongside
    if isinstance(config.get("model"), dict):
        config["model"]["default"] = model_id
    else:
        config["model"] = {"default": model_id}
    save_config(config)


# Public for plugins (catalog rule 9): the interactive model picker under a caller's title.
prompt_model_selection = _prompt_model_selection
