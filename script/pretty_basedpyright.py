#!/usr/bin/env python3
"""Pretty print basedpyright output."""

import json
import os
import sys


class C:
    """ANSI color codes for pretty printing."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"


def color_for_severity(sev: str) -> str:
    """Return ANSI color code for severity."""
    sev = sev.lower()
    if sev == "error":
        return C.RED + C.BOLD
    if sev == "warning":
        return C.YELLOW + C.BOLD
    return C.BLUE  # information / hint


def main() -> int:  # noqa: C901
    """Pretty print basedpyright output."""
    data = json.load(sys.stdin)

    diags = data.get("generalDiagnostics", [])
    if not diags:
        return 0

    errors = 0
    warnings = 0

    use_color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None

    for diag in diags:
        file = diag["file"]
        start = diag["range"]["start"]
        line = start["line"] + 1
        col = start["character"] + 1
        severity = diag["severity"]
        msg = diag["message"]
        rule = diag.get("rule")

        if severity.lower() == "error":
            errors += 1
        elif severity.lower() == "warning":
            warnings += 1

        if use_color:
            sev_color = color_for_severity(severity)
            sev_str = f"{sev_color}{severity.upper()}{C.RESET}"
        else:
            sev_str = severity.upper()

        if rule:
            print(f"{file}:{line}:{col}: {sev_str}: {msg} [{rule}]")
        else:
            print(f"{file}:{line}:{col}: {sev_str}: {msg}")
    if use_color:
        summary_parts = []
        if errors:
            summary_parts.append(f"{C.RED}{errors} error(s){C.RESET}")
        if warnings:
            summary_parts.append(f"{C.YELLOW}{warnings} warning(s){C.RESET}")
        if summary_parts:
            print("--- " + ", ".join(summary_parts))
    else:
        print(f"--- {errors} error(s), {warnings} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
