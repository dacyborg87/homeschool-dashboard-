import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st

# Optional Supabase support (Option 3)
# If SUPABASE_URL / SUPABASE_ANON_KEY are present in Streamlit Secrets,
# the app will use Supabase Postgres + Auth. Otherwise it falls back to local SQLite.
USE_SUPABASE = False

try:
    from supabase import create_client  # type: ignore

    SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")
    LOGO_URL = st.secrets.get("LOGO_URL", "")
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        USE_SUPABASE = True
    else:
        supabase = None
        LOGO_URL = st.secrets.get("LOGO_URL", "")
except Exception:
    supabase = None
    LOGO_URL = st.secrets.get("LOGO_URL", "")


# -----------------------------
# SQLite fallback (local-only)
# -----------------------------
import sqlite3

DB_PATH = "homeschool.db"

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
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def sqlite_add_student(name: str, age: Optional[int], grade: str) -> None:
    conn = db()
    conn.execute(
        "INSERT INTO students(name, age, grade, created_at) VALUES(?,?,?,?)",
        (name.strip(), age if age else None, grade.strip(), int(time.time())),
    )
    conn.commit()


def sqlite_get_students() -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("SELECT * FROM students ORDER BY created_at DESC", conn)
    return df


def sqlite_log_attempt(student_id: int, subject: str, test_name: str, score: float, meta_json: str = "") -> None:
    conn = db()
    conn.execute(
        "INSERT INTO attempts(student_id, subject, test_name, score, meta_json, created_at) VALUES(?,?,?,?,?,?)",
        (student_id, subject, test_name, float(score), meta_json, int(time.time())),
    )
    conn.commit()


def sqlite_get_attempts(student_id: int) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query(
        "SELECT * FROM attempts WHERE student_id = ? ORDER BY created_at DESC",
        conn,
        params=(student_id,),
    )
    return df


# -----------------------------
# Supabase (Option 3)
# -----------------------------

def sb_sign_in(email: str, password: str) -> Dict:
    assert supabase is not None
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    # supabase-py returns an object with .session/.user; store minimal dict
    session = getattr(res, "session", None)
    user = getattr(res, "user", None)
    if session is None or user is None:
        raise RuntimeError("Login failed. Check email/password.")
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user": {"id": user.id, "email": user.email},
    }


def sb_get_profile(user_id: str) -> Dict:
    assert supabase is not None
    data = supabase.table("profiles").select("id,email,role").eq("id", user_id).execute()
    rows = getattr(data, "data", None) or []
    if rows:
        return rows[0]
    # If profiles trigger wasn't installed yet, create a default profile row.
    user_email = st.session_state.get("auth", {}).get("user", {}).get("email")
    ins = supabase.table("profiles").insert({"id": user_id, "email": user_email, "role": "parent"}).execute()
    rows2 = getattr(ins, "data", None) or []
    return rows2[0] if rows2 else {"id": user_id, "email": user_email, "role": "parent"}


def sb_get_students(family_id: str) -> pd.DataFrame:
    assert supabase is not None
    res = supabase.table("students").select("id,name,age,grade,created_at").eq("family_id", family_id).order("created_at", desc=True).execute()
    rows = getattr(res, "data", None) or []
    return pd.DataFrame(rows)


def sb_add_student(family_id: str, name: str, age: Optional[int], grade: str) -> None:
    assert supabase is not None
    supabase.table("students").insert({
        "family_id": family_id,
        "name": name.strip(),
        "age": int(age) if age else None,
        "grade": grade.strip(),
    }).execute()


def sb_log_attempt(family_id: str, student_id: int, subject: str, test_name: str, score: float, meta: Dict) -> None:
    assert supabase is not None
    supabase.table("attempts").insert({
        "family_id": family_id,
        "student_id": int(student_id),
        "subject": subject,
        "test_name": test_name,
        "score": float(score),
        "meta_json": meta,
    }).execute()


def sb_get_attempts(family_id: str, student_id: int) -> pd.DataFrame:
    assert supabase is not None
    res = (
        supabase.table("attempts")
        .select("id,student_id,subject,test_name,score,meta_json,created_at")
        .eq("family_id", family_id)
        .eq("student_id", int(student_id))
        .order("created_at", desc=True)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    return pd.DataFrame(rows)


# -----------------------------
# Adaptive logic
# -----------------------------

def band_from_score(score: float) -> str:
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

    answered = sum(
        1 for i in range(len(bank))
        if st.session_state.get(f"{key_prefix}_{i}") is not None
    )
    if answered == 0:
        return 0.0, misses_by_skill

    score = (correct / len(bank)) * 100.0
    return score, misses_by_skill


# -----------------------------
# Auth UI (Supabase)
# -----------------------------

def render_auth_box() -> Optional[Dict]:
    st.sidebar.markdown("## Login")
    email = st.sidebar.text_input("Email", key="login_email")
    password = st.sidebar.text_input("Password", type="password", key="login_password")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("Sign in"):
            if not email or not password:
                st.sidebar.error("Enter email + password")
                return None
            try:
                auth = sb_sign_in(email, password)
                st.session_state["auth"] = auth
                st.sidebar.success("Signed in")
                st.rerun()
            except Exception as e:
                st.sidebar.error(str(e))
                return None

    with col2:
        if st.button("Sign out"):
            st.session_state.pop("auth", None)
            st.rerun()

    return st.session_state.get("auth")


# -----------------------------
# Kid-friendly UI helpers
# -----------------------------

def render_brand_header() -> None:
    """Top-of-page brand header with optional logo."""
    if LOGO_URL:
        # Center the logo
        st.markdown(
            f"""
            <div style='display:flex; justify-content:center; margin-top:10px; margin-bottom:10px;'>
              <img src='{LOGO_URL}' style='max-width:520px; width:90%; height:auto;' />
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_welcome(student_label: str, kid_mode: bool) -> None:
    """Welcome screen. In kid mode it becomes the main navigation."""
    render_brand_header()

    st.markdown(
        """
        <div style='text-align:center;'>
          <h2 style='margin-bottom:0;'>Welcome to Jones Academy ✨</h2>
          <p style='opacity:0.85; margin-top:6px;'>Pick what you want to do today.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📚 Start Reading", use_container_width=True):
            st.session_state["active_tab"] = "Assessments"
            st.session_state["focus_subject"] = "Reading"
            st.rerun()
    with col2:
        if st.button("➗ Start Math", use_container_width=True):
            st.session_state["active_tab"] = "Assessments"
            st.session_state["focus_subject"] = "Math"
            st.rerun()
    with col3:
        if st.button("🗓️ Today's Plan", use_container_width=True):
            st.session_state["active_tab"] = "Adaptive Plan"
            st.session_state["focus_subject"] = None
            st.rerun()

    st.divider()

    # Simple fun progress widget (local-only; we can persist later)
    stars = int(st.session_state.get("stars", 0))
    st.markdown(
        f"<div style='text-align:center; font-size:20px;'>⭐ Stars earned today: <b>{stars}</b></div>",
        unsafe_allow_html=True,
    )

    colA, colB = st.columns(2)
    with colA:
        if st.button("✅ I finished a task", use_container_width=True):
            st.session_state["stars"] = stars + 1
            st.success("Nice! +1 star ⭐")
            st.rerun()
    with colB:
        if st.button("🔄 Reset stars (today)", use_container_width=True):
            st.session_state["stars"] = 0
            st.rerun()

    if not kid_mode:
        st.info("Tip: Turn on **Student Mode** in the sidebar to lock this down for the kids.")

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Jones Academy", layout="wide")
# Use a branded header; the H1 title remains for accessibility/search
st.title("🏫 Jones Academy")
st.caption("Personalized Homeschool Dashboard")

# If Supabase is configured, require login
family_id = None
role = "parent"
if "student_mode" not in st.session_state:
    st.session_state["student_mode"] = False

if USE_SUPABASE:
    auth = st.session_state.get("auth")
    if not auth:
        render_auth_box()
        st.info("Log in to continue.")
        st.stop()

    # 🔐 IMPORTANT: Re-apply Supabase session on EVERY rerun so PostgREST uses the JWT (RLS needs this)
    try:
        if supabase is not None:
            supabase.auth.set_session(auth["access_token"], auth["refresh_token"])
    except Exception:
        try:
            if supabase is not None:
                supabase.postgrest.auth(auth["access_token"])
        except Exception:
            pass

    family_id = auth["user"]["id"]
    profile = sb_get_profile(family_id)
    role = profile.get("role", "parent")

    st.sidebar.markdown(f"**Role:** {role}")
    # Kid-safe mode toggle (locks down the UI)
    if role in ("admin", "parent"):
        st.sidebar.toggle("Student Mode (Kid-safe)", key="student_mode", value=bool(st.session_state.get("student_mode", False)))
    else:
        st.session_state["student_mode"] = True

# Sidebar: Add Student (Admin + Parent only)
with st.sidebar:
    if (not st.session_state.get("student_mode", False)) and ((not USE_SUPABASE) or role in ("admin", "parent")):
        st.header("Add Student")
        name = st.text_input("Name", key="new_student_name")
        age = st.number_input("Age (optional)", min_value=0, max_value=25, value=0, key="new_student_age")
        grade = st.text_input("Grade (optional)", placeholder="e.g., 4th", key="new_student_grade")

        if st.button("Create Student"):
            if not name.strip():
                st.error("Name is required.")
            else:
                if USE_SUPABASE:
                    sb_add_student(family_id, name, int(age) if age else None, grade)
                else:
                    sqlite_add_student(name, int(age) if age else None, grade)
                st.success("Student created.")
                st.rerun()

# Load students
if USE_SUPABASE:
    students_df = sb_get_students(family_id)
else:
    students_df = sqlite_get_students()

if students_df is None or len(students_df) == 0:
    st.info("Create a student profile in the sidebar to begin.")
    st.stop()

student_names = [f"{row['name']} (id:{row['id']})" for _, row in students_df.iterrows()]
selected = st.selectbox("Select student", student_names)
# Store selected student name for the Welcome screen
try:
    st.session_state["selected_student_name"] = selected.split(" (id:")[0]
except Exception:
    pass
student_id = int(selected.split("id:")[1].replace(")", "").strip())

kid_mode = bool(st.session_state.get("student_mode", False))

# Tabs
base_tabs = ["Welcome", "Assessments", "Results", "Adaptive Plan"]
if (not USE_SUPABASE) or role == "admin":
    base_tabs.append("Admin")

# In kid mode, hide Results/Admin
if kid_mode:
    base_tabs = ["Welcome", "Assessments", "Adaptive Plan"]

# Track active tab preference
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "Welcome"

tabs = st.tabs(base_tabs)

# ---- Welcome
with tabs[0]:
    # Student label for the welcome screen
    student_label = ""
    try:
        # If a student is already selected, show their name
        if "selected_student_name" in st.session_state:
            student_label = st.session_state["selected_student_name"]
    except Exception:
        pass

    render_welcome(student_label, kid_mode)

# ---- Assessments
with tabs[1]:
    st.subheader("Baseline Assessments")
    if kid_mode:
        st.success("Kid Mode is ON ✅  Ask a parent for help with the 1-minute reading timer.")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📚 Reading Check")
        st.caption("Answer MCQs, then enter Fluency + Comprehension (parent observes).")
        reading_score, reading_misses = run_mcq_test("Reading Mini-Assessment", READING_MCQS, "read")
        wpm = st.number_input("Fluency (Words Correct Per Minute) — enter after 1 minute read", min_value=0, max_value=300, value=0)
        comprehension_rating = st.slider("Comprehension (your rating)", 0, 10, 5)

        fluency_component = min(10.0, (wpm / 120.0) * 10.0)  # caps at 120 wpm
        combined_reading = (0.7 * reading_score) + (0.2 * (comprehension_rating * 10)) + (0.1 * (fluency_component * 10))

        if st.button("Save Reading Result"):
            meta = {
                "mcq_score": reading_score,
                "wpm": wpm,
                "comprehension_rating_0_10": comprehension_rating,
                "misses_by_skill": reading_misses,
            }
            if USE_SUPABASE:
                sb_log_attempt(family_id, student_id, "Reading", "Baseline", combined_reading, meta)
            else:
                sqlite_log_attempt(student_id, "Reading", "Baseline", combined_reading, str(meta))
            st.success(f"Saved. Combined Reading Score: {combined_reading:.1f}")
            st.rerun()

    with col2:
        st.markdown("### ➗ Math Check")
        st.caption("Mini-assessment. We'll expand skill-specific drills after baseline.")
        math_score, math_misses = run_mcq_test("Math Mini-Assessment", MATH_MCQS, "math")

        if st.button("Save Math Result"):
            meta = {"mcq_score": math_score, "misses_by_skill": math_misses}
            if USE_SUPABASE:
                sb_log_attempt(family_id, student_id, "Math", "Baseline", math_score, meta)
            else:
                sqlite_log_attempt(student_id, "Math", "Baseline", math_score, str(meta))
            st.success(f"Saved. Math Score: {math_score:.1f}")
            st.rerun()

# ---- Results
if not kid_mode:
    with tabs[2]:
        st.subheader("Results History")

        if USE_SUPABASE:
            attempts = sb_get_attempts(family_id, student_id)
        else:
            attempts = sqlite_get_attempts(student_id)

        if attempts is None or len(attempts) == 0:
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
with tabs[-1 if kid_mode else 3]:
    st.subheader("Adaptive Weekly Plan (auto-generated)")

    if USE_SUPABASE:
        attempts = sb_get_attempts(family_id, student_id)
    else:
        attempts = sqlite_get_attempts(student_id)

    latest_read_score = None
    latest_math_score = None

    if attempts is not None and len(attempts) > 0:
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

# ---- Admin (only if present)
if (not kid_mode) and (((not USE_SUPABASE) or role == "admin") and ("Admin" in base_tabs)):
    with tabs[-1]:
        st.subheader("Admin")
        st.caption("Admin-only actions.")

        st.warning("Reset is disabled in cloud mode. Use Supabase to manage data.")

        if not USE_SUPABASE:
            if st.button("Reset database (DANGER)"):
                conn = db()
                conn.execute("DROP TABLE IF EXISTS attempts")
                conn.execute("DROP TABLE IF EXISTS students")
                conn.commit()
                st.error("Database reset. Reload the page.")