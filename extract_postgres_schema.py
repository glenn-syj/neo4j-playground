import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def extract_table_info(table_name, sample_limit=5):
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    conn = None
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        print(f"--- Table: {table_name} ---")

        # 1. Get column names, data types, and comments
        column_info_query = f"""
        SELECT
            c.column_name,
            c.data_type,
            pgd.description as column_comment
        FROM
            information_schema.columns c
        LEFT JOIN
            pg_catalog.pg_statio_all_tables as st
            ON c.table_schema = st.schemaname AND c.table_name = st.relname
        LEFT JOIN
            pg_catalog.pg_description pgd
            ON pgd.objoid = st.relid
            AND pgd.objsubid = c.ordinal_position
        WHERE
            c.table_schema = 'public' AND c.table_name = '{table_name}'
        ORDER BY
            c.ordinal_position;
        """
        cur.execute(column_info_query)
        columns_metadata = cur.fetchall()

        if not columns_metadata:
            print(f"Table '{table_name}' not found or has no columns.")
            return

        column_names = [col[0] for col in columns_metadata]

        # Print column name, data type and comment
        print("\nColumn Details:")
        for col_name, data_type, col_comment in columns_metadata:
            comment_display = col_comment if col_comment else "(No comment)"
            print(f"  - {col_name} ({data_type}): {comment_display}")

        # 2. Get sample data
        print(f"\nSample Data (first {sample_limit} rows):")
        sample_data_query = f"SELECT {', '.join(column_names)} FROM {table_name} LIMIT {sample_limit};"
        cur.execute(sample_data_query)
        sample_rows = cur.fetchall()

        if not sample_rows:
            print("  No sample data available.")
        else:
            # Print header
            header = " | ".join(column_names)
            print(f"  {header}")
            print(f"  {'---' * len(column_names)}") # Separator

            # Print rows
            for row in sample_rows:
                row_str = " | ".join(str(item) for item in row)
                print(f"  {row_str}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            print("\nDatabase connection closed.")

if __name__ == "__main__":
    target_table_name = "bigbasket_products" # Replace with your table name
    extract_table_info(target_table_name, sample_limit=5)