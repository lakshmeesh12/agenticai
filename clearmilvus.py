from pymilvus import Collection, CollectionSchema, FieldSchema, DataType, connections, utility

# Connect to Milvus
connections.connect(host="localhost", port="19530")

# Drop existing collection if it exists
if utility.has_collection("ticket_details"):
    utility.drop_collection("ticket_details")
    print("Dropped old collection")

# Define schema
schema = CollectionSchema([
    FieldSchema("ado_ticket_id", DataType.INT64, is_primary=True),
    FieldSchema("ticket_title", DataType.VARCHAR, max_length=512),
    FieldSchema("ticket_description", DataType.VARCHAR, max_length=4096),
    FieldSchema("updates", DataType.VARCHAR, max_length=8192),
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=384)
])

# Create new empty collection
collection = Collection("ticket_details", schema)
print("Recreated empty collection")

# Disconnect properly
connections.disconnect(alias="default")
