import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

DB_PATH = "homeschool.db"

# -----------------------------
# Database helpers
# -----------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            grade TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            test_name TEXT NOT NULL,
            score REAL NOT NULL,
            meta_json TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
        """
    )
    conn.commit()
    return conn

def add_student(name: str, age: int | None, grade: str) -> None:
    conn = db()
    conn.execute(
        "INSERT INTO students(name, age, grade, created_at) VALUES(?,?,?,?)",
        (name.strip(), age if age else None, grade.strip(), int(time.time())),
    )
    conn.commit()

def get_students() -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("SELECT * FROM students ORDER BY created_at DESC", conn)
    return df

def log_attempt(student_id: int, subject: str, test_name: str, score: float, meta_json: str = "") -> None:
    conn = db()
    conn.execute(
        "INSERT INTO attempts(student_id, subject, test_name, score, meta_json, created_at) VALUES(?,?,?,?,?,?)",
        (student_id, subject, test_name, float(score), meta_json, int(time.time())),
    )
    conn.commit()

def get_attempts(student_id: int) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query(
        "SELECT * FROM attempts WHERE student_id = ? ORDER BY created_at DESC",
        conn,
        params=(student_id,),
    )
    return df

# -----------------------------
# Adaptive logic (simple + useful)
# -----------------------------
def band_from_score(score: float) -> str:
    # score in [0,100]
    if score < 50:
        return "Foundations"
    if score < 75:
        return "Developing"
    if score < 90:
        return "On Track"
    return "Advanced"

def reading_plan(band: str) -> List[str]:
    if band == "Foundations":
        return [
            "Daily phonics/word patterns (10 min): short vowels, blends, digraphs",
            "Guided reading (15 min): 1 short leveled text, stop and decode",
            "Comprehension (10 min): who/what/where + 1 retell",
            "Fluency: 1-minute reread of same passage (track WPM weekly)",
        ]
    if band == "Developing":
        return [
            "Word study (8–10 min): prefixes/suffixes + multisyllable decoding",
            "Guided reading (15 min): 1 leveled text, focus on accuracy",
            "Comprehension (10 min): main idea + 2 text-evidence questions",
            "Vocabulary (5 min): 5 words used in a sentence",
        ]
    if band == "On Track":
        return [
            "Reading (20 min): grade-level text (fiction/nonfiction alternating)",
            "Comprehension (10 min): main idea, inference, evidence",
            "Writing (10 min): short response using 2 details from text",
        ]
    return [
        "Reading (25 min): higher lexile text + discussion",
        "Comprehension (10 min): theme/argument + evidence",
        "Writing (10 min): structured paragraph (claim → evidence → explain)",
    ]

def math_plan(band: str) -> List[str]:
    if band == "Foundations":
        return [
            "Fluency (10 min): addition/subtraction facts using number bonds",
            "Concept (15 min): place value + regrouping visuals",
            "Practice (10 min): 8–12 problems, then explain 1 out loud",
        ]
    if band == "Developing":
        return [
            "Fluency (8–10 min): mixed facts + skip counting",
            "Concept (15 min): multi-digit ops OR intro fractions (based on misses)",
            "Practice (10 min): 10–15 problems + 1 word problem",
        ]
    if band == "On Track":
        return [
            "Fluency (8 min): mixed facts timed set",
            "Concept (15 min): fractions/decimals/measurement (rotate)",
            "Practice (12 min): word problems + show work",
        ]
    return [
        "Fluency (8 min): multi-step mental math",
        "Concept (20 min): pre-algebra thinking, ratios, multi-step problems",
        "Practice (10 min): challenge problem + explain reasoning",
    ]

# -----------------------------
# Question banks
# -----------------------------
@dataclass
class MCQ:
    prompt: str
    options: List[str]
    answer_index: int
    skill: str

READING_MCQS: List[MCQ] = [
    MCQ("Which word is closest in meaning to 'happy'?", ["sad", "glad", "angry", "tired"], 1, "Vocabulary"),
    MCQ("In a story, the 'setting' is…", ["the problem", "where/when it happens", "the main character", "the ending"], 1, "Story Elements"),
    MCQ("If a character is 'brave', they are…", ["scared", "lazy", "courageous", "confused"], 2, "Vocabulary"),
    MCQ("A 'summary' should…", ["include every detail", "be the main points", "be only opinions", "be the first sentence"], 1, "Comprehension"),
    MCQ("An 'inference' is…", ["a guess based on clues", "a dictionary meaning", "a title", "a rhyme"], 0, "Comprehension"),
]

MATH_MCQS: List[MCQ] = [
    MCQ("What is 37 + 25?", ["52", "62", "72", "82"], 2, "Addition"),
    MCQ("What is 90 - 46?", ["34", "44", "54", "64"], 1, "Subtraction"),
    MCQ("Which is the largest?", ["0.5", "0.05", "0.15", "0.9"], 3, "Decimals"),
    MCQ("What is 3/4 of 20?", ["10", "12", "15", "18"], 2, "Fractions"),
    MCQ("If a rectangle is 6 by 4, its area is…", ["10", "20", "24", "30"], 2, "Geometry"),
]

def run_mcq_test(test_name: str, bank: List[MCQ], key_prefix: str) -> Tuple[float, Dict[str, int]]:
    st.write(f"**{test_name}** — {len(bank)} questions")
    correct = 0
    misses_by_skill: Dict[str, int] = {}
    for i, q in enumerate(bank):
        choice = st.radio(q.prompt, q.options, key=f"{key_prefix}_{i}", index=None)
        if choice is None:
            continue
        if q.options.index(choice) == q.answer_index:
            correct += 1
        else:
            misses_by_skill[q.skill] = misses_by_skill.get(q.skill, 0) + 1

    answered = sum(1 for i in range(len(bank)) if st.session_state.get(f"{key_prefix}_{i}") is not None)
    if answered == 0:
        return 0.0, misses_by_skill
    score = (correct / len(bank)) * 100.0
    return score, misses_by_skill

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Homeschool Adaptive Dashboard", layout="wide")
st.title("🏠 Homeschool Adaptive Dashboard")

students_df = get_students()

with st.sidebar:
    st.header("Add Student")
    name = st.text_input("Name")
    age = st.number_input("Age (optional)", min_value=0, max_value=25, value=0)
    grade = st.text_input("Grade (optional)", placeholder="e.g., 4th")
    if st.button("Create Student"):
        if not name.strip():
            st.error("Name is required.")
        else:
            add_student(name, int(age) if age else None, grade)
            st.success("Student created.")
            st.rerun()

if students_df.empty:
    st.info("Create a student profile in the sidebar to begin.")
    st.stop()

student_names = [f"{row['name']} (id:{row['id']})" for _, row in students_df.iterrows()]
selected = st.selectbox("Select student", student_names)
student_id = int(selected.split("id:")[1].replace(")", "").strip())

tabs = st.tabs(["Assessments", "Results", "Adaptive Plan", "Admin"])

# ---- Assessments
with tabs[0]:
    st.subheader("Baseline Assessments")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📚 Reading Check")
        st.caption("Do this first: answer MCQs, then enter Fluency + Comprehension info (you observe).")
        reading_score, reading_misses = run_mcq_test("Reading Mini-Assessment", READING_MCQS, "read")
        wpm = st.number_input("Fluency (Words Correct Per Minute) — enter after 1 minute read", min_value=0, max_value=300, value=0)
        comprehension_rating = st.slider("Comprehension (your rating)", 0, 10, 5)

        # Simple combined score boost: MCQ 70%, comprehension 20%, fluency 10%
        # (You can adjust later.)
        fluency_component = min(10.0, (wpm / 120.0) * 10.0)  # caps at 120 wpm
        combined_reading = (0.7 * reading_score) + (0.2 * (comprehension_rating * 10)) + (0.1 * (fluency_component * 10))

        if st.button("Save Reading Result"):
            meta = {
                "mcq_score": reading_score,
                "wpm": wpm,
                "comprehension_rating_0_10": comprehension_rating,
                "misses_by_skill": reading_misses,
            }
            log_attempt(student_id, "Reading", "Baseline", combined_reading, str(meta))
            st.success(f"Saved. Combined Reading Score: {combined_reading:.1f}")
            st.rerun()

    with col2:
        st.markdown("### ➗ Math Check")
        st.caption("Mini-assessment. We'll expand skill-specific drills after baseline.")
        math_score, math_misses = run_mcq_test("Math Mini-Assessment", MATH_MCQS, "math")

        if st.button("Save Math Result"):
            meta = {"mcq_score": math_score, "misses_by_skill": math_misses}
            log_attempt(student_id, "Math", "Baseline", math_score, str(meta))
            st.success(f"Saved. Math Score: {math_score:.1f}")
            st.rerun()

# ---- Results
with tabs[1]:
    st.subheader("Results History")
    attempts = get_attempts(student_id)
    if attempts.empty:
        st.info("No results yet. Go to Assessments and save Reading and Math baselines.")
    else:
        st.dataframe(attempts, use_container_width=True)
        latest_read = attempts[attempts["subject"] == "Reading"].head(1)
        latest_math = attempts[attempts["subject"] == "Math"].head(1)

        colA, colB = st.columns(2)
        with colA:
            st.markdown("### Latest Reading")
            if not latest_read.empty:
                score = float(latest_read.iloc[0]["score"])
                st.metric("Reading score", f"{score:.1f}", band_from_score(score))
            else:
                st.write("No reading score yet.")
        with colB:
            st.markdown("### Latest Math")
            if not latest_math.empty:
                score = float(latest_math.iloc[0]["score"])
                st.metric("Math score", f"{score:.1f}", band_from_score(score))
            else:
                st.write("No math score yet.")

# ---- Adaptive Plan
with tabs[2]:
    st.subheader("Adaptive Weekly Plan (auto-generated)")
    attempts = get_attempts(student_id)

    latest_read_score = None
    latest_math_score = None
    if not attempts.empty:
        r = attempts[attempts["subject"] == "Reading"].head(1)
        m = attempts[attempts["subject"] == "Math"].head(1)
        if not r.empty:
            latest_read_score = float(r.iloc[0]["score"])
        if not m.empty:
            latest_math_score = float(m.iloc[0]["score"])

    if latest_read_score is None or latest_math_score is None:
        st.warning("Save BOTH a Reading and a Math baseline first.")
    else:
        rb = band_from_score(latest_read_score)
        mb = band_from_score(latest_math_score)

        st.markdown(f"**Reading Band:** {rb}  \n**Math Band:** {mb}")

        st.markdown("### Monday–Thursday (2 hr 15 min)")
        plan = [
            ("Warm-up (10 min)", "Copywork/typing + parent read-aloud (2 minutes)"),
            ("Reading Core (35 min)", "\n- " + "\n- ".join(reading_plan(rb))),
            ("Math Core (35 min)", "\n- " + "\n- ".join(math_plan(mb))),
            ("Writing (20 min)", "Sentence → paragraph. Use reading text for prompts."),
            ("Science/Social Studies (25 min)", "Short video/article + discussion + 5-min summary."),
        ]
        for title, detail in plan:
            st.markdown(f"**{title}**")
            st.write(detail)

        st.markdown("### Friday (60–90 min)")
        st.write("- Re-test 1 short reading passage (WPM + 3 questions)\n- 10-question math check\n- Finish weekly mini-project")

# ---- Admin
with tabs[3]:
    st.subheader("Admin")
    st.caption("Basic utilities.")
    if st.button("Reset database (DANGER)"):
        conn = db()
        conn.execute("DROP TABLE IF EXISTS attempts")
        conn.execute("DROP TABLE IF EXISTS students")
        conn.commit()
        st.error("Database reset. Reload the page.")