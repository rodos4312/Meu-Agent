"""Fast-index Python scanner: definitions and imports from lines, without ``ast.parse``.

Parsing every Python file of a large repository costs about a minute (``ast.parse`` builds
the whole tree); the fast index only needs names, kinds, lines, containers and imports.
This scanner follows indentation for containers, skips triple-quoted strings and bracket
continuations, and finds imports at any depth (late imports inside functions are common).
It is approximate where Python is ambiguous without a parser; the deep pass (stdlib AST)
replaces its result for every file that becomes relevant.
"""

from __future__ import annotations

import re
from dataclasses import replace

from meu_coding.interfaces import FAST, ExtractionResult, Symbol

_DEF = re.compile(r"(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_]\w*)")
_IMPORT = re.compile(r"import[ \t]+(.+)")
_FROM = re.compile(r"from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]*(.*)")
_VARIABLE = re.compile(r"([A-Za-z_]\w*)[ \t]*(?::[^=]*)?(?:=(?!=)|$)")
_CHAINED = re.compile(r"[ \t]*([A-Za-z_]\w*)[ \t]*=(?!=)")
_STRINGS = re.compile(r"""'[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*\"""")
_STRUCTURE_STARTS = ("def ", "def\t", "class ", "class\t", "async ")
_KEYWORDS = frozenset({
    "if", "elif", "else", "for", "while", "try", "except", "finally", "with", "return",
    "yield", "raise", "assert", "del", "pass", "break", "continue", "global", "nonlocal",
    "import", "from", "lambda", "match", "case", "print", "await", "type",
})


def _bracket_delta(code: str) -> int:
    """Net open brackets in one line of code, ignoring string literals and the comment
    (strings first: a ``#`` inside a string is not a comment)."""
    if not any(c in code for c in "()[]{}"):
        return 0
    if "'" in code or '"' in code:
        code = _STRINGS.sub("", code)
    code = code.split("#", 1)[0]
    return (code.count("(") + code.count("[") + code.count("{")
            - code.count(")") - code.count("]") - code.count("}"))


_SINGLE_QUOTED = re.compile(r"'[^'\\\n]*(?:\\.[^'\\\n]*)*'")
_DOUBLE_QUOTED = re.compile(r'"[^"\\\n]*(?:\\.[^"\\\n]*)*"')


def _opens_triple_string(line: str) -> str | None:
    """The triple quote this line leaves open, if any. A triple quote inside an ordinary
    string of the other quote type is not a delimiter, so those strings are blanked first."""
    for quote, other in (('"""', _SINGLE_QUOTED), ("'''", _DOUBLE_QUOTED)):
        if quote in line and other.sub("", line).count(quote) % 2 == 1:
            return quote
    return None


def _import_names(text: str) -> list[str]:
    names = []
    for part in text.replace("(", " ").replace(")", " ").replace("\\", " ").split(","):
        words = part.split("#", 1)[0].split()
        if words:
            names.append(words[0])
    return names


class PythonOutlineScanner:
    name = "python-outline"

    def supports(self, language: str) -> bool:
        return language == "python"

    def extract(self, path: str, source: str, language: str) -> ExtractionResult:
        return ExtractionResult(path, tuple(_Scan(path).run(source)), self.name, depth=FAST)


class _Scan:
    def __init__(self, path: str) -> None:
        self.path = path
        self.out: list[Symbol] = []
        self.stack: list[tuple[int, str, str, int]] = []  # indent, name, kind, index in out
        self.last_code_line = 0

    def _symbol(self, name: str, kind: str, line: int, column: int, container: str | None) -> int:
        self.out.append(Symbol(name, kind, self.path, line, "python", column, container))
        return len(self.out) - 1

    def _container(self) -> str | None:
        return ".".join(name for _, name, _, _ in self.stack) or None

    def _close_until(self, indent: int) -> None:
        while self.stack and self.stack[-1][0] >= indent:
            _, _, _, index = self.stack.pop()
            self.out[index] = replace(self.out[index], end_line=self.last_code_line)

    def run(self, source: str) -> list[Symbol]:
        in_string: str | None = None
        depth = 0
        pending_from: tuple[str, int, int, list[str]] | None = None
        for number, line in enumerate(source.splitlines(), start=1):
            if in_string is not None:
                self.last_code_line = number
                if line.count(in_string) % 2 == 1:  # ``""" + x + """`` closes and reopens
                    depth += _bracket_delta(line[line.rindex(in_string) + 3:])
                    in_string = None
                continue
            stripped = line.lstrip()
            if not stripped or stripped[0] == "#":
                continue
            if pending_from is not None:
                pending_from = self._continue_from(pending_from, stripped)
                continue
            indent = len(line) - len(stripped)
            # A def/class, or any statement at column 0, cannot be a bracket continuation in
            # practice; restarting there bounds the damage of a miscounted bracket.
            structural = stripped.startswith(_STRUCTURE_STARTS) or (
                indent == 0 and (stripped[0].isalpha() or stripped[0] in "_@"))
            if depth <= 0 or structural:
                depth = 0
                pending_from = self._statement(stripped, number, indent)
            in_string = _opens_triple_string(line)
            if pending_from is None:  # a pending import tracks its own parenthesis
                code = line[: line.rindex(in_string)] if in_string else line
                depth += _bracket_delta(code)
            self.last_code_line = number
        self._close_until(0)
        return self.out

    def _statement(self, stripped: str, number: int, indent: int):
        self._close_until(indent)
        match = _DEF.match(stripped)
        if match:
            keyword, name = match.groups()
            parent_is_class = bool(self.stack) and self.stack[-1][2] == "class"
            kind = "class" if keyword == "class" else ("method" if parent_is_class else "function")
            index = self._symbol(name, kind, number, indent, self._container())
            self.stack.append((indent, name, kind, index))
            return None
        if stripped.startswith("from"):
            return self._from(stripped, number, indent)
        if stripped.startswith("import"):
            match = _IMPORT.match(stripped)
            for module in _import_names(match.group(1)) if match else ():
                self._symbol(module, "import", number, indent, None)
            return None
        if not self.stack:
            self._variable(stripped, number, indent)
        return None

    def _from(self, stripped: str, number: int, indent: int):
        match = _FROM.match(stripped)
        if not match:
            return None
        module, rest = match.groups()
        mode = "paren" if rest.lstrip().startswith("(") else None
        return self._continue_from((module, number, indent, [], mode), rest)

    def _continue_from(self, pending, text: str):
        module, number, indent, names, mode = pending
        names.extend(_import_names(text))
        code = text.split("#", 1)[0].rstrip()
        if mode == "paren" and ")" not in code:
            return pending
        if code.endswith("\\"):
            return (module, number, indent, names, "backslash")
        for name in names:
            self._symbol(module, "import", number, indent, name)
        return None

    def _variable(self, stripped: str, number: int, indent: int) -> None:
        match = _VARIABLE.match(stripped)
        if not match or match.group(1) in _KEYWORDS:
            return
        self._symbol(match.group(1), "variable", number, indent, None)
        rest = stripped[match.end():]
        while (chained := _CHAINED.match(rest)) is not None:  # ``a = b = None`` binds both
            self._symbol(chained.group(1), "variable", number, indent, None)
            rest = rest[chained.end():]
