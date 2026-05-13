"""
llm.py — Anthropic API integration for in-app resume generation.

Used by app.py's "Generate from JD" button. Wraps a single Messages API call
to Claude Sonnet 4.6, with prompt caching on the system rules + parsed
experiences (the static portions). The JD text is the only fresh input.

Public API:
    generate_resume_content(jd_text, parsed_experiences_json=None) -> dict
        Returns:
          {
            "slug":           "abc-supply_data-scientist",
            "score":          {"keyword": 22, "skills": 20, "industry": 25,
                               "role": 22, "total": 89},
            "analysis":       "...short prose assessment...",
            "projects":       ["Electric Demand Forecasting", "Loan Approval System"],
            "keywords":       ["python -> role1.b2", ...],
            "gaps":           [...],
            "resume_content": {...full JSON ready for generate_resume.py...},
            "raw":            "...full model reply for debugging...",
            "usage":          {"input": int, "output": int,
                               "cache_creation": int, "cache_read": int,
                               "approx_usd": float},
          }

Requires:  os.environ["ANTHROPIC_API_KEY"]
"""

import json
import os
import re
import urllib.request
from pathlib import Path
from string import Template

from anthropic import Anthropic
from dotenv import load_dotenv

# Pick up ANTHROPIC_API_KEY from a project-root .env (if present).
# Falls back silently to whatever's already in the process environment.
load_dotenv(Path(__file__).parent.parent / ".env")


ROOT = Path(__file__).parent.parent

MODEL = "claude-sonnet-4-6"

# Sonnet 4.6 pricing as of Q2 2026 ($ / 1M tokens).
PRICE_INPUT       = 3.00
PRICE_CACHE_WRITE = 3.75
PRICE_CACHE_READ  = 0.30
PRICE_OUTPUT      = 15.00


# ── System prompt (built dynamically per-call from profile.json) ─────────────

def _load_profile() -> dict:
    """Load profile.json from project root; return placeholder defaults if missing."""
    path = ROOT / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "name": "[Your Name]",
        "email": "[your.email@example.com]",
        "phone": "[your phone]",
        "linkedin_url": "[your LinkedIn URL]",
        "github_url": "",
        "location": "[Your City, ST]",
        "target_roles": "",
        "education": [],
    }


def _format_education(profile: dict) -> str:
    """Render the education block for the system prompt from profile.json."""
    entries = profile.get("education") or []
    if not entries:
        return "(Education entries come from profile.json — never fabricate degrees or dates.)"
    lines = []
    for e in entries:
        courses = e.get("relevant_courses") or e.get("courses") or []
        if isinstance(courses, list):
            courses = ", ".join(courses)
        line = (
            f"- {e.get('institution', '?')} — {e.get('degree', '?')} — "
            f"{e.get('dates', '?')} — {e.get('location', '?')}"
        )
        if courses:
            line += f"\n  Relevant courses: {courses}"
        lines.append(line)
    return "\n".join(lines)


SYSTEM_RULES_TEMPLATE = Template("""You are an expert resume writer and ATS optimization specialist for $candidate_name.

## Fixed candidate profile

- Name: $name
- Email: $email
- Phone: $phone
- LinkedIn: $linkedin_url
- GitHub: $github_or_omit
- Default location: $default_location  (used only when JD has no city)

## Fixed dates (NEVER change)

Use the dates exactly as they appear in the parsed experiences input. Never invent, adjust, or estimate dates.

## Fixed education

$education_block

## Task

For each JD, output a tailored `resume_content.json` plus a short analysis.

## Hard rules — NEVER violate

1. **Bullets tweaked, never fabricated.** Each output bullet must derive from a bullet in the supplied parsed experiences. You may reword, swap synonyms, change action verb. You may NOT invent metrics, tools, outcomes, or new bullets.
2. **Tool names locked.** A bullet may only mention tools/platforms/products that appear in the source bullet's text. No adding "AWS" because the JD wants it.
3. **Exactly 2 projects.** Priority: domain match > keyword overlap > recency. Pick from the available projects.
4. **All professional roles included** (every entry from professional.md), in the order they appear.

## Line budget — STRICT (validator will fail otherwise)

After stripping `**bold**` markers, count chars per bullet.

| Section | Lines | Bullets | Per-bullet shape |
|---|---|---|---|
| Lead role (most recent / first listed) | **8** | 4 | each ~140–190 rendered chars → wraps to 2 lines |
| Each other role | **4** | 3 | mix of 1L (≤135 chars) and 2L (140–200 chars) summing to 4 |
| Each project | **4** | 2 | each ~140–190 chars → 2 lines |

Wrap threshold = **135 chars per rendered line** (Times 10pt, current margins).

## Bolding rule

Every named tool / platform / framework / library / AI product → wrap in `**`.
Examples: `**Python**`, `**AWS SageMaker**`, `**Power BI**`, `**LangChain**`, `**XGBoost**`, `**Docker**`.

## Approved action verbs (use one to START every bullet)

Accelerated, Architected, Automated, Boosted, Built, Championed, Delivered, Designed, Developed, Drove, Enabled, Engineered, Established, Executed, Generated, Improved, Indexed, Integrated, Launched, Led, Optimized, Performed, Reduced, Scaled, Shipped, Streamlined, Trained, Unified.

NEVER start a bullet with "Responsible for", "Worked on", "Helped", a tool name, or a noun.

## Title rename rule

May rename titles for JD alignment if believable given actual scope (e.g. "Student Analyst" → "Student Data Analyst"). Never overstate seniority.

## Location rule

| JD says | Use |
|---|---|
| Specific city | That city, State |
| Hybrid + city | The city |
| Multiple cities | First listed |
| Remote / unspecified | $default_location |

Never write "Open to Relocation."

## Output format — RETURN EXACTLY THIS STRUCTURE

```
SLUG: <company-slug>_<role-slug>

ANALYSIS:
<2-3 sentences on match quality, strengths, gaps>

SCORE:
- Keyword:  <0-25>/25
- Skills:   <0-25>/25
- Industry: <0-25>/25
- Role:     <0-25>/25
- TOTAL:    <0-100>/100

PROJECTS:
- Selected: <name1>, <name2>
- Reason:   <one line>

KEYWORDS_INJECTED:
- <keyword> -> <which bullet>
- ...

GAPS:
- <honest gap>
- ...

RESUME_CONTENT:
```json
{
  "candidate": {...},
  "education": [...],
  "experience": [...],
  "skills": {...},
  "projects": [...]
}
```
```

Schema for the JSON block (match exactly):

```json
{
  "candidate": {
    "name": "<full name>",
    "email": "<email>",
    "phone": "<phone>",
    "linkedin_url": "<LinkedIn URL or handle>",
    "github_url": "<GitHub URL or empty string>",
    "location": "<city derived from location rule>"
  },
  "education": [
    {"institution": "...", "location": "...", "degree": "...", "dates": "...", "courses": "..."}
  ],
  "experience": [
    {"company": "...", "location": "...", "title": "...", "dates": "...", "bullets": ["...", "..."]}
  ],
  "skills": {
    "languages": "...", "frameworks": "...", "data_science": "...",
    "visualization": "...", "other_tools": "..."
  },
  "projects": [
    {"name": "...", "tools": "...", "bullets": ["...", "..."]}
  ]
}
```

Output ONLY the format above. No preamble, no commentary outside the labeled sections.
""")


PROMPT_MODULES = {
    "grounding": """## Grounding module

Treat the parsed experiences and confirmed profile as the only evidence base.
For every rewritten bullet, first choose one source bullet mentally, then preserve
its tools, metrics, scope, and outcome. If a JD keyword is unsupported by the
source bullet, list it as a gap instead of adding it.""",

    "edit_style": """## Edit-style module

You are editing an existing resume, not inventing a new career history.
Prefer conservative, recruiter-readable edits. Avoid keyword stuffing, vague
phrases, and over-claiming. Strong bullets should state what was done, the
tool/method used, and the technical or business outcome supported.""",

    "project_rules": """## Project module

Select exactly 2 projects. Project names, tools, metrics, and project outcomes
must come from the parsed project inventory. If the JD asks for an unsupported
project skill, do not add it; note the gap.""",

    "self_audit": """## Silent self-audit module

Before returning, silently check:
1. No new tools or metrics were added beyond the source bullet.
2. Every bullet starts with an approved action verb.
3. All fixed dates and education fields are preserved unless the confirmed
   local profile explicitly overrides them.
4. Exactly 2 projects are returned.
5. The response matches the requested labeled format exactly.""",
}


def build_system_rules() -> str:
    """Assemble the generation prompt by filling SYSTEM_RULES_TEMPLATE from
    profile.json and appending the named modules. Returns the exact text we
    send as the cached system block — same profile in → same cache key."""
    profile = _load_profile()
    name = profile.get("name") or "[Your Name]"
    github = profile.get("github_url") or "(omit from header)"
    default_location = profile.get("location") or "[Your City, ST]"
    rules = SYSTEM_RULES_TEMPLATE.substitute(
        candidate_name=name,
        name=name,
        email=profile.get("email") or "[your.email@example.com]",
        phone=profile.get("phone") or "[your phone]",
        linkedin_url=profile.get("linkedin_url") or "[your LinkedIn URL]",
        github_or_omit=github,
        default_location=default_location,
        education_block=_format_education(profile),
    )
    modules = "\n\n".join(PROMPT_MODULES.values())
    return f"{rules}\n\n{modules}"


# ── Response parsing ─────────────────────────────────────────────────────────

_JSON_BLOCK = re.compile(r"```json\s*(.+?)```", re.DOTALL)


def _section(text: str, label: str, end_labels: list = None) -> str:
    """Extract the body of a labeled section like 'ANALYSIS:' up to the next label."""
    end_labels = end_labels or []
    end_pattern = "|".join(re.escape(l + ":") for l in end_labels)
    pattern = (
        rf"^{re.escape(label)}:\s*\n?(.*?)(?=^(?:{end_pattern})|\Z)"
        if end_pattern else
        rf"^{re.escape(label)}:\s*\n?(.*)\Z"
    )
    m = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_score(text: str) -> dict:
    """Parse the SCORE section's four dimensions + total."""
    score = {"keyword": 0, "skills": 0, "industry": 0, "role": 0, "total": 0}
    for key, pattern in [
        ("keyword",  r"Keyword[^:]*:\s*(\d+)"),
        ("skills",   r"Skills[^:]*:\s*(\d+)"),
        ("industry", r"Industry[^:]*:\s*(\d+)"),
        ("role",     r"Role[^:]*:\s*(\d+)"),
        ("total",    r"TOTAL[^:]*:\s*(\d+)"),
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            score[key] = int(m.group(1))
    return score


def _parse_bullets(section_body: str) -> list:
    """Pull bullet lines (lines starting with '-') from a section body."""
    return [line.lstrip("- ").strip()
            for line in section_body.splitlines()
            if line.strip().startswith("-")]


def _estimate_cost(usage) -> float:
    inp        = getattr(usage, "input_tokens", 0)
    out        = getattr(usage, "output_tokens", 0)
    cache_in   = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_hit  = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = (
        inp       * PRICE_INPUT       / 1_000_000 +
        out       * PRICE_OUTPUT      / 1_000_000 +
        cache_in  * PRICE_CACHE_WRITE / 1_000_000 +
        cache_hit * PRICE_CACHE_READ  / 1_000_000
    )
    return round(cost, 4)


_PROFILE_EXTRACT_SYSTEM = """You convert uploaded resumes and user-entered profile details into a reliable resume-tailoring workspace.

Rules:
- Extract only facts explicitly present in the provided resumes or user profile.
- Do not invent metrics, tools, dates, companies, schools, titles, or project outcomes.
- If resumes conflict, keep the most specific version and add a review note.
- Write concise markdown that matches the app's expected experiences/professional.md and experiences/projects.md format.
- Each professional role/project must include domain tags, skill tags, and bullets.
- Bullets should be factual, source-backed, and reusable for future JD tailoring.

Return exactly one JSON block:
```json
{
  "profile": {
    "name": "",
    "email": "",
    "phone": "",
    "linkedin_url": "",
    "github_url": "",
    "location": "",
    "target_roles": "",
    "education": []
  },
  "professional_md": "# Professional Experience\\n\\n...",
  "projects_md": "# Projects\\n\\n...",
  "review_notes": ["..."]
}
```
"""


def extract_profile_from_resumes(
    profile: dict,
    resume_documents: list[dict],
    model: str = MODEL,
) -> dict:
    """Generate profile/professional/projects drafts from uploaded resume text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it in setup first.")

    if not resume_documents:
        raise RuntimeError("Upload at least one resume or paste resume text.")

    docs = "\n\n".join(
        f"## Resume file: {doc['name']}\n\n```text\n{doc['text'][:20000]}\n```"
        for doc in resume_documents
        if doc.get("text", "").strip()
    )
    if not docs.strip():
        raise RuntimeError("No readable resume text found in the uploaded files.")

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_PROFILE_EXTRACT_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "User-entered profile fields:\n"
                f"```json\n{json.dumps(profile, indent=2)}\n```\n\n"
                "Uploaded resume text:\n\n"
                f"{docs}\n\n"
                "Create the draft workspace files."
            ),
        }],
    )

    text = response.content[0].text
    jm = _JSON_BLOCK.search(text)
    if not jm:
        raise ValueError(f"Couldn't find JSON block in profile extraction response:\n{text[:400]}")
    result = json.loads(jm.group(1))
    result["raw"] = text
    result["usage"] = {
        "input":      getattr(response.usage, "input_tokens", 0),
        "output":     getattr(response.usage, "output_tokens", 0),
        "approx_usd": _estimate_cost(response.usage),
    }
    return result


def _confirmed_profile_block() -> dict | None:
    path = ROOT / "profile.json"
    if not path.exists():
        return None
    profile = path.read_text(encoding="utf-8")
    return {
        "type": "text",
        "text": (
            "## Confirmed candidate profile override\n\n"
            "This local profile supersedes any hardcoded candidate identity, contact, "
            "education, location, and target-role defaults in the generic system rules. "
            "Use this profile for candidate fields and never use another person's contact info.\n\n"
            f"```json\n{profile}\n```"
        ),
        "cache_control": {"type": "ephemeral"},
    }


# ── Public ────────────────────────────────────────────────────────────────────

def generate_resume_content(
    jd_text: str,
    parsed_experiences_json: str = None,
    model: str = MODEL,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. "
            "Set it in your shell (export ANTHROPIC_API_KEY=sk-...) and restart Streamlit."
        )

    client = Anthropic(api_key=api_key)

    if parsed_experiences_json is None:
        path = ROOT / "parsed_experiences.json"
        if not path.exists():
            raise FileNotFoundError(
                "parsed_experiences.json not found. Run "
                "`uv run scripts/read_experiences.py --base . --output parsed_experiences.json` first."
            )
        parsed_experiences_json = path.read_text(encoding="utf-8")

    system_blocks = [
        {
            "type": "text",
            "text": build_system_rules(),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                "## Parsed experiences (the ONLY source of truth for bullets)\n\n"
                f"```json\n{parsed_experiences_json}\n```"
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    profile_block = _confirmed_profile_block()
    if profile_block:
        system_blocks.append(profile_block)

    user_message = (
        "Job posting:\n\n"
        f"```\n{jd_text}\n```\n\n"
        "Produce the analysis + tailored resume_content.json per the rules. "
        "Watch the line budgets — they will be validated."
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
    )
    return _parse_model_response(response)


def _parse_model_response(response) -> dict:
    """Shared parser for both generate_resume_content and regenerate_with_feedback."""
    text = response.content[0].text

    jm = _JSON_BLOCK.search(text)
    if not jm:
        raise ValueError(
            "Couldn't find a ```json``` block in the model response. "
            f"First 400 chars:\n{text[:400]}"
        )
    try:
        resume_content = json.loads(jm.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON in response was malformed: {e}")

    labels = ["SLUG", "ANALYSIS", "SCORE", "PROJECTS", "KEYWORDS_INJECTED", "GAPS", "RESUME_CONTENT"]
    slug_body     = _section(text, "SLUG", labels)
    analysis      = _section(text, "ANALYSIS", labels)
    projects_body = _section(text, "PROJECTS", labels)
    keywords_body = _section(text, "KEYWORDS_INJECTED", labels)
    gaps_body     = _section(text, "GAPS", labels)
    score         = _parse_score(_section(text, "SCORE", labels))

    slug = slug_body.split("\n", 1)[0].strip() if slug_body else ""
    slug = re.sub(r"[^a-z0-9_\-]", "", slug.lower().replace(" ", "-"))
    if not slug:
        slug = "untitled"

    usage = response.usage
    return {
        "slug":            slug,
        "score":           score,
        "analysis":        analysis,
        "projects":        _parse_bullets(projects_body),
        "keywords":        _parse_bullets(keywords_body),
        "gaps":            _parse_bullets(gaps_body),
        "resume_content":  resume_content,
        "raw":             text,
        "usage": {
            "input":          getattr(usage, "input_tokens", 0),
            "output":         getattr(usage, "output_tokens", 0),
            "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read":     getattr(usage, "cache_read_input_tokens", 0) or 0,
            "approx_usd":     _estimate_cost(usage),
        },
    }


def regenerate_with_feedback(
    jd_text: str,
    validator_errors: list,
    previous_raw: str,
    parsed_experiences_json: str = None,
    model: str = MODEL,
) -> dict:
    """
    Re-run generation with the previous (failed) response + the validator's
    error list. Same cached system prompt — only the user message differs,
    so caching still applies.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to .env and restart Streamlit."
        )

    client = Anthropic(api_key=api_key)

    if parsed_experiences_json is None:
        path = ROOT / "parsed_experiences.json"
        if not path.exists():
            raise FileNotFoundError(
                "parsed_experiences.json not found. Run read_experiences.py first."
            )
        parsed_experiences_json = path.read_text(encoding="utf-8")

    system_blocks = [
        {"type": "text", "text": build_system_rules(), "cache_control": {"type": "ephemeral"}},
        {
            "type": "text",
            "text": (
                "## Parsed experiences (the ONLY source of truth for bullets)\n\n"
                f"```json\n{parsed_experiences_json}\n```"
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    profile_block = _confirmed_profile_block()
    if profile_block:
        system_blocks.append(profile_block)

    errors_block = "\n".join(f"- {e}" for e in validator_errors)
    feedback_message = (
        "Job posting:\n\n"
        f"```\n{jd_text}\n```\n\n"
        "Your previous response failed validation:\n\n"
        f"```\n{previous_raw}\n```\n\n"
        "**Validator errors (must be fixed):**\n"
        f"{errors_block}\n\n"
        "## Critical line-budget reminders\n\n"
        "- After stripping `**bold**` markers, count the rendered length of each bullet.\n"
        "- Threshold: 135 chars/line. ≤135 chars → 1 rendered line. 136–200 chars → 2 lines.\n"
        "- Per section totals (STRICT, no slack):\n"
        "  - Lead role (first listed): exactly 8 lines across 4 bullets → each bullet 140–190 rendered chars.\n"
        "  - Other roles: exactly 4 lines across 3 bullets → mix of 1L (~95–130 chars) and 2L (140–190 chars).\n"
        "  - Each project: exactly 4 lines across 2 bullets → each bullet 140–190 rendered chars.\n\n"
        "## What to do\n\n"
        "Return the complete corrected output in the same labeled format. "
        "Change ONLY the sections that violated; keep every other section, bullet, and field identical to your previous response. "
        "For each previously violating bullet, compute the expected line count by counting rendered chars before submitting."
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_blocks,
        messages=[{"role": "user", "content": feedback_message}],
    )
    return _parse_model_response(response)


# ── URL → JD extraction ──────────────────────────────────────────────────────

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        encoding = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(encoding, errors="replace")


def _strip_html(html: str) -> str:
    """Drop script/style/nav, strip remaining tags, decode common entities."""
    for tag in ("script", "style", "noscript", "svg"):
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", " ", html, flags=re.DOTALL | re.IGNORECASE
        )
    html = re.sub(r"<[^>]+>", " ", html)
    for entity, replacement in [
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&mdash;", "—"),
        ("&ndash;", "–"), ("&hellip;", "…"),
    ]:
        html = html.replace(entity, replacement)
    return re.sub(r"\s+", " ", html).strip()


_FETCH_SYSTEM = """You extract a job posting from raw scraped web page text.

Return the JD losslessly. Do not paraphrase, summarize, consolidate, or omit. Output sections:

1. Company name, exact role title (verbatim), and EVERY location string mentioned.
2. Seniority / experience signals.
3. Industry / sub-domain.
4. EVERY named technology, platform, tool, framework, library, language, cloud service, certification, methodology, acronym, model, and vendor product — verbatim, including ones mentioned only once or in a footer / nice-to-have / company-overview. Preserve casing. Do not deduplicate.
5. Every required qualification — bulleted, verbatim.
6. Every preferred / nice-to-have — bulleted, verbatim.
7. Every key responsibility — bulleted, verbatim.
8. AI / GenAI / LLM tools by name (Copilot, Cursor, ChatGPT, Claude, etc.) — flag and quote.
9. Company tone (corporate / startup / technical / casual).
10. Deal-breakers (clearance, citizenship, on-site only).

If a section is missing on the page, write "NOT PRESENT". Err on the side of including too much.

Input is noisy: nav, ads, footer, sidebar may be mixed in. Find the job posting and extract per above. Ignore non-JD content."""


def _normalize_url(url: str) -> str:
    """Convert LinkedIn search URLs (JS-rendered) to /jobs/view/<id> (server-rendered)."""
    m = re.search(r"linkedin\.com/jobs/search/?\?.*?currentJobId=(\d+)", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    # Trim tracking params from /jobs/view URLs
    m = re.search(r"(linkedin\.com/jobs/view/\d+)", url)
    if m:
        return f"https://www.{m.group(1)}"
    return url


def fetch_jd_from_url(url: str, model: str = MODEL) -> dict:
    """
    Fetch a job posting URL, strip the HTML, hand the cleaned text to Claude
    for keyword-paranoid extraction. Returns extracted JD text + token usage.

    Raises RuntimeError on fetch failures (network, JS-rendered pages, paywalls).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. "
            "Set it in your shell and restart Streamlit."
        )

    original_url = url
    url = _normalize_url(url)

    try:
        html = _fetch_html(url)
    except Exception as e:
        raise RuntimeError(f"Couldn't fetch {url}: {e}")

    text = _strip_html(html)
    if len(text) < 500:
        raise RuntimeError(
            f"Page returned only {len(text)} chars of text from {url}. "
            "It's likely JS-rendered (Workday, Greenhouse, Lever) or behind auth. "
            "Paste the JD body text into the box directly instead."
        )

    # If the page looks like a LinkedIn sign-in wall, bail with a clear message.
    if "sign in" in text.lower()[:2000] and "linkedin" in url.lower() and len(text) < 5000:
        raise RuntimeError(
            "LinkedIn returned a sign-in wall instead of the JD. This happens "
            "for some postings. Open the URL in your browser, copy the JD body "
            "text, and paste it into the box directly."
        )

    # Cap input — defends against giant pages with 100KB+ of irrelevant DOM.
    text = text[:30_000]

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_FETCH_SYSTEM,
        messages=[{"role": "user", "content": f"Raw page text:\n\n{text}"}],
    )

    return {
        "jd_text": response.content[0].text,
        "url": url,
        "usage": {
            "input":      getattr(response.usage, "input_tokens", 0),
            "output":     getattr(response.usage, "output_tokens", 0),
            "approx_usd": _estimate_cost(response.usage),
        },
    }
