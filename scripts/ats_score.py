"""
ats_score.py
------------
Local, live ATS-style scoring for the current resume TeX against a pasted JD.

This is a heuristic guide, not an employer ATS simulation. It is designed to
update instantly while the user edits the LaTeX source.
"""

import re


TECH_TERMS = {
    "python", "sql", "r", "java", "scala", "spark", "pyspark", "pandas",
    "numpy", "scikit-learn", "sklearn", "tensorflow", "pytorch", "keras",
    "xgboost", "lightgbm", "power bi", "tableau", "looker", "excel",
    "aws", "sagemaker", "ec2", "s3", "lambda", "azure", "gcp",
    "docker", "kubernetes", "airflow", "dbt", "snowflake", "databricks",
    "mlops", "machine learning", "deep learning", "nlp", "llm", "llms",
    "rag", "langchain", "pinecone", "hugging face", "elasticsearch",
    "logstash", "kibana", "flask", "fastapi", "git", "github actions",
    "ci/cd", "statistics", "forecasting", "time series", "a/b testing",
    "experimentation", "etl", "data pipelines", "data visualization",
}

ROLE_TERMS = {
    "data scientist", "data analyst", "machine learning engineer",
    "ml engineer", "business intelligence", "bi analyst", "analytics",
    "data engineer", "ai engineer", "research scientist",
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "you", "your",
    "our", "are", "will", "can", "have", "has", "data", "team", "role",
    "work", "using", "including", "experience", "skills", "ability",
    "knowledge", "preferred", "required", "responsibilities",
}


def strip_latex(tex: str) -> str:
    text = re.sub(r"\\text(?:bf|it)\{([^{}]*)\}", r"\1", tex)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\section\*\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}$&#_%]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _phrases(text: str) -> set[str]:
    found = set()
    lower = text.lower()

    for term in TECH_TERMS | ROLE_TERMS:
        if term in lower:
            found.add(term)

    for match in re.finditer(r"\b[A-Z][A-Za-z0-9+#]*(?:\s+[A-Z][A-Za-z0-9+#]*){0,2}\b", text):
        token = match.group(0).lower()
        if token not in STOPWORDS and len(token) > 2:
            found.add(token)

    for match in re.finditer(r"\b[A-Z]{2,}[A-Za-z0-9]*\b", text):
        found.add(match.group(0).lower())

    for match in re.finditer(r"\b[a-z]+(?:-[a-z]+){1,2}\b", lower):
        found.add(match.group(0))

    return {p for p in found if p not in STOPWORDS and len(p) > 1}


def _coverage_score(matched: int, total: int, points: int) -> int:
    if total <= 0:
        return 0
    return round(points * matched / total)


def compute_ats_score(jd_text: str, tex: str, parsed: dict, pdf_exists: bool = False) -> dict:
    resume_text = strip_latex(tex)
    jd_keywords = _phrases(jd_text)
    resume_keywords = _phrases(resume_text)

    matched_keywords = sorted(k for k in jd_keywords if k in resume_text or k in resume_keywords)
    missed_keywords = sorted(k for k in jd_keywords if k not in matched_keywords)

    jd_skills = sorted(k for k in jd_keywords if k in TECH_TERMS)
    matched_skills = sorted(k for k in jd_skills if k in resume_text or k in resume_keywords)
    missed_skills = sorted(k for k in jd_skills if k not in matched_skills)

    jd_roles = sorted(k for k in ROLE_TERMS if k in jd_text.lower())
    matched_roles = sorted(k for k in jd_roles if k in resume_text)

    sections_present = {
        "education": "\\section*{Education}" in tex,
        "experience": "\\section*{Experience}" in tex and bool(parsed.get("experience")),
        "skills": "\\section*{Skills}" in tex,
        "projects": "\\section*{Projects}" in tex and bool(parsed.get("projects")),
    }
    structure_points = round(10 * sum(sections_present.values()) / 4)
    bullet_count = sum(len(e.get("bullets", [])) for e in parsed.get("experience", []))
    project_count = len(parsed.get("projects", []))
    if bullet_count >= 8:
        structure_points += 3
    if project_count == 2:
        structure_points += 2
    structure_points = min(15, structure_points)

    warnings = []
    if not jd_text.strip():
        warnings.append("Paste a JD to compute a meaningful ATS score.")
    if missed_skills:
        warnings.append(f"{len(missed_skills)} JD skill(s) are not visible in the resume.")
    if project_count != 2:
        warnings.append("Project section should contain exactly 2 projects.")
    if "\\item" in tex and re.search(r"\\item\s*(?:\\end\{itemize\}|$)", tex):
        warnings.append("Resume contains an empty bullet item.")
    if not pdf_exists:
        warnings.append("PDF has not been compiled yet.")

    keyword_points = _coverage_score(len(matched_keywords), len(jd_keywords), 35)
    skills_points = _coverage_score(len(matched_skills), len(jd_skills), 25)
    role_points = 15 if not jd_roles else _coverage_score(len(matched_roles), len(jd_roles), 15)
    warning_points = max(0, 10 - min(10, len(warnings) * 2))
    total = keyword_points + skills_points + role_points + structure_points + warning_points

    return {
        "total": min(100, total),
        "breakdown": {
            "keyword": keyword_points,
            "skills": skills_points,
            "role": role_points,
            "structure": structure_points,
            "warnings": warning_points,
        },
        "matched_keywords": matched_keywords,
        "missed_keywords": missed_keywords,
        "matched_skills": matched_skills,
        "missed_skills": missed_skills,
        "role_terms": jd_roles,
        "warnings_list": warnings,
        "counts": {
            "jd_keywords": len(jd_keywords),
            "jd_skills": len(jd_skills),
            "resume_bullets": bullet_count,
            "projects": project_count,
        },
    }
