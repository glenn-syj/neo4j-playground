import os
import json
import psycopg2
from dotenv import load_dotenv

from chromadb.utils import embedding_functions
import chromadb
from neo4j import GraphDatabase
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import List, Dict, Any, Tuple, Optional

# Load environment variables from .env file
load_dotenv()

# --- Configuration --- #
# PostgreSQL
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Gemini LLM
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

# ChromaDB
CHROMA_PERSIST_DIRECTORY = "./chroma_db"
CHROMA_COLLECTION_NAME = "postgres_schemas"
GEMINI_EMBEDDING_MODEL = "models/embedding-001"

# --- Client Initializations --- #
# ChromaDB Embedding Function (must match the one used during embedding)
# Use ChromaDB's own GoogleGenerativeAIEmbeddingFunction for direct client usage
chroma_embedding_function = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
    api_key=GEMINI_API_KEY, model_name=GEMINI_EMBEDDING_MODEL
)

# ChromaDB Client
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIRECTORY)
chroma_collection = chroma_client.get_or_create_collection(
    name=CHROMA_COLLECTION_NAME,
    embedding_function=chroma_embedding_function
)

# Neo4j Driver
neo4j_driver = None
try:
    neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    neo4j_driver.verify_connectivity()
    print("Successfully connected to Neo4j.")
except Exception as e:
    print(f"Could not connect to Neo4j: {e}")
    neo4j_driver = None

# Gemini LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=GEMINI_API_KEY)
output_parser = StrOutputParser()

# --- RAG Functions --- #
def retrieve_schema_from_chromadb(query: str, n_results: int = 5) -> str:
    """
    Retrieves relevant schema documents from ChromaDB based on the natural language query.
    """
    try:
        results = chroma_collection.query(
            query_texts=[query],
            n_results=n_results,
            include=['documents', 'metadatas']
        )
        retrieved_docs = []
        if results and results['documents']:
            for i, doc_content in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] and results['metadatas'][0] else {}
                retrieved_docs.append(f"Document Content:\n{doc_content}\nMetadata: {json.dumps(metadata)}")
        return "\n\n".join(retrieved_docs) if retrieved_docs else "No relevant schema information found in ChromaDB."
    except Exception as e:
        return f"Error retrieving from ChromaDB: {e}"

def retrieve_graph_context_from_neo4j(tables_and_columns: List[str]) -> str:
    """
    Queries Neo4j for relationships involving the identified tables/columns.
    This is a basic example; more sophisticated queries could be built based on specific needs.
    """
    if not neo4j_driver:
        return "Neo4j driver not initialized. Skipping graph context retrieval."

    graph_context = []
    try:
        with neo4j_driver.session() as session:
            # Query for relationships involving the identified tables/columns
            # This query assumes nodes are labeled :Table and :Column with a 'name' property
            # And relationships like :HAS_COLUMN, :CATEGORIZES
            query = """
            MATCH (n)-[r]->(m)
            WHERE n.name IN $names OR m.name IN $names
            RETURN n.name, type(r), m.name
            LIMIT 30
            """
            parameters = {"names": tables_and_columns}
            results = session.run(query, parameters)

            for record in results:
                graph_context.append(f"Relationship: {record[0]} -[{record[1]}]-> {record[2]}")

        return "\n".join(graph_context) if graph_context else "No relevant graph relationships found in Neo4j."
    except Exception as e:
        return f"Error retrieving from Neo4j: {e}"

def generate_sql_with_llm(nl_query: str, schema_context: str, graph_context: str, chat_model: ChatGoogleGenerativeAI) -> str:
    """
    Generates a SQL query using LLM based on NL query, schema, and graph context.
    """
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant that translates natural language questions into PostgreSQL SQL queries.\n"+
                   "Use the provided database schema context and graph relationships to generate accurate SQL. "+
                   "For any aggregation on numeric columns (e.g., AVG, SUM, COUNT), always use NULLIF(column_name, 'NaN'::numeric) to exclude NaN values and ensure only valid numbers are processed.\n"+
                   "Only output the SQL query, no other text or explanations. Do not wrap the SQL query in markdown code blocks."+
                   "When creating the SQL query, you need to return the proper name of the record, too."
                   "If the query is not possible, return 'No relevant data found.'"),
        ("user", "Natural Language Query: {nl_query}\n\n"+
                 "Database Schema Context (from ChromaDB):\n{schema_context}\n\n"+
                 "Graph Relationships (from Neo4j):\n{graph_context}\n\n"+
                 "Generate the PostgreSQL SQL query:")
    ])

    chain = prompt_template | chat_model | output_parser
    sql_query = chain.invoke({
        "nl_query": nl_query,
        "schema_context": schema_context,
        "graph_context": graph_context
    })
    return sql_query.strip()

def execute_sql_query_on_postgres(sql_query: str) -> Tuple[bool, str, Optional[List[Tuple]]]:
    """
    Executes a given SQL query on the PostgreSQL database.
    Returns (success, message, results_if_select).
    """
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT
        )
        cur = conn.cursor()
        conn.autocommit = True

        cur.execute(sql_query)

        if sql_query.strip().upper().startswith(("SELECT", "WITH")):
            results = cur.fetchall()
            return True, "Query executed successfully.", results
        else:
            return True, "Non-SELECT query executed successfully.", None

    except psycopg2.Error as e:
        return False, f"PostgreSQL Error: {e}", None
    except Exception as e:
        return False, f"General execution error: {e}", None
    finally:
        if conn:
            cur.close()
            conn.close()

def answer_question_with_graph_rag(nl_query: str) -> Dict[str, Any]:
    """
    Main function to answer a natural language question using Graph RAG.
    """
    print(f"\n--- Answering: '{nl_query}' ---")

    # Step 1: Retrieve schema context from ChromaDB
    print("Retrieving schema context from ChromaDB...")
    schema_context = retrieve_schema_from_chromadb(nl_query)
    print("ChromaDB Context:\n"+schema_context)

    # Extract potential table/column names from NL query for Neo4j context (simple approach for now)
    # A more robust solution might parse ChromaDB results for specific entities
    potential_entities = [word.lower() for word in nl_query.replace('모든','').replace('알려주세요','').replace('무엇인가요','').replace('무엇인가요','').split()]
    # Add known table/column names if they are generally relevant
    known_schema_elements = ["bigbasket_products", "category", "sub_category", "product", "sale_price", "market_price", "rating", "brand", "description", "type"]
    entities_for_neo4j = list(set(potential_entities + known_schema_elements))

    # Step 2: Retrieve graph context from Neo4j
    print("\nRetrieving graph context from Neo4j...")
    graph_context = retrieve_graph_context_from_neo4j(entities_for_neo4j)
    print("Neo4j Context:\n"+graph_context)

    # Step 3: Generate SQL with LLM
    print("\nGenerating SQL query with LLM...")
    generated_sql = generate_sql_with_llm(nl_query, schema_context, graph_context, llm)
    print(f"Generated SQL:\n{generated_sql}")

    # Step 4: Execute SQL on PostgreSQL
    print("\nExecuting SQL on PostgreSQL...")
    success, message, results = execute_sql_query_on_postgres(generated_sql)

    response = {
        "nl_query": nl_query,
        "generated_sql": generated_sql,
        "sql_execution_success": success,
        "sql_execution_message": message,
        "sql_results": results
    }

    if success and results is not None:
        print("\nSQL Execution Results:")
        for row in results:
            print(row)
    elif success and results is None:
        print("\nSQL Execution Results: No data to display (Non-SELECT query).")
    else:
        print(f"\nSQL Execution Failed: {message}")

    return response

if __name__ == "__main__":
    # Example Usage
    # Make sure your PostgreSQL and Neo4j containers are running
    # And your ChromaDB has been populated with schema embeddings (run embed_postgres_schema.py first)

    # Example 2: Query involving rating and aggregation
    # (Requires proper handling of NaN/NULL ratings in DB as discussed previously)
    # answer_question_with_graph_rag("Beauty & Hygiene 카테고리 내에서 각 서브 카테고리별 평균 평점은 얼마인가요?")

    answer_question_with_graph_rag("평점이 3.5 이상인 제품 중에서 20% 이상 할인하는 제품들이 속하는 카테고리가 어디에 속하는지 각각의 비율을 알려주세요.")

