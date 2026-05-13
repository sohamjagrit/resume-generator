"""
app.py — Home for the multi-page Resume Tailor.

Streamlit auto-discovers anything in scripts/pages/ and lists it in the left
sidebar. This page is just the entry point: status banner, page cards, and a
list of recent resumes.

Run with:
    uv run streamlit run scripts/app.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from ui_common import (
    PROFILE_PATH,
    OUTPUT_DIR,
    list_resume_slugs,
)


st.set_page_config(page_title="Resume Tailor", layout="wide", page_icon="📄")

st.title("📄 Resume Tailor")
st.caption("Tailor your resume to a specific job posting in one click.")

# ── Status banner ───────────────────────────────────────────────────────────

profile_ok = PROFILE_PATH.exists()
api_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))

if not (profile_ok and api_ok):
    with st.container(border=True):
        st.warning("Setup is incomplete")
        if not profile_ok:
            st.markdown(
                "- **Profile not configured.** Upload your resumes on the Setup page "
                "so Claude knows your background."
            )
        if not api_ok:
            st.markdown(
                "- **Anthropic API key not loaded.** Add it on the Setup page (or paste "
                "into `.env`) so generation works."
            )
        if st.button("⚙️ Go to Setup", type="primary"):
            st.switch_page("pages/0_Setup.py")

# ── Page cards ──────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns(3, gap="medium")
with c1:
    with st.container(border=True):
        st.markdown("### ⚙️ Setup")
        st.caption(
            "Configure your profile and upload existing resumes. Claude drafts "
            "your workspace files; you confirm before they're saved."
        )
        if st.button("Open Setup", key="open_setup_card", use_container_width=True):
            st.switch_page("pages/0_Setup.py")
with c2:
    with st.container(border=True):
        st.markdown("### 📝 Generate")
        st.caption(
            "Paste a job URL or JD text. Claude returns a tailored draft in ~15 seconds. "
            "Click **Update LaTeX** to compile the PDF."
        )
        if st.button("Open Generate", key="open_generate_card", use_container_width=True):
            st.switch_page("pages/1_Generate.py")
with c3:
    with st.container(border=True):
        st.markdown("### ✏️ Refine")
        st.caption(
            "Pick any existing resume. Edit the LaTeX, watch the PDF and ATS score "
            "update, recompile, download."
        )
        if st.button("Open Refine", key="open_refine_card", use_container_width=True):
            st.switch_page("pages/2_Refine.py")

st.divider()

# ── Recent resumes ──────────────────────────────────────────────────────────

st.markdown("### Recent resumes")
slugs = list_resume_slugs()
if not slugs:
    st.info(
        "No resumes yet. Head to **Generate** to create your first one, "
        "or **Setup** if you haven't configured your profile."
    )
else:
    # Sort by mtime, newest first; cap at 10.
    def _mtime(slug: str) -> float:
        path = OUTPUT_DIR / f"{slug}.tex"
        return path.stat().st_mtime if path.exists() else 0.0

    slugs_sorted = sorted(slugs, key=_mtime, reverse=True)[:10]

    for slug in slugs_sorted:
        pdf_path = OUTPUT_DIR / f"{slug}.pdf"
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            label = slug.replace("resume_", "").replace("_", " — ").replace("-", " ")
            st.markdown(f"**{label}**")
            if not pdf_path.exists():
                st.caption("⚠️ PDF not compiled")
        with c2:
            st.caption(datetime.fromtimestamp(_mtime(slug)).strftime("%b %d, %H:%M"))
        with c3:
            if st.button("Open", key=f"open_{slug}", use_container_width=True):
                st.session_state["selected_slug"] = slug
                st.switch_page("pages/2_Refine.py")
