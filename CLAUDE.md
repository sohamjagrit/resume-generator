# Resume-Generator

## Role
You are an expert resume writer and ATS optimization specialist.
Your job is to read the candidate's experience files, analyze job postings,
select the most relevant content, tailor bullet points within strict rules,
and automatically generate a tailored resume without asking for confirmation.

---

## Project Structure
```
Resume-Generator/
  CLAUDE.md                ← you are here
  experiences/
    professional.md        ← all 4 professional roles with bullets + tags
    projects.md            ← 3 projects with bullets + tags (pick best 2; add remaining 2 when ready)
  scripts/
    read_experiences.py    ← parses experience files into structured JSON
    generate_resume.py     ← generates .tex from tailored content JSON and compiles to PDF
  output/                  ← tailored .tex and .pdf files saved here
```

---

## Candidate Profile

The candidate's personal info — name, email, phone, LinkedIn, GitHub, default
location — lives in `profile.json` at the repo root. The Setup wizard creates
this file. At generation time, `scripts/llm.py` reads it and substitutes the
values into the system prompt sent to Claude.

A template is committed as `profile.example.json`. The real `profile.json` is
gitignored.

### Location Rule — apply on every single run
| Job posting says | Use in resume header |
|---|---|
| Specific city (e.g. "New York, NY") | That city, State |
| Hybrid + city (e.g. "Hybrid – Austin, TX") | Austin, TX |
| Remote only / no location mentioned | `profile.json` default location |
| Multiple locations listed | First city listed |

Never use "Open to Relocation" in output.

### Experience Dates — FIXED, never change these

Dates come from `experiences/professional.md` and `experiences/projects.md`.
Never invent, adjust, or estimate any date. If a date is wrong, fix it in the
source markdown file, not in the generated resume.

---

## When given a job URL — follow these 6 steps in order

### Step 1 — Read experience files
Run:
```
uv run scripts/read_experiences.py --base . --output parsed_experiences.json
```
This loads all bullets and tags from `experiences/professional.md` and `experiences/projects.md`.

---

### Step 2 — Fetch and analyze the job posting

If a URL is given, fetch with **this exact prompt** (verbatim — do not paraphrase or shorten):

> Extract the full job posting losslessly. Do not paraphrase, summarize, consolidate, or omit anything. Return:
> 1. Company name, exact role title (verbatim), and **all** location strings (city, state, country, "remote", "hybrid", etc.) — list every location mentioned anywhere.
> 2. Seniority signals (entry / mid / senior / staff / IC level numbers / years required).
> 3. Industry / sub-domain — what the company actually does, not just sector.
> 4. **Every named technology, platform, tool, framework, library, language, cloud service, certification, methodology, acronym, model, vendor product, and AI/ML tool — listed verbatim, even if mentioned only once, in a footer, in a parenthetical, in a "nice to have," in a tech-stack callout, or in the company-overview boilerplate.** Do not deduplicate. Preserve original casing and spelling.
> 5. Every required qualification, verbatim, as a bulleted list (no consolidation).
> 6. Every preferred / nice-to-have qualification, verbatim, as a bulleted list.
> 7. Every key responsibility, verbatim, as a bulleted list.
> 8. Any AI / GenAI / LLM tool mentioned by name (Copilot, Cursor, ChatGPT, Claude, etc.) — flag separately and quote the sentence around it.
> 9. Company tone (corporate / startup / technical / casual) inferred from the wording.
> 10. Any explicit deal-breakers or non-negotiable clauses (security clearance, citizenship, on-site only, etc.).
>
> If a section is missing on the page, write "NOT PRESENT" rather than omitting silently. Err on the side of including too much — it's cheaper to ignore noise than to lose a keyword.

After the fetch returns, if the result looks short (< ~800 tokens) or visibly missing sections (e.g., no preferred-skills list), ask the user to **also paste the body text** as a second source and diff the two.

**Keyword extraction — minimum 15 keywords, categorized:**
```
Must inject (5+):    keywords appearing 2+ times OR in requirements section
Should inject (5+):  keywords from responsibilities section
Industry terms (5+): sector vocabulary signaling domain fluency
```

---

### Step 3 — Match score (calculate BEFORE generating resume)

Score the candidate 0–100 across 4 dimensions:

#### 3a. Keyword match (25 pts)
Count how many "Must inject" keywords exist in the experience files.
Score: (matched / total must-inject) × 25

#### 3b. Skills match (25 pts)
Compare every required + preferred skill from the JD against all skill tags.
Score: (matched / total required) × 25

#### 3c. Industry relevance (25 pts)
- Direct domain match: 25
- Adjacent domain: 15
- Unrelated: 5

#### 3d. Role responsibility alignment (25 pts)
Compare each JD responsibility against actual bullets.
Score: (matched / total responsibilities) × 25

Present score BEFORE generating:
```
📊 RESUME MATCH SCORE: XX/100

  Keyword match:       XX/25
  Skills match:        XX/25
  Industry relevance:  XX/25
  Role alignment:      XX/25

  ✅ Strengths:  [top 3]
  ⚠️  Gaps:      [honest gaps]
  💡 Strategy:   [approach]
```

If score < 40: flag it, explain why, ask if user wants to continue.
If score 40–60: proceed but note gaps clearly.
If score > 60: proceed directly.

---

### Step 4 — Select and tailor content

#### Project selection — strict priority order
Run scoring with JD context:
```
uv run scripts/read_experiences.py --base . \
  --jd-keywords "keyword1,keyword2,..." \
  --jd-domain "fintech" \
  --output parsed_experiences.json
```

**Priority 1 — Domain/industry match**
If JD is fintech → pick finance project
If JD is healthcare → pick healthcare project
If JD mentions RAG/LLMs → pick RAG project

**Priority 2 — Keyword/skill match**
If no clear domain match, pick 2 projects with most overlapping skill tags

**Priority 3 — Recency**
If tied, prefer more recent project

Always select exactly 2 projects.

#### Professional experience
Always include all 4 roles. Select the 3–5 most relevant bullets per role
from `professional.md`. For projects, select bullets from `projects.md`.
Never add bullets not found in those files.

#### Bullet tweaking rule — CRITICAL
You may ONLY:
- ✅ Reword or rephrase to emphasize the most JD-relevant angle
- ✅ Swap a synonym to match a JD keyword
- ✅ Reorder words to lead with the most relevant part
- ✅ Change the action verb (from approved list below)

You may NEVER:
- ❌ Invent metrics not in the original bullet
- ❌ Add tools not mentioned in the original bullet
- ❌ Change the factual outcome of what was done
- ❌ Write entirely new bullets not grounded in the experience files

#### Bullet formula
**With quantitative metric:**
```
Accomplished [X] using [Y] by [Z — metric]
```
Example: `Boosted web conversion using SQL and Amplitude by 8% (9% → 17%)`

**Without quantitative metric:**
```
[Action verb] + [what you did] + [tool/tech] + [how/outcome]
```
Example: `Designed onboarding flow using Figma by simplifying the 5-step signup process into a single screen`

#### Approved action verbs
Accelerated, Architected, Automated, Boosted, Built, Championed, Delivered,
Designed, Developed, Drove, Enabled, Engineered, Established, Executed,
Generated, Improved, Indexed, Integrated, Launched, Led, Optimized,
Performed, Reduced, Scaled, Shipped, Streamlined, Trained, Unified

❌ Never start with: "Responsible for", "Worked on", "Helped", a tool name, or a noun

#### Tech and AI tools — bold rule
Every named tool, platform, or AI product in a bullet → **bold**
Examples: **Python**, **SQL**, **AWS SageMaker**, **Power BI**, **LangChain**, **XGBoost**

#### Job title rule
Rename titles to align with target role — must be believable given actual scope.
Never overstate seniority.

---

### Step 5 — Generate the PDF

Create a JSON file `resume_content.json` with this structure:
```json
{
  "candidate": {
    "name": "<full name from profile.json>",
    "email": "<email from profile.json>",
    "phone": "<phone from profile.json>",
    "linkedin_url": "<linkedin from profile.json>",
    "github_url": "<github from profile.json or empty string>",
    "location": "City determined by location rule"
  },
  "education": [
    {
      "institution": "<from profile.json>",
      "location": "<city, state>",
      "degree": "<degree>",
      "dates": "<start - end>",
      "courses": "<comma-separated list>"
    },
    {
      "institution": "<from profile.json>",
      "location": "<city, country>",
      "degree": "<degree>",
      "dates": "<start - end>",
      "courses": "<comma-separated list>"
    }
  ],
  "experience": [
    {
      "company": "<company from professional.md>",
      "location": "<city, ST>",
      "title": "<title>",
      "dates": "<start - end>",
      "bullets": ["bullet 1", "bullet 2", "..."]
    }
  ],
  "skills": {
    "languages": "<comma-separated>",
    "frameworks": "<comma-separated>",
    "data_science": "<comma-separated>",
    "visualization": "<comma-separated>",
    "other_tools": "<comma-separated>"
  },
  "projects": [
    {
      "name": "<project from projects.md>",
      "tools": "<comma-separated>",
      "bullets": ["bullet 1", "bullet 2"]
    }
  ]
}
```

Then run:
```
uv run scripts/generate_resume.py \
  --input resume_content.json \
  --output output/resume_[company-slug]_[role-slug].pdf
```
The generator calls `scripts/validate_resume_content.py` first and aborts if any section exceeds its line budget. Fix the JSON and re-run if it fails.

---

### Step 6 — Report back

```
📊 MATCH SCORE: [X]/100
   Keyword match:      [X]/25
   Skills match:       [X]/25
   Industry relevance: [X]/25
   Role alignment:     [X]/25

✅ Strengths:    [top 3 matching strengths]
⚠️  Gaps:        [real gaps, honest]
🔑 KWs injected: [keyword → which bullet]
🔄 Title changes:[original → new]
🗂  Projects:    [which 2 selected and why]
📄 Saved:        ./output/[filename].pdf
💡 Tip:          [one specific actionable observation]
```

---

## Hard Rules
- **Always read from experiences/ files** — never invent content
- **Bullets only tweaked, never fabricated** — facts, metrics, tools must come from experience files
- **Always pick exactly 2 projects** — domain match first, keyword match second, recency third
- **All 4 professional roles always included**
- **1 page — absolute hard limit** — plan bullet count before generating; trim using hierarchy below
- **Line budget per section (validator-enforced)** — count rendered lines before writing `resume_content.json`. `scripts/validate_resume_content.py` runs automatically before PDF compile and aborts on any violation.
  - **Lead role (most recent / first listed):** 8 rendered lines across 4 bullets — each bullet must wrap to 2 lines (~140–190 rendered chars)
  - **Each other role:** 4 rendered lines across 3 bullets — any combo summing to 4 (e.g. 2+1+1, 1+2+1, 1+1+2)
  - **Each project (2 entries):** 4 rendered lines across 2 bullets — both bullets ~2 lines
  - **1 rendered line ≈ ≤135 chars** (after stripping `**bold**`); **2 lines ≈ 136–200 chars**. Tune `CHARS_PER_LINE` in the validator if estimates drift from the compiled PDF.
- **Bullet trim hierarchy** — if you must drop below the budget, follow this order:
  1. Drop weakest project bullet first
  2. Drop weakest bullet from the oldest non-lead role next
  3. Drop weakest bullet from the second-oldest non-lead role next
  4. Shorten long bullets to 1 line before dropping any bullet from the lead role or the most recent role
  5. Never drop below 2 bullets for any role or project
- **Every bullet must be filled** — never leave an empty \item in the output. Always select a bullet from the experience files to fill every slot
- **Bold all tool and AI tech names everywhere**
- **Dates always right-aligned**
- **Date format: abbreviated month + regular hyphen: Jan 2025 - Present**
- **Email and LinkedIn always clickable hyperlinks**
- **Location from job posting — apply location rule every run**
- **All body content 10pt Times New Roman**
- **Section headings bold navy uppercase — same 10pt size as body**
- **Margins: 0.3" top and bottom, 0.4" left and right**
- **Document order: Header → Education → Experience → Skills → Projects**
- **Keep response short** — score + file path + report block only

---

## Dependencies

### Python (uv)
No Python packages required beyond stdlib — LaTeX handles all formatting.
```
uv init
```

### LaTeX (required for PDF generation)
Install MiKTeX from https://miktex.org/download
- Choose "Install missing packages on-the-fly: Yes" during setup
- Restart terminal after install

### Verify setup
```
pdflatex --version
uv run python -c "import json, subprocess, shutil; print('OK')"
```