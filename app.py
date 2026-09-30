import datetime
import json
import os
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
from streamlit_gsheets import GSheetsConnection

# --- GOOGLE SHEETS CONNECTION ---
def get_gsheets_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def log_meal_to_gsheets(dish_idea, calories, protein, carbs, fat, breakdown):
    conn = get_gsheets_connection()
    
    # Read existing sheet data
    existing_data = conn.read(ttl=0)
    
    now = datetime.datetime.now()
    new_row = pd.DataFrame([{
        "Date": now.strftime("%Y-%m-%d"),
        "Time": now.strftime("%H:%M"),
        "Dish Idea": dish_idea,
        "Calories": calories,
        "Protein": protein,
        "Carbs": carbs,
        "Fat": fat,
        "Breakdown": json.dumps(breakdown)
    }])
    
    # Append the new row and update sheet
    updated_data = pd.concat([existing_data, new_row], ignore_index=True)
    conn.update(data=updated_data)

def get_daily_logs_from_gsheets(selected_date):
    try:
        conn = get_gsheets_connection()
        df = conn.read(ttl=0)
        if df.empty:
            return []
        
        date_str = selected_date.strftime("%Y-%m-%d")
        filtered_df = df[df["Date"] == date_str]
        return filtered_df.to_dict(orient="records")
    except Exception:
        return []

# --- GEMINI AI ANALYSIS ---
def analyze_meal(image: Image.Image, general_idea: str):
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        st.error("Missing GEMINI_API_KEY environment variable or secret.")
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
        model="gemini-2.0-flash",  # Fixed model name
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

# Replaces the radio/camera input so your Oppo opens its native Camera app
uploaded_file = st.file_uploader(
    "Take photo or select from gallery", 
    type=["jpg", "jpeg", "png", "heic", "webp"]
)

uploaded_image = None
if uploaded_file is not None:
    uploaded_image = Image.open(uploaded_file)

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
        with st.spinner("Analyzing photo and saving to Google Sheets..."):
            result = analyze_meal(uploaded_image, general_idea)

            if result:
                log_meal_to_gsheets(
                    dish_idea=result.get("dish_name", general_idea),
                    calories=int(result.get("total_calories", 0)),
                    protein=int(result.get("protein_g", 0)),
                    carbs=int(result.get("carbs_g", 0)),
                    fat=int(result.get("fat_g", 0)),
                    breakdown=result.get("ingredient_breakdown", [])
                )
                st.success(f"Logged {result.get('dish_name')} ({result.get('total_calories')} kcal) to Google Sheets!")

st.divider()

# --- DAILY SUMMARY DASHBOARD ---
st.subheader(f"📊 Summary for {selected_date.strftime('%Y-%m-%d')}")

logs = get_daily_logs_from_gsheets(selected_date)

total_cal = sum(int(row["Calories"]) for row in logs) if logs else 0
total_p = sum(int(row["Protein"]) for row in logs) if logs else 0
total_c = sum(int(row["Carbs"]) for row in logs) if logs else 0
total_f = sum(int(row["Fat"]) for row in logs) if logs else 0

progress = min(total_cal / daily_target, 1.0)
st.progress(progress, text=f"**{total_cal} / {daily_target} kcal** ({int(progress * 100)}%)")

col1, col2, col3 = st.columns(3)
col1.metric("Protein", f"{total_p} g")
col2.metric("Carbs", f"{total_c} g")
col3.metric("Fat", f"{total_f} g")

if logs:
    st.markdown("### Logged Meals")
    for log in logs:
        time_str = log["Time"]
        dish = log["Dish Idea"]
        cals = log["Calories"]
        p, c, f = log["Protein"], log["Carbs"], log["Fat"]
        breakdown_str = log.get("Breakdown", "[]")

        with st.expander(f"**{time_str}** - {dish} ({cals} kcal)"):
            st.write(f"**Macros:** P: {p}g | C: {c}g | F: {f}g")
            if breakdown_str:
                try:
                    breakdown = json.loads(breakdown_str)
                    st.write("**Estimated Breakdown:**")
                    for item in breakdown:
                        st.write(f"- {item.get('ingredient')}: ~{item.get('estimated_weight_g')}g ({item.get('calories')} kcal)")
                except Exception:
                    pass
else:
    st.info("No meals logged for this date in your Google Sheet.")
