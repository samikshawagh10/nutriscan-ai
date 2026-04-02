import os
import psycopg2
from flask import Flask, render_template, request, jsonify
from google import genai
from PIL import Image

app = Flask(__name__)

# --- 1. GEMINI CONFIG (Using 2.5 Flash) ---
API_KEY = os.getenv("GEMINI_API_KEY", "")
genai_client = genai.Client(api_key=API_KEY) if API_KEY else None

# --- 2. DATABASE CONFIG (Samiksha's Mac User) ---
def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname="samikshawagh",
            user="samikshawagh",
            password="1234",
            host="localhost",
            port="5432"
        )
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

# --- 3. HOME ROUTE ---
@app.route('/')
def home():
    return render_template('index.html')

# --- 4. ANALYZE ROUTE ---
@app.route('/analyze', methods=['POST'])
def analyze_food():
    if not genai_client:
        return jsonify({"success": False, "error": "GEMINI_API_KEY is not configured"}), 500

    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"}), 400

    image_file = request.files['image']
    
    try:
        # Convert Flask file storage to PIL Image
        img = Image.open(image_file)

        # Requesting identification
        prompt = "Identify the food in this image. Return ONLY the simple name (e.g. 'Pizza')."
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, img],
        )
        
        response_text = (response.text or "").strip()
        if not response_text:
            return jsonify({"success": False, "error": "AI response was empty"}), 500
            
        ai_food_name = response_text.replace('"', '')

        # --- DATABASE LOGGING & LOOKUP ---
        conn = get_db_connection()
        nutrients = []
        
        if conn:
            cur = conn.cursor()
            # Log the scan
            cur.execute("SELECT nutrient, amount, unit FROM food_scans WHERE food_name ILIKE %s", (f"%{ai_food_name}%",))
            rows = cur.fetchall()
            
            for row in rows:
                nutrients.append({"nutrient": row[0], "amount": float(row[1]), "unit": row[2]})
            
            conn.commit()
            cur.close()
            conn.close()

        # Fallback if your database doesn't have the item yet
        if not nutrients:
            nutrients = [
                {"nutrient": "Calories", "amount": 220, "unit": "kcal"},
                {"nutrient": "Protein", "amount": 9, "unit": "g"},
                {"nutrient": "Carbs", "amount": 28, "unit": "g"},
                {"nutrient": "Fat", "amount": 8, "unit": "g"}
            ]

        return jsonify({
            "success": True,
            "food_identified": ai_food_name,
            "nutritional_breakdown": nutrients
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)