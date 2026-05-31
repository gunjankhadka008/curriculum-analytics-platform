"""
export_for_powerbi.py
---------------------
Generate a clean, star-schema set of CSV files that Power BI can connect to
directly via "Get Data > Folder".

Usage
-----
  # Use the built-in synthetic dataset:
  python export_for_powerbi.py

  # Use your own CSVs (folder must contain students.csv, courses.csv,
  # enrollments.csv, and optionally course_skills.csv):
  python export_for_powerbi.py --input-dir ./my_data --out-dir ./data/powerbi

Outputs (into --out-dir)
------------------------
  dim_students.csv              one row per student
  dim_courses.csv               one row per course
  dim_course_skills.csv         course_id -> skill
  fact_enrollments.csv          raw enrollment grain (the fact table)
  fact_enrollments_enriched.csv enrollments joined to all dimensions (flat)
  agg_course_kpis.csv           pre-aggregated per-course KPIs
"""
import argparse
import os

import pandas as pd

import analytics as A


def load_inputs(input_dir):
    if input_dir:
        req = ["students.csv", "courses.csv", "enrollments.csv"]
        missing = [f for f in req if not os.path.exists(os.path.join(input_dir, f))]
        if missing:
            raise FileNotFoundError(f"Missing required file(s) in {input_dir}: {missing}")
        students = pd.read_csv(os.path.join(input_dir, "students.csv"))
        courses = pd.read_csv(os.path.join(input_dir, "courses.csv"))
        enrollments = pd.read_csv(os.path.join(input_dir, "enrollments.csv"))
        skill_path = os.path.join(input_dir, "course_skills.csv")
        course_skills = (pd.read_csv(skill_path) if os.path.exists(skill_path)
                         else pd.DataFrame({"course_id": [], "skill": []}))
    else:
        students, courses, course_skills, enrollments = A.make_demo_data()

    if "student_name" not in students.columns:
        students = students.copy()
        students["student_name"] = students["student_id"].apply(lambda x: f"Student {int(x)}")
    return students, courses, course_skills, enrollments


def main():
    parser = argparse.ArgumentParser(description="Export curriculum data for Power BI.")
    parser.add_argument("--input-dir", default=None,
                        help="Folder with your own CSVs. Omit to use demo data.")
    parser.add_argument("--out-dir", default=os.path.join("data", "powerbi"))
    args = parser.parse_args()

    students, courses, course_skills, enrollments = load_inputs(args.input_dir)
    df = A.merge_data(students, courses, course_skills, enrollments)
    course_kpis = A.calculate_course_kpis(df)

    os.makedirs(args.out_dir, exist_ok=True)
    outputs = {
        "dim_students.csv": students,
        "dim_courses.csv": courses,
        "dim_course_skills.csv": course_skills,
        "fact_enrollments.csv": enrollments,
        "fact_enrollments_enriched.csv": df,
        "agg_course_kpis.csv": course_kpis,
    }
    for name, frame in outputs.items():
        frame.to_csv(os.path.join(args.out_dir, name), index=False)

    print(f"Exported {len(enrollments):,} enrollment rows and "
          f"{len(course_kpis):,} course-KPI rows to '{args.out_dir}/'.")


if __name__ == "__main__":
    main()
