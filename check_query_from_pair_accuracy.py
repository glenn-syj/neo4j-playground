import os
import json
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def check_sql_query_accuracy(json_file_path: str):
    """
    Reads NL2SQL pairs from a JSON file, connects to a PostgreSQL database,
    and attempts to execute each SQL query to check its validity.
    """
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    if not all([db_name, db_user, db_password]):
        print("Error: Database credentials (POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD) not set in .env file.")
        return

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            query_pairs = json.load(f)
    except FileNotFoundError:
        print(f"Error: JSON file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {json_file_path}. Check file format.")
        return

    conn = None
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        conn.autocommit = True # To ensure each query is run independently
        cur = conn.cursor()

        print(f"--- Checking SQL Query Accuracy from {json_file_path} ---")
        for i, pair in enumerate(query_pairs):
            nl_query = pair.get("NL", "N/A")
            sql_query = pair.get("SQL", "N/A")

            print(f"\n--- Query {i+1} ---")
            print(f"NL: {nl_query}")
            print(f"SQL: {sql_query}")

            if sql_query == "N/A":
                print("Result: Skipped (SQL query missing).")
                continue

            try:
                cur.execute(sql_query)
                # If it's a SELECT query, try to fetch some rows to confirm it works
                if sql_query.strip().upper().startswith("SELECT"):
                    try:
                        _ = cur.fetchone() # Just try to fetch one to see if it errors
                        print("Result: SUCCESS (SELECT query executed and fetched data).")
                    except psycopg2.ProgrammingError as e:
                        print(f"Result: SUCCESS (Non-data returning query or data not fetched: {e})")
                else:
                    print("Result: SUCCESS (Non-SELECT query executed).")
            except psycopg2.Error as e:
                print(f"Result: FAILED - Database Error: {e}")
            except Exception as e:
                print(f"Result: FAILED - General Error: {e}")

    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            print("\nDatabase connection closed.")

if __name__ == "__main__":
    target_json_file = "bigbasket_nl_kr_query_pairs.json"
    check_sql_query_accuracy(target_json_file)
