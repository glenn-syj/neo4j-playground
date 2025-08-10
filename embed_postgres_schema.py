import os
import psycopg2
from dotenv import load_dotenv
from typing import List, Any, Dict

from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document

# Load environment variables from .env file
load_dotenv()

# Constants for embedding
GEMINI_EMBEDDING_MODEL = "models/embedding-001"

def prepare_schema_documents(table_name: str, sample_limit: int = 5) -> List[Document]:
    """
    Extracts schema and sample data for a given table and prepares it as a list of Document objects,
    with each column as a separate document.
    """
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    conn = None
    documents = []
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        # Get table comment (if available)
        table_comment_query = f"""
        SELECT
            obj_description('{table_name}'::regclass, 'pg_class') AS table_comment;
        """
        cur.execute(table_comment_query)
        table_comment = cur.fetchone()[0]

        # Table-level document
        table_content = f"Table: {table_name}"
        if table_comment:
            table_content += f"\nDescription: {table_comment}"
        documents.append(Document(
            page_content=table_content,
            metadata={"source": "postgres_table_schema", "table_name": table_name, "type": "table_overview"}
        ))

        # Get column names, data types, and comments
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
            return []

        column_names = [col[0] for col in columns_metadata]

        # Get sample data for all columns to distribute per column document
        sample_data_query = f"SELECT {', '.join(column_names)} FROM {table_name} LIMIT {sample_limit};"
        cur.execute(sample_data_query)
        sample_rows = cur.fetchall()

        # Create a document for each column
        for i, (col_name, data_type, col_comment) in enumerate(columns_metadata):
            col_doc_content = f"Table: {table_name}\nColumn: {col_name}\nData Type: {data_type}"
            comment_display = col_comment if col_comment else "(No comment)"
            col_doc_content += f"\nComment: {comment_display}"

            # Add sample data for this specific column if available
            column_sample_values = []
            if sample_rows:
                for row in sample_rows:
                    if i < len(row):
                        column_sample_values.append(str(row[i]))
                if column_sample_values:
                    col_doc_content += f"\nSample Values: {', '.join(column_sample_values[:5])}" # Limit to 5 samples

            documents.append(Document(
                page_content=col_doc_content,
                metadata={"source": "postgres_column_schema", "table_name": table_name, "column_name": col_name, "type": "column_detail"}
            ))

    except Exception as e:
        print(f"An error occurred during schema extraction: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            print("Database connection closed for extraction.")
    return documents

def embed_schema_to_chromadb(table_name: str, documents: List[Document]):
    """
    Embeds the extracted schema Document objects into ChromaDB.
    """
    try:
        google_api_key = os.getenv("GEMINI_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        embeddings = GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL, google_api_key=google_api_key)

        # Initialize ChromaDB with the embedding function and add documents
        vectordb = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            persist_directory="./chroma_db", # Directory to store ChromaDB data
            collection_name="postgres_schemas" # Explicitly set collection name
        )
        vectordb.persist() # Save the database to disk
        print(f"Successfully embedded {len(documents)} schema documents for table '{table_name}' into ChromaDB.")
    except Exception as e:
        print(f"An error occurred during embedding to ChromaDB: {e}")

if __name__ == "__main__":
    target_table_name = "bigbasket_products" # Example table name
    print(f"Preparing schema documents for table: {target_table_name}")
    schema_documents = prepare_schema_documents(target_table_name, sample_limit=5)
    print(f"\n--- Prepared {len(schema_documents)} Schema Documents ---")
    for i, doc in enumerate(schema_documents):
        print(f"Document {i+1} (Type: {doc.metadata.get('type', 'N/A')}):")
        print(f"Content:\n{doc.page_content}")
        print(f"Metadata: {doc.metadata}\n")

    print("\n--- Embedding Schema to ChromaDB ---")
    embed_schema_to_chromadb(target_table_name, schema_documents)
