import os
import psycopg2
from dotenv import load_dotenv
from neo4j import GraphDatabase
from typing import Dict, List, Any

# Load environment variables from .env file
load_dotenv()

# Neo4j Connection Details
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

def extract_table_schema_for_graph_import(table_name: str) -> Dict[str, Any]:
    """
    Connects to PostgreSQL and extracts schema information for a given table,
    returning it as a structured dictionary.
    """
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    conn = None
    schema_data = {
        "table_name": table_name,
        "table_comment": None,
        "columns": []
    }
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        # Get table comment
        table_comment_query = f"""
        SELECT
            obj_description('{table_name}'::regclass, 'pg_class') AS table_comment;
        """
        cur.execute(table_comment_query)
        schema_data["table_comment"] = cur.fetchone()[0]

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
            print(f"Error: Table '{table_name}' not found or has no columns.")
            return None

        for col_name, data_type, col_comment in columns_metadata:
            schema_data["columns"].append({
                "column_name": col_name,
                "data_type": data_type,
                "column_comment": col_comment
            })

    except Exception as e:
        print(f"Error extracting schema from PostgreSQL: {e}")
        return None
    finally:
        if conn:
            cur.close()
            conn.close()
            print("Database connection closed for schema extraction.")
    return schema_data

def create_schema_graph_in_neo4j(schema_data: Dict[str, Any]):
    """
    Connects to Neo4j and creates nodes and relationships based on the extracted schema data.
    """
    if not schema_data:
        print("No schema data provided to create graph.")
        return

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        with driver.session() as session:
            # 1. Create Table Node
            table_name = schema_data["table_name"]
            table_comment = schema_data["table_comment"]
            table_props = {"name": table_name}
            if table_comment:
                table_props["comment"] = table_comment

            session.run(
                "MERGE (t:Table {name: $name}) SET t += $props",
                name=table_name, props=table_props
            )
            print(f"Created/Merged Table node: {table_name}")

            # 2. Create Column Nodes and HAS_COLUMN relationships
            for col in schema_data["columns"]:
                col_name = col["column_name"]
                data_type = col["data_type"]
                col_comment = col["column_comment"]

                col_props = {"name": col_name, "type": data_type}
                if col_comment:
                    col_props["comment"] = col_comment

                session.run(
                    "MERGE (c:Column {name: $col_name}) SET c += $props",
                    col_name=col_name, props=col_props
                )
                session.run(
                    "MATCH (t:Table {name: $table_name}) MATCH (c:Column {name: $col_name}) MERGE (t)-[:HAS_COLUMN]->(c)",
                    table_name=table_name, col_name=col_name
                )
                print(f"Created/Merged Column node: {col_name} and HAS_COLUMN relationship.")

            # 3. Create CATEGORIZES relationship between category and sub_category
            if any(c["column_name"] == 'category' for c in schema_data["columns"]) and \
               any(c["column_name"] == 'sub_category' for c in schema_data["columns"]):
                session.run(
                    "MATCH (cat:Column {name: 'category'}) MATCH (subcat:Column {name: 'sub_category'}) MERGE (cat)-[:CATEGORIZES]->(subcat)"
                )
                print("Created CATEGORIZES relationship between category and sub_category.")

    except Exception as e:
        print(f"Error connecting to or writing to Neo4j: {e}")
    finally:
        if driver:
            driver.close()
            print("Neo4j connection closed.")

if __name__ == "__main__":
    target_table = "bigbasket_products"
    print(f"Extracting schema for table: {target_table} from PostgreSQL...")
    schema_data = extract_table_schema_for_graph_import(target_table)

    if schema_data:
        print(f"\nCreating graph for schema in Neo4j for table: {target_table}...")
        create_schema_graph_in_neo4j(schema_data)
    else:
        print("Schema extraction failed. Cannot create graph in Neo4j.")
