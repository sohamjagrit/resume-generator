"""
validate_resume_content.py
--------------------------
Enforces per-section line budgets defined in CLAUDE.md before PDF generation.

Budget (rendered LaTeX lines):
  - First experience entry (lead role): up to 8 lines across 4 bullets
  - Remaining experience entries:       up to 4 lines across 3 bullets
  - Each project:                       up to 4 lines across 2 bullets

A bullet's rendered line count is estimated from its character length after
stripping **bold** markers. CHARS_PER_LINE is calibrated for 10pt Times Roman
with the current 0.4" left/right margins and 1.5em itemize indent. Tune it if
the validator's predictions stop matching the compiled PDF.

Usage:
    uv run scripts/validate_resume_content.py --input resume_content.json
"""

import json
import re
import sys
import argparse
from pathlib import Path


CHARS_PER_LINE = 135  # empirical: 10pt Times, 7.5" content width.
                       # Calibrated against rendered PDF — bullets at 132c render
                       # as 1L, bullets at 140c+ wrap to 2L. Tune if you change
                       # the font, margins, or itemize indent.

LINE_BUDGETS = {
    "experience_first": (8, 4),  # (exact lines, expected bullets)
    "experience_other": (4, 3),
    "project":          (4, 2),
}

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def rendered_length(bullet: str) -> int:
    """Bullet length after stripping markdown bold markers."""
    return len(_BOLD.sub(r"\1", bullet))


def lines_for(bullet: str) -> int:
    """Ceiling-divide rendered length by CHARS_PER_LINE."""
    return max(1, -(-rendered_length(bullet) // CHARS_PER_LINE))


def _check_section(label: str, bullets: list, target_lines: int,
                   expected_bullets: int) -> list:
    """Section total must equal target exactly; each bullet must be 1L or 2L."""
    errors = []
    total = sum(lines_for(b) for b in bullets)
    breakdown = " + ".join(
        f"{lines_for(b)}L ({rendered_length(b)}c)" for b in bullets
    )
    ok = total == target_lines and len(bullets) == expected_bullets and all(
        lines_for(b) <= 2 for b in bullets
    )
    status = "OK " if ok else "BAD"
    print(f"  [{status}] {label[:34]:34} {total}/{target_lines}L  bullets={len(bullets)}/{expected_bullets}  | {breakdown}")

    if len(bullets) != expected_bullets:
        errors.append(
            f"{label}: has {len(bullets)} bullets, expected {expected_bullets}"
        )
    if total != target_lines:
        verdict = "exceeds" if total > target_lines else "is under"
        errors.append(
            f"{label}: {total} rendered lines {verdict} target of {target_lines}"
        )
    for i, b in enumerate(bullets):
        if lines_for(b) > 2:
            errors.append(
                f"{label} bullet {i+1}: {lines_for(b)}L ({rendered_length(b)}c) "
                f"exceeds the 2-line per-bullet cap"
            )
    return errors


def validate(content: dict) -> list:
    """Return list of error messages; empty list means valid."""
    errors = []

    experiences = content.get("experience", [])
    print("\n[validator] experience sections:")
    for i, role in enumerate(experiences):
        key = "experience_first" if i == 0 else "experience_other"
        max_lines, expected = LINE_BUDGETS[key]
        errors += _check_section(
            role.get("company", f"role[{i}]"),
            role.get("bullets", []),
            max_lines,
            expected,
        )

    projects = content.get("projects", [])
    print("\n[validator] projects:")
    max_lines, expected = LINE_BUDGETS["project"]
    for proj in projects:
        errors += _check_section(
            proj.get("name", "project"),
            proj.get("bullets", []),
            max_lines,
            expected,
        )

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate resume_content.json line budgets")
    parser.add_argument("--input", required=True, help="Path to resume_content.json")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"[ERROR] Input not found: {path}")
        sys.exit(2)

    content = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(content)

    if errors:
        print("\n[FAIL] line-budget violations:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("\n[OK] all sections within budget")


if __name__ == "__main__":
    main()
