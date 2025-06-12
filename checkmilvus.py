from pymilvus import connections, Collection, list_collections

# ----------- Config ------------
MILVUS_HOST = "localhost"   # Change to your IP or hostname if needed
MILVUS_PORT = "19530"
COLLECTION_NAME = "ticket_details"  # <-- replace with your actual collection name
RECORD_LIMIT = 5
# -------------------------------

# Connect to Milvus
print("🔗 Connecting to Milvus...")
connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)

# List available collections
collections = list_collections()
print(f"📦 Available Collections: {collections}")

if COLLECTION_NAME not in collections:
    print(f"❌ Collection '{COLLECTION_NAME}' not found.")
    exit(1)

# Load collection
collection = Collection(COLLECTION_NAME)
print(f"\n📘 Loaded Collection: {COLLECTION_NAME}")
print("📄 Schema Fields:")
for field in collection.schema.fields:
    print(f"  - {field.name} ({field.dtype})")

# Load data into memory
collection.load()

# Query and show the first few records
print(f"\n🔍 Fetching first {RECORD_LIMIT} records...")
results = collection.query(
    expr="",  # no filter
    output_fields=[field.name for field in collection.schema.fields],
    limit=RECORD_LIMIT
)

print("\n📊 Sample Records:")
for record in results:
    print(record)

# Optionally release the collection
collection.release()
