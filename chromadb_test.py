import chromadb

# Initialize the ChromaDB client with the same persist_directory
client = chromadb.PersistentClient(path="./chroma_db")

# Get the existing collection
collection = client.get_collection("postgres_schemas")

# Retrieve all documents from the collection
# You can add parameters like where={}, query_texts=[], etc. to filter results
documents = collection.get(include=['documents', 'metadatas'])

print("--- Contents of 'postgres_schemas' collection ---")
if documents and documents['documents']:
    for i, doc_content in enumerate(documents['documents']):
        print(f"Document {i+1}:\n{doc_content}")
        if documents['metadatas'] and documents['metadatas'][i]:
            print(f"Metadata: {documents['metadatas'][i]}\n")
else:
    print("No documents found in 'postgres_schemas' collection.")