"""
ui_common.py — Shared helpers used by app.py and every page in pages/.

Groups:
  • Paths and constants
  • File I/O (resume / JD / API key / uploaded files / workspace)
  • Backend ops (compile_pdf, validate_resume_rules, compute_readiness)
  • Render helpers (readiness, quality cards, ATS panel, onboarding, PDF preview)
  • Workflow handlers (_run_url_fetch, _run_generation, _run_autofix, _run_update_latex)
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple

import streamlit as st

# Make sibling scripts importable when ui_common is imported from pages/.
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tex_stats import (
    parse_tex_sections,
    compute_line_stats,
    compute_keyword_stats,
)
from ats_score import compute_ats_score
from validate_resume_content import validate as validate_line_budgets
from generate_resume import generate_resume as render_pdf_from_json


# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_PATH = ROOT / "profile.json"
EXPERIENCES_DIR = ROOT / "experiences"
EXPERIENCES_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_TEX = ROOT / "reference" / "resume.tex"


# ── Resume I/O ────────────────────────────────────────────────────────────────

def list_resume_slugs() -> list:
    if not OUTPUT_DIR.exists():
        return []
    return sorted(p.stem for p in OUTPUT_DIR.glob("resume_*.tex"))


def load_resume(slug: str) -> dict:
    tex_path = OUTPUT_DIR / f"{slug}.tex"
    pdf_path = OUTPUT_DIR / f"{slug}.pdf"
    jd_path  = OUTPUT_DIR / f"{slug}.jd.txt"
    return {
        "slug": slug,
        "tex_path": tex_path,
        "pdf_path": pdf_path,
        "tex": (
            tex_path.read_text(encoding="utf-8")
            if tex_path.exists()
            else REFERENCE_TEX.read_text(encoding="utf-8")
            if REFERENCE_TEX.exists()
            else ""
        ),
        "jd":  jd_path.read_text(encoding="utf-8") if jd_path.exists() else "",
    }


def save_tex(slug: str, tex: str) -> None:
    (OUTPUT_DIR / f"{slug}.tex").write_text(tex, encoding="utf-8")


def save_jd(slug: str, jd: str) -> None:
    (OUTPUT_DIR / f"{slug}.jd.txt").write_text(jd, encoding="utf-8")


def save_api_key(api_key: str) -> None:
    env_path = ROOT / ".env"
    lines = []
    if env_path.exists():
        lines = [
            line for line in env_path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("ANTHROPIC_API_KEY=")
        ]
    lines.append(f"ANTHROPIC_API_KEY={api_key.strip()}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    st.toast("API key saved locally.")


def extract_uploaded_text(uploaded_file) -> Tuple[str, str]:
    """Pull plain text out of a PDF / DOCX / TXT / MD / TEX upload."""
    suffix = Path(uploaded_file.name).suffix.lower()
    data = uploaded_file.getvalue()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip(), ""
        except Exception as e:
            return "", f"{uploaded_file.name}: PDF text extraction failed ({e}). Try TXT/MD export."

    if suffix == ".docx":
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs)
            return text.strip(), ""
        except Exception as e:
            return "", f"{uploaded_file.name}: DOCX text extraction failed ({e}). Try TXT/MD export."

    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding).strip(), ""
        except UnicodeDecodeError:
            continue
    return "", f"{uploaded_file.name}: could not decode file text."


def confirm_workspace(profile: dict, professional_md: str, projects_md: str) -> None:
    PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    (EXPERIENCES_DIR / "professional.md").write_text(professional_md, encoding="utf-8")
    (EXPERIENCES_DIR / "projects.md").write_text(projects_md, encoding="utf-8")

    try:
        from read_experiences import load_all_experiences
        parsed = load_all_experiences(str(ROOT))
        (ROOT / "parsed_experiences.json").write_text(
            json.dumps(parsed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        st.warning(f"Profile saved, but parsed_experiences.json could not be refreshed: {e}")
        return

    st.session_state["profile_confirmed"] = True
    st.session_state["show_setup"] = False
    st.toast("Workspace confirmed and files updated.")
    st.rerun()


# ── PDF compile + validators ──────────────────────────────────────────────────

def compile_pdf(slug: str) -> Tuple[bool, str, list]:
    """Compile <slug>.tex via pdflatex.

    Returns (ok, message, warnings):
      • ok=True iff pdflatex produced a PDF, regardless of page count.
      • message is "compiled" on success or the pdflatex log on failure.
      • warnings are non-fatal (e.g. multi-page); callers should surface but
        NOT block on these — the PDF is on disk and ready to display.
    """
    tex_path = OUTPUT_DIR / f"{slug}.tex"
    warnings: list = []
    if not shutil.which("pdflatex"):
        return False, "pdflatex not on PATH. Install MiKTeX or TeX Live.", warnings

    last_log = ""
    for _ in range(2):
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
        )
        last_log = result.stdout
        if result.returncode != 0:
            return False, last_log, warnings

    for ext in (".aux", ".log", ".out", ".fls", ".fdb_latexmk"):
        artifact = OUTPUT_DIR / f"{slug}{ext}"
        if artifact.exists():
            artifact.unlink()

    pdf_path = OUTPUT_DIR / f"{slug}.pdf"
    if pdf_path.exists():
        try:
            from pypdf import PdfReader
            pages = len(PdfReader(str(pdf_path)).pages)
            if pages != 1:
                warnings.append(
                    f"PDF compiled but spans {pages} page(s); target is 1. "
                    "Trim a bullet or two — the PDF is shown anyway."
                )
        except Exception as e:
            warnings.append(f"PDF compiled but page count could not be checked: {e}")

    return True, "compiled", warnings


def validate_resume_rules(content: dict) -> list:
    """Blocking validations beyond the line budget."""
    errors = []
    projects = content.get("projects", [])
    if len(projects) != 2:
        errors.append(f"Project section has {len(projects)} projects; expected exactly 2.")
    for i, project in enumerate(projects, start=1):
        if not project.get("name"):
            errors.append(f"Project {i} is missing a name.")
        if not project.get("tools"):
            errors.append(f"Project {i} is missing tools.")
        if len(project.get("bullets", [])) < 1:
            errors.append(f"Project {i} has no bullets.")
    return errors


def reset_editor_to_reference(slug: str) -> None:
    if not REFERENCE_TEX.exists():
        st.error("reference/resume.tex was not found.")
        return
    st.session_state[f"editor_tex_{slug}"] = REFERENCE_TEX.read_text(encoding="utf-8")
    st.toast("Editor reset to reference resume.")
    st.rerun()


# ── Readiness state ───────────────────────────────────────────────────────────

def compute_readiness(jd_text: str, data: dict) -> dict:
    validation = st.session_state.get("last_validation")
    last_gen = st.session_state.get("last_gen")
    rendered_gen = st.session_state.get("rendered_gen")
    pending_slug = st.session_state.get("pending_slug")

    jd_loaded = bool(jd_text.strip())
    draft_generated = bool(last_gen)
    validation_passed = bool(validation and validation.get("passed"))
    validation_failed = bool(validation and not validation.get("passed"))
    tex_updated = bool(rendered_gen and data["tex_path"].exists())
    pdf_compiled = data["pdf_path"].exists()
    download_ready = pdf_compiled

    checks = [
        ("Job description loaded", jd_loaded),
        ("Claude draft generated", draft_generated),
        ("Project rules passed", validation_passed),
        ("LaTeX source updated", tex_updated),
        ("PDF compiled", pdf_compiled),
        ("Download available", download_ready),
    ]

    if validation_failed:
        status = "Needs Edits"
        tone = "warning"
        next_action = "Ask Claude to fix project/structure errors, then update the LaTeX source."
    elif not jd_loaded:
        status = "Not Started"
        tone = "info"
        next_action = "Paste a job description or fetch one from a URL."
    elif not draft_generated:
        status = "Ready For Draft"
        tone = "info"
        next_action = "Generate a Claude draft."
    elif not tex_updated:
        status = "Draft Ready"
        tone = "success"
        next_action = "Update the LaTeX source."
    elif not pdf_compiled:
        status = "Needs Compile"
        tone = "warning"
        next_action = "Compile the PDF from the updated LaTeX source."
    else:
        status = "Ready To Download"
        tone = "success"
        next_action = "Review the PDF visually, then download it."

    return {
        "status": status,
        "tone": tone,
        "next_action": next_action,
        "checks": checks,
        "pending_slug": pending_slug,
    }


# ── Render helpers ────────────────────────────────────────────────────────────

def render_readiness_panel(state: dict) -> None:
    with st.container(border=True):
        c_status, c_next = st.columns([1, 2])
        with c_status:
            if state["tone"] == "success":
                st.success(state["status"])
            elif state["tone"] == "warning":
                st.warning(state["status"])
            else:
                st.info(state["status"])
        with c_next:
            st.markdown("**Next action**")
            st.caption(state["next_action"])

        cols = st.columns(6)
        for col, (label, ok) in zip(cols, state["checks"]):
            with col:
                st.metric(label, "OK" if ok else "Pending")


def render_quality_cards(line_stats: dict, kw_stats: dict, validation: dict) -> None:
    sections = line_stats.get("sections", [])
    line_ok = line_stats.get("all_ok", False)
    failed_sections = [s for s in sections if not s.get("ok")]
    coverage = kw_stats.get("coverage_pct", 0)

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("**Line Budget**")
            st.metric("Status", "OK" if line_ok else "Needs edits")
            if failed_sections:
                st.caption(f"{len(failed_sections)} section(s) need attention")
            elif sections:
                st.caption("All parsed sections fit the target budget")
            else:
                st.caption("No rendered sections parsed yet")
    with c2:
        with st.container(border=True):
            st.markdown("**Keyword Coverage**")
            st.metric("Coverage", f"{coverage}%")
            missed = kw_stats.get("missed", [])
            st.caption(
                "Review missed keywords" if missed else "No missed keywords from current JD"
            )
    with c3:
        with st.container(border=True):
            st.markdown("**Claude Draft**")
            if validation and validation.get("passed"):
                st.metric("Project Rules", "Passed")
                st.caption("Ready to update LaTeX")
            elif validation:
                st.metric("Project Rules", "Failed")
                st.caption(f"{len(validation.get('errors', []))} issue(s) found")
            else:
                st.metric("Project Rules", "Pending")
                st.caption("Generate a draft to validate")


def render_ats_panel(ats: dict) -> None:
    score = ats["total"]
    if score >= 80:
        status = "Strong"
    elif score >= 65:
        status = "Good, review gaps"
    elif score >= 45:
        status = "Needs work"
    else:
        status = "Weak match"

    with st.container(border=True):
        c_score, c_breakdown = st.columns([1, 3])
        with c_score:
            st.metric("Live ATS Score", f"{score}/100", status)
            st.caption("Local heuristic, updates without Claude tokens.")
        with c_breakdown:
            b = ats["breakdown"]
            cols = st.columns(5)
            cols[0].metric("Keywords", f"{b['keyword']}/35")
            cols[1].metric("Skills", f"{b['skills']}/25")
            cols[2].metric("Role", f"{b['role']}/15")
            cols[3].metric("Structure", f"{b['structure']}/15")
            cols[4].metric("Warnings", f"{b['warnings']}/10")

        m1, m2, m3 = st.columns(3)
        with m1:
            with st.expander(f"Matched skills ({len(ats['matched_skills'])})"):
                st.write(", ".join(ats["matched_skills"]) or "_none_")
        with m2:
            with st.expander(f"Missed skills ({len(ats['missed_skills'])})"):
                st.write(", ".join(ats["missed_skills"]) or "_none_")
        with m3:
            with st.expander(f"Warnings ({len(ats['warnings_list'])})"):
                for warning in ats["warnings_list"]:
                    st.markdown(f"- {warning}")


def render_pdf(pdf_path: Path) -> None:
    if not pdf_path.exists():
        st.info("No compiled PDF yet. Click **Recompile PDF**.")
        return
    try:
        from streamlit_pdf_viewer import pdf_viewer
        pdf_viewer(str(pdf_path), width="100%", height=900)
    except Exception:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="900px" style="border:1px solid #ccc"></iframe>',
            unsafe_allow_html=True,
        )


def render_onboarding() -> None:
    confirmed = PROFILE_PATH.exists() or st.session_state.get("profile_confirmed")
    if confirmed and not st.session_state.get("show_setup"):
        st.caption("Profile loaded.")
        if st.button("Edit setup / profile"):
            st.session_state["show_setup"] = True
            st.rerun()
        return

    with st.expander(
        "First-time setup: personalize this app",
        expanded=True,
    ):
        if confirmed:
            if st.button("Hide setup"):
                st.session_state["show_setup"] = False
                st.rerun()

        st.caption(
            "Claude drafts the workspace files from your profile and uploaded resumes. "
            "Review the drafts, then confirm before using them for resume generation."
        )

        st.markdown("**1. API key**")
        api_key = st.text_input(
            "Anthropic API key",
            type="password",
            placeholder="sk-ant-...",
            label_visibility="collapsed",
        )
        if st.button("Save API Key", use_container_width=True):
            if not api_key.strip():
                st.warning("Paste an API key first.")
            else:
                save_api_key(api_key)

        st.markdown("**2. Basic profile**")
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Name", value="")
            email = st.text_input("Email", value="")
            phone = st.text_input("Phone", value="")
        with c2:
            linkedin = st.text_input("LinkedIn URL", value="")
            github = st.text_input("GitHub / Portfolio URL", value="")
            location = st.text_input("Current location", value="")
        with c3:
            target_roles = st.text_area(
                "Target roles",
                placeholder="Data Scientist, Data Analyst, ML Engineer...",
                height=124,
            )

        st.markdown("**3. Upload resumes**")
        uploaded = st.file_uploader(
            "Upload 1-4 resumes",
            type=["pdf", "docx", "txt", "md", "tex"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if st.button("Extract Profile From Resumes", type="primary", use_container_width=True):
            profile = {
                "name": name,
                "email": email,
                "phone": phone,
                "linkedin_url": linkedin,
                "github_url": github,
                "location": location,
                "target_roles": target_roles,
            }
            documents = []
            warnings = []
            for f in uploaded[:4]:
                text, warning = extract_uploaded_text(f)
                if warning:
                    warnings.append(warning)
                if text:
                    documents.append({"name": f.name, "text": text})
            for warning in warnings:
                st.warning(warning)
            if not documents:
                st.error("No readable resume text found. Try uploading TXT, MD, TEX, searchable PDF, or DOCX.")
            else:
                try:
                    from llm import extract_profile_from_resumes
                    with st.spinner("Claude is drafting your workspace files..."):
                        result = extract_profile_from_resumes(profile, documents)
                except Exception as e:
                    st.error(f"Profile extraction failed: {e}")
                else:
                    st.session_state["setup_profile"] = result.get("profile", profile)
                    st.session_state["setup_professional_md"] = result.get("professional_md", "")
                    st.session_state["setup_projects_md"] = result.get("projects_md", "")
                    st.session_state["setup_review_notes"] = result.get("review_notes", [])
                    st.success(f"Draft created (~${result['usage']['approx_usd']:.4f}). Review below.")

        if "setup_professional_md" in st.session_state:
            st.markdown("**4. Review and confirm**")
            notes = st.session_state.get("setup_review_notes", [])
            if notes:
                with st.container(border=True):
                    st.markdown("**Review notes**")
                    for note in notes:
                        st.markdown(f"- {note}")

            profile_json = st.text_area(
                "profile.json",
                value=json.dumps(st.session_state.get("setup_profile", {}), indent=2),
                height=220,
            )
            professional_md = st.text_area(
                "experiences/professional.md",
                value=st.session_state.get("setup_professional_md", ""),
                height=320,
            )
            projects_md = st.text_area(
                "experiences/projects.md",
                value=st.session_state.get("setup_projects_md", ""),
                height=260,
            )
            if st.button("Confirm Profile And Update Files", type="primary", use_container_width=True):
                try:
                    parsed_profile = json.loads(profile_json)
                except json.JSONDecodeError as e:
                    st.error(f"profile.json is invalid JSON: {e}")
                else:
                    confirm_workspace(parsed_profile, professional_md, projects_md)


# ── Workflow handlers (Claude API calls) ─────────────────────────────────────

def _run_url_fetch(url: str, slug: str) -> None:
    """Fetch a job URL, extract JD via Claude, write to <slug>.jd.txt."""
    try:
        from llm import fetch_jd_from_url
    except ImportError as e:
        st.error(f"llm module import failed: {e}")
        return

    with st.spinner("Fetching page + extracting JD via Claude…"):
        try:
            result = fetch_jd_from_url(url)
        except RuntimeError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Fetch failed: {e}")
            return

    save_jd(slug, result["jd_text"])
    st.session_state.pop(f"jd_text_{slug}", None)
    st.session_state["last_fetch"] = result
    st.toast(
        f"JD fetched (~${result['usage']['approx_usd']:.4f}, "
        f"in {result['usage']['input']}, out {result['usage']['output']})",
        icon="🌐",
    )
    st.rerun()


def _run_generation(jd_text: str) -> None:
    """Call Claude, validate, stash a pending draft for the user to approve."""
    try:
        from llm import generate_resume_content
    except ImportError as e:
        st.error(f"llm module import failed: {e}")
        return

    with st.spinner("Calling Claude Sonnet 4.6 (~10–20s)…"):
        try:
            result = generate_resume_content(jd_text)
        except RuntimeError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"API call failed: {e}")
            return

    (ROOT / "resume_content.json").write_text(
        json.dumps(result["resume_content"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    errors = validate_resume_rules(result["resume_content"])

    parsed_for_stats = {
        "experience": [
            {"name": r["company"], "bullets": r["bullets"]}
            for r in result["resume_content"].get("experience", [])
        ],
        "projects": [
            {"name": p["name"], "bullets": p["bullets"]}
            for p in result["resume_content"].get("projects", [])
        ],
    }
    st.session_state["last_validation"] = {
        "errors": errors,
        "sections": compute_line_stats(parsed_for_stats)["sections"],
        "passed": len(errors) == 0,
    }

    slug = f"resume_{result['slug']}"
    st.session_state["last_gen"] = result
    st.session_state["pending_slug"] = slug
    st.session_state["pending_jd"] = jd_text
    st.session_state["pending_ready"] = len(errors) == 0
    st.toast(f"Generated draft {slug} (~${result['usage']['approx_usd']:.3f})")
    st.rerun()


def _run_autofix() -> None:
    """Ask Claude to fix the last failed generation by feeding back validator errors."""
    try:
        from llm import regenerate_with_feedback
    except ImportError as e:
        st.error(f"llm module import failed: {e}")
        return

    vr = st.session_state.get("last_validation")
    last_gen = st.session_state.get("last_gen")
    if not vr or not last_gen or vr.get("passed"):
        st.error("No failed generation to fix.")
        return

    jd_text = ""
    for candidate in (last_gen.get("slug", ""), st.session_state.get("selected_slug", "")):
        jd_path = OUTPUT_DIR / f"resume_{candidate}.jd.txt"
        if not jd_path.exists():
            jd_path = OUTPUT_DIR / f"{candidate}.jd.txt"
        if jd_path.exists():
            jd_text = jd_path.read_text(encoding="utf-8")
            break
    if not jd_text:
        jd_text = st.session_state.get(f"jd_text_{st.session_state.get('selected_slug', '')}", "")
    if not jd_text.strip():
        st.error("Couldn't recover the JD text used for the failed generation.")
        return

    with st.spinner("Asking Claude to fix the violations…"):
        try:
            result = regenerate_with_feedback(
                jd_text=jd_text,
                validator_errors=vr["errors"],
                previous_raw=last_gen["raw"],
            )
        except RuntimeError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Auto-fix API call failed: {e}")
            return

    (ROOT / "resume_content.json").write_text(
        json.dumps(result["resume_content"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    errors = validate_resume_rules(result["resume_content"])
    parsed_for_stats = {
        "experience": [
            {"name": r["company"], "bullets": r["bullets"]}
            for r in result["resume_content"].get("experience", [])
        ],
        "projects": [
            {"name": p["name"], "bullets": p["bullets"]}
            for p in result["resume_content"].get("projects", [])
        ],
    }
    st.session_state["last_validation"] = {
        "errors": errors,
        "sections": compute_line_stats(parsed_for_stats)["sections"],
        "passed": len(errors) == 0,
    }

    prior_cost = last_gen["usage"]["approx_usd"]
    result["usage"]["cumulative_usd"] = prior_cost + result["usage"]["approx_usd"]

    if errors:
        st.session_state["last_gen"] = result
        st.warning(
            f"Auto-fix attempt still has {len(errors)} violation(s). "
            "Click again to try once more, or edit manually."
        )
        st.rerun()
        return

    slug = f"resume_{result['slug']}"
    st.session_state["last_gen"] = result
    st.session_state["pending_slug"] = slug
    st.session_state["pending_jd"] = jd_text
    st.session_state["pending_ready"] = True
    st.toast(
        f"Auto-fix succeeded. Draft ready ({slug}) · cumulative ~${result['usage']['cumulative_usd']:.4f}"
    )
    st.rerun()


def _run_update_latex(compile_after: bool) -> None:
    """Write the pending Claude content into output/<slug>.tex, optionally compiling."""
    result = st.session_state.get("last_gen")
    slug = st.session_state.get("pending_slug")
    if not result or not slug:
        st.error("Generate a resume draft first.")
        return

    vr = st.session_state.get("last_validation")
    if vr and not vr.get("passed"):
        st.error("The current draft failed validation. Ask Claude to fix it before updating LaTeX.")
        return

    output_pdf = OUTPUT_DIR / f"{slug}.pdf"
    editor_slug = st.session_state.get("selected_slug", slug)
    editor_tex = st.session_state.get(f"editor_tex_{editor_slug}", "")
    try:
        with st.spinner("Updating LaTeX source..."):
            render_pdf_from_json(
                result["resume_content"],
                str(output_pdf),
                compile_pdf_output=compile_after,
                reference_text=editor_tex or None,
            )
    except Exception as e:
        st.error(f"Could not update LaTeX source: {e}")
        return

    save_jd(slug, st.session_state.get("pending_jd", ""))
    st.session_state["selected_slug"] = slug
    st.session_state["rendered_gen"] = result
    st.session_state.pop(f"editor_tex_{slug}", None)
    st.session_state.pop(f"jd_text_{slug}", None)

    if compile_after:
        st.toast(f"Updated LaTeX and PDF for {slug}.")
    else:
        st.toast(f"Updated LaTeX source for {slug}.")
    st.rerun()
