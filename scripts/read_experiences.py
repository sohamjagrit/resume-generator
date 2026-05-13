"""
read_experiences.py
-------------------
Reads and parses professional.md and projects.md from the experiences/ folder.
Returns structured JSON that Claude uses for bullet selection and resume generation.

Usage:
    python scripts/read_experiences.py
    python scripts/read_experiences.py --output parsed_experiences.json
"""

import re
import json
import argparse
from pathlib import Path


def parse_experience_block(block: str) -> dict:
    """Parse a single experience or project block into structured dict."""
    lines = block.strip().split("\n")
    if not lines:
        return {}

    # First line: ## Title | Role/Tools | Dates (optional)
    header = lines[0].lstrip("#").strip()
    parts = [p.strip() for p in header.split("|")]

    entry = {
        "name": parts[0] if len(parts) > 0 else "",
        "role_or_tools": parts[1] if len(parts) > 1 else "",
        "dates": parts[2] if len(parts) > 2 else "",
        "domain_tags": [],
        "skill_tags": [],
        "bullets": []
    }

    current_bullet = None
    current_tag_field = None

    def append_tags(field: str, raw: str) -> None:
        entry[field].extend(
            t.strip().lower() for t in raw.split(",") if t.strip()
        )

    def flush_bullet() -> None:
        nonlocal current_bullet
        if current_bullet and not current_bullet.startswith("["):
            entry["bullets"].append(current_bullet)
        current_bullet = None

    for raw_line in lines[1:]:
        line = raw_line.strip()

        # Domain tags
        if line.startswith("**Domain:**"):
            flush_bullet()
            current_tag_field = "domain_tags"
            raw = line.replace("**Domain:**", "").strip()
            append_tags(current_tag_field, raw)

        # Skill tags
        elif line.startswith("**Skills:**"):
            flush_bullet()
            current_tag_field = "skill_tags"
            raw = line.replace("**Skills:**", "").strip()
            append_tags(current_tag_field, raw)

        # Bullet points
        elif line.startswith("- "):
            flush_bullet()
            current_tag_field = None
            bullet = line[2:].strip()
            if bullet:
                current_bullet = bullet

        # Wrapped bullet continuation lines.
        elif line and current_bullet is not None:
            current_bullet = f"{current_bullet} {line}"

        # Wrapped tag continuation lines.
        elif line and current_tag_field is not None:
            append_tags(current_tag_field, line)

        elif not line:
            flush_bullet()
            current_tag_field = None

    flush_bullet()

    return entry


def parse_md_file(filepath: Path) -> list:
    """Parse a markdown file into a list of experience/project entries."""
    content = filepath.read_text(encoding="utf-8")

    # Split on ## headings (each role/project starts with ##)
    blocks = re.split(r"\n(?=## )", content)
    entries = []

    for block in blocks:
        block = block.strip()
        if block.startswith("## "):
            entry = parse_experience_block(block)
            if entry.get("name") and entry.get("bullets"):
                entries.append(entry)

    return entries


def load_all_experiences(base_path: str = ".") -> dict:
    """Load and parse both professional.md and projects.md."""
    base = Path(base_path)
    experiences_dir = base / "experiences"

    professional_path = experiences_dir / "professional.md"
    projects_path = experiences_dir / "projects.md"

    result = {
        "professional": [],
        "projects": []
    }

    if professional_path.exists():
        result["professional"] = parse_md_file(professional_path)
        print(f"[OK] Loaded {len(result['professional'])} professional roles from {professional_path}")
    else:
        print(f"[WARN] professional.md not found at {professional_path}")

    if projects_path.exists():
        result["projects"] = parse_md_file(projects_path)
        print(f"[OK] Loaded {len(result['projects'])} projects from {projects_path}")
    else:
        print(f"[WARN] projects.md not found at {projects_path}")

    return result


# Synonym groups — each set is a cluster of equivalent JD/resume terms.
# When a project tag matches any member of a group, the project is treated as
# matching every other member too. Same for JD keywords. Keeps "genai" routing
# to NutriBot, "forecasting" to Electric Demand, etc.
SYNONYM_GROUPS = [
    # GenAI / LLM / RAG cluster → NutriBot
    {"genai", "generative ai", "llm", "llms", "language model", "language models",
     "rag", "retrieval-augmented", "retrieval augmented", "embeddings",
     "vector database", "vector db", "vector store", "prompt engineering",
     "langchain", "fine-tuning", "fine tuning"},

    # Forecasting / time series cluster → Electric Demand
    {"forecasting", "time series", "time-series", "predictive modeling",
     "demand forecasting", "sarimax", "arima", "var", "seasonality",
     "seasonal", "trend analysis"},

    # Energy / utility cluster → Electric Demand
    {"energy", "utility", "utilities", "electricity", "electric", "power",
     "power grid", "demand response", "electrification", "renewables",
     "energy consumption"},

    # MLOps / deployment cluster → Loan Approval
    {"mlops", "model deployment", "model serving", "model monitoring",
     "ci/cd", "continuous integration", "continuous deployment",
     "automated deployment", "model registry"},

    # Classification / supervised learning cluster → Loan Approval
    {"classification", "supervised learning", "binary classification",
     "multiclass", "logistic regression", "decision tree", "random forest",
     "gradient boosting", "tree-based", "tabular"},

    # Containerization / cloud-ops cluster
    {"docker", "containerization", "containerized", "container",
     "kubernetes", "k8s"},

    # Cloud cluster
    {"aws", "amazon web services", "ec2", "lambda", "s3", "sagemaker",
     "athena", "glue"},
]


def expand_through_synonyms(terms: list, groups: list = SYNONYM_GROUPS) -> set:
    """Return the input terms plus every synonym that shares a group with any term."""
    expanded = set()
    for term in terms:
        if not term:
            continue
        t = term.lower().strip()
        expanded.add(t)
        for group in groups:
            # Match if the input term overlaps with any group member (substring either way).
            if any(s == t or s in t or t in s for s in group):
                expanded |= group
    return expanded


def score_entry_against_jd(entry: dict, jd_keywords: list, jd_domain: str = "") -> float:
    """
    Score one project against JD keywords + domain via synonym-expanded matching.

    Priority 1 — Domain match (50 points, hit or miss).
    Priority 2 — Keyword overlap (up to 40 points; 4 pts per matched cluster).
    Priority 3 — Recency is added by the caller via index order.
    """
    score = 0.0

    project_terms = expand_through_synonyms(
        entry.get("domain_tags", []) + entry.get("skill_tags", [])
    )

    if jd_domain:
        domain_terms = expand_through_synonyms([jd_domain])
        if project_terms & domain_terms:
            score += 50

    if jd_keywords:
        jd_terms = expand_through_synonyms(jd_keywords)
        overlap = project_terms & jd_terms
        score += min(40, len(overlap) * 4)

    return round(score, 2)


def select_top_projects(projects: list, jd_keywords: list, jd_domain: str = "", top_n: int = 2) -> list:
    """Select top N projects based on domain and keyword matching."""
    scored = []
    for i, project in enumerate(projects):
        score = score_entry_against_jd(project, jd_keywords, jd_domain)
        # Recency bonus: earlier entries (index 0) are assumed more recent
        recency_bonus = max(0, (len(projects) - i) * 0.5)
        scored.append((score + recency_bonus, i, project))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [item[2] for item in scored[:top_n]]
    print(f"\n[Project Selection]")
    for score, idx, project in scored:
        marker = "[SELECTED]" if project in selected else "  skipped "
        print(f"  {marker} | Score: {score:.1f} | {project['name']}")

    return selected


def main():
    parser = argparse.ArgumentParser(description="Parse experience files for resume generation")
    parser.add_argument("--output", type=str, default=None, help="Save parsed JSON to file")
    parser.add_argument("--jd-keywords", type=str, default="", help="Comma-separated JD keywords for project scoring")
    parser.add_argument("--jd-domain", type=str, default="", help="Primary domain of the job (e.g. fintech, healthcare)")
    parser.add_argument("--base", type=str, default=".", help="Base project directory")
    args = parser.parse_args()

    # Load all experiences
    data = load_all_experiences(args.base)

    # Score and select projects if JD info provided
    if args.jd_keywords or args.jd_domain:
        jd_keywords = [k.strip() for k in args.jd_keywords.split(",") if k.strip()]
        selected_projects = select_top_projects(
            data["projects"],
            jd_keywords=jd_keywords,
            jd_domain=args.jd_domain,
            top_n=2
        )
        data["selected_projects"] = selected_projects
    else:
        data["selected_projects"] = data["projects"][:2]  # default: first 2

    # Output
    output_json = json.dumps(data, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"\n[OK] Saved parsed experiences to {args.output}")
    else:
        print("\n--- PARSED EXPERIENCES JSON ---")
        print(output_json)


if __name__ == "__main__":
    main()
