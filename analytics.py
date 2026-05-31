"""
analytics.py
-------------
Pure data-processing and machine-learning logic for the Curriculum Analytics
platform.

This module deliberately contains NO Streamlit and NO plotting code, so the
same logic can be reused by:
  * the web app            (streamlit_app.py)
  * the Power BI exporter  (export_for_powerbi.py)
  * notebooks / unit tests

Keeping I/O and UI out of here is what makes the project testable and modular.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score

# 10-point grade scale used throughout the app.
GRADE_POINTS = {"S": 10, "A": 9, "B": 8, "C": 7, "D": 6, "E": 5, "F": 0}


def letter_to_points(letter) -> int:
    """Convert a letter grade to its 10-point value (unknown -> 0)."""
    return GRADE_POINTS.get(str(letter).upper(), 0)


# ---------------------------------------------------------------------------
# Synthetic data generator (used when no real CSVs are supplied)
# ---------------------------------------------------------------------------
def make_demo_data(seed: int = 42):
    """Return (students, courses, course_skills, enrollments) DataFrames.

    Note: enrollment rows intentionally do NOT carry dept/semester/credits;
    those live on the course dimension and are joined in by merge_data().
    """
    rng = np.random.default_rng(seed)
    n_students = 400
    depts = ["CSE", "ECE", "ME", "CE", "EEE", "AIML", "ISE"]

    students = pd.DataFrame({
        "student_id": np.arange(1, n_students + 1),
        "program_level": rng.choice(["UG", "PG"], n_students, p=[0.85, 0.15]),
        "department": rng.choice(depts, n_students),
        "gender": rng.choice(["M", "F"], n_students),
        "hs_percent": np.clip(rng.normal(78, 8, n_students), 40, 100).round(1),
        "family_income_lpa": np.clip(rng.normal(6.0, 2.0, n_students), 1.0, 20.0).round(1),
        "attendance_overall": np.clip(rng.normal(82, 10, n_students), 40, 100).round(1),
        "extracurricular_index": np.clip(rng.normal(0.5, 0.2, n_students), 0.0, 1.0).round(2),
    })

    course_catalog = []
    cid = 1000
    for d in depts:
        for sem in range(1, 9):
            for i in range(2):
                course_catalog.append({
                    "course_id": cid,
                    "course_code": f"{d}{sem}{i}",
                    "course_name": f"{d} Course {sem}-{i}",
                    "dept": d,
                    "semester": sem,
                    "credits": int(rng.integers(3, 5)),
                    "is_core": int(rng.choice([0, 1], p=[0.35, 0.65])),
                    "contact_hours": int(rng.integers(36, 60)),
                })
                cid += 1
    courses = pd.DataFrame(course_catalog)

    skills = ["Data Structures", "DBMS", "Networks", "AI/ML",
              "Embedded", "Signals", "Thermo", "Concrete"]
    course_skills = pd.DataFrame({
        "course_id": courses["course_id"],
        "skill": rng.choice(skills, len(courses)),
    })

    records = []
    for year in (2022, 2023, 2024):
        for term in ("Odd", "Even"):
            offered = courses.sample(frac=0.4, random_state=int(year * 13 + (term == "Even") * 7))
            for _, course in offered.iterrows():
                picks = rng.choice(students.index, size=min(80, len(students)), replace=False)
                for sid in picks:
                    stud = students.loc[sid]
                    difficulty = 0.12 + 0.02 * course["semester"] + (0.05 if course["is_core"] == 1 else 0.0)
                    mu = (75
                          + 0.08 * (stud["hs_percent"] - 75)
                          + 0.05 * (stud["attendance_overall"] - 80)
                          + 3.0 * (stud["extracurricular_index"] - 0.5)
                          - 10 * difficulty)
                    score = float(np.clip(rng.normal(mu, 10), 0, 100))
                    grade = ("S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70
                             else "C" if score >= 60 else "D" if score >= 50
                             else "E" if score >= 40 else "F")
                    passed = int(grade != "F")
                    records.append({
                        "student_id": int(stud["student_id"]),
                        "course_id": int(course["course_id"]),
                        "year": year,
                        "term": term,
                        "grade": grade,
                        "numeric_score": round(score, 1),
                        "passed": passed,
                        "attempts": 1 + (0 if passed else int(rng.choice([0, 1], p=[0.7, 0.3]))),
                        "absences": max(0, int(rng.normal(3, 2))),
                    })
    enrollments = pd.DataFrame(records)
    return students, courses, course_skills, enrollments


# ---------------------------------------------------------------------------
# Joins & feature engineering
# ---------------------------------------------------------------------------
def merge_data(students, courses, course_skills, enrollments):
    """Join the four tables into one analysis-ready frame.

    Only non-overlapping columns are pulled from each dimension, which avoids
    the _x / _y suffix collisions you get from a naive merge.
    """
    course_cols = [c for c in courses.columns
                   if c == "course_id" or c not in enrollments.columns]
    df = enrollments.merge(courses[course_cols], on="course_id", how="left")

    student_cols = [c for c in students.columns
                    if c == "student_id" or c not in df.columns]
    df = df.merge(students[student_cols], on="student_id", how="left")

    if course_skills is not None and not course_skills.empty and "skill" in course_skills.columns:
        skills = course_skills[["course_id", "skill"]].drop_duplicates("course_id")
        df = df.merge(skills, on="course_id", how="left")
    if "skill" not in df.columns:
        df["skill"] = np.nan

    # Derive a semester if neither side supplied one.
    if "semester" not in df.columns:
        df["semester"] = pd.factorize(df["year"].astype(str) + "_" + df["term"].astype(str))[0] + 1

    return df


def calculate_course_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-course KPIs and a composite difficulty index."""
    group_cols = [c for c in ["course_id", "course_code", "course_name", "dept",
                              "semester", "credits", "is_core", "skill"]
                  if c in df.columns]
    g = df.groupby(group_cols, dropna=False).agg(
        enrollments=("student_id", "count"),
        pass_rate=("passed", "mean"),
        avg_score=("numeric_score", "mean"),
        absences_avg=("absences", "mean"),
        attempts_avg=("attempts", "mean"),
        gpa=("grade", lambda s: np.mean([letter_to_points(x) for x in s]) if len(s) else np.nan),
    ).reset_index()

    g["dfw_rate"] = 1 - g["pass_rate"]
    abs_max = max(1.0, float(g["absences_avg"].max()))
    att_max = max(1.0, float(g["attempts_avg"].max()))
    g["difficulty_index"] = (
        (1 - g["pass_rate"]) * 0.5
        + ((10 - g["gpa"]) / 10) * 0.3
        + (g["absences_avg"] / abs_max) * 0.1
        + (g["attempts_avg"] / att_max) * 0.1
    )
    return g.sort_values("difficulty_index", ascending=False)


def grade_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Mean GPA and pass rate per (year, term)."""
    if "grade" not in df.columns:
        return pd.DataFrame()
    t = df.copy()
    t["points"] = t["grade"].apply(letter_to_points)
    return (t.groupby(["year", "term"])
             .agg(gpa=("points", "mean"), pass_rate=("passed", "mean"))
             .reset_index()
             .sort_values(["year", "term"]))


def top_courses_by_enrollment(course_kpi: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    return course_kpi.sort_values("enrollments", ascending=False).head(top_n)


def compute_correlation(df: pd.DataFrame):
    """Return the numeric correlation matrix, or None if too few numeric cols."""
    num = df.select_dtypes(include=[np.number])
    if num.shape[1] < 2:
        return None
    return num.corr()


def at_risk_students(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Heuristic risk score from low attendance and low scores."""
    needed = {"attendance_overall", "numeric_score", "student_id"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    sc = df.copy()
    sc["risk_score"] = (100 - sc["attendance_overall"]) * 0.6 + (50 - sc["numeric_score"]) * 0.4
    cols = [c for c in ["student_id", "department", "numeric_score",
                        "attendance_overall", "risk_score"] if c in sc.columns]
    return sc.sort_values("risk_score", ascending=False).head(n)[cols]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def workload_model(df: pd.DataFrame):
    """Linear regression: which factors drive numeric_score?"""
    cols = ["numeric_score", "attendance_overall", "contact_hours", "credits", "absences"]
    if not set(cols).issubset(df.columns):
        return None, None
    fe = df[cols].dropna()
    if len(fe) < 30:
        return None, None
    features = ["attendance_overall", "contact_hours", "credits", "absences"]
    model = LinearRegression().fit(fe[features].values, fe["numeric_score"].values)
    coefs = (pd.DataFrame({"feature": features, "coef": model.coef_.round(3)})
             .sort_values("coef", ascending=False))
    return model, coefs


def random_forest_model(df: pd.DataFrame, random_state: int = 42):
    """Random Forest classifier for pass/fail prediction."""
    features = ["hs_percent", "family_income_lpa", "attendance_overall",
                "extracurricular_index", "credits", "contact_hours", "is_core"]
    if not set(features + ["passed"]).issubset(df.columns):
        return None, None, None, None
    df2 = df.dropna(subset=features + ["passed"])
    if len(df2) < 50:
        return None, None, None, None

    X, y = df2[features], df2["passed"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=random_state)
    model = RandomForestClassifier(n_estimators=150, random_state=random_state)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    importances = (pd.DataFrame({"Feature": features, "Importance": model.feature_importances_})
                   .sort_values("Importance", ascending=False))
    test_info = (X_test, y_test, y_pred, model.predict_proba(X_test)[:, 1])
    return model, acc, importances, test_info


def knn_model(df: pd.DataFrame, random_state: int = 42):
    """KNN classifier for grade prediction. Returns the REAL test accuracy."""
    features = ["hs_percent", "attendance_overall", "family_income_lpa",
                "extracurricular_index", "credits", "contact_hours"]
    if not set(features + ["grade"]).issubset(df.columns):
        return None, None, None
    df2 = df.dropna(subset=features + ["grade"])
    if len(df2) < 50:
        return None, None, None

    Xs = StandardScaler().fit_transform(df2[features])
    X_train, X_test, y_train, y_test = train_test_split(
        Xs, df2["grade"], test_size=0.25, random_state=random_state)
    knn = KNeighborsClassifier(n_neighbors=5).fit(X_train, y_train)
    acc = knn.score(X_test, y_test)
    return knn, acc, (X_test, y_test, knn.predict(X_test))


# ---------------------------------------------------------------------------
# Recommendations & chatbot support
# ---------------------------------------------------------------------------
def get_recommendation(row, rf_importances) -> str:
    """Rule-based, actionable recommendation for one student/course row."""
    try:
        score = float(row.get("numeric_score", np.nan))
    except Exception:
        score = np.nan

    skill = row.get("skill", "") or row.get("course_name", "")
    top_feature = "attendance_overall"
    try:
        if rf_importances is not None and not rf_importances.empty:
            top_feature = rf_importances.iloc[0]["Feature"]
    except Exception:
        pass

    if np.isnan(score):
        return "No numeric score available to generate a recommendation."
    if score < 50:
        return (f"Needs improvement - focus on fundamentals related to '{top_feature}'. "
                f"Use extra tutorials, remedial assignments, and office hours.")
    if score < 75:
        return (f"Average performer - strengthen '{top_feature}' and practice applied "
                f"projects related to '{skill}' to build mastery.")
    return (f"High performer - pursue advanced projects or internships in '{skill}', "
            f"and consider mentoring peers or research tasks.")


def build_summary(df: pd.DataFrame) -> dict:
    """Compact, JSON-serializable summary of the filtered data for the LLM."""
    summary = {"rows": int(len(df)), "columns": list(df.columns)}
    summary["avg_score"] = float(df["numeric_score"].mean()) if "numeric_score" in df.columns else None
    summary["pass_rate"] = float(df["passed"].mean()) if "passed" in df.columns else None

    try:
        summary["top_departments_by_avg_score"] = (
            df.groupby("dept")["numeric_score"].mean()
              .sort_values(ascending=False).head(5).round(2).to_dict())
    except Exception:
        summary["top_departments_by_avg_score"] = {}

    try:
        cols = [c for c in ["student_id", "student_name", "numeric_score"] if c in df.columns]
        summary["top_students"] = (df.sort_values("numeric_score", ascending=False)
                                     .head(5)[cols].to_dict(orient="records"))
    except Exception:
        summary["top_students"] = []

    return summary
