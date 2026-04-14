from app import get_db_connection, initialize_database

conn = get_db_connection()
if not conn:
    raise SystemExit("Could not connect to PostgreSQL. Check DATABASE_URL or local DB settings.")

try:
    with conn.cursor() as cur:
        print("Dropping old food_scans table...")
        cur.execute("DROP TABLE IF EXISTS food_scans;")
    conn.commit()

    print("Recreating food_scans table based on the current schema...")
    initialize_database()

    print("Database reset successfully! Ready to scan.")
finally:
    conn.close()