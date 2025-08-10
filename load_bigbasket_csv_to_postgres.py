import os
import pandas as pd
import psycopg2
import psycopg2.extras # Added for execute_batch
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def load_bigbasket_data_to_postgres():
    # Database connection parameters from environment variables
    db_name = os.getenv("POSTGRES_DB")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST", "127.0.0.1") # Default to localhost if not set
    db_port = os.getenv("POSTGRES_PORT", "5432") # Default to 5432 if not set

    conn = None
    try:
        # Establish connection
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        cur = conn.cursor()

        # Define table name and schema based on CSV columns
        table_name = "bigbasket_products"
        
        # SQL to create table - adjusted for common data types
        # Assuming 'index' is integer, prices are numeric, rating is float, others are text
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            index INT PRIMARY KEY,
            product TEXT,
            category TEXT,
            sub_category TEXT,
            brand TEXT,
            sale_price NUMERIC,
            market_price NUMERIC,
            type TEXT,
            rating NUMERIC,
            description TEXT
        );
        """
        cur.execute(create_table_sql)
        conn.commit()
        print(f"Table '{table_name}' created or already exists.")

        # Add column descriptions
        column_descriptions = {
            "index": "Unique identifier for each row in the dataset.",
            "product": "Name or title of the product, e.g., 'Tata Tea Premium', 'Kellogg\'s Corn Flakes'.",
            "category": "Top-level category to which the product belongs, e.g., Beverages, Snacks, Fruits & Vegetables.",
            "sub_category": "Subcategory under the main category, e.g., Tea, Chips, Apples.",
            "brand": "Brand name of the product, e.g., Tata, Kellogg\'s, Haldiram.",
            "sale_price": "The current selling price of the product on the website, including any discounts.",
            "market_price": "The regular or market price of the product before any discounts.",
            "type": "Type or classification of the product, e.g., Packaged, Fresh, Organic.",
            "rating": "Average customer rating for the product on a scale from 0 to 5.",
            "description": "Detailed textual description of the product or dataset entry."
        }

        for column, desc in column_descriptions.items():
            comment_sql = f"COMMENT ON COLUMN {table_name}.{column} IS '{desc.replace("'", "''")}';"
            cur.execute(comment_sql)
            conn.commit()
            print(f"Comment added to column {column}.")

        # Read CSV file
        csv_file_path = "dataset/bigbasket_products.csv"
        df = pd.read_csv(csv_file_path)

        # Convert DataFrame to a list of tuples for insertion
        # Ensure the order of columns matches the table definition
        columns = ["index", "product", "category", "sub_category", "brand", 
                   "sale_price", "market_price", "type", "rating", "description"]
        
        # Replace NaN values with None for database insertion
        df = df.where(pd.notna(df), None)

        # Ensure correct column order and handle potential missing columns by mapping
        data_to_insert = []
        for index, row in df.iterrows():
            row_data = []
            for col in columns:
                row_data.append(row.get(col)) # Use .get() to safely handle missing columns
            data_to_insert.append(tuple(row_data))

        # SQL to insert data
        insert_sql = f"""
        INSERT INTO {table_name} (index, product, category, sub_category, brand, sale_price, market_price, type, rating, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (index) DO NOTHING;
        """

        # Execute batch insert
        psycopg2.extras.execute_batch(cur, insert_sql, data_to_insert)
        conn.commit()
        print(f"Successfully inserted {len(data_to_insert)} rows into '{table_name}'.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    load_bigbasket_data_to_postgres()
