import asyncio
import json
import logging
import uuid
from typing import Dict, List, Optional
from datetime import datetime
import os
import requests
from bson import ObjectId
from dotenv import load_dotenv
from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import PyMongoError
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, Range
from qdrant_client.http.models import Filter, FieldCondition, Range, MatchValue, MatchAny, MatchText, PointsSelector, PointIdsList
from typing import Dict, List, Optional, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
OPEN_AI_KEY = os.getenv("OPEN_AI_KEY")
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "tickets"
SYNC_METADATA_COLLECTION = "sync_metadata"
SERVICENOW_COLLECTION = "servicenow"
SERVICENOW_INSTANCE_URL = os.getenv("SERVICENOW_INSTANCE_URL")
SERVICENOW_CLIENT_ID = os.getenv("SERVICENOW_CLIENT_ID")
SERVICENOW_CLIENT_SECRET = os.getenv("SERVICENOW_CLIENT_SECRET")
SERVICENOW_USERNAME = os.getenv("SERVICENOW_USERNAME")
SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD")

class QdrantManager:
    def __init__(self, tickets_collection: AsyncIOMotorCollection, sync_metadata_collection: AsyncIOMotorCollection):
        self.tickets_collection = tickets_collection
        self.sync_metadata_collection = sync_metadata_collection
        self.qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
        self.openai_client = AsyncOpenAI(api_key=OPEN_AI_KEY)
        self.collection_name = COLLECTION_NAME
        self.servicenow_collection = SERVICENOW_COLLECTION

    def serialize_document(self, document: Dict) -> Dict:
        def convert_value(value):
            if isinstance(value, ObjectId):
                return str(value)
            elif isinstance(value, dict):
                return {k: convert_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [convert_value(item) for item in value]
            elif isinstance(value, datetime):
                return value.isoformat()
            return value
        return convert_value(document)

    async def initialize_collection(self, collection_name: str = None) -> None:
        try:
            collection_name = collection_name or self.collection_name
            collections = await self.qdrant_client.get_collections()
            collection_names = [c.name for c in collections.collections]
            if collection_name not in collection_names:
                logger.info(f"Creating Qdrant collection: {collection_name}")
                await self.qdrant_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
                )
                logger.info(f"Collection {collection_name} created successfully")
            else:
                logger.info(f"Collection {collection_name} already exists")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection {collection_name}: {str(e)}")
            raise

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = await self.openai_client.embeddings.create(
                input=text[:8192],
                model="text-embedding-3-large"
            )
            embedding = response.data[0].embedding
            logger.info(f"Generated embedding for text (length {len(text)}): {text[:50]}...")
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            return None

    async def upsert_document(self, document: Dict, collection_name: str = None) -> bool:
        try:
            collection_name = collection_name or self.collection_name
            if "_id" not in document and "sys_id" not in document:
                logger.error("Document missing '_id' or 'sys_id' field")
                return False

            key_fields = [
                str(document.get("ado_ticket_id", document.get("sys_id", ""))),
                document.get("number", ""),
                document.get("short_description", ""),
                document.get("description", ""),
                document.get("state", ""),
                " ".join([u.get("value", "") for u in document.get("work_notes", []) if u.get("value")]),
                " ".join([c.get("value", "") for c in document.get("comments", []) if c.get("value")])
            ]
            text_for_embedding = " ".join([f for f in key_fields if f]).strip()
            if not text_for_embedding:
                logger.error(f"No valid text for embedding for document {document.get('_id', document.get('sys_id', 'unknown'))}")
                return False
            logger.info(f"Text for embedding (doc {document.get('_id', document.get('sys_id', 'unknown'))}): {text_for_embedding[:100]}...")

            serialized_doc = self.serialize_document(document)
            doc_id = serialized_doc.get("_id", serialized_doc.get("sys_id"))
            mapping = await self.sync_metadata_collection.find_one({"mongo_id": doc_id, "collection": collection_name})
            qdrant_id = str(uuid.uuid4()) if not mapping else mapping["qdrant_id"]

            embedding = await self.generate_embedding(text_for_embedding)
            if not embedding:
                logger.error(f"Failed to generate embedding for document {doc_id}")
                return False
            logger.info(f"Generated embedding for {doc_id}, length: {len(embedding)}")

            point = PointStruct(
                id=qdrant_id,
                vector=embedding,
                payload=serialized_doc
            )

            upsert_result = await self.qdrant_client.upsert(
                collection_name=collection_name,
                points=[point]
            )
            logger.info(f"Upsert result: {upsert_result}")

            await self.sync_metadata_collection.update_one(
                {"mongo_id": doc_id, "collection": collection_name},
                {"$set": {"qdrant_id": qdrant_id, "collection": collection_name}},
                upsert=True
            )

            logger.info(f"Upserted document {doc_id} to Qdrant collection {collection_name} with ID {qdrant_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to upsert document {document.get('_id', document.get('sys_id', 'unknown'))} in {collection_name}: {str(e)}")
            return False

    async def delete_document(self, mongo_id: str, collection_name: str = None) -> bool:
        try:
            collection_name = collection_name or self.collection_name
            mapping = await self.sync_metadata_collection.find_one({"mongo_id": mongo_id, "collection": collection_name})
            if not mapping:
                logger.warning(f"No Qdrant ID mapping found for MongoDB ID {mongo_id} in {collection_name}")
                return False
            qdrant_id = mapping["qdrant_id"]

            await self.qdrant_client.delete(
                collection_name=collection_name,
                points_selector=[qdrant_id]
            )
            await self.sync_metadata_collection.delete_one({"mongo_id": mongo_id, "collection": collection_name})
            logger.info(f"Deleted document {mongo_id} from Qdrant collection {collection_name} with ID {qdrant_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {mongo_id} in {collection_name}: {str(e)}")
            return False

    async def sync_existing_documents(self) -> None:
        try:
            cursor = self.tickets_collection.find()
            count = 0
            async for doc in cursor:
                success = await self.upsert_document(doc)
                if success:
                    count += 1
                logger.info(f"Processed document {doc.get('_id')}, Success: {success}")
            logger.info(f"Synced {count} documents to Qdrant")
        except PyMongoError as e:
            logger.error(f"Failed to sync existing documents: {str(e)}")
            raise

    async def sync_servicenow_incidents(self) -> Dict:
        try:
            auth_url = f"{SERVICENOW_INSTANCE_URL}/oauth_token.do"
            auth_data = {
                "grant_type": "password",
                "client_id": SERVICENOW_CLIENT_ID,
                "client_secret": SERVICENOW_CLIENT_SECRET,
                "username": SERVICENOW_USERNAME,
                "password": SERVICENOW_PASSWORD
            }
            auth_response = requests.post(auth_url, data=auth_data)
            if auth_response.status_code != 200:
                logger.error(f"ServiceNow authentication failed: {auth_response.text}")
                return {"status": "error", "message": "ServiceNow authentication failed", "synced": 0}
            access_token = auth_response.json().get("access_token")
            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

            await self.initialize_collection(self.servicenow_collection)

            incidents_url = f"{SERVICENOW_INSTANCE_URL}/api/now/table/incident"
            params = {"sysparm_limit": 1000, "sysparm_offset": 0}
            all_incidents = []
            while True:
                response = requests.get(incidents_url, headers=headers, params=params)
                if response.status_code != 200:
                    logger.error(f"Failed to fetch incidents: {response.text}")
                    return {"status": "error", "message": "Failed to fetch incidents", "synced": 0}
                incidents = response.json().get("result", [])
                all_incidents.extend(incidents)
                if len(incidents) < params["sysparm_limit"]:
                    break
                params["sysparm_offset"] += params["sysparm_limit"]

            synced_count = 0
            for incident in all_incidents:
                sys_id = incident.get("sys_id")
                work_notes_url = f"{SERVICENOW_INSTANCE_URL}/api/now/table/sys_journal_field?sysparm_query=element=work_notes^element_id={sys_id}"
                work_notes_response = requests.get(work_notes_url, headers=headers)
                work_notes = work_notes_response.json().get("result", []) if work_notes_response.status_code == 200 else []
                incident["work_notes"] = work_notes

                comments_url = f"{SERVICENOW_INSTANCE_URL}/api/now/table/sys_journal_field?sysparm_query=element=comments^element_id={sys_id}"
                comments_response = requests.get(comments_url, headers=headers)
                comments = comments_response.json().get("result", []) if comments_response.status_code == 200 else []
                incident["comments"] = comments

                success = await self.upsert_document(incident, collection_name=self.servicenow_collection)
                if success:
                    synced_count += 1
                logger.info(f"Processed incident {sys_id}, Success: {success}")

            logger.info(f"Synced {synced_count} ServiceNow incidents to Qdrant collection {self.servicenow_collection}")
            return {"status": "success", "message": f"Synced {synced_count} incidents", "synced": synced_count}
        except Exception as e:
            logger.error(f"Failed to sync ServiceNow incidents: {str(e)}")
            return {"status": "error", "message": str(e), "synced": 0}

    def _construct_filter(self, key: str, value: Any) -> Optional[FieldCondition]:
        """Enhanced filter construction with better type handling and error recovery."""
        try:
            if isinstance(value, dict):
                # Handle array operations
                if "$in" in value:
                    return FieldCondition(key=key, match=MatchAny(any=value["$in"]))
                
                # Handle range operations with proper type conversion
                if any(op in value for op in ["$gte", "$lte", "$gt", "$lt"]):
                    range_params = {}
                    for op, val in value.items():
                        if op == "$gte":
                            range_params["gte"] = self._convert_to_number(val)
                        elif op == "$lte":
                            range_params["lte"] = self._convert_to_number(val)
                        elif op == "$gt":
                            range_params["gt"] = self._convert_to_number(val)
                        elif op == "$lt":
                            range_params["lt"] = self._convert_to_number(val)
                    
                    # Only create range if we have valid numeric values
                    if any(v is not None for v in range_params.values()):
                        return FieldCondition(key=key, range=Range(**range_params))
                
                # Handle text search
                if "$text" in value:
                    return FieldCondition(key=key, match=MatchText(text=value["$text"]))
                
                # Handle contains operation for partial string matching
                if "$contains" in value:
                    # Use text search for substring matching
                    return FieldCondition(key=key, match=MatchText(text=value["$contains"]))
                    
            elif isinstance(value, (str, int, bool, float)):
                return FieldCondition(key=key, match=MatchValue(value=value))
            
            elif isinstance(value, list):
                # If a list is provided directly, treat as $in operation
                return FieldCondition(key=key, match=MatchAny(any=value))
                
        except Exception as e:
            logger.warning(f"Failed to construct filter for {key}={value}: {str(e)}")
        
        return None

    def _convert_to_number(self, value: Any) -> Optional[float]:
        """Convert various input types to numbers, with special handling for dates."""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Try to parse as ISO date first
            if "T" in value and ("Z" in value or "+" in value):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return dt.timestamp()  # Convert to Unix timestamp
                except:
                    pass
            
            # Try to parse as regular number
            try:
                return float(value)
            except ValueError:
                pass
        
        return None

    async def search_qdrant(self, query: str, limit: int = 5, filters: Optional[Dict] = None, 
                        collection_name: str = "servicenow", score_threshold: float = 0.3) -> List[Dict]:
        """
        Enhanced search with better error handling and multiple fallback strategies.
        """
        try:
            collection_name = collection_name or self.servicenow_collection
            query_embedding = await self.generate_embedding(query)
            if not query_embedding:
                logger.error(f"Failed to generate embedding for query: {query}")
                return []

            # Build Qdrant filter with enhanced error handling
            qdrant_filter_conditions = {}
            if filters:
                for condition_type in ["must", "should", "must_not"]:
                    if condition_type in filters:
                        conditions = []
                        for f in filters[condition_type]:
                            for key, value in f.items():
                                condition = self._construct_filter(key, value)
                                if condition:
                                    conditions.append(condition)
                                else:
                                    logger.warning(f"Skipped invalid filter: {key}={value}")
                        
                        if conditions:
                            qdrant_filter_conditions[condition_type] = conditions
            
            qdrant_filter = Filter(**qdrant_filter_conditions) if qdrant_filter_conditions else None
            logger.info(f"Applying Qdrant filter: {qdrant_filter}")

            # Primary search
            search_result = await self.qdrant_client.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold
            )

            results = [{"payload": point.payload, "score": point.score} for point in search_result]
            logger.info(f"Retrieved {len(results)} results for query: '{query}' in {collection_name}")
            
            # If no results with filters, try without filters (fallback)
            if len(results) == 0 and qdrant_filter:
                logger.info("No results with filters, trying without filters...")
                fallback_result = await self.qdrant_client.search(
                    collection_name=collection_name,
                    query_vector=query_embedding,
                    limit=limit,
                    with_payload=True,
                    score_threshold=max(0.2, score_threshold - 0.1)  # Lower threshold for fallback
                )
                results = [{"payload": point.payload, "score": point.score} for point in fallback_result]
                logger.info(f"Fallback search retrieved {len(results)} results")
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to search Qdrant in {collection_name}: {str(e)}")
            return []

    async def multi_query_search(self, queries: List[str], limit: int = 3, 
                            filters: Optional[Dict] = None, 
                            collection_name: str = "servicenow") -> List[Dict]:
        """
        Search with multiple query variations to improve recall.
        """
        all_results = []
        seen_ids = set()
        
        for query in queries[:3]:  # Limit to 3 queries to avoid overload
            try:
                results = await self.search_qdrant(
                    query=query,
                    limit=limit,
                    filters=filters,
                    collection_name=collection_name
                )
                
                # Deduplicate based on incident number or document ID
                for result in results:
                    doc_id = (result["payload"].get("number") or 
                            result["payload"].get("_id") or 
                            str(result["payload"])[:50])
                    
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        result["query_used"] = query  # Track which query found this
                        all_results.append(result)
                
            except Exception as e:
                logger.warning(f"Query failed: {query} - {str(e)}")
        
        # Sort by score descending
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:limit * 2]  # Return top results across all queries

    async def adaptive_search(self, query: str, filters: Optional[Dict] = None,
                            collection_name: str = "servicenow") -> List[Dict]:
        """
        Adaptive search that adjusts strategy based on query characteristics.
        """
        results = []
        
        # Strategy 1: Exact match for incident numbers
        incident_pattern = r'INC\d+'
        import re
        incident_matches = re.findall(incident_pattern, query, re.IGNORECASE)
        
        if incident_matches:
            logger.info(f"Found incident numbers: {incident_matches}")
            for inc_num in incident_matches:
                exact_filters = {"must": [{"number": inc_num.upper()}]}
                exact_results = await self.search_qdrant(
                    query=f"incident {inc_num}",
                    limit=5,
                    filters=exact_filters,
                    collection_name=collection_name,
                    score_threshold=0.1  # Very low threshold for exact matches
                )
                results.extend(exact_results)
        
        # Strategy 2: Multi-query semantic search
        if len(results) < 3:
            # Generate query variations
            query_variations = await self._generate_query_variations(query)
            semantic_results = await self.multi_query_search(
                queries=query_variations,
                limit=3,
                filters=filters,
                collection_name=collection_name
            )
            results.extend(semantic_results)
        
        # Strategy 3: Broad search with relaxed filters
        if len(results) < 2:
            # Remove some filters for broader search
            relaxed_filters = self._relax_filters(filters) if filters else None
            broad_results = await self.search_qdrant(
                query=query,
                limit=5,
                filters=relaxed_filters,
                collection_name=collection_name,
                score_threshold=0.2
            )
            results.extend(broad_results)
        
        # Deduplicate and return
        return self._deduplicate_results(results)

    async def _generate_query_variations(self, query: str) -> List[str]:
        """Generate semantic variations of the query for better matching."""
        variations = [query]  # Always include original
        
        # Simple keyword-based variations
        if "work notes" in query.lower():
            variations.extend([
                query.replace("work notes", "activity"),
                query.replace("work notes", "comments"),
                query.replace("work notes", "updates")
            ])
        
        if "sla" in query.lower():
            variations.extend([
                query.replace("sla", "service level agreement"),
                query + " deadline",
                query + " response time"
            ])
        
        if "database" in query.lower():
            variations.extend([
                query.replace("database", "DB"),
                query.replace("database", "data"),
                query + " connection"
            ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for var in variations:
            if var not in seen:
                seen.add(var)
                unique_variations.append(var)
        
        return unique_variations[:5]  # Limit variations

    def _relax_filters(self, filters: Dict) -> Optional[Dict]:
        """Create a more permissive version of filters for broader search."""
        if not filters:
            return None
        
        relaxed = {}
        
        # Convert some 'must' conditions to 'should' for broader matching
        if "must" in filters:
            must_conditions = []
            should_conditions = []
            
            for condition in filters["must"]:
                # Keep exact matches (like incident numbers) in must
                if any(key in condition for key in ["number", "sys_id"]):
                    must_conditions.append(condition)
                else:
                    # Move other conditions to should for optional matching
                    should_conditions.append(condition)
            
            if must_conditions:
                relaxed["must"] = must_conditions
            if should_conditions:
                relaxed["should"] = should_conditions
        
        # Keep other filter types as-is
        for key in ["should", "must_not"]:
            if key in filters:
                relaxed[key] = filters[key]
        
        return relaxed if relaxed else None

    def _deduplicate_results(self, results: List[Dict]) -> List[Dict]:
        """Remove duplicate results based on document identity."""
        seen_ids = set()
        unique_results = []
        
        for result in results:
            # Create a unique identifier for the document
            payload = result["payload"]
            doc_id = (payload.get("number") or 
                    payload.get("_id") or 
                    payload.get("sys_id") or
                    str(hash(str(payload)))[:16])
            
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_results.append(result)
        
        # Sort by score descending
        unique_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return unique_results

async def start_qdrant_sync(tickets_collection: AsyncIOMotorCollection) -> None:
    try:
        sync_metadata_collection = tickets_collection.database[SYNC_METADATA_COLLECTION]
        qdrant_manager = QdrantManager(tickets_collection, sync_metadata_collection)
        await qdrant_manager.initialize_collection()
        await qdrant_manager.sync_existing_documents()
        await qdrant_manager.poll_for_changes()
    except Exception as e:
        logger.error(f"Failed to start Qdrant sync: {str(e)}")
        raise