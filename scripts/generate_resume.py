"""
generate_resume.py
------------------
Renders a one-page resume PDF from resume_content.json using
scripts/resume_template.tex as the layout source. The .tex template
is the single source of truth for structure, fonts, margins, and spacing.

Usage:
    uv run scripts/generate_resume.py --input resume_content.json \
                                      --output output/resume.pdf
"""

import json
import argparse
import subprocess
import shutil
import sys
import re
from pathlib import Path

try:
    from validate_resume_content import validate as validate_line_budgets
except ImportError:
    from scripts.validate_resume_content import validate as validate_line_budgets


# ── LaTeX escaping ─────────────────────────────────────────────────────────────

_ESCAPE_MAP = {
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}

def escape(text: str) -> str:
    if not text:
        return ""
    return "".join(_ESCAPE_MAP.get(c, c) for c in text)


def render_bullet(text: str) -> str:
    """Convert **bold** markers to \\textbf{...}; escape everything else."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(r"\textbf{" + escape(part) + "}")
        else:
            out.append(escape(part))
    return "".join(out)


# ── Templating ────────────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def substitute(text: str, values: dict) -> str:
    """Replace {{key}} with values[key]; unknown keys are left intact."""
    return _PLACEHOLDER.sub(
        lambda m: values[m.group(1)] if m.group(1) in values else m.group(0),
        text,
    )


def split_block(text: str, name: str) -> tuple[str, str, str]:
    """Find %% BEGIN: name … %% END: name; return (before, inner, after)."""
    pattern = re.compile(
        rf"^[ \t]*%% BEGIN: {name}\n(.*?)^[ \t]*%% END: {name}\n?",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"Block '{name}' not found in template")
    return text[:m.start()], m.group(1), text[m.end():]


def render_bullets(block: str, bullets: list) -> str:
    before, item_tmpl, after = split_block(block, "bullet")
    rendered = "".join(
        substitute(item_tmpl, {"bullet": render_bullet(b)})
        for b in bullets
    )
    return before + rendered + after


def render_section(template: str, section: str, entries: list) -> str:
    """Repeat a %% BEGIN: section block per entry; substitute scalar fields."""
    before, block, after = split_block(template, section)
    parts = []
    for entry in entries:
        body = block
        if "bullets" in entry:
            body = render_bullets(body, entry["bullets"])
        values = {k: escape(v) for k, v in entry.items() if isinstance(v, str)}
        parts.append(substitute(body, values))
    return before + "".join(parts) + after


# ── Header ────────────────────────────────────────────────────────────────────

def build_contact_line(c: dict) -> str:
    phone    = c.get("phone", "")
    email    = c.get("email", "")
    linkedin = c.get("linkedin_url", "").rstrip("/")
    github   = c.get("github_url", "").rstrip("/")

    links = []
    if phone:
        links.append(escape(phone))
    if email:
        links.append(rf"\href{{mailto:{email}}}{{{escape(email)}}}")
    if linkedin:
        disp = "linkedin.com/in/" + linkedin.rsplit("/", 1)[-1]
        links.append(rf"\href{{{linkedin}}}{{{escape(disp)}}}")
    if github:
        disp = "github.com/" + github.rsplit("/", 1)[-1]
        links.append(rf"\href{{{github}}}{{{escape(disp)}}}")
    return r"  \textbar{}  ".join(links)


# ── Document assembly ─────────────────────────────────────────────────────────

TEMPLATE_PATH = Path(__file__).parent / "resume_template.tex"
REFERENCE_PATH = Path(__file__).parent.parent / "reference" / "resume.tex"


def replace_section_body(tex: str, section_name: str, body: str) -> str:
    """Replace the body after a section heading, preserving the heading itself."""
    pattern = re.compile(
        rf"(\\section\*\{{{re.escape(section_name)}\}}\n)(.*?)(?=\\section\*\{{|\\end\{{document\}})",
        re.DOTALL,
    )
    updated, count = pattern.subn(
        lambda m: m.group(1) + body.rstrip() + "\n",
        tex,
        count=1,
    )
    if count != 1:
        raise ValueError(f"Section '{section_name}' not found in reference resume")
    return updated


def render_header(content: dict) -> str:
    candidate = content.get("candidate", {})
    return (
        "\\begin{center}\n"
        f"  {{\\LARGE\\bfseries\\color{{navy}} {escape(candidate.get('name', ''))}}}\\\\[2pt]\n"
        f"  {{\\small\\color{{darkgray}} {build_contact_line(candidate)}}}\n"
        "\\end{center}"
    )


def render_education(entries: list) -> str:
    parts = []
    for entry in entries:
        parts.append(
            "\\noindent\\textbf{"
            f"{escape(entry.get('institution', ''))}, {escape(entry.get('degree', ''))}"
            "}\\hfill\\textcolor{darkgray}{"
            f"{escape(entry.get('location', ''))}"
            "}\\\\[-2pt]\n"
            "\\noindent \\textit{Relevant courses: "
            f"{escape(entry.get('courses', ''))}"
            "}\\hfill\\textcolor{darkgray}{"
            f"{escape(entry.get('dates', ''))}"
            "}\n\n"
            "\\vspace{3pt}\n"
        )
    return "\n".join(parts)


def render_experience(entries: list) -> str:
    parts = []
    for entry in entries:
        bullets = "\n".join(
            f"  \\item {render_bullet(b)}" for b in entry.get("bullets", [])
        )
        parts.append(
            "\\noindent\\textbf{"
            f"{escape(entry.get('company', ''))}"
            "}\\hfill\\textcolor{darkgray}{"
            f"{escape(entry.get('location', ''))}"
            "}\\\\[-2pt]\n"
            "\\noindent \\textit{"
            f"{escape(entry.get('title', ''))}"
            "}\\hfill\\textcolor{darkgray}{"
            f"{escape(entry.get('dates', ''))}"
            "}\n"
            "\\begin{itemize}[leftmargin=1.5em, topsep=1pt, itemsep=0pt, parsep=0pt]\n"
            f"{bullets}\n"
            "\\end{itemize}\n"
            "\\vspace{1pt}\n"
        )
    return "\n".join(parts)


def render_skills(skills: dict) -> str:
    return (
        f"\\noindent\\textbf{{Languages:}} {escape(skills.get('languages', ''))}\\\\\n"
        "\\noindent\\textbf{Frameworks and Libraries:} "
        f"{escape(skills.get('frameworks', ''))}\\\\\n"
        f"\\noindent\\textbf{{Data Science:}} {escape(skills.get('data_science', ''))}\\\\\n"
        "\\noindent\\textbf{Visualization Tools:} "
        f"{escape(skills.get('visualization', ''))}\\\\\n"
        f"\\noindent\\textbf{{Other Tools:}} {escape(skills.get('other_tools', ''))}\n"
    )


def render_projects(entries: list) -> str:
    parts = []
    for entry in entries:
        bullets = "\n".join(
            f"  \\item {render_bullet(b)}" for b in entry.get("bullets", [])
        )
        parts.append(
            "\\noindent\\textbf{"
            f"{escape(entry.get('name', ''))} | "
            "}\\textit{"
            f"{escape(entry.get('tools', ''))}"
            "}\n"
            "\\begin{itemize}[leftmargin=1.5em, topsep=1pt, itemsep=0pt, parsep=0pt]\n"
            f"{bullets}\n"
            "\\end{itemize}\n"
            "\\vspace{1pt}\n"
        )
    return "\n".join(parts)


def build_document_from_template(content: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Render per-entry blocks first — they own placeholders like {{name}}
    # (project name) and {{location}} that would collide with header/skills
    # if we did a global substitution before extracting the blocks.
    template = render_section(template, "education", content.get("education", []))
    template = render_section(template, "experience", content.get("experience", []))
    template = render_section(template, "project",    content.get("projects", []))

    candidate = content.get("candidate", {})
    template = substitute(template, {
        "name":         escape(candidate.get("name", "")),
        "contact_line": build_contact_line(candidate),
    })

    skills = content.get("skills", {})
    template = substitute(template, {k: escape(v) for k, v in skills.items()})
    return template


def build_document_from_reference(content: dict, reference_text: str = None) -> str:
    """Render content into a copy of reference/resume.tex without modifying it."""
    if reference_text is None and not REFERENCE_PATH.exists():
        return build_document_from_template(content)

    tex = reference_text if reference_text is not None else REFERENCE_PATH.read_text(encoding="utf-8")
    tex, count = re.subn(
        r"\\begin\{center\}.*?\\end\{center\}",
        lambda _m: render_header(content),
        tex,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Header block not found in reference resume")

    tex = replace_section_body(tex, "Education", render_education(content.get("education", [])))
    tex = replace_section_body(tex, "Experience", render_experience(content.get("experience", [])))
    tex = replace_section_body(tex, "Skills", render_skills(content.get("skills", {})))
    tex = replace_section_body(tex, "Projects", render_projects(content.get("projects", [])))
    return tex


def build_document(content: dict, use_reference: bool = True, reference_text: str = None) -> str:
    if use_reference:
        return build_document_from_reference(content, reference_text=reference_text)
    return build_document_from_template(content)


# ── Compilation ───────────────────────────────────────────────────────────────

def compile_latex(tex_path: Path, output_pdf: Path) -> bool:
    if not shutil.which("pdflatex"):
        print("[ERROR] pdflatex not found on PATH.")
        print("        Install MiKTeX from https://miktex.org/download")
        return False

    for pass_num in (1, 2):
        print(f"[LaTeX] Compiling pass {pass_num}/2...")
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] pdflatex failed on pass {pass_num}.")
            for line in result.stdout.splitlines():
                if line.startswith("!") or "Error" in line:
                    print(" ", line)
            print(f"Full log: {tex_path.with_suffix('.log')}")
            return False

    compiled = tex_path.with_suffix(".pdf")
    if compiled.exists():
        try:
            from pypdf import PdfReader
            pages = len(PdfReader(str(compiled)).pages)
            if pages != 1:
                print(f"[ERROR] PDF compiled but is {pages} pages; target is exactly 1 page.")
                return False
        except Exception as e:
            print(f"[ERROR] Could not verify PDF page count: {e}")
            return False

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(compiled), str(output_pdf))
        print(f"[OK] PDF saved to {output_pdf}")
        return True

    print("[ERROR] Compilation appeared to succeed but PDF not found.")
    return False


def cleanup_artifacts(tex_path: Path) -> None:
    for ext in (".aux", ".log", ".out", ".fls", ".fdb_latexmk"):
        artifact = tex_path.with_suffix(ext)
        if artifact.exists():
            artifact.unlink()


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_resume(
    content: dict,
    output_path: str,
    compile_pdf_output: bool = True,
    reference_text: str = None,
) -> None:
    out = Path(output_path)
    tex_path = out.with_suffix(".tex")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[LaTeX] Building {tex_path.name}...")
    tex_path.write_text(build_document(content, reference_text=reference_text), encoding="utf-8")

    if not compile_pdf_output:
        print(f"[LaTeX] Source saved to {tex_path}")
        return

    if compile_latex(tex_path, out):
        cleanup_artifacts(tex_path)
        print(f"[LaTeX] Source kept at {tex_path}")
    else:
        print(f"[LaTeX] Debug the source at {tex_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Render resume PDF from JSON via LaTeX template"
    )
    parser.add_argument("--input",  required=True, help="Path to resume_content.json")
    parser.add_argument("--output", required=True, help="Output PDF path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}")
        return

    content = json.loads(input_path.read_text(encoding="utf-8"))

    errors = validate_line_budgets(content)
    if errors:
        print("\n[FAIL] line-budget violations — fix resume_content.json before generating:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    generate_resume(content, args.output)


if __name__ == "__main__":
    main()
