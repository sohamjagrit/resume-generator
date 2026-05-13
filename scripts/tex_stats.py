"""
tex_stats.py
------------
Parses a rendered resume .tex file and computes the same line-budget metrics
that validate_resume_content.py applies to resume_content.json. Used by the
Streamlit app to refresh stats live as the user edits the LaTeX source.

Public API:
  parse_tex_sections(tex)   -> {"experience": [...], "projects": [...]}
  compute_line_stats(parsed) -> per-section line counts vs budget
  compute_keyword_stats(parsed, jd_text, extra_keywords=None)
                             -> coverage of JD keywords in bullet text
"""

import re
from typing import Optional

CHARS_PER_LINE = 135  # mirror validate_resume_content.py

SECTION_BUDGETS = {
    "experience_first": 8,
    "experience_other": 4,
    "project":          4,
}


# ── TeX parsing ──────────────────────────────────────────────────────────────

_BOLD_OR_ITALIC = re.compile(r"\\text(bf|it)\{((?:[^{}]|\{[^}]*\})*)\}")
_ESCAPED = re.compile(r"\\([&%$#_{}])")


def _strip_latex(s: str) -> str:
    """Reduce a bullet's TeX source to roughly the rendered plain text."""
    # \textbf{x} / \textit{x} → x  (run twice for any nesting)
    for _ in range(3):
        s = _BOLD_OR_ITALIC.sub(lambda m: m.group(2), s)
    # \& → &, \% → %, etc.
    s = _ESCAPED.sub(r"\1", s)
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


_ROLE_HEADER = re.compile(
    r"\\noindent\\textbf\{([^}]+?)\}"          # company / role name
    r"\\hfill\\textcolor\{darkgray\}\{[^}]*\}" # location
    r"\\\\\[-2pt\]",
    re.DOTALL,
)

_PROJECT_HEADER = re.compile(
    r"\\noindent\\textbf\{([^|}]+?)\s*\|\s*\}" # project name before " | "
    r"\\textit\{[^}]*\}",
    re.DOTALL,
)

_ITEMIZE_BLOCK = re.compile(
    r"\\begin\{itemize\}.*?\\end\{itemize\}",
    re.DOTALL,
)

_ITEM = re.compile(
    r"\\item\s+(.+?)(?=\\item|\\end\{itemize\})",
    re.DOTALL,
)


def _extract_entries(section_text: str, header_re: re.Pattern) -> list:
    """Walk a section, pairing each header match with the next itemize block."""
    entries = []
    headers = list(header_re.finditer(section_text))
    for i, hm in enumerate(headers):
        name = hm.group(1).strip()
        start = hm.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(section_text)
        body = section_text[start:end]
        item_block = _ITEMIZE_BLOCK.search(body)
        bullets = []
        if item_block:
            bullets = [_strip_latex(m.group(1)) for m in _ITEM.finditer(item_block.group(0))]
        entries.append({"name": name, "bullets": bullets})
    return entries


def parse_tex_sections(tex: str) -> dict:
    """Pull the Experience and Projects sections out of a rendered resume .tex."""
    exp_match = re.search(
        r"\\section\*\{Experience\}(.*?)(?=\\section\*\{|\Z)", tex, re.DOTALL
    )
    proj_match = re.search(
        r"\\section\*\{Projects\}(.*?)(?=\\section\*\{|\\end\{document\}|\Z)",
        tex, re.DOTALL,
    )

    return {
        "experience": _extract_entries(exp_match.group(1) if exp_match else "", _ROLE_HEADER),
        "projects":   _extract_entries(proj_match.group(1) if proj_match else "", _PROJECT_HEADER),
    }


# ── Line budget stats ────────────────────────────────────────────────────────

def _lines_for(bullet: str, chars_per_line: int = CHARS_PER_LINE) -> int:
    return max(1, -(-len(bullet) // chars_per_line))


def compute_line_stats(parsed: dict) -> dict:
    """Per-section line counts vs budget; flags violations."""
    sections = []
    all_ok = True

    for i, role in enumerate(parsed.get("experience", [])):
        target = SECTION_BUDGETS["experience_first" if i == 0 else "experience_other"]
        expected_bullets = 4 if i == 0 else 3
        bullets = role["bullets"]
        lines = [_lines_for(b) for b in bullets]
        total = sum(lines)
        ok = (
            total == target
            and len(bullets) == expected_bullets
            and all(l <= 2 for l in lines)
        )
        all_ok = all_ok and ok
        sections.append({
            "kind": "experience",
            "name": role["name"],
            "target": target,
            "expected_bullets": expected_bullets,
            "actual": total,
            "bullets": [
                {"text": b, "chars": len(b), "lines": l}
                for b, l in zip(bullets, lines)
            ],
            "ok": ok,
        })

    for proj in parsed.get("projects", []):
        target = SECTION_BUDGETS["project"]
        bullets = proj["bullets"]
        lines = [_lines_for(b) for b in bullets]
        total = sum(lines)
        ok = total == target and len(bullets) == 2 and all(l <= 2 for l in lines)
        all_ok = all_ok and ok
        sections.append({
            "kind": "project",
            "name": proj["name"],
            "target": target,
            "expected_bullets": 2,
            "actual": total,
            "bullets": [
                {"text": b, "chars": len(b), "lines": l}
                for b, l in zip(bullets, lines)
            ],
            "ok": ok,
        })

    return {"sections": sections, "all_ok": all_ok}


# ── Keyword coverage ─────────────────────────────────────────────────────────

# Stop-list of generic tokens that show up capitalized in JDs but aren't keywords.
_STOPLIST = {
    "the", "and", "or", "but", "of", "to", "in", "for", "by", "on", "at", "with",
    "from", "as", "is", "are", "be", "an", "a", "you", "we", "our", "your",
    "this", "that", "these", "those", "their", "they", "them", "it", "its",
    "data", "team", "role", "job", "company", "candidate", "applicant", "us",
    "if", "when", "what", "who", "why", "how", "all", "any", "some", "more",
    "less", "very", "such", "also", "may", "must", "should", "will", "can",
    "us", "do", "does", "did", "have", "has", "had", "been", "being",
}


def _extract_jd_keywords(jd_text: str) -> set:
    """Naive keyword extraction: proper nouns, all-caps acronyms, hyphenated tech."""
    if not jd_text:
        return set()
    tokens = set()

    # Capitalized words / phrases (e.g., "Power BI", "Random Forest").
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9+#]*(?:\s+[A-Z][a-zA-Z0-9+#]*){0,2})\b", jd_text):
        tokens.add(m.group(1).lower())

    # All-caps acronyms (SQL, RAG, ETL, MLOps).
    for m in re.finditer(r"\b([A-Z]{2,}[A-Za-z0-9]*)\b", jd_text):
        tokens.add(m.group(1).lower())

    # Hyphenated tech (scikit-learn, time-series).
    for m in re.finditer(r"\b([a-z]+(?:-[a-z]+){1,2})\b", jd_text.lower()):
        tokens.add(m.group(1))

    # Strip stop-list and very short tokens.
    return {t for t in tokens if t not in _STOPLIST and len(t) > 1}


def compute_keyword_stats(
    parsed: dict,
    jd_text: str,
    extra_keywords: Optional[list] = None,
) -> dict:
    """Coverage of JD-derived keywords in the bullet text of the resume."""
    keywords = _extract_jd_keywords(jd_text)
    if extra_keywords:
        keywords |= {k.lower().strip() for k in extra_keywords if k.strip()}

    if not keywords:
        return {"total": 0, "matched": [], "missed": [], "coverage_pct": 0}

    bullet_text = " ".join(
        b["text"]
        for section_list in (parsed.get("experience", []), parsed.get("projects", []))
        for section in section_list
        for b in [{"text": x} for x in section["bullets"]]
    ).lower()

    matched = sorted(k for k in keywords if k in bullet_text)
    missed = sorted(k for k in keywords if k not in bullet_text)
    coverage = round(100 * len(matched) / len(keywords), 1)

    return {
        "total": len(keywords),
        "matched": matched,
        "missed": missed,
        "coverage_pct": coverage,
    }
