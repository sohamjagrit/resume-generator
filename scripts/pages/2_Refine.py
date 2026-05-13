"""
Refine page — pick any existing resume, edit the LaTeX, watch the PDF + stats update.

Layout:
  • Sidebar: history of generated resumes (radio)
  • Top: live ATS panel for the currently selected resume + JD
  • Below: LaTeX editor (left) + PDF preview (right)
  • Bottom: recompile / save / download actions
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from tex_stats import (
    parse_tex_sections,
    compute_line_stats,
    compute_keyword_stats,
)
from ats_score import compute_ats_score
from ui_common import (
    list_resume_slugs,
    load_resume,
    save_tex,
    save_jd,
    compile_pdf,
    reset_editor_to_reference,
    render_pdf,
    render_ats_panel,
)


st.set_page_config(page_title="Refine · Resume Tailor", layout="wide", page_icon="✏️")
st.session_state.setdefault("selected_slug", "resume_draft")

st.title("✏️ Refine")

# ── Sidebar: history of resumes ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Resumes")
    slugs = list_resume_slugs()
    if not slugs:
        st.info("No resumes yet. Head to the **Generate** page first.")
        st.stop()

    default_idx = 0
    if st.session_state["selected_slug"] in slugs:
        default_idx = slugs.index(st.session_state["selected_slug"])
    selected = st.radio(
        "Pick one",
        slugs,
        index=default_idx,
        format_func=lambda s: s.replace("resume_", "").replace("_", " — ").replace("-", " "),
        label_visibility="collapsed",
    )
    if selected != st.session_state["selected_slug"]:
        st.session_state["selected_slug"] = selected
        # Clear the editor's bound state so it reloads the new slug's TeX.
        st.session_state.pop(f"editor_tex_{selected}", None)
        st.rerun()

slug = st.session_state["selected_slug"]
data = load_resume(slug)
jd_text = data["jd"]

# ── Live stats (parsed from current editor TeX) ──────────────────────────────
current_tex = st.session_state.get(f"editor_tex_{slug}", data["tex"])
parsed = parse_tex_sections(current_tex)
line_stats = compute_line_stats(parsed)
kw_stats = compute_keyword_stats(parsed, jd_text)
ats_stats = compute_ats_score(
    jd_text,
    current_tex,
    parsed,
    pdf_exists=data["pdf_path"].exists(),
)

render_ats_panel(ats_stats)

# Compact line-budget summary below the ATS panel
with st.container(border=True):
    ok_count = sum(1 for s in line_stats["sections"] if s["ok"])
    total_sections = len(line_stats["sections"])
    overall = "✅" if line_stats["all_ok"] else "⚠️"
    st.markdown(f"{overall} **Line budget — {ok_count}/{total_sections} sections OK**")
    for s in line_stats["sections"]:
        icon = "✅" if s["ok"] else "⚠️"
        breakdown = " + ".join(f"{b['lines']}L ({b['chars']}c)" for b in s["bullets"])
        st.caption(
            f"{icon} {s['name'][:32]} — {s['actual']}/{s['target']}L · {breakdown}"
        )

st.divider()

# ── Editor + PDF ─────────────────────────────────────────────────────────────
col_tex, col_pdf = st.columns(2, gap="medium")

with col_tex:
    st.markdown("**LaTeX source**")
    tex = st.text_area(
        "TeX",
        value=data["tex"],
        height=720,
        key=f"editor_tex_{slug}",
        label_visibility="collapsed",
    )

    e1, e2, e3 = st.columns(3)
    with e1:
        if st.button("Save TeX", use_container_width=True):
            save_tex(slug, tex)
            st.toast("Saved.", icon="💾")
    with e2:
        if st.button("💾 Save + Recompile", type="primary", use_container_width=True):
            save_tex(slug, tex)
            with st.spinner("pdflatex…"):
                ok, log, warnings = compile_pdf(slug)
            if ok:
                if warnings:
                    for w in warnings:
                        st.warning(w)
                else:
                    st.toast("Recompiled.", icon="✅")
                st.rerun()
            else:
                st.error("Compile failed — log below.")
                with st.expander("pdflatex log"):
                    st.code(log[-3000:], language="text")
    with e3:
        if st.button("Reset To Reference", use_container_width=True):
            reset_editor_to_reference(slug)

    # JD reference (read-only, helpful while editing bullets)
    if jd_text:
        with st.expander("Job description (reference)", expanded=False):
            st.text_area(
                "JD",
                value=jd_text,
                height=240,
                key=f"jd_ref_{slug}",
                label_visibility="collapsed",
                disabled=True,
            )

with col_pdf:
    st.markdown("**PDF preview**")
    render_pdf(data["pdf_path"])
    pdf_exists = data["pdf_path"].exists()
    st.download_button(
        "Download PDF",
        data=data["pdf_path"].read_bytes() if pdf_exists else b"",
        file_name=f"{slug}.pdf",
        mime="application/pdf",
        use_container_width=True,
        disabled=not pdf_exists,
    )
