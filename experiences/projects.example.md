# Projects

Exactly two projects are picked per generated resume — domain match first,
keyword overlap second, recency third. Keep this file as a small portfolio
(3–5 projects); the scorer picks the best fit for each JD.

---

## Customer Churn Predictor
**Tools:** Python, Scikit-learn, XGBoost, FastAPI, Docker, AWS

**Domain tags:** SaaS, Retention, MLOps
**Skill tags:** Python, Scikit-learn, XGBoost, Classification, MLOps, Docker, FastAPI, AWS, CI/CD

- Developed end-to-end churn-prediction service using **Python**, **Scikit-learn**, and **XGBoost** by training on 24 months of feature data and exposing predictions through a **FastAPI** endpoint with sub-100ms p95 latency.
- Deployed using **Docker** and **AWS** by containerizing the model and standing up a CI/CD pipeline through GitHub Actions, enabling weekly retraining with no manual intervention.

---

## Local-Search Recommender
**Tools:** Python, Sentence Transformers, FAISS, Streamlit

**Domain tags:** Search, Recommendations, NLP
**Skill tags:** Python, NLP, Embeddings, FAISS, Sentence Transformers, Streamlit, Vector Search

- Built a semantic-search prototype using **Sentence Transformers** and **FAISS** by encoding 50k product descriptions into dense vectors and serving nearest-neighbor lookups in under 30ms.
- Shipped an interactive demo using **Streamlit** that let stakeholders compare keyword-based search against the embedding-based recommender on the same query set.

---

## Energy Demand Forecasting
**Tools:** Python, Statsmodels, XGBoost, Pandas

**Domain tags:** Energy, Utilities, Time Series
**Skill tags:** Python, Time Series, Forecasting, SARIMAX, XGBoost, Statsmodels, EDA

- Performed exploratory data analysis using **Statsmodels** and **Pandas** by identifying trends, seasonality, and weather-correlated patterns across 3 years of hourly load data.
- Achieved 5.4% MAPE using **XGBoost** by training VAR, SARIMAX, and gradient-boosted models on weather-augmented features, benchmarking forecast accuracy across modeling approaches.
