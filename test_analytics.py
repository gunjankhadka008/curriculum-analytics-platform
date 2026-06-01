"""
test_analytics.py
-----------------
Unit tests for the pure logic in analytics.py.

Run with:
    pip install pytest
    pytest                # or: python -m pytest -v

These tests use the built-in synthetic data, so they need no external files.
"""
import numpy as np
import pandas as pd

import analytics as A


def test_letter_to_points_known_grades():
    assert A.letter_to_points("S") == 10
    assert A.letter_to_points("A") == 9
    assert A.letter_to_points("F") == 0


def test_letter_to_points_unknown_defaults_to_zero():
    assert A.letter_to_points("Z") == 0
    assert A.letter_to_points(None) == 0


def test_make_demo_data_shapes_and_columns():
    students, courses, course_skills, enrollments = A.make_demo_data()
    assert len(students) == 400
    assert {"student_id", "department", "attendance_overall"}.issubset(students.columns)
    assert {"course_id", "course_code", "is_core"}.issubset(courses.columns)
    assert {"student_id", "course_id", "grade", "passed"}.issubset(enrollments.columns)
    assert len(enrollments) > 0


def test_make_demo_data_is_deterministic():
    a = A.make_demo_data(seed=1)[3]
    b = A.make_demo_data(seed=1)[3]
    pd.testing.assert_frame_equal(a, b)


def test_merge_data_has_no_suffix_collisions():
    df = A.merge_data(*A.make_demo_data())
    bad = [c for c in df.columns if c.endswith("_x") or c.endswith("_y")]
    assert bad == [], f"unexpected merge-suffix columns: {bad}"
    # Key analysis columns must survive the join.
    for col in ["dept", "semester", "credits", "skill", "numeric_score"]:
        assert col in df.columns


def test_calculate_course_kpis_columns_and_bounds():
    df = A.merge_data(*A.make_demo_data())
    kpi = A.calculate_course_kpis(df)
    for col in ["enrollments", "pass_rate", "dfw_rate", "gpa", "difficulty_index"]:
        assert col in kpi.columns
    # Rates are proportions.
    assert kpi["pass_rate"].between(0, 1).all()
    assert kpi["dfw_rate"].between(0, 1).all()


def test_random_forest_returns_valid_accuracy():
    df = A.merge_data(*A.make_demo_data())
    model, acc, importances, test_info = A.random_forest_model(df)
    assert model is not None
    assert 0.0 <= acc <= 1.0
    # Importances should sum to ~1 and be ranked.
    assert abs(importances["Importance"].sum() - 1.0) < 1e-6


def test_classification_diagnostics_keys():
    df = A.merge_data(*A.make_demo_data())
    _, _, _, test_info = A.random_forest_model(df)
    _, y_test, y_pred, _ = test_info
    diag = A.classification_diagnostics(y_test, y_pred)
    assert set(diag) == {"accuracy", "balanced_accuracy", "confusion_matrix"}
    assert 0.0 <= diag["balanced_accuracy"] <= 1.0
    assert isinstance(diag["confusion_matrix"], pd.DataFrame)


def test_build_summary_keys():
    df = A.merge_data(*A.make_demo_data())
    summary = A.build_summary(df)
    for key in ["rows", "columns", "avg_score", "pass_rate"]:
        assert key in summary
    assert summary["rows"] == len(df)


def test_at_risk_students_returns_requested_count():
    df = A.merge_data(*A.make_demo_data())
    risky = A.at_risk_students(df, n=15)
    assert len(risky) == 15
    assert "risk_score" in risky.columns
