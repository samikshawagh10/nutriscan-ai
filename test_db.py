from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
# Your exact connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://samikshawagh@localhost:5432/food_analyzer_db'

db = SQLAlchemy(app)

with app.app_context():
    try:
        # We try to run a simple 'Hello' query to the database
        db.session.execute(text('SELECT 1'))
        print("✅ SUCCESS! Your Python backend is connected to the database.")
    except Exception as e:
        print("❌ CONNECTION FAILED. Here is the exact error:")
        print(e)