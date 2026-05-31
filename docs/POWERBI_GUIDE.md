# Power BI Dashboard — Build Guide

This guide walks you from the exported CSVs to a publishable Power BI report.
You'll need **Power BI Desktop** (free, Windows).

---

## 1. Generate the data

From the project root:

```bash
python export_for_powerbi.py
```

This creates `data/powerbi/` containing:

| File | Role in the model |
|------|-------------------|
| `dim_students.csv` | Student dimension |
| `dim_courses.csv` | Course dimension |
| `dim_course_skills.csv` | Skill dimension |
| `fact_enrollments.csv` | **Fact table** (one row per enrollment) |
| `agg_course_kpis.csv` | Pre-aggregated per-course KPIs (handy for quick visuals) |
| `fact_enrollments_enriched.csv` | Flat, fully-joined table (optional fallback) |

> For a clean model, import the **dim_** and **fact_enrollments** tables and
> build relationships (Section 3). Use `fact_enrollments_enriched.csv` only if
> you want a single flat table with no modeling.

---

## 2. Load into Power BI

1. Open **Power BI Desktop**.
2. **Home → Get Data → Folder**, point to your `data/powerbi/` folder
   (or **Get Data → Text/CSV** and add each file individually).
3. For each table, click **Transform Data** to confirm column types
   (IDs as Whole Number, rates as Decimal, `term`/`grade` as Text).
4. **Close & Apply**.

---

## 3. Build relationships (star schema)

Go to **Model view** and create these relationships (all one-to-many, single direction):

- `dim_students[student_id]` → `fact_enrollments[student_id]`
- `dim_courses[course_id]` → `fact_enrollments[course_id]`
- `dim_course_skills[course_id]` → `dim_courses[course_id]`

The fact table sits in the middle; dimensions fan out around it.

---

## 4. Create DAX measures

In the **fact_enrollments** table, **New measure** for each:

```DAX
Pass Rate = AVERAGE(fact_enrollments[passed])

Avg Score = AVERAGE(fact_enrollments[numeric_score])

DFW Rate = 1 - [Pass Rate]

Avg Absences = AVERAGE(fact_enrollments[absences])

Total Enrollments = COUNTROWS(fact_enrollments)

Mean GPA (10pt) =
AVERAGEX(
    fact_enrollments,
    SWITCH(
        fact_enrollments[grade],
        "S", 10, "A", 9, "B", 8, "C", 7, "D", 6, "E", 5, "F", 0,
        0
    )
)
```

Format `Pass Rate` and `DFW Rate` as percentages.

---

## 5. Suggested report pages

**Page 1 — Overview**
- Cards: `Pass Rate`, `Mean GPA (10pt)`, `Avg Absences`, `Total Enrollments`
- Clustered column: `Avg Score` by `dim_courses[dept]`
- Line: `Pass Rate` by `year` (legend = `term`)
- Slicers: `year`, `term`, `dim_courses[dept]`, `dim_courses[semester]`

**Page 2 — Course Difficulty**
- Scatter: X = `gpa`, Y = `dfw_rate`, size = `enrollments` (from `agg_course_kpis`)
- Table: hardest courses sorted by `difficulty_index`

**Page 3 — Skills**
- Bar: `DFW Rate` by `dim_course_skills[skill]`
- Matrix: skill × department

Match the app's color story: a teal/blue accent for positive metrics and an
amber/red accent for DFW and risk visuals.

---

## 6. Publish & screenshot

1. **Home → Publish** to the Power BI Service (free account) for a shareable link.
2. For the README, capture each report page:
   **File → Export → PDF**, or screenshot the report canvas.
3. Save the image as `docs/images/powerbi.png` so it shows in the main README.

---

## 7. Commit the dashboard

Save your report as `curriculum_dashboard.pbix` in a `powerbi/` folder and commit it:

```bash
git add powerbi/curriculum_dashboard.pbix docs/images/powerbi.png
git commit -m "Add Power BI dashboard and screenshot"
```

> `.pbix` files can be large. If it exceeds ~50 MB, consider
> [Git LFS](https://git-lfs.com/) or commit a PDF export instead.
