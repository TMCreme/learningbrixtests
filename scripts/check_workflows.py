#!/usr/bin/env python
"""Catch unescaped backticks inside workflow template literals.

Workflow scripts are mostly English prose living inside JS template literals.
A backtick written naturally in that prose — "check the ones in `modules`" —
silently terminates the literal, and the file fails to parse only when the
workflow is actually launched, which is after preflight has passed and agents
have already started. That is an expensive place to discover a typo.

There is no JS runtime on this machine to `node --check` with, so this walks the
prose blocks instead: any line between an opening backtick at end-of-line and
its closing backtick at start-of-line is prose, and a bare backtick there is a
bug. Escaped backticks (\\`) and interpolations (${...}) are fine.

This is a heuristic, not a parser. It catches the one mistake that actually
happens in these files; it will not catch arbitrary JS syntax errors.

    python scripts/check_workflows.py            # check workflows/*.workflow.js
    python scripts/check_workflows.py path.js    # check specific files
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ROOT  # noqa: E402


CODE, TEMPLATE = "code", "template"


def check_file(path: Path) -> list[str]:
    """Lex the file just enough to know when we are inside template prose.

    A stack models nesting, because ${...} inside a template returns to code
    context and may itself contain another template — which is exactly the
    pattern a naive line-based scan gets wrong.
    """
    src = path.read_text()
    lines = src.splitlines()
    stack: list[str] = [CODE]
    line = 0

    # Lines whose prose was interrupted by a backtick that closed the literal.
    suspicious: dict[int, str] = {}
    # Whether each line began inside template prose.
    started_in_template: dict[int, bool] = {0: False}

    i = 0
    while i < len(src):
        ch = src[i]
        if ch == "\n":
            line += 1
            started_in_template[line] = stack[-1] == TEMPLATE
            i += 1
            continue

        ctx = stack[-1]

        if ctx == TEMPLATE:
            if ch == "\\":
                i += 2
                continue
            if ch == "$" and src[i + 1:i + 2] == "{":
                stack.append(CODE)
                i += 2
                continue
            if ch == "`":
                stack.pop()
                # A legitimate close is followed by end-of-line or JS
                # punctuation (`, ) ; . } ] :`). If English text follows
                # instead, the backtick was written inside prose and has just
                # truncated the literal — which is the bug.
                rest = src[i + 1:src.find("\n", i + 1) if "\n" in src[i:] else len(src)]
                if started_in_template.get(line) and rest.strip() \
                        and rest.lstrip()[0] not in ",);.}]:+ &|?":
                    suspicious.setdefault(line, lines[line] if line < len(lines) else "")
                i += 1
                continue
            i += 1
            continue

        # ctx == CODE
        if ch == "`":
            stack.append(TEMPLATE)
            i += 1
            continue
        if ch == "}" and len(stack) > 1:
            stack.pop()
            i += 1
            continue
        if ch in "'\"":
            quote, i = ch, i + 1
            while i < len(src) and src[i] != quote:
                if src[i] == "\\":
                    i += 1
                elif src[i] == "\n":
                    break
                i += 1
            i += 1
            continue
        if ch == "/" and src[i + 1:i + 2] == "/":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and src[i + 1:i + 2] == "*":
            end = src.find("*/", i + 2)
            if end == -1:
                break
            line += src.count("\n", i, end)
            i = end + 2
            continue
        i += 1

    problems = [
        f"{path}:{lineno + 1}: backtick inside template prose closes the "
        f"literal — escape it as \\`\n    {text.strip()[:100]}"
        for lineno, text in sorted(suspicious.items())
    ]
    if stack[-1] == TEMPLATE:
        problems.append(f"{path}: a template literal is never closed")
    return problems


def main() -> int:
    if len(sys.argv) > 1:
        paths = [Path(a) for a in sys.argv[1:]]
    else:
        paths = sorted((ROOT / "workflows").glob("*.workflow.js"))

    if not paths:
        print("No workflow scripts found.")
        return 0

    total: list[str] = []
    for path in paths:
        problems = check_file(path)
        total.extend(problems)
        print(f"{'✗' if problems else '✓'} {path.name}"
              f"{f' — {len(problems)} problem(s)' if problems else ''}")

    for problem in total:
        print(f"\n{problem}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
