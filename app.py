import datetime
import json
import os
import sqlite3
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image

# --- DATABASE SETUP ---
DB_FILE = "calorie_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meal_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            dish_idea TEXT,
            calories INTEGER,
            protein INTEGER,
            carbs INTEGER,
            fat INTEGER,
            breakdown TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_meal(dish_idea, calories, protein, carbs, fat, breakdown):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.datetime.now()
    cursor.execute("""
        INSERT INTO meal_logs (date, time, dish_idea, calories, protein, carbs, fat, breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M"),
        dish_idea,
        calories,
        protein,
        carbs,
        fat,
        json.dumps(breakdown)
    ))
    conn.commit()
    conn.close()

def get_daily_logs(selected_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, time, dish_idea, calories, protein, carbs, fat, breakdown
        FROM meal_logs WHERE date = ? ORDER BY id DESC
    """, (selected_date.strftime("%Y-%m-%d"),))
    rows = cursor.fetchall()
    conn.close()
    return rows

init_db()

# --- GEMINI AI ANALYSIS ---
def analyze_meal(image: Image.Image, general_idea: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        st.error("Missing GEMINI_API_KEY environment variable. Please set it before running.")
        return None

    client = genai.Client(api_key=api_key)

    prompt = f"""
    Analyze this meal photo along with the user's general description and weights.
    User description/weight details: "{general_idea}"

    Tasks:
    1. Look at the photo to identify all visible components and ingredients.
    2. Combine the visual components with the user's weight info to estimate accurate portion sizes.
    3. Calculate total Calories, Protein (g), Carbs (g), and Fat (g).
    4. Provide a breakdown of estimated ingredients.

    Return JSON matching this exact structure:
    {{
      "dish_name": "Name of dish",
      "total_calories": 500,
      "protein_g": 35,
      "carbs_g": 45,
      "fat_g": 15,
      "ingredient_breakdown": [
        {{"ingredient": "Chicken breast", "estimated_weight_g": 150, "calories": 240}},
        {{"ingredient": "Olive oil", "estimated_weight_g": 10, "calories": 88}}
      ]
    }}
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[image, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    try:
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Failed to parse AI output: {e}")
        return None

# --- STREAMLIT APP INTERFACE ---
st.set_page_config(page_title="AI Calorie Tracker", page_icon="🥗", layout="centered")
st.title("🥗 Photo Calorie Tracker")

daily_target = st.sidebar.number_input("Daily Calorie Target", value=2000, step=50)
selected_date = st.sidebar.date_input("Select Date", datetime.date.today())

st.subheader("📷 Log a Meal")

input_mode = st.radio("Choose Photo Source:", ["Take Photo (Camera)", "Upload File"], horizontal=True)

uploaded_image = None

if input_mode == "Take Photo (Camera)":
    camera_photo = st.camera_input("Take a photo of your meal")
    if camera_photo:
        uploaded_image = Image.open(camera_photo)
else:
    file_photo = st.file_uploader("Upload meal photo", type=["jpg", "jpeg", "png"])
    if file_photo:
        uploaded_image = Image.open(file_photo)

general_idea = st.text_input(
    "General dish idea + weight info",
    placeholder="e.g., Homemade pasta with beef sauce, total ~350g"
)

if st.button("Analyze & Log Meal", type="primary"):
    if not uploaded_image:
        st.warning("Please provide or take a photo.")
    elif not general_idea.strip():
        st.warning("Please provide a brief dish idea and weight.")
    else:
        with st.spinner("Analyzing photo and scaling ingredients..."):
            result = analyze_meal(uploaded_image, general_idea)

            if result:
                log_meal(
                    dish_idea=result.get("dish_name", general_idea),
                    calories=result.get("total_calories", 0),
                    protein=result.get("protein_g", 0),
                    carbs=result.get("carbs_g", 0),
                    fat=result.get("fat_g", 0),
                    breakdown=result.get("ingredient_breakdown", [])
                )
                st.success(f"Logged {result.get('dish_name')} ({result.get('total_calories')} kcal)!")

st.divider()

# --- DAILY SUMMARY DASHBOARD ---
st.subheader(f"📊 Summary for {selected_date.strftime('%Y-%m-%d')}")

logs = get_daily_logs(selected_date)
total_cal = sum(row[3] for row in logs)
total_p = sum(row[4] for row in logs)
total_c = sum(row[5] for row in logs)
total_f = sum(row[6] for row in logs)

progress = min(total_cal / daily_target, 1.0)
st.progress(progress, text=f"**{total_cal} / {daily_target} kcal** ({int(progress * 100)}%)")

col1, col2, col3 = st.columns(3)
col1.metric("Protein", f"{total_p} g")
col2.metric("Carbs", f"{total_c} g")
col3.metric("Fat", f"{total_f} g")

if logs:
    st.markdown("### Logged Meals")
    for log in logs:
        meal_id, time_str, dish, cals, p, c, f, breakdown_str = log
        with st.expander(f"**{time_str}** - {dish} ({cals} kcal)"):
            st.write(f"**Macros:** P: {p}g | C: {c}g | F: {f}g")
            if breakdown_str:
                breakdown = json.loads(breakdown_str)
                st.write("**Estimated Breakdown:**")
                for item in breakdown:
                    st.write(f"- {item.get('ingredient')}: ~{item.get('estimated_weight_g')}g ({item.get('calories')} kcal)")
else:
    st.info("No meals logged for this date.")
