"""
Setup page — workspace configuration wizard.

Uploads resumes, asks Claude to draft profile.json + experience files, lets
the user review and confirm.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui_common import render_onboarding


st.set_page_config(page_title="Setup · Resume Tailor", layout="wide", page_icon="⚙️")

st.title("⚙️ Setup")
st.caption(
    "First-time configuration: paste your Anthropic API key, add your basic profile, "
    "and upload existing resumes. Claude will draft your workspace files; you confirm "
    "before they're saved."
)

render_onboarding()
