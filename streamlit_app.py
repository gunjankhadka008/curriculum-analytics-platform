"""
streamlit_app.py
----------------
Interactive web UI for the Curriculum Analytics platform.

All data and model logic lives in analytics.py; this file is purely the
Streamlit presentation layer (widgets, charts, layout).

Run with:  streamlit run streamlit_app.py
"""
import os
import json
import html
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

import analytics as A

# Optional local LLM (Ollama). The app degrades gracefully without it.
try:
    import ollama
    OLLAMA_AVAILABLE = True
except Exception:
    OLLAMA_AVAILABLE = False

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "tinyllama")
CHAT_FILE = "chat_history.json"

st.set_page_config(page_title="Curriculum Analytics + AI Assistant",
                   layout="wide", page_icon="🎓")

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
dark_mode = st.sidebar.checkbox("🌙 Dark mode", value=st.session_state.get("dark_mode", False))
st.session_state["dark_mode"] = dark_mode

if dark_mode:
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        .block-container { background-color: #071024; color: #e6eef8; }
        .metric { background: rgba(255,255,255,0.03); padding:12px; border-radius:8px; }
        .chat-bot { background:#1f2a44;color:#fff;padding:10px;border-radius:12px;margin:8px 0;text-align:left;}
        </style>
        """, unsafe_allow_html=True)
else:
    st.markdown(
        """
        <style>
        .metric { background: rgba(0,0,0,0.03); padding:12px; border-radius:8px; }
        .chat-bot { background:#F1F3F5;padding:10px;border-radius:12px;margin:8px 0;text-align:left;}
        </style>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data
def load_demo_data():
    return A.make_demo_data()


st.sidebar.header("Data Inputs")
stud_file = st.sidebar.file_uploader("Students CSV", type=["csv"])
course_file = st.sidebar.file_uploader("Courses CSV", type=["csv"])
skill_file = st.sidebar.file_uploader("Course Skills CSV (optional)", type=["csv"])
enr_file = st.sidebar.file_uploader("Enrollments CSV", type=["csv"])
use_demo = st.sidebar.checkbox("Use demo data (if no files uploaded)", value=True)

if stud_file and course_file and enr_file:
    students = pd.read_csv(stud_file)
    courses = pd.read_csv(course_file)
    enrollments = pd.read_csv(enr_file)
    course_skills = pd.read_csv(skill_file) if skill_file else pd.DataFrame({"course_id": [], "skill": []})
elif use_demo:
    students, courses, course_skills, enrollments = load_demo_data()
else:
    st.sidebar.warning("Upload Students, Courses & Enrollments CSV, or enable demo data.")
    st.stop()

# Friendly display name if the dataset doesn't provide one.
if "student_name" not in students.columns:
    students = students.copy()
    students["student_name"] = students["student_id"].apply(lambda x: f"Student {int(x)}")

df = A.merge_data(students, courses, course_skills, enrollments)

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")
years = sorted(df["year"].unique()) if "year" in df.columns else []
year_sel = st.sidebar.multiselect("Year", years, default=years)
terms = sorted(df["term"].unique()) if "term" in df.columns else []
term_sel = st.sidebar.multiselect("Term", terms, default=terms)
depts = sorted(df["dept"].dropna().unique()) if "dept" in df.columns else []
dept_sel = st.sidebar.multiselect("Department", depts, default=depts)

sem_min, sem_max = int(df["semester"].min()), int(df["semester"].max())
sem_sel = st.sidebar.slider("Semester range", sem_min, sem_max, (sem_min, sem_max))

mask = (
    (df["year"].isin(year_sel) if year_sel else True) &
    (df["term"].isin(term_sel) if term_sel else True) &
    (df["dept"].isin(dept_sel) if dept_sel else True) &
    (df["semester"].between(sem_sel[0], sem_sel[1]))
)
F = df[mask].copy()

if F.empty:
    st.warning("No rows match the current filters. Widen them in the sidebar.")
    st.stop()

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
st.title("🎓 Curriculum Analytics & AI Assistant")
tab_overview, tab_courses, tab_models, tab_insights, tab_chat = st.tabs(
    ["Overview", "Courses & Skills", "Models", "Insights", "AI Chatbot"])

course_kpi = A.calculate_course_kpis(F)

# ---- Overview --------------------------------------------------------------
with tab_overview:
    st.header("Overview & KPIs")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall Pass Rate", f"{F['passed'].mean():.1%}" if "passed" in F.columns else "N/A")
    c2.metric("Mean GPA (10-pt)",
              f"{np.mean([A.letter_to_points(x) for x in F['grade']]):.2f}" if "grade" in F.columns else "N/A")
    c3.metric("Avg Absences", f"{F['absences'].mean():.2f}" if "absences" in F.columns else "N/A")
    c4.metric("Enrollments", f"{len(F):,}")

    st.subheader("Course Difficulty & Outcomes")
    fig1 = px.scatter(course_kpi, x="gpa", y="dfw_rate", size="enrollments", color="dept",
                      hover_data=["course_code", "course_name", "semester", "credits", "is_core", "skill"],
                      labels={"gpa": "GPA (10-pt)", "dfw_rate": "DFW Rate"},
                      title="Courses: GPA vs DFW")
    st.plotly_chart(fig1, width="stretch")
    st.download_button("Download course KPIs (CSV)",
                       course_kpi.to_csv(index=False).encode("utf-8"),
                       file_name="course_kpis.csv", mime="text/csv")

    left, right = st.columns(2)
    with left:
        st.markdown("**Top Hardest Courses**")
        st.dataframe(course_kpi[["course_code", "course_name", "dept", "semester",
                                 "enrollments", "gpa", "dfw_rate", "difficulty_index"]].head(12))
    with right:
        trend = A.grade_trend(F)
        if not trend.empty:
            st.plotly_chart(px.line(trend, x="year", y="gpa", color="term", markers=True,
                                    title="Mean GPA by Term"), width="stretch")
            st.plotly_chart(px.line(trend, x="year", y="pass_rate", color="term", markers=True,
                                    title="Pass Rate by Term"), width="stretch")
        else:
            st.info("No grade/term trend available.")

# ---- Courses & Skills ------------------------------------------------------
with tab_courses:
    st.header("Courses & Skills")
    skill_view = (course_kpi.groupby("skill", dropna=False)
                  .agg(courses=("course_id", "nunique"),
                       enrollments=("enrollments", "sum"),
                       mean_gpa=("gpa", "mean"),
                       mean_dfw=("dfw_rate", "mean"))
                  .reset_index().sort_values("mean_dfw", ascending=False))
    st.plotly_chart(px.bar(skill_view.fillna({"skill": "(No Tag)"}),
                           x="skill", y="mean_dfw",
                           hover_data=["courses", "enrollments", "mean_gpa"],
                           title="Skill-wise DFW"), width="stretch")
    st.download_button("Download skill summary (CSV)",
                       skill_view.to_csv(index=False).encode("utf-8"),
                       file_name="skill_summary.csv", mime="text/csv")

    st.subheader("Top courses by enrollment")
    top_enroll = A.top_courses_by_enrollment(course_kpi, top_n=20)
    st.dataframe(top_enroll[["course_code", "course_name", "dept", "enrollments", "gpa"]])

# ---- Models ----------------------------------------------------------------
with tab_models:
    st.header("Predictive Models")

    st.subheader("Random Forest (Pass / Fail)")
    rf_model, rf_acc, rf_importances, rf_test = A.random_forest_model(F)
    if rf_model is not None:
        _, y_test, y_pred, _ = rf_test
        diag = A.classification_diagnostics(y_test, y_pred)
        m1, m2 = st.columns(2)
        m1.metric("RF accuracy", f"{diag['accuracy']:.2%}")
        m2.metric("RF balanced accuracy", f"{diag['balanced_accuracy']:.2%}")
        if diag["accuracy"] - diag["balanced_accuracy"] > 0.15:
            st.caption("⚠️ Accuracy far exceeds balanced accuracy — the target is "
                       "imbalanced (most students pass), so accuracy alone is "
                       "misleading. See the confusion matrix below.")
        st.markdown("**Confusion matrix**")
        st.dataframe(diag["confusion_matrix"])
        st.dataframe(rf_importances)
        fig_rf = px.bar(rf_importances.head(10), x="Feature", y="Importance",
                        title="Random Forest Feature Importances", color="Importance")
        st.plotly_chart(fig_rf, width="stretch")
        st.download_button("Download RF importances (CSV)",
                           rf_importances.to_csv(index=False).encode("utf-8"),
                           file_name="rf_importances.csv", mime="text/csv")
        try:
            png = pio.to_image(fig_rf, format="png")
            st.download_button("Download RF importances (PNG)", png,
                               file_name="rf_importances.png", mime="image/png")
        except Exception:
            st.download_button("Download RF importances (HTML)",
                               fig_rf.to_html().encode("utf-8"),
                               file_name="rf_importances.html", mime="text/html")
    else:
        st.info("Not enough data to train Random Forest for the current filter (~50 rows needed).")

    st.subheader("KNN (Grade Classification)")
    knn_obj, knn_acc, _ = A.knn_model(F)
    if knn_obj is not None:
        st.metric("KNN accuracy", f"{knn_acc:.2%}")  # real, measured accuracy
    else:
        st.info("Not enough data to train KNN for the current filter.")

    st.subheader("Score Drivers (Linear Regression)")
    _, coefs = A.workload_model(F)
    if coefs is not None:
        st.dataframe(coefs)
        st.caption("Each coefficient estimates that factor's marginal effect on numeric_score.")
    else:
        st.info("Not enough data to fit the regression for the current filter.")

    st.markdown("### 🎯 Personalized Recommendations")
    rf_imp = rf_importances if rf_importances is not None else \
        pd.DataFrame({"Feature": ["attendance_overall"], "Importance": [1.0]})
    with st.expander("Show recommendations for filtered students"):
        if "numeric_score" not in F.columns:
            st.warning("`numeric_score` column not found.")
        else:
            rec = F.copy()
            if "student_name" not in rec.columns:
                rec["student_name"] = rec.get("student_id", pd.Series(range(len(rec)))).apply(
                    lambda x: f"Student {int(x)}")
            rec["Recommendation"] = rec.apply(lambda r: A.get_recommendation(r, rf_imp), axis=1)
            agg = (rec.groupby(["student_id", "student_name"])
                   .agg(mean_score=("numeric_score", "mean"),
                        sample_course=("course_name", "first"),
                        recommendation=("Recommendation",
                                        lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]))
                   .reset_index().sort_values("mean_score"))
            st.dataframe(agg.head(200))
            st.download_button("📥 Download Recommendations (CSV)",
                               agg.to_csv(index=False).encode("utf-8"),
                               file_name="student_recommendations.csv", mime="text/csv")

# ---- Insights --------------------------------------------------------------
with tab_insights:
    st.header("Advanced Insights & Diagnostics")
    corr = A.compute_correlation(F)
    if corr is not None:
        st.plotly_chart(px.imshow(corr, text_auto=True, aspect="auto",
                                  title="Numeric Feature Correlation"),
                        width="stretch")
    else:
        st.info("Not enough numeric columns for a correlation heatmap.")

    st.subheader("At-risk students (heuristic)")
    risky = A.at_risk_students(F, n=20)
    if not risky.empty:
        st.dataframe(risky)
        st.download_button("Download at-risk students (CSV)",
                           risky.to_csv(index=False).encode("utf-8"),
                           file_name="at_risk_students.csv", mime="text/csv")
    else:
        st.info("Insufficient columns for at-risk calculation.")

# ---- AI Chatbot ------------------------------------------------------------
# Clear any stale on-disk history once per session (not on every rerun).
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    if os.path.exists(CHAT_FILE):
        try:
            os.remove(CHAT_FILE)
        except Exception:
            pass


def _save_history():
    try:
        with open(CHAT_FILE, "w", encoding="utf-8") as fh:
            json.dump(st.session_state.chat_history, fh, indent=2)
    except Exception:
        pass


# Sidebar history inspector
st.sidebar.header("Chat History")
if st.sidebar.checkbox("Show / Inspect Chat History", value=False):
    if st.session_state.chat_history:
        labels = [f"{i+1}. {m['role'].upper()} @ {m.get('ts','')}: {m['content'][:60]}"
                  for i, m in enumerate(st.session_state.chat_history)]
        sel = st.sidebar.selectbox("Select message", options=list(range(len(labels))),
                                   format_func=lambda i: labels[i])
        sel_item = st.session_state.chat_history[sel]
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**Role:** {sel_item['role']}")
        st.sidebar.markdown(f"**Time:** {sel_item.get('ts','')}")
        st.sidebar.markdown(f"**Message:** {sel_item['content']}")
        if st.sidebar.button("Clear chat history"):
            st.session_state.chat_history = []
            try:
                os.remove(CHAT_FILE)
            except Exception:
                pass
            st.rerun()
    else:
        st.sidebar.info("No chat history yet.")

with tab_chat:
    st.header("🤖 AI Chat Assistant")
    st.markdown("Ask plain-language questions about the filtered dataset.")

    summary = A.build_summary(F)

    last_user = next((m for m in reversed(st.session_state.chat_history) if m["role"] == "user"), None)
    last_assistant = next((m for m in reversed(st.session_state.chat_history) if m["role"] == "assistant"), None)
    if last_user:
        st.markdown(f"**Last question:** {html.escape(last_user['content'])}")
    if last_assistant:
        st.markdown(f"<div class='chat-bot'><b>Assistant</b><br/>{html.escape(last_assistant['content'])}</div>",
                    unsafe_allow_html=True)

    user_q = st.text_input("e.g. 'Which dept has the highest pass rate?'")
    if user_q:
        st.session_state.chat_history.append(
            {"role": "user", "content": user_q, "ts": datetime.now(timezone.utc).isoformat()})
        _save_history()

        prompt = ("You are an academic advisor. Use the dataset summary below to answer in plain "
                  "language (1-3 sentences). Do NOT output code, tables, or JSON. "
                  f"Dataset summary: {json.dumps(summary, default=str)} User question: {user_q}")

        if OLLAMA_AVAILABLE:
            try:
                resp = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
                answer = (resp.get("message", {}).get("content", "") or "").strip() or "Empty response from model."
            except Exception as e:
                answer = f"Ollama error: {e}. Falling back to local summary."
        else:
            ql = user_q.lower()
            if "department" in ql and "score" in ql and summary.get("top_departments_by_avg_score"):
                top = summary["top_departments_by_avg_score"]
                dept = next(iter(top))
                answer = f"{dept} has the highest average score (~{top[dept]:.2f})."
            elif "student" in ql and summary.get("top_students"):
                s = summary["top_students"][0]
                name = s.get("student_name") or f"ID {s.get('student_id')}"
                answer = f"Top student is {name} with a score of {s.get('numeric_score'):.1f}."
            else:
                parts = []
                if summary.get("avg_score") is not None:
                    parts.append(f"mean score is {summary['avg_score']:.1f}")
                if summary.get("pass_rate") is not None:
                    parts.append(f"overall pass rate is {summary['pass_rate']:.1%}")
                answer = ("The " + ", ".join(parts) + ".") if parts else \
                    "I can't answer precisely - ensure numeric_score & passed columns exist."

        st.session_state.chat_history.append(
            {"role": "assistant", "content": answer, "ts": datetime.now(timezone.utc).isoformat()})
        _save_history()
        st.markdown(f"<div class='chat-bot'><b>Assistant</b><br/>{html.escape(answer)}</div>",
                    unsafe_allow_html=True)
