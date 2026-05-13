# Resume Tailor

A Streamlit app that tailors a one-page resume to a specific job posting using
Claude as the writer and LaTeX as the renderer. Paste a job URL → ~15 seconds
later you have a PDF and a match score.

The pipeline:

```
Your experience files  ─┐
Job description (URL    │
or text)              ──┼──► Claude (tailors bullets)
                        │           │
                        │           ▼
                        │      resume_content.json
                        │           │
                        │           ▼
LaTeX template  ────────┴──► generate_resume.py ──► pdflatex ──► PDF
```

Strict guarantees the app enforces:

- **No fabricated bullets.** Every bullet in the output is a tweaked version
  of a bullet in your own experience files. Claude is not allowed to invent
  metrics or add tools that weren't already in the source.
- **One page.** Per-section line budgets keep the output bounded; a soft
  warning fires if the compiled PDF still spills.
- **ATS-friendly layout.** Standard sections, Times 10pt, no images.

---

## Prerequisites

You need three things installed locally **before** cloning:

| Tool | Why | Get it from |
|---|---|---|
| **Python 3.12 or newer** | Backend language | [python.org/downloads](https://www.python.org/downloads/) |
| **uv** | Fast Python package manager / runner | [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **pdflatex** | Compiles LaTeX → PDF | **Windows:** [MiKTeX](https://miktex.org/download) (choose "install missing packages on-the-fly: yes"). **Mac:** [MacTeX](https://www.tug.org/mactex/) (or `brew install --cask mactex-no-gui`). **Linux:** `sudo apt install texlive-latex-extra` |

Plus one credential:

- **An Anthropic API key.** Sign up at [console.anthropic.com](https://console.anthropic.com/),
  add a payment method ($5 minimum), then **Settings → API Keys → Create Key**.
  Copy the key (Anthropic shows it only once).

After installing, verify each from a terminal:

```bash
python --version          # should print 3.12.x or higher
uv --version              # any version
pdflatex --version        # should print "pdfTeX 3.x" or similar
```

If any of these don't print, fix that one before continuing.

---

## Install

```bash
git clone <this-repo-url> resume-tailor
cd resume-tailor
uv sync                   # installs all Python dependencies into .venv/
```

`uv sync` reads `pyproject.toml` and creates a virtual environment with
Streamlit, the Anthropic SDK, pypdf, python-dotenv, etc. It takes ~30 seconds
the first time and is instant after.

---

## Configure

### 1. Set your API key

Copy the template:

```bash
cp .env.example .env      # macOS / Linux
copy .env.example .env    # Windows PowerShell
```

Open `.env` and replace the placeholder with your real key:

```
ANTHROPIC_API_KEY=sk-ant-api03-...your-actual-key...
```

`.env` is gitignored — it will never be committed.

### 2. Launch the app

```bash
uv run streamlit run scripts/app.py
```

This opens `http://localhost:8501` in your browser. You'll see a Home page
with a status banner warning that **Setup is incomplete** — that's expected
for a fresh install.

### 3. Run the Setup wizard

Click **Setup** in the left sidebar (or "Go to Setup" on the banner).

1. **Paste your API key** in the password field, click **Save API Key**. (This
   writes it back to `.env`. Skip if you already set it manually above.)
2. **Fill in basic profile** — name, email, phone, LinkedIn, GitHub, location,
   target roles you're applying to.
3. **Upload 1–4 existing resumes** (PDF, DOCX, TXT, MD, or TEX). These are
   your source of truth — every bullet the app outputs will trace back to one
   of these.
4. Click **Extract Profile From Resumes**. Claude reads them and drafts:
   - `profile.json` — your candidate metadata
   - `experiences/professional.md` — every role with bullets + tags
   - `experiences/projects.md` — every project with bullets + tags
5. **Review the drafts** in the text areas that appear. Fix anything wrong.
6. Click **Confirm Profile And Update Files**. The workspace is now ready.

Setup costs ~$0.05–0.15 in API tokens, depending on how many resumes you
uploaded.

---

## Daily usage

The app has three pages — all visible in the left sidebar.

### Generate (most common path)

1. Open **Generate**.
2. Paste a job URL (LinkedIn `/jobs/view/...` works best) → click **🌐 Fetch
   JD**. The JD area auto-fills in ~5 seconds. Cost: ~$0.02. *Alternatively,
   skip the URL and paste the JD body text directly.*
3. Click **🪄 Generate tailored resume**. Cost: ~$0.05.
4. Wait ~15 seconds. You'll see a **Draft ready** banner with:
   - The match score (0–100)
   - Two buttons: **Update LaTeX + Compile** and **Open in Refine →**
5. Click **Update LaTeX + Compile** to write the resume to disk and render the
   PDF.
6. Click **Open in Refine →** to switch to the editor.

### Refine

For tweaking bullets after generation.

- **Left sidebar**: list of every resume in `output/`. Click one to load it.
- **Top**: live ATS score + line-budget compliance for the loaded resume.
  Updates instantly as you type in the editor below.
- **LaTeX editor (left)** + **PDF preview (right)**: edit, click **Save +
  Recompile**, see the PDF update. The JD that produced this resume is
  available as a read-only expander next to the editor.
- **Download PDF**: bottom-right.

### Home

Just a launcher with a recent-resumes list. The "Open" button on any recent
resume jumps straight to Refine with it pre-loaded.

---

## How it works under the hood

The app is a thin Streamlit shell over a deterministic generation pipeline.
Each step is its own Python module so you can read or modify any of them.

### 1. Experience files are the only source of truth

`experiences/professional.md` and `experiences/projects.md` are your locked
factual base. Claude is forbidden from inventing tools, metrics, or outcomes
that aren't in these files. It can only rephrase, swap synonyms, or change
action verbs.

This means: if a tool isn't in your experience files, it won't appear in any
generated resume — even if the JD asks for it loudly. The right fix is to
update your experience files when you learn a new skill, not to let Claude
make things up.

### 2. JD → Claude → JSON

When you click Generate, the app calls
[`llm.generate_resume_content`](scripts/llm.py). The Anthropic API gets:

- **System prompt** (cached for 5 minutes): the rules from
  [CLAUDE.md](CLAUDE.md), your candidate profile, your parsed experiences.
  About 4,300 tokens — cached so the second resume in a session costs ~$0.001
  on this part.
- **User prompt**: just the JD text + "go" instruction.

Claude returns a structured response: analysis, score, project picks,
keywords injected, and a JSON block. The JSON gets saved as
`resume_content.json`.

### 3. JSON → LaTeX

[`generate_resume.py`](scripts/generate_resume.py) loads
[`scripts/resume_template.tex`](scripts/resume_template.tex), substitutes the
bullet content into placeholder regions, and writes the rendered `.tex` to
`output/<slug>.tex`. The template is the single source of layout truth —
fonts, margins, spacing, section order. Tweak the template, every future
resume looks different.

### 4. LaTeX → PDF

`pdflatex` runs twice (for reference resolution) and produces
`output/<slug>.pdf`. Auxiliary files (`.aux`, `.log`) get cleaned up.

### 5. Validators

Two layers:

- **Pre-compile** ([`validate_resume_content.py`](scripts/validate_resume_content.py)):
  checks that each section has the right number of bullets and that the total
  rendered character count fits the per-section budget. Empirical:
  `CHARS_PER_LINE = 135` for Times 10pt at our margins.
- **Post-compile**: reads the compiled PDF's page count via `pypdf`. If it
  spans more than 1 page, fires a soft warning (doesn't block — you still see
  the PDF).

If either check fails on a fresh generation, you'll see a red validation
panel with per-section pass/fail breakdown plus a **🔁 Ask Claude to fix**
button that re-calls the API with the specific errors fed back (~$0.05).

### 6. Live ATS scoring

[`ats_score.py`](scripts/ats_score.py) runs entirely locally — no API tokens.
It extracts tech terms / role terms / acronyms from the JD, checks which
appear in your resume text, and computes a 0–100 heuristic score. This is
what updates instantly when you edit a bullet in Refine. It's not a real ATS
simulation; it's a fast guide for closing keyword gaps.

---

## Costs

All in Anthropic API spend. Local compute (LaTeX, parsing, ATS scoring) is
free.

| Action | Cost (Sonnet 4.6, cached) |
|---|---|
| Setup wizard (one-time) | ~$0.05–0.15 |
| 🌐 Fetch JD from URL | ~$0.02 |
| 🪄 Generate tailored resume | ~$0.05 (warm cache) / ~$0.07 (cold) |
| 🔁 Auto-fix validator violations | ~$0.05 per attempt |
| Refine editing (no API calls) | free |

At a steady pace of 5 resumes per sitting, 3 sittings/week (60 resumes/month),
expect ~$3–5/month. Set a hard monthly limit at
[console.anthropic.com](https://console.anthropic.com/settings/limits) until
you're confident.

---

## Troubleshooting

**"pdflatex not on PATH"** — MiKTeX or TeX Live isn't installed, or your
terminal hasn't picked it up. Close and reopen the terminal after install.
Verify with `pdflatex --version`.

**"ANTHROPIC_API_KEY not set"** — `.env` doesn't exist or doesn't have the
key. Check `cat .env` (or `type .env` on Windows). Restart `streamlit` after
editing `.env`.

**"Could not find page: pages/2_Refine.py"** — Streamlit indexed pages at
startup but the `pages/` directory was added later. Stop the server
(`Ctrl+C`) and restart with `uv run streamlit run scripts/app.py`.

**JD fetch returns "JS-rendered" error** — the URL points to a JavaScript
page (Workday, Greenhouse, etc.). Open the URL in your browser, select the
JD body text manually, and paste it into the textarea.

**PDF spans 2 pages** — the soft-warning banner tells you which section to
trim. Go to Refine and shorten one bullet, click **Save + Recompile**.

**App looks frozen during generation** — Claude calls take 10–20 seconds.
Watch for the spinner; don't refresh until you see the toast or an error.

---

## Project layout

```
resume-tailor/
├─ .env                    your API key (gitignored)
├─ .env.example            template (committed)
├─ profile.json            your basic candidate info (created by Setup)
├─ experiences/
│  ├─ professional.md      every role you've held, bullets + tags
│  └─ projects.md          every project, bullets + tags
├─ resume_content.json     latest Claude draft (regenerated each run)
├─ output/                 generated .tex / .pdf / .jd.txt (gitignored)
├─ reference/
│  └─ resume.tex           example output for visual reference
└─ scripts/
   ├─ app.py               Streamlit home page (entry point)
   ├─ ui_common.py         shared helpers used by all pages
   ├─ pages/
   │  ├─ 0_Setup.py        workspace setup wizard
   │  ├─ 1_Generate.py     JD → tailored draft → PDF
   │  └─ 2_Refine.py       sidebar history + LaTeX editor + PDF
   ├─ llm.py               Anthropic API calls (caching, JD fetch, fix loops)
   ├─ generate_resume.py   resume_content.json → .tex → .pdf
   ├─ resume_template.tex  LaTeX template (single source of layout truth)
   ├─ read_experiences.py  parses experience markdown → JSON
   ├─ tex_stats.py         live line-budget + keyword stats from .tex
   ├─ ats_score.py         local heuristic ATS scoring (no API tokens)
   └─ validate_resume_content.py    pre-compile line-budget validator
```
