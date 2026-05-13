"""
Generate page — JD in, tailored draft out.

Flow:
  1. Paste URL / fetch JD          (~$0.02)
  2. Click Generate                (~$0.05)
  3. Review draft + score
  4. Click "Update LaTeX Source" → writes output/<slug>.tex + PDF
  5. (optional) "Open in Refine" → switches to the editor page
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui_common import (
    load_resume,
    save_jd,
    _run_url_fetch,
    _run_generation,
    _run_autofix,
    _run_update_latex,
)


st.set_page_config(page_title="Generate · Resume Tailor", layout="wide", page_icon="📝")
st.session_state.setdefault("selected_slug", "resume_draft")

slug = st.session_state["selected_slug"]
data = load_resume(slug)

st.title("📝 Generate")
st.caption("Paste a job posting URL or its body text. Claude tailors a draft from your experience files.")

# ── URL bar ──────────────────────────────────────────────────────────────────
col_url, col_fetch = st.columns([4, 1], vertical_alignment="bottom")
with col_url:
    url = st.text_input(
        "Job posting URL",
        placeholder="https://www.linkedin.com/jobs/view/...  —  LinkedIn /jobs/view/ URLs work best",
        key="jd_url_input",
        label_visibility="collapsed",
    )
with col_fetch:
    if st.button("🌐 Fetch JD (~$0.02)", use_container_width=True):
        if not url.strip():
            st.warning("Paste a URL first.")
        else:
            _run_url_fetch(url, slug)

# ── JD body + Generate ───────────────────────────────────────────────────────
st.markdown("**Job description**")
jd_text = st.text_area(
    "JD body",
    value=data["jd"],
    height=300,
    key=f"jd_text_{slug}",
    label_visibility="collapsed",
    placeholder="Paste the JD body text here, or click Fetch JD above to populate it from a URL.",
)
b1, b2 = st.columns([1, 2])
with b1:
    if st.button("Save JD", use_container_width=True):
        save_jd(slug, jd_text)
        st.toast("JD saved.", icon="💾")
with b2:
    if st.button("🪄 Generate tailored resume (~$0.05)", type="primary", use_container_width=True):
        if not jd_text.strip():
            st.warning("Paste a JD first.")
        else:
            _run_generation(jd_text)

# ── Validation panel (only on failure) ──────────────────────────────────────
vr = st.session_state.get("last_validation")
if vr and not vr["passed"]:
    with st.container(border=True):
        st.error(f"❌ Last generation failed {len(vr['errors'])} validator check(s)")
        for s in vr["sections"]:
            icon = "✅" if s["ok"] else "❌"
            breakdown = " + ".join(f"{b['lines']}L ({b['chars']}c)" for b in s["bullets"])
            st.markdown(f"{icon} **{s['name']}** — {s['actual']}/{s['target']}L · {breakdown}")
        st.markdown("**Failures:**")
        for err in vr["errors"]:
            st.markdown(f"- {err}")

        f1, f2 = st.columns(2)
        with f1:
            if st.button("🔁 Ask Claude to fix (~$0.05)", type="primary", use_container_width=True):
                _run_autofix()
        with f2:
            if st.button("Dismiss", use_container_width=True):
                st.session_state.pop("last_validation", None)
                st.rerun()
        with st.expander("Raw model response (debug)"):
            st.code(
                st.session_state.get("last_gen", {}).get("raw", "(no response captured)"),
                language="text",
            )

# ── Pending draft panel (after a successful generation) ──────────────────────
pending_slug = st.session_state.get("pending_slug")
if pending_slug and st.session_state.get("last_gen"):
    with st.container(border=True):
        st.success(f"Draft ready: **{pending_slug}**")
        c_update, c_open = st.columns(2)
        with c_update:
            if st.button(
                "Update LaTeX + Compile",
                type="primary",
                use_container_width=True,
                help="Writes the draft to output/<slug>.tex and recompiles the PDF.",
            ):
                _run_update_latex(compile_after=True)
        with c_open:
            if st.button(
                "Open in Refine →",
                use_container_width=True,
                help="Switch to the Refine page to edit the LaTeX and see the PDF.",
            ):
                st.session_state["selected_slug"] = pending_slug
                st.switch_page("pages/2_Refine.py")

# ── Last rendered generation summary ─────────────────────────────────────────
lg = st.session_state.get("rendered_gen")
if lg and (not vr or vr.get("passed")):
    with st.expander(
        f"📊  {lg['slug']} · score {lg['score']['total']}/100 · ~${lg['usage']['approx_usd']:.4f}",
        expanded=False,
    ):
        st.markdown(f"**Analysis:** {lg['analysis']}")
        st.markdown(
            f"**Score:** keyword {lg['score']['keyword']}/25 · "
            f"skills {lg['score']['skills']}/25 · "
            f"industry {lg['score']['industry']}/25 · "
            f"role {lg['score']['role']}/25"
        )
        if lg["projects"]:
            st.markdown("**Projects:** " + "; ".join(lg["projects"]))
        if lg["keywords"]:
            st.markdown("**Keywords injected:**")
            for k in lg["keywords"]:
                st.markdown(f"- {k}")
        if lg["gaps"]:
            st.markdown("**Gaps:**")
            for g in lg["gaps"]:
                st.markdown(f"- {g}")
