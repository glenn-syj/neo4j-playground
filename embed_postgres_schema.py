import os
import psycopg2
from dotenv import load_dotenv
from typing import Dict, Any

from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document

# Load environment variables from .env file
load_dotenv()

# Constants for embedding
GEMINI_EMBEDDING_MODEL = "models/embedding-001"
EMBEDDING_DIMENSION = 768  # As identified from the web search for Gemini embedding-001

def extract_table_info_as_string(table_name: str, sample_limit: int = 5) -> str:
    """
    Extracts schema and sample data for a given table and returns it as a formatted string.
    Reuses the logic from extract_postgres_schema.py.
    """
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    conn = None
    schema_info = []
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        schema_info.append(f"--- Table: {table_name} ---")

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
            schema_info.append(f"Table '{table_name}' not found or has no columns.")
            return "\n".join(schema_info)

        column_names = [col[0] for col in columns_metadata]

        schema_info.append("\nColumn Details:")
        for col_name, data_type, col_comment in columns_metadata:
            comment_display = col_comment if col_comment else "(No comment)"
            schema_info.append(f"  - {col_name} ({data_type}): {comment_display}")

        # 2. Get sample data
        schema_info.append(f"\nSample Data (first {sample_limit} rows):")
        sample_data_query = f"SELECT {', '.join(column_names)} FROM {table_name} LIMIT {sample_limit};"
        cur.execute(sample_data_query)
        sample_rows = cur.fetchall()

        if not sample_rows:
            schema_info.append("  No sample data available.")
        else:
            header = " | ".join(column_names)
            schema_info.append(f"  {header}")
            schema_info.append(f"  {'---' * len(column_names)}")
            for row in sample_rows:
                row_str = " | ".join(str(item) for item in row)
                schema_info.append(f"  {row_str}")

    except Exception as e:
        schema_info.append(f"An error occurred during schema extraction: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            schema_info.append("\nDatabase connection closed for extraction.")
    return "\n".join(schema_info)

def embed_schema_to_chromadb(table_name: str, schema_string: str):
    """
    Embeds the extracted schema string into ChromaDB.
    """
    try:
        # Initialize GoogleGenerativeAIEmbeddings with the specified model
        google_api_key = os.getenv("GEMINI_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        embeddings = GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL, google_api_key=google_api_key)

        # Create a Document object from the schema string
        # You might want to add more metadata here, e.g., source table, timestamp
        document = Document(
            page_content=schema_string,
            metadata={"source": "postgres_schema_extraction", "table_name": table_name}
        )

        # Initialize ChromaDB with the embedding function
        # ChromaDB will create a persistent collection if it doesn't exist
        # The collection name could be dynamic, e.g., based on database name or purpose
        # We'll use a simple "postgres_schemas" collection for this example
        vectordb = Chroma.from_documents(
            documents=[document],
            embedding=embeddings,
            persist_directory="./chroma_db", # Directory to store ChromaDB data
            collection_name="postgres_schemas" # Explicitly set collection name
        )
        vectordb.persist() # Save the database to disk
        print(f"Successfully embedded schema for table '{table_name}' into ChromaDB.")
    except Exception as e:
        print(f"An error occurred during embedding to ChromaDB: {e}")

if __name__ == "__main__":
    target_table_name = "bigbasket_products" # Example table name
    print(f"Extracting schema for table: {target_table_name}")
    schema_content = extract_table_info_as_string(target_table_name, sample_limit=5)
    print("\n--- Extracted Schema Content ---")
    print(schema_content)
    print("\n--- Embedding Schema to ChromaDB ---")
    embed_schema_to_chromadb(target_table_name, schema_content)
