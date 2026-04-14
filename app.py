import os
import psycopg2
from flask import Flask, render_template, request, jsonify
from google import genai
from PIL import Image
import io
import json
import time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- 1. GEMINI CONFIG (Using 2.5 Flash) ---
API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyB6jdWpKcb5HQC80AtUGi89e7UyA6_a0fE")
genai_client = genai.Client(api_key=API_KEY) if API_KEY else None

DEFAULT_NUTRITION = [
    {"nutrient": "Calories", "amount": 220, "unit": "kcal"},
    {"nutrient": "Protein", "amount": 9, "unit": "g"},
    {"nutrient": "Carbs", "amount": 28, "unit": "g"},
    {"nutrient": "Fat", "amount": 8, "unit": "g"},
]

# --- 2. DATABASE CONFIG (Samiksha's Mac User) ---
def get_db_connection():
    try:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            conn = psycopg2.connect(database_url)
        else:
            conn = psycopg2.connect(
                dbname=os.getenv("DB_NAME", "food_app"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", "1234"),
                host=os.getenv("DB_HOST", "localhost"),
                port=os.getenv("DB_PORT", "5432"),
            )
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None


def initialize_database():
    conn = get_db_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS food_scans (
                    id SERIAL PRIMARY KEY,
                    food_data TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
            cur.execute("ALTER TABLE food_scans ADD COLUMN IF NOT EXISTS food_data TEXT;")
            cur.execute("ALTER TABLE food_scans ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")
        conn.commit()
    except Exception as e:
        print(f"Database initialization error: {e}")
    finally:
        conn.close()


def normalize_nutrition_payload(payload):
    if not payload:
        return []

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        if "nutritional_breakdown" in payload and isinstance(payload["nutritional_breakdown"], list):
            return payload["nutritional_breakdown"]

        if all(key in payload for key in ("calories", "protein", "carbs", "fats")):
            return [
                {"nutrient": "Calories", "amount": payload.get("calories", "N/A"), "unit": "kcal"},
                {"nutrient": "Protein", "amount": payload.get("protein", "N/A"), "unit": "g"},
                {"nutrient": "Carbs", "amount": payload.get("carbs", "N/A"), "unit": "g"},
                {"nutrient": "Fat", "amount": payload.get("fats", "N/A"), "unit": "g"},
            ]

    return []


def get_food_scans_columns(cur):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'food_scans'
        """
    )
    return {row[0] for row in cur.fetchall()}


def parse_amount(value):
    if isinstance(value, (int, float)):
        return float(value)

    if value is None:
        return 0.0

    raw = str(value).strip().lower().replace("kcal", "").replace("g", "")
    try:
        return float(raw)
    except Exception:
        return 0.0


def fetch_cached_scan(cur, food_name):
    columns = get_food_scans_columns(cur)

    cur.execute(
        """
        SELECT food_data
        FROM food_scans
        WHERE food_data ILIKE %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (f"%{food_name}%",),
    )
    row = cur.fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return {"food_identified": food_name, "nutritional_breakdown": DEFAULT_NUTRITION}

    if {"food_name", "nutrient", "amount", "unit"}.issubset(columns):
        cur.execute(
            """
            SELECT nutrient, amount, unit
            FROM food_scans
            WHERE food_name ILIKE %s
            ORDER BY created_at DESC
            """,
            (f"%{food_name}%",),
        )
        legacy_rows = cur.fetchall()
        if legacy_rows:
            breakdown = [
                {"nutrient": nutrient, "amount": float(amount), "unit": unit}
                for nutrient, amount, unit in legacy_rows
            ]
            return {"food_identified": food_name, "nutritional_breakdown": breakdown}

    return None


def save_scan(cur, food_name, nutrients):
    payload = {
        "food_identified": food_name,
        "nutritional_breakdown": nutrients,
    }
    columns = get_food_scans_columns(cur)

    requires_legacy_rows = any(col in columns for col in ("nutrient", "amount", "unit"))
    rows_to_insert = nutrients if requires_legacy_rows else [None]

    for nutrient_row in rows_to_insert:
        col_names = []
        placeholders = []
        values = []

        if "food_name" in columns:
            col_names.append("food_name")
            placeholders.append("%s")
            values.append(food_name)

        if "nutrient" in columns:
            col_names.append("nutrient")
            placeholders.append("%s")
            values.append((nutrient_row or {}).get("nutrient", "Unknown"))

        if "amount" in columns:
            col_names.append("amount")
            placeholders.append("%s")
            values.append(parse_amount((nutrient_row or {}).get("amount", 0)))

        if "unit" in columns:
            col_names.append("unit")
            placeholders.append("%s")
            values.append((nutrient_row or {}).get("unit", "unit"))

        if "food_data" in columns:
            col_names.append("food_data")
            placeholders.append("%s")
            values.append(json.dumps(payload))

        if "created_at" in columns:
            col_names.append("created_at")
            placeholders.append("NOW()")

        query = f"INSERT INTO food_scans ({', '.join(col_names)}) VALUES ({', '.join(placeholders)})"
        cur.execute(query, values)


initialize_database()

# --- 3. HOME ROUTE ---
@app.route('/')
def home():
    return render_template('index.html')

# --- 4. ANALYZE ROUTE ---
@app.route('/analyze', methods=['POST'])
def analyze_food():
    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"}), 400

    image_file = request.files['image']
    
    try:
        # Convert Flask file storage to PIL Image
        img = Image.open(image_file)

        ai_food_name = "Unknown food"
        if genai_client:
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
        db_saved = False
        db_error = None
        
        if conn:
            try:
                with conn.cursor() as cur:
                    cached_scan = fetch_cached_scan(cur, ai_food_name)
                    nutrients = normalize_nutrition_payload(cached_scan) or DEFAULT_NUTRITION
                    save_scan(cur, ai_food_name, nutrients)
                conn.commit()
                db_saved = True
            except Exception as db_exc:
                conn.rollback()
                db_error = str(db_exc)
                print(f"DB write error: {db_error}")
            finally:
                conn.close()
        else:
            db_error = "Database connection unavailable"

        if not nutrients:
            nutrients = DEFAULT_NUTRITION

        return jsonify({
            "success": True,
            "food_identified": ai_food_name,
            "nutritional_breakdown": nutrients,
            "warning": None if genai_client else "GEMINI_API_KEY is not configured; saved fallback result.",
            "db_saved": db_saved,
            "db_error": db_error,
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)