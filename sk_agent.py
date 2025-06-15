import asyncio
import os
from datetime import datetime
import uuid
import logging
import json
from semantic_kernel import Kernel
from openai import AzureOpenAI
from bs4 import BeautifulSoup
from pymongo.collection import Collection
from pymilvus import connections, Collection
from sentence_transformers import SentenceTransformer
from aws import AWSPlugin
import re
from task_manager import TaskManager
from typing import Dict
from monitor import MonitorPlugin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SKAgent:
    def __init__(self, kernel: Kernel, tickets_collection: Collection):
        self.kernel = kernel
        self.tickets_collection = tickets_collection
        self.monitor_tasks = {}
        self.fix_events: Dict[str, asyncio.Event] = {}
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2023-05-15"
        )
        self.github_token = os.getenv("GITHUB_TOKEN")
        if not self.github_token:
            logger.error("GITHUB_TOKEN not found in .env file")
        self.kernel.add_plugin(AWSPlugin(), plugin_name="aws")
        if "monitor" not in self.kernel.plugins:
            self.kernel.add_plugin(MonitorPlugin(), plugin_name="monitor")
            logger.info("Registered MonitorPlugin in SKAgent")
            
        # Initialize Milvus connection and sentence transformer model
        self.milvus_collection_name = "ticket_details"
        try:
            connections.connect(host="localhost", port="19530")
            logger.info("Connected to Milvus successfully")
            
            # Import pymilvus components before using DataType
            from pymilvus import utility, FieldSchema, CollectionSchema, DataType
            
            # Define expected schema fields
            expected_fields = [
                {"name": "ado_ticket_id", "dtype": DataType.INT64, "is_primary": True},
                {"name": "ticket_title", "dtype": DataType.VARCHAR, "max_length": 255},
                {"name": "ticket_description", "dtype": DataType.VARCHAR, "max_length": 65535},
                {"name": "updates", "dtype": DataType.VARCHAR, "max_length": 65535},
                {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": 384}  # Dimension for all-MiniLM-L6-v2
            ]
            
            # Check if collection exists and has correct schema
            collection_valid = False
            if utility.has_collection(self.milvus_collection_name):
                collection = Collection(self.milvus_collection_name)
                schema = collection.schema
                actual_fields = [(f.name, f.dtype, f.is_primary, f.params.get('max_length', 0), f.params.get('dim', None)) for f in schema.fields]
                expected_fields_set = set((f["name"], f["dtype"], f.get("is_primary", False), f.get("max_length", 0), f.get("dim", None)) for f in expected_fields)
                actual_fields_set = set(actual_fields)
                
                if actual_fields_set == expected_fields_set:
                    collection_valid = True
                    logger.info(f"Collection {self.milvus_collection_name} has valid schema")
                else:
                    logger.warning(f"Collection {self.milvus_collection_name} has incorrect schema, dropping and recreating")
                    utility.drop_collection(self.milvus_collection_name)
            
            if not collection_valid:
                logger.info(f"Collection {self.milvus_collection_name} does not exist or is invalid, creating it")
                fields = [
                    FieldSchema(name="ado_ticket_id", dtype=DataType.INT64, is_primary=True),
                    FieldSchema(name="ticket_title", dtype=DataType.VARCHAR, max_length=255),
                    FieldSchema(name="ticket_description", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="updates", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384)
                ]
                schema = CollectionSchema(fields=fields, description="Ticket details for RAG")
                self.milvus_collection = Collection(name=self.milvus_collection_name, schema=schema)
                logger.info(f"Created collection {self.milvus_collection_name}")
                
                # Create index for embedding field
                index_params = {
                    "metric_type": "L2",
                    "index_type": "IVF_FLAT",
                    "params": {"nlist": 1024}
                }
                self.milvus_collection.create_index(field_name="embedding", index_params=index_params)
                logger.info(f"Created index on embedding field for collection {self.milvus_collection_name}")
            
            else:
                self.milvus_collection = Collection(self.milvus_collection_name)
                # Check if index exists, create if not
                if not self.milvus_collection.has_index():
                    logger.info(f"No index found for collection {self.milvus_collection_name}, creating index")
                    index_params = {
                        "metric_type": "L2",
                        "index_type": "IVF_FLAT",
                        "params": {"nlist": 1024}
                    }
                    self.milvus_collection.create_index(field_name="embedding", index_params=index_params)
                    logger.info(f"Created index on embedding field for collection {self.milvus_collection_name}")
            
            self.milvus_collection.load()
            logger.info(f"Loaded collection {self.milvus_collection_name}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Milvus or initialize collection: {str(e)}")
            raise
        
        try:
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Initialized sentence-transformers model")
        except Exception as e:
            logger.error(f"Failed to initialize sentence-transformers: {str(e)}")
            raise
        
        logger.info("Initialized SKAgent with AzureOpenAI client, AWS plugin, and Milvus")

    async def send_to_milvus(self, ticket: dict):
        """Send or update ticket details in Milvus for RAG."""
        try:
            ado_ticket_id = ticket.get("ado_ticket_id")
            if not ado_ticket_id:
                logger.warning("No ado_ticket_id provided, skipping Milvus operation")
                return

            ticket_title = ticket.get("ticket_title", "")
            ticket_description = ticket.get("ticket_description", "")
            updates = json.dumps(ticket.get("updates", []))

            # Generate embedding
            text_to_embed = f"{ticket_title} {ticket_description} {updates}"
            embedding = self.embedding_model.encode(text_to_embed).tolist()

            # Prepare data for upsert
            data = [
                [ado_ticket_id],
                [ticket_title],
                [ticket_description],
                [updates],
                [embedding]
            ]

            # Check if ticket exists in Milvus
            self.milvus_collection.load()
            results = self.milvus_collection.query(
                expr=f"ado_ticket_id == {ado_ticket_id}",
                output_fields=["ado_ticket_id"]
            )

            if results:
                # Update existing entry
                self.milvus_collection.delete(expr=f"ado_ticket_id == {ado_ticket_id}")
                logger.info(f"Deleted old Milvus entry for ticket ID={ado_ticket_id} before upsert")
                self.milvus_collection.insert(data)
                logger.info(f"Updated ticket ID={ado_ticket_id} in Milvus with new updates")
            else:
                # Insert new entry
                self.milvus_collection.insert(data)
                logger.info(f"Inserted new ticket ID={ado_ticket_id} in Milvus")

            # Update MongoDB with in_milvus flag
            self.tickets_collection.update_one(
                {"ado_ticket_id": ado_ticket_id},
                {"$set": {"in_milvus": True}}
            )

        except Exception as e:
            logger.error(f"Error in Milvus operation for ticket {ado_ticket_id}: {str(e)}")

    async def search_milvus_for_solution(self, ticket_title: str, ticket_description: str, comments: str = "") -> tuple[bool, dict | None]:
        """Search Milvus for tickets similar to the given ticket_title, ticket_description, and comments."""
        try:
            # Combine title, description, and comments for embedding
            text_to_embed = f"{ticket_title} {ticket_description} {comments}".strip()
            embedding = self.embedding_model.encode(text_to_embed).tolist()
            search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
            results = self.milvus_collection.search(
                data=[embedding],
                anns_field="embedding",
                param=search_params,
                limit=3,
                output_fields=["ado_ticket_id", "ticket_title", "ticket_description", "updates"]
            )

            found_match = False
            threshold = 1.5  # Relaxed threshold for better match detection
            best_match = None
            min_distance = float('inf')

            for hits in results:
                for hit in hits:
                    logger.info(f"Search hit: ado_ticket_id={hit.entity.get('ado_ticket_id')}, distance={hit.distance}")
                    ticket_data = {
                        "ado_ticket_id": hit.entity.get('ado_ticket_id'),
                        "ticket_title": hit.entity.get('ticket_title'),
                        "ticket_description": hit.entity.get('ticket_description'),
                        "updates": hit.entity.get('updates')
                    }
                    if hit.distance < threshold and hit.distance < min_distance:
                        found_match = True
                        min_distance = hit.distance
                        best_match = ticket_data

            if found_match:
                logger.info(f"Found matching ticket: ado_ticket_id={best_match['ado_ticket_id']}, distance={min_distance}")
            else:
                logger.info("No matching ticket found in Milvus")
            return (found_match, best_match)

        except Exception as e:
            logger.error(f"Error searching Milvus: {str(e)}")
            return (False, None)

    async def restructure_remediation_from_milvus(self, matching_ticket: dict, user_name: str) -> str:
        """Extract all remediation steps from matching ticket's updates and restructure using LLM."""
        try:
            ticket_id = matching_ticket.get("ado_ticket_id", "Unknown")
            updates = json.loads(matching_ticket.get("updates", "[]"))
            
            # Log raw updates for debugging
            logger.info(f"Raw updates for ticket ID={ticket_id}: {updates}")
            
            # Collect all non-placeholder comments from updates
            remediation_steps = []
            for update in updates:
                comment = update.get("comment", "")
                if comment and comment != "No comment provided":
                    # Clean HTML tags
                    soup = BeautifulSoup(comment, "html.parser")
                    cleaned_comment = soup.get_text().strip()
                    if cleaned_comment:
                        remediation_steps.append(cleaned_comment)
            
            if not remediation_steps:
                logger.warning(f"No valid remediation steps found in updates for ticket ID={ticket_id}")
                return ""

            # Join all steps for LLM input
            raw_remediation = "\n".join(remediation_steps)
            logger.info(f"Collected remediation steps for ticket ID={ticket_id}: {raw_remediation}")
            
            # LLM prompt to restructure steps
            remediation_prompt = (
                f"You are an IT support assistant. Restructure the following IT remediation steps into a concise numbered list. "
                "Use a polite and professional tone, with clear, actionable steps suitable for a non-technical user. "
                "Combine related steps and remove redundancies while preserving all unique actions. "
                "Include only the numbered steps, without a greeting or closing signature. "
                f"Raw Remediation Steps:\n{raw_remediation}\n"
                "Example Output:\n"
                "1. Restart your Citrix Workspace application.\n"
                "2. Check your internet connection by restarting your router.\n"
                "3. Contact IT if the issue persists."
            )

            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are an IT support assistant."},
                    {"role": "user", "content": remediation_prompt}
                ],
                temperature=0.2,
                max_tokens=250
            )

            restructured = response.choices[0].message.content.strip()
            logger.info(f"Restructured remediation for ticket ID={ticket_id}: {restructured}")
            return restructured

        except Exception as e:
            logger.error(f"Error restructuring remediation for ticket ID={ticket_id}: {str(e)}")
            return ""
            
    async def analyze_intent(self, subject: str, body: str, attachments: list = None) -> dict:
        """Analyze email intent using Azure OpenAI, relying on contextual understanding."""
        try:
            # Clean HTML from body
            if "<html>" in body.lower():
                body = BeautifulSoup(body, "html.parser").get_text(separator=" ").strip()
            else:
                body = body.strip()

            # Store the email body for later use in checking CloudWatch logging requests
            self.current_email_body = body
            
            logger.info(f"Analyzing intent - Subject: {subject}, Body: {body[:100]}..., Attachments={len(attachments or [])}")

            content = f"Subject: {subject}\nBody: {body}"
            file_content = ""
            if attachments:
                attachment_info = "\nAttachments: " + ", ".join(a['filename'] for a in attachments)
                content += attachment_info
                # Extract file content for shell scripts
                for attachment in attachments:
                    if attachment['filename'].endswith('.sh'):
                        file_content = attachment.get('content', '').strip()
                        if file_content:
                            content += f"\nAttachment Content ({attachment['filename']}):\n{file_content}"

            # Validate instance ID format
            instance_id_pattern = r'i-[0-9a-f]{17}'
            instance_ids = re.findall(instance_id_pattern, body)
            for instance_id in instance_ids:
                if not re.match(r'^i-[0-9a-f]{17}$', instance_id):
                    logger.warning(f"Invalid instance ID format detected: {instance_id}")

            prompt = (
                "You are an IT support assistant analyzing an email to determine the user's intent based on its context and purpose, without relying solely on specific keywords. "
                "Classify the intent as one of: 'github_access_request', 'github_revoke_access', 'github_create_repo', 'github_commit_file', 'github_delete_repo', "
                "'aws_s3_create_bucket', 'aws_s3_delete_bucket', 'aws_ec2_launch_instance', 'aws_ec2_run_script', 'aws_ec2_terminate_instance', 'aws_iam_add_user', 'aws_iam_remove_user', "
                "'aws_iam_add_user_permission', 'aws_iam_remove_user_permission', 'git_and_aws_intent', 'general_it_request', 'request_summary', or 'non_intent'. "
                "Understand the email's overall intent by evaluating whether it requests a specific, immediate IT action or is non-actionable (e.g., appreciation, acknowledgment). "
                "Extract relevant details for actionable intents. For 'general_it_request', include attachment details if present. "
                "Extract the username or requester name from the sender address (before the @ symbol) if available. "
                "For follow-up emails (e.g., subject starts with 'Re:'), prioritize intents related to previous requests in the thread. "
                "For emails with multiple GitHub and AWS actions, classify as 'git_and_aws_intent' with sub-intents. "
                "Include attachment file content in details for 'github_commit_file' sub-intent. "
                "Detect if the user requests CloudWatch log monitoring and error fixing (e.g., 'monitor logs and fix errors', 'fix any errors', 'resolve issues', 'handle errors', 'troubleshoot', or similar phrases indicating error resolution) and set enable_cloudwatch_monitoring to true. "
                "Rules:\n"
                "- Non-intent email:\n"
                "  - Intent: 'non_intent'.\n"
                "  - Applies to emails with no specific, immediate IT request, such as appreciation (e.g., 'Thanks for creating the bucket'), acknowledgments, greetings, or vague future requests (e.g., 'Let me know if there are updates').\n"
                "  - Characteristics: No clear demand for action, no specific IT issue, or no immediate task.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'Non-actionable email (e.g., appreciation or generic message)'.\n"
                "- Request summary:\n"
                "  - Intent: 'request_summary'.\n"
                "  - Applies to emails requesting a status, summary, or details of a previous request (e.g., 'Can you summarize my S3 bucket request?' or 'What’s the status of my ticket?').\n"
                "  - Characteristics: Clear demand for information about an existing ticket.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'User requested summary of previous request'.\n"
                "- GitHub create repository:\n"
                "  - Intent: 'github_create_repo' or sub-intent.\n"
                "  - Applies to emails requesting to create a GitHub repository (e.g., 'Create a private repository named testing').\n"
                "  - Extract: repo_name, github_username (owner, default 'unspecified').\n"
                "  - Action: {'action': 'create_repo', 'repo_name', 'github_username'}.\n"
                "  - Pending actions: true (assumes potential future deletion).\n"
                "  - Ticket description: e.g., 'Create private repository testing'.\n"
                "- GitHub commit file:\n"
                "  - Intent: 'github_commit_file' or sub-intent.\n"
                "  - Applies to emails requesting to commit a file to a repository (e.g., 'Commit list_files.sh to testing repo').\n"
                "  - Extract: repo_name, file_name, file_content (from attachment).\n"
                "  - Action: {'action': 'commit_file', 'repo_name', 'file_name', 'file_content'}.\n"
                "  - Pending actions: true (assumes potential future deletion).\n"
                "  - Ticket description: e.g., 'Commit list_files.sh to testing repository'.\n"
                "- GitHub delete repository:\n"
                "  - Intent: 'github_delete_repo' or sub-intent.\n"
                "  - Applies to emails requesting to delete a GitHub repository (e.g., 'Delete the testing repository').\n"
                "  - Extract: repo_name.\n"
                "  - Action: {'action': 'delete_repo', 'repo_name'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Delete testing repository'.\n"
                "- GitHub access request:\n"
                "  - Intent: 'github_access_request'.\n"
                "  - Applies to emails requesting access to a GitHub repository (e.g., 'Please grant read access to poc for testuser9731').\n"
                "  - Extract: repo_name, access_type ('pull' for read, 'push' for write, 'unspecified' if unclear), github_username.\n"
                "  - Action: {'action': 'grant_access', 'repo_name', 'access_type', 'github_username'}.\n"
                "  - Pending actions: true if the email implies future revocation (e.g., 'I will let you know when to revoke'); false otherwise.\n"
                "  - Ticket description: e.g., 'Grant read access to poc for testuser9731'.\n"
                "- GitHub access revocation:\n"
                "  - Intent: 'github_revoke_access'.\n"
                "  - Applies to emails requesting removal of GitHub access (e.g., 'Please revoke access to poc for testuser9731').\n"
                "  - Extract: repo_name, github_username.\n"
                "  - Action: {'action': 'revoke_access', 'repo_name', 'github_username'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Revoke access to poc for testuser9731'.\n"
                "- AWS S3 create bucket:\n"
                "  - Intent: 'aws_s3_create_bucket' or sub-intent.\n"
                "  - Applies to emails requesting creation of an S3 bucket (e.g., 'Create an S3 bucket named audit-9731 in us-east-2 with private access').\n"
                "  - Extract: bucket_name, region (default 'us-east-1' if unspecified), acl ('private', 'public-read', 'public-read-write', 'authenticated-read', or 'unspecified').\n"
                "  - Action: {'action': 'create_bucket', 'bucket_name', 'region', 'acl'}.\n"
                "  - Pending actions: true (assumes potential future deletion).\n"
                "  - Ticket description: e.g., 'Create S3 bucket audit-9731 in us-east-2 with private access'.\n"
                "- AWS S3 delete bucket:\n"
                "  - Intent: 'aws_s3_delete_bucket' or sub-intent.\n"
                "  - Applies to emails requesting deletion of an S3 bucket (e.g., 'Delete the S3 bucket audit-9731').\n"
                "  - Extract: bucket_name, region (default 'us-east-1' if unspecified).\n"
                "  - Action: {'action': 'delete_bucket', 'bucket_name', 'region'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Delete S3 bucket audit-9731 in us-east-2'.\n"
                "- AWS EC2 launch instance:\n"
                "  - Intent: 'aws_ec2_launch_instance' or sub-intent.\n"
                "  - Applies to emails requesting to launch a new EC2 instance (e.g., 'Launch an EC2 instance with t3.micro in us-east-2, clone testing repo, run list_files.sh').\n"
                "  - Extract: instance_type (default 't2.micro' if unspecified), ami_id (default 'unspecified'), region (default 'us-east-1'), repo_name (if cloning), script_name (if running a script), source_bucket, destination_bucket (if applicable), enable_cloudwatch_logs (true if phrases like 'forward logs to CloudWatch' are detected, false otherwise), enable_cloudwatch_monitoring (true if phrases like 'monitor logs and fix errors', 'fix any errors', 'resolve issues', 'handle errors', or 'troubleshoot' are detected, false otherwise).\n"
                "  - Action: {'action': 'launch_instance', 'instance_type', 'ami_id', 'region', 'repo_name', 'script_name', 'source_bucket', 'destination_bucket', 'enable_cloudwatch_logs', 'enable_cloudwatch_monitoring'}.\n"
                "  - Pending actions: true (assumes potential future termination).\n"
                "  - Ticket description: e.g., 'Launch EC2 instance t3.micro in us-east-2, clone testing repo, run list_files.sh'.\n"
                "- AWS EC2 run script on existing instance:\n"
                "  - Intent: 'aws_ec2_run_script' or sub-intent.\n"
                "  - Applies to emails requesting to run a script on an existing EC2 instance (e.g., 'Use existing EC2 instance i-066ae40255e9ee748 to clone testing repo, run list_files.sh').\n"
                "  - Extract: instance_id, region (default 'us-east-1'), repo_name (if cloning), script_name (if running a script), source_bucket, destination_bucket (if applicable), enable_cloudwatch_logs (true if phrases like 'forward logs to CloudWatch' are detected, false otherwise), enable_cloudwatch_monitoring (true if phrases like 'monitor logs and fix errors', 'fix any errors', 'resolve issues', 'handle errors', or 'troubleshoot' are detected, false otherwise).\n"
                "  - Action: {'action': 'run_script', 'instance_id', 'region', 'repo_name', 'script_name', 'source_bucket', 'destination_bucket', 'enable_cloudwatch_logs', 'enable_cloudwatch_monitoring'}.\n"
                "  - Pending actions: true (assumes potential future actions).\n"
                "  - Ticket description: e.g., 'Run list_files.sh on existing EC2 instance i-066ae40255e9ee748 in us-east-2'.\n"
                "- AWS EC2 terminate instance:\n"
                "  - Intent: 'aws_ec2_terminate_instance' or sub-intent.\n"
                "  - Applies to emails requesting termination of an EC2 instance (e.g., 'Terminate EC2 instance i-1234567890abcdef0').\n"
                "  - Extract: instance_id, region (default 'us-east-1').\n"
                "  - Action: {'action': 'terminate_instance', 'instance_id', 'region'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Terminate EC2 instance i-1234567890abcdef0 in us-east-2'.\n"
                "- AWS IAM add user:\n"
                "  - Intent: 'aws_iam_add_user'.\n"
                "  - Applies to emails requesting creation of an IAM user (e.g., 'Create an IAM user johndoe').\n"
                "  - Extract: username.\n"
                "  - Action: {'action': 'add_user', 'username'}.\n"
                "  - Pending actions: true (assumes potential future removal).\n"
                "  - Ticket description: e.g., 'Create IAM user johndoe'.\n"
                "- AWS IAM remove user:\n"
                "  - Intent: 'aws_iam_remove_user'.\n"
                "  - Applies to emails requesting deletion of an IAM user (e.g., 'Remove IAM user johndoe').\n"
                "  - Extract: username.\n"
                "  - Action: {'action': 'remove_user', 'username'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Remove IAM user johndoe'.\n"
                "- AWS IAM add user permission:\n"
                "  - Intent: 'aws_iam_add_user_permission'.\n"
                "  - Applies to emails requesting to attach a permission to an IAM user (e.g., 'Add S3 full access to IAM user johndoe').\n"
                "  - Extract: username, permission (e.g., 'S3FullAccess', 'unspecified' if unclear).\n"
                "  - Action: {'action': 'add_user_permission', 'username', 'permission'}.\n"
                "  - Pending actions: true (assumes potential future removal).\n"
                "  - Ticket description: e.g., 'Add S3 full access to IAM user johndoe'.\n"
                "- AWS IAM remove user permission:\n"
                "  - Intent: 'aws_iam_remove_user_permission'.\n"
                "  - Applies to emails requesting to detach a permission from an IAM user (e.g., 'Remove S3 full access from IAM user johndoe').\n"
                "  - Extract: username, permission (e.g., 'S3FullAccess', 'unspecified' if unclear).\n"
                "  - Action: {'action': 'remove_user_permission', 'username', 'permission'}.\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: e.g., 'Remove S3 full access from IAM user johndoe'.\n"
                "- Combined GitHub and AWS request:\n"
                "  - Intent: 'git_and_aws_intent'.\n"
                "  - Applies to emails requesting multiple actions involving GitHub and AWS (e.g., 'Create a GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, run script on existing EC2 instance').\n"
                "  - Extract: sub_intents (list of intents like 'github_create_repo', 'github_commit_file', 'aws_s3_create_bucket', 'aws_ec2_run_script'), with details for each, including enable_cloudwatch_monitoring for relevant sub-intents.\n"
                "  - Actions: List of actions for each sub-intent.\n"
                "  - Pending actions: true if any sub-intent has pending actions (e.g., creation intents); false otherwise.\n"
                "  - Ticket description: e.g., 'Create GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, run script on existing EC2 instance'.\n"
                "- General IT request:\n"
                "  - Intent: 'general_it_request'.\n"
                "  - Applies to emails describing a specific IT issue or request not related to GitHub or AWS (e.g., 'I’m having VPN connection issues').\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: Create a specific, detailed description, e.g., 'User johndoe reports VPN connection error.' Include attachment details if present.\n"
                "- Unclear intent:\n"
                "  - Intent: 'error'.\n"
                "  - Applies when the email’s intent cannot be determined and is not clearly non-actionable.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'Unable to determine intent'.\n"
                "Return JSON: {'intent', 'ticket_description', 'actions', 'pending_actions', 'sub_intents', 'repo_name', 'access_type', 'github_username', "
                "'bucket_name', 'region', 'acl', 'instance_type', 'ami_id', 'instance_id', 'username', 'permission', 'file_name', 'source_bucket', 'destination_bucket', 'script_name', 'file_content', 'enable_cloudwatch_monitoring'}.\n"
                f"Email:\n{content}\n\n"
                "Examples:\n"
                "1. Subject: Request access to poc repo\nBody: Please grant read access to poc for testuser9731. I will let you know when to revoke.\n"
                "   ```json\n{\"intent\": \"github_access_request\", \"ticket_description\": \"Grant read access to poc for testuser9731\", \"actions\": [{\"action\": \"grant_access\", \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}], \"pending_actions\": true, \"sub_intents\": [], \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "2. Subject: Create S3 bucket\nBody: Please create an S3 bucket named mybucket in us-west-2 with private access.\n"
                "   ```json\n{\"intent\": \"aws_s3_create_bucket\", \"ticket_description\": \"Create S3 bucket mybucket in us-west-2 with private access\", \"actions\": [{\"action\": \"create_bucket\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"private\"}], \"pending_actions\": true, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"private\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "3. Subject: Re: Create S3 bucket\nBody: Please delete the S3 bucket mybucket.\n"
                "   ```json\n{\"intent\": \"aws_s3_delete_bucket\", \"ticket_description\": \"Delete S3 bucket mybucket in us-west-2\", \"actions\": [{\"action\": \"delete_bucket\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\"}], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "4. Subject: Deploy File Listing Application on Existing EC2 Instance\nBody: Please create a private GitHub repository named 'testing' under my account (lakshmeesh12). I’ve attached a shell script, `list_files.sh`, which should be committed to the repository. Next, create an S3 bucket named 'audit-9731' in the us-east-2 region with private access. Finally, use the existing EC2 instance (i-066ae40255e9ee748) in us-east-2 to clone the 'testing' repository, run `list_files.sh` to list files from the existing S3 bucket 'lakshmeesh9731', save the output to the 'audit-9731' bucket, and forward all logs to the CloudWatch log group 'EC2logs' for future reference.\nAttachments: list_files.sh\nAttachment Content (list_files.sh): #!/bin/bash\naws s3 ls s3://lakshmeesh9731 > output.txt\naws s3 cp output.txt s3://audit-9731/output.txt\n"
                "   ```json\n{\"intent\": \"git_and_aws_intent\", \"ticket_description\": \"Create GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, run script on existing EC2 instance in us-east-2\", \"actions\": [{\"action\": \"create_repo\", \"repo_name\": \"testing\", \"github_username\": \"lakshmeesh12\"}, {\"action\": \"commit_file\", \"repo_name\": \"testing\", \"file_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\"}, {\"action\": \"create_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\"}, {\"action\": \"run_script\", \"instance_id\": \"i-066ae40255e9ee748\", \"region\": \"us-east-2\", \"repo_name\": \"testing\", \"script_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"enable_cloudwatch_logs\": true, \"enable_cloudwatch_monitoring\": false}], \"pending_actions\": true, \"sub_intents\": [{\"intent\": \"github_create_repo\", \"repo_name\": \"testing\", \"github_username\": \"lakshmeesh12\"}, {\"intent\": \"github_commit_file\", \"repo_name\": \"testing\", \"file_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\"}, {\"intent\": \"aws_s3_create_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\"}, {\"intent\": \"aws_ec2_run_script\", \"instance_id\": \"i-066ae40255e9ee748\", \"region\": \"us-east-2\", \"repo_name\": \"testing\", \"script_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"enable_cloudwatch_logs\": true, \"enable_cloudwatch_monitoring\": false}], \"repo_name\": \"testing\", \"access_type\": \"unspecified\", \"github_username\": \"lakshmeesh12\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"i-066ae40255e9ee748\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"script_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "5. Subject: Re: Create GitHub repo and AWS resources\nBody: Please clean up the resources: delete the 'testing' repository, delete the 'audit-9731' bucket, and terminate the EC2 instance.\n"
                "   ```json\n{\"intent\": \"git_and_aws_intent\", \"ticket_description\": \"Delete GitHub repo testing, delete S3 bucket audit-9731, terminate EC2 instance\", \"actions\": [{\"action\": \"delete_repo\", \"repo_name\": \"testing\"}, {\"action\": \"delete_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\"}, {\"action\": \"terminate_instance\", \"instance_id\": \"unspecified\", \"region\": \"us-east-2\"}], \"pending_actions\": false, \"sub_intents\": [{\"intent\": \"github_delete_repo\", \"repo_name\": \"testing\"}, {\"intent\": \"aws_s3_delete_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\"}, {\"intent\": \"aws_ec2_terminate_instance\", \"instance_id\": \"unspecified\", \"region\": \"us-east-2\"}], \"repo_name\": \"testing\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "6. Subject: Status of my request\nBody: Can you provide a summary of my S3 bucket request X request? \n"
                "   ```json\n{\"intent\": \"request_summary\", \"ticket_description\": \"User requested summary of previous request\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "7. Subject: Thanks for your help\nBody: Thanks for creating the bucket. Appreciate it!\n"
                "   ```json\n{\"intent\": \"non_intent\", \"ticket_description\": \"Non-actionable email (e.g., appreciation or generic message)\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "8. Subject: VPN issue\nBody: I’m having trouble connecting to the VPN. Can you help?\n"
                "   ```json\n{\"intent\": \"general_it_request\", \"ticket_description\": \"User reports VPN connection error\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\", \"enable_cloudwatch_monitoring\": false}\n```\n"
                "9. Subject: Run Script and Fix Errors\nBody: Please use the existing EC2 instance i-066ae40255e9ee748 in us-east-2 to clone the 'testing' repository, run `list_files.sh` to list files from the S3 bucket 'lakshmeesh9731', save the output to the 'audit-9731' bucket, and fix any errors that occur.\nAttachments: list_files.sh\nAttachment Content (list_files.sh): #!/bin/bash\naws s3 ls s3://lakshmeesh9731 > output.txt\naws s3 cp output.txt s3://audit-9731/output.txt\n"
                "   ```json\n{\"intent\": \"aws_ec2_run_script\", \"ticket_description\": \"Run list_files.sh on existing EC2 instance i-066ae40255e9ee748 in us-east-2, fix any errors\", \"actions\": [{\"action\": \"run_script\", \"instance_id\": \"i-066ae40255e9ee748\", \"region\": \"us-east-2\", \"repo_name\": \"testing\", \"script_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"enable_cloudwatch_logs\": true, \"enable_cloudwatch_monitoring\": true}], \"pending_actions\": true, \"sub_intents\": [], \"repo_name\": \"testing\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"i-066ae40255e9ee748\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"script_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\", \"enable_cloudwatch_monitoring\": true}\n```\n"
                "Output format:\n"
                "```json\n{\"intent\": \"<intent>\", \"ticket_description\": \"<description>\", \"actions\": [<action_objects>], \"pending_actions\": <bool>, \"sub_intents\": [<sub_intent_objects>], \"repo_name\": \"<repo>\", \"access_type\": \"<pull|push|unspecified>\", \"github_username\": \"<username>\", \"bucket_name\": \"<bucket>\", \"region\": \"<region>\", \"acl\": \"<acl>\", \"instance_type\": \"<type>\", \"ami_id\": \"<ami>\", \"instance_id\": \"<id>\", \"username\": \"<user>\", \"permission\": \"<permission>\", \"file_name\": \"<file>\", \"source_bucket\": \"<source>\", \"destination_bucket\": \"<dest>\", \"script_name\": \"<script>\", \"file_content\": \"<content>\", \"enable_cloudwatch_monitoring\": <bool>}\n```"
            )

            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a precise IT support assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )

            result = response.choices[0].message.content.strip()
            if result.startswith("```json") and result.endswith("```"):
                result = result[7:-3].strip()

            parsed_result = json.loads(result)
            logger.info(f"Analyzed intent: {parsed_result['intent']}, Pending actions: {parsed_result['pending_actions']}")
            return parsed_result
        except Exception as e:
            logger.error(f"Error analyzing intent: {str(e)}")
            return {
                "intent": "error",
                "ticket_description": f"Error analyzing intent: {str(e)}",
                "actions": [],
                "pending_actions": False,
                "sub_intents": [],
                "repo_name": "unspecified",
                "access_type": "unspecified",
                "github_username": "unspecified",
                "bucket_name": "unspecified",
                "region": "us-east-1",
                "acl": "unspecified",
                "instance_type": "unspecified",
                "ami_id": "unspecified",
                "instance_id": "unspecified",
                "username": "unspecified",
                "permission": "unspecified",
                "file_name": "unspecified",
                "source_bucket": "unspecified",
                "destination_bucket": "unspecified",
                "script_name": "unspecified",
                "file_content": "",
                "enable_cloudwatch_monitoring": False
            }

    async def perform_action(self, intent: str, details: dict, fix_event: asyncio.Event = None, broadcast=None, email_id=None, thread_id=None) -> dict:
        """Perform the action corresponding to the intent."""
        max_attempts = 3
        retry_delay = 20  # seconds

        try:
            logger.info(f"Performing action: {intent}")
            
            # Handle GitHub actions
            if intent == "github_access_request":
                result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["grant_repo_access"],
                    repo_name=details["repo_name"],
                    github_username=details["github_username"],
                    access_type=details["access_type"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "github_revoke_access":
                result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["revoke_repo_access"],
                    repo_name=details["repo_name"],
                    github_username=details["github_username"]
                )
                status = "revoked" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "github_create_repo":
                result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["create_repo"],
                    repo_name=details["repo_name"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "github_commit_file":
                result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["commit_file"],
                    repo_name=details["repo_name"],
                    file_name=details["file_name"],
                    file_content=details["file_content"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "github_delete_repo":
                result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["delete_repo"],
                    repo_name=details["repo_name"]
                )
                status = "terminated" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            
            # Handle AWS actions
            elif intent == "aws_s3_create_bucket":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["create_bucket"],
                    bucket_name=details["bucket_name"],
                    region=details["region"],
                    acl=details["acl"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_s3_delete_bucket":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["delete_bucket"],
                    bucket_name=details["bucket_name"],
                    region=details["region"]
                )
                status = "terminated" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_ec2_launch_instance":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["launch_instance"],
                    instance_type=details["instance_type"],
                    ami_id=details["ami_id"],
                    region=details["region"],
                    repo_name=details["repo_name"],
                    script_name=details["script_name"],
                    source_bucket=details["source_bucket"],
                    destination_bucket=details["destination_bucket"],
                    github_token=self.github_token,
                    enable_cloudwatch_logs=details.get("enable_cloudwatch_logs", True)
                )
                status = "completed" if result.value["success"] else "failed"
                logs = result.value.get("logs", "No logs captured")
                return {
                    "success": result.value["success"],
                    "message": result.value["message"],
                    "status": status,
                    "instance_id": result.value.get("instance_id"),
                    "logs": logs
                }
            elif intent == "aws_ec2_run_script":
                attempt = 1
                logs = "No logs captured"
                max_attempts = 3
                retry_delay = 20  # seconds
                fix_event = asyncio.Event()
                
                while attempt <= max_attempts:
                    try:
                        logger.info(f"Running script on instance {details['instance_id']} (attempt {attempt}/{max_attempts})")
                        result = await self.kernel.invoke(
                            self.kernel.plugins["aws"]["run_script"],
                            instance_id=details["instance_id"],
                            region=details["region"],
                            repo_name=details["repo_name"],
                            script_name=details["script_name"],
                            github_token=self.github_token,
                            github_username=details.get("github_username"),
                            source_bucket=details["source_bucket"],
                            destination_bucket=details["destination_bucket"],
                            enable_cloudwatch_logs=details.get("enable_cloudwatch_logs", True),
                            enable_cloudwatch_monitoring=details.get("enable_cloudwatch_monitoring", False),
                            log_group_name=details.get("log_group_name", "EC2logs"),
                            monitor_interval=details.get("monitor_interval", 5),
                            broadcast=broadcast,  # Pass broadcast function
                            email_id=email_id     # Pass email_id
                        )
                        logs = result.value.get("logs", "No logs captured")
                        if result.value["success"]:
                            return {
                                "success": True,
                                "message": f"Script {details['script_name']} executed successfully on instance {details['instance_id']}",
                                "status": "completed",
                                "instance_id": details["instance_id"],
                                "logs": logs
                            }
                        else:
                            # Check for AccessDenied error and wait for fix if fix_event is provided
                            if "AccessDenied" in result.value["message"] and fix_event:
                                logger.info(f"AccessDenied error detected on attempt {attempt}. Waiting for permission fix...")
                                try:
                                    # Wait for the permission fix with a 60-second timeout
                                    await asyncio.wait_for(fix_event.wait(), timeout=60)
                                    logger.info(f"Permission fix detected. Retrying script execution (attempt {attempt + 1})")
                                    fix_event.clear()  # Reset the event for the next potential fix
                                    attempt += 1
                                    continue
                                except asyncio.TimeoutError:
                                    logger.warning(f"Timeout waiting for permission fix on attempt {attempt}")
                            
                            if attempt < max_attempts:
                                logger.info(f"Script execution failed (attempt {attempt}/{max_attempts}), waiting {retry_delay} seconds before retry")
                                await asyncio.sleep(retry_delay)
                                attempt += 1
                                continue
                            else:
                                return {
                                    "success": False,
                                    "message": f"Script {details['script_name']} failed after {max_attempts} attempts: {result.value['message']}",
                                    "status": "failed",
                                    "instance_id": details["instance_id"],
                                    "logs": logs
                                }
                    
                    except Exception as e:
                        logger.error(f"Error running script on attempt {attempt}: {str(e)}")
                        if attempt < max_attempts:
                            logger.info(f"Script execution failed (attempt {attempt}/{max_attempts}), waiting {retry_delay} seconds before retry")
                            await asyncio.sleep(retry_delay)
                            attempt += 1
                            continue
                        else:
                            return {
                                "success": False,
                                "message": f"Failed to run script after {max_attempts} attempts: {str(e)}",
                                "status": "failed",
                                "instance_id": details["instance_id"],
                                "logs": logs
                            }
            
            elif intent == "aws_ec2_terminate_instance":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["terminate_instance"],
                    instance_id=details["instance_id"],
                    region=details["region"]
                )
                status = "terminated" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_iam_add_user":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["add_user"],
                    username=details["username"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_iam_remove_user":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["remove_user"],
                    username=details["username"]
                )
                status = "terminated" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_iam_add_user_permission":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["add_user_permission"],
                    username=details["username"],
                    permission=details["permission"]
                )
                status = "completed" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "aws_iam_remove_user_permission":
                result = await self.kernel.invoke(
                    self.kernel.plugins["aws"]["remove_user_permission"],
                    username=details["username"],
                    permission=details["permission"]
                )
                status = "terminated" if result.value["success"] else "failed"
                return {"success": result.value["success"], "message": result.value["message"], "status": status}
            elif intent == "git_and_aws_intent":
                results = []
                for action in details.get("actions", []):
                    sub_intent = next((si["intent"] for si in details.get("sub_intents", []) if si["intent"] in action["action"]), action["action"])
                    sub_result = await self.perform_action(sub_intent, details, broadcast=broadcast, email_id=email_id, thread_id=thread_id)
                    results.append(sub_result)
                    if not sub_result["success"]:
                        logger.warning(f"Sub-action {sub_intent} failed: {sub_result['message']}")

                success = all(r["success"] for r in results)
                message = "; ".join(r["message"] for r in results)
                status = "completed" if success else ("pending" if any(r.get("status") == "pending" for r in results) else "failed")
                return {
                    "success": success,
                    "message": message,
                    "status": status,
                    "instance_id": details.get("instance_id"),
                    "logs": "; ".join(r.get("logs", "") for r in results if r.get("logs"))
                }
            else:
                return {"success": False, "message": f"Unsupported intent: {intent}", "status": "failed"}
        
        except Exception as e:
            logger.error(f"Error performing action for intent {intent}: {str(e)}")
            return {"success": False, "message": f"Failed to perform action: {str(e)}", "status": "failed"}
        
    async def generate_summary_response(self, ticket_record: dict, user_request: str, request_source: str = "email") -> dict:
        """Generate a summary or response based on the MongoDB ticket record, tailored for email or UI, including only ServiceNow updates and GitHub actions."""
        try:
            ticket_id = ticket_record.get("servicenow_sys_id", "Unknown")
            subject = ticket_record.get("subject", "Unknown Request")
            email_chain = ticket_record.get("email_chain", [])
            updates = ticket_record.get("updates", [])
            details = ticket_record.get("details", {})
            github_actions = details.get("github", [])

            # Filter updates to include only ServiceNow updates
            servicenow_updates = [u for u in updates if u.get("source") == "servicenow"]
            # Extract GitHub actions for inclusion in the summary
            github_updates = [
                f"- {action['message']} (Repo: {action['repo_name']}, User: {action['username']}, Status: {action['status'].capitalize()}) on {action.get('email_timestamp', 'Unknown')}"
                for action in github_actions
            ]

            # Prepare content for LLM
            email_chain_text = "\n".join(
                f"From: {e['from']}\nSubject: {e['subject']}\nTimestamp: {e['timestamp']}\nBody: {e['body']}\n"
                for e in email_chain
            ) if email_chain else "No email chain available."
            updates_text = "\n".join(
                f"Field: {u['field']}\nNew Value: {u['new_value']}\nTimestamp: {u['sys_updated_on']}"
                for u in servicenow_updates
            ) if servicenow_updates else "No ServiceNow updates recorded."
            github_updates_text = "\n".join(github_updates) if github_updates else "No GitHub actions recorded."
            details_text = json.dumps(details, indent=2) if details else "{}"

            if request_source == "email":
                prompt = (
                    "You are an IT support assistant generating a concise, conversational email response summarizing a user's request. "
                    "The user has asked for a summary of a previous IT request, identified by a ticket record. "
                    "Include only updates from ServiceNow (e.g., work notes, state changes, resolution codes) and GitHub actions (e.g., access granted/revoked). "
                    "Do NOT include any Azure DevOps (ADO) updates, status, or references. "
                    "Create a natural, friendly email with the ServiceNow ticket ID, a brief summary of the request based on the email chain, key ServiceNow updates with timestamps, and GitHub actions with status and timestamps. "
                    "If no ServiceNow updates or GitHub actions are available, state that no actions have been recorded yet. "
                    "Use timestamps from ServiceNow updates (sys_updated_on) and GitHub actions to specify when key events occurred. "
                    "Keep the tone professional yet approachable, as if written by a real IT support agent named Agent. "
                    "Return JSON: {'summary_intent': 'summary_provided', 'email_response': '<response>'}.\n\n"
                    f"User Request: {user_request}\n"
                    f"ServiceNow Ticket ID: {ticket_id}\n"
                    f"Subject: {subject}\n"
                    f"Email Chain:\n{email_chain_text}\n"
                    f"ServiceNow Updates:\n{updates_text}\n"
                    f"GitHub Actions:\n{github_updates_text}\n"
                    f"Details:\n{details_text}\n\n"
                    "Example:\n"
                    "User Request: Can you give a quick summary of the poc access request?\n"
                    "```json\n"
                    "{\"summary_intent\": \"summary_provided\", \"email_response\": \"Hi,\\n\\nThanks for reaching out! Here's a quick summary of your ServiceNow request (ticket #{ticket_id}):\\n\\n- Initial Request: You asked to grant read access to the 'poc' repo for testuser9731 on 2025-06-05 at 22:55:41.\\n- ServiceNow Updates:\\n  - Work note added on 2025-06-05 at 18:32:28: Pull access granted to testuser9731 for poc.\\n- GitHub Actions:\\n  - Pull access granted on 2025-06-05 at 22:56:17 (Status: Completed).\\n- Current Status: In progress as per the latest ServiceNow update.\\n\\nLet me know if you need more details!\\n\\nBest,\\nAgent\\nIT Support\"}\n"
                    "```\n"
                    "Output format:\n"
                    "```json\n{\"summary_intent\": \"summary_provided\", \"email_response\": \"<response>\"}\n```"
                )
            else:  # request_source == "ui"
                prompt = (
                    "You are an IT support admin generating a concise summary of a ticket for an admin dashboard. "
                    "Include only updates from ServiceNow (e.g., work notes, state changes, resolution codes) and GitHub actions (e.g., access granted/revoked). "
                    "Do NOT include any Azure DevOps (ADO) updates, status, or references. "
                    "Create a brief, professional summary with the ServiceNow ticket ID, request type, key ServiceNow updates with timestamps, and GitHub actions with status and timestamps in bullet points. "
                    "If no ServiceNow updates or GitHub actions are available, state that no actions have been recorded yet. "
                    "Use timestamps from ServiceNow updates (sys_updated_on) and GitHub actions to specify when key events occurred. "
                    "Return JSON: {'summary_intent': 'summary_provided', 'email_response': '<summary>'}.\n\n"
                    f"User Request: {user_request}\n"
                    f"ServiceNow Ticket ID: {ticket_id}\n"
                    f"Subject: {subject}\n"
                    f"Email Chain:\n{email_chain_text}\n"
                    f"ServiceNow Updates:\n{updates_text}\n"
                    f"GitHub Actions:\n{github_updates_text}\n"
                    f"Details:\n{details_text}\n\n"
                    "Example:\n"
                    "User Request: Can you give a quick summary of the poc access request?\n"
                    "```json\n"
                    "{\"summary_intent\": \"summary_provided\", \"email_response\": \"ServiceNow Ticket #{ticket_id} Summary:\\n- Request Type: GitHub Access\\n- Initial Request: Grant read access to 'poc' repo for testuser9731 on 2025-06-05 at 22:55:41.\\n- ServiceNow Updates:\\n  - Work note added on 2025-06-05 at 18:32:28: Pull access granted to testuser9731 for poc.\\n- GitHub Actions:\\n  - Pull access granted on 2025-06-05 at 22:56:17 (Status: Completed).\\n- Status: In Progress as per latest ServiceNow update.\"}\n"
                    "```\n"
                    "Output format:\n"
                    "```json\n{\"summary_intent\": \"summary_provided\", \"email_response\": \"<summary>\"}\n```"
                )

            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a precise IT support assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=600  # Increased to accommodate longer responses
            )

            result = response.choices[0].message.content.strip()
            if not result:
                raise ValueError("Empty response from Azure OpenAI API")

            # Handle JSON formatting
            if result.startswith("```json") and result.endswith("```"):
                result = result[7:-3].strip()
            elif not result.startswith("{"):
                logger.error(f"Malformed response from Azure OpenAI API: {result}")
                raise ValueError(f"Invalid JSON response: {result}")

            try:
                parsed_result = json.loads(result)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {result}, Error: {str(e)}")
                raise ValueError(f"Invalid JSON format in response: {str(e)}")

            # Validate required fields
            if "summary_intent" not in parsed_result or "email_response" not in parsed_result:
                raise ValueError(f"Missing required fields in response: {result}")

            logger.info(f"Generated summary response for ServiceNow ticket ID={ticket_id} (source={request_source}): {parsed_result['summary_intent']}")
            return parsed_result
        except Exception as e:
            logger.error(f"Error generating summary for ServiceNow ticket ID={ticket_id}: {str(e)}")
            if request_source == "email":
                return {
                    "summary_intent": "error",
                    "email_response": (
                        f"Hi,\n\nI couldn't generate a summary for your ServiceNow request (ticket #{ticket_id}) due to an issue. "
                        f"Please provide more details or contact IT support for assistance.\n\nBest,\nAgent\nIT Support"
                    )
                }
            else:
                return {
                    "summary_intent": "error",
                    "email_response": (
                        f"Error generating summary for ServiceNow ticket #{ticket_id}: {str(e)}. "
                        f"Please check the ticket details or contact support."
                    )
                }
    # Relevant section of analyze_ticket_update function
    async def analyze_ticket_update(self, ticket_id: str, ado_updates: list, servicenow_updates: list = None, attachments: list = None) -> dict:
        """Analyze ServiceNow ticket updates and generate email response with remediation if attachments are present, excluding ADO updates from email."""
        try:
            # Use ticket_id (sys_id) directly since it's provided
            ticket_description = f"Ticket ID: {ticket_id} (ServiceNow ID: {ticket_id}) - IT support request"
            
            # Process ServiceNow updates only for email content
            servicenow_update_content = []
            if servicenow_updates:
                for u in servicenow_updates:
                    if not isinstance(u, dict):
                        logger.warning(f"Invalid update format in servicenow_updates: {u}")
                        continue
                    field = u.get('field', 'Unknown')
                    old_value = u.get('old_value', 'N/A')
                    new_value = u.get('new_value', 'N/A')
                    sys_updated_on = u.get('sys_updated_on', 'N/A')
                    # Human-readable field names
                    field_map = {
                        'state': 'State',
                        'caller_id': 'Caller',
                        'close_code': 'Resolution Code',
                        'close_notes': 'Resolution Notes',
                        'work_notes': 'Work Notes',
                        'comments': 'Comments',
                        'short_description': 'Short Description',
                        'priority': 'Priority'
                    }
                    field_name = field_map.get(field, field.capitalize())
                    servicenow_update_content.append(
                        f"ServiceNow Update - {field_name}: Changed from '{old_value}' to '{new_value}' (Updated: {sys_updated_on})"
                    )
            
            # Combine only ServiceNow updates for email
            update_text = "\n".join(servicenow_update_content) if servicenow_update_content else "No new ServiceNow updates."
            attachment_info = ""
            remediation = ""

            if attachments:
                attachment_info = f"Attachments: {', '.join(a['filename'] for a in attachments if isinstance(a, dict) and 'filename' in a)}"
                remediation_prompt = (
                    "You are an IT support assistant generating troubleshooting steps based on image attachments. "
                    "Provide 3-5 concise, actionable steps to help the user troubleshoot the issue. "
                    "Format as a numbered list. "
                    f"Attachments: {', '.join(a['filename'] for a in attachments if isinstance(a, dict) and 'filename' in a)}\n"
                    "Return only the numbered list as plain text."
                )
                remediation_response = self.client.chat.completions.create(
                    model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                    messages=[
                        {"role": "system", "content": "You are a helpful IT support assistant."},
                        {"role": "user", "content": remediation_prompt}
                    ],
                    temperature=0.2,
                    max_tokens=200
                )
                remediation = remediation_response.choices[0].message.content.strip()

            prompt = (
                "You are a helpful IT support admin named Agent writing a personalized email reply to a user. "
                "Create a natural, conversational response as if you're a real IT support person. "
                "Include only ServiceNow ticket ID and updates (field changes like state, caller, work notes, resolution codes, etc.) in a clear, structured format using bullet points. "
                "Exclude any Azure DevOps (ADO) updates or references from the email response. "
                "If no ServiceNow updates are provided, state that no changes have occurred. "
                "If attachments are present, mention they are included for reference. "
                "Sound friendly and helpful, use first-person, and vary your language. "
                "Keep it concise but complete. "
                "Do NOT include a closing signature (e.g., 'Best regards', 'Cheers') as it will be added later. "
                "Return JSON: {'update_intent', 'email_response', 'remediation'}.\n\n"
                f"Ticket Description: {ticket_description}\n"
                f"Updates:\n{update_text}\n"
                f"{attachment_info}\n\n"
                "Examples:\n"
                "1. Updates: ServiceNow Update - State: Changed from 'New' to 'In Progress' (Updated: 2025-06-05)\n"
                "   ServiceNow Update - Work Notes: Changed from 'N/A' to 'Started investigation' (Updated: 2025-06-05)\n"
                "   ```json\n"
                "{\"update_intent\": \"action_completed\", "
                "\"email_response\": \"Hi there,\\n\\nI've got an update on your ServiceNow ticket (ID: INC001)! Here's what's happened:\\n"
                "- State changed from 'New' to 'In Progress'.\\n"
                "- Added work notes: 'Started investigation'.\\n\\n"
                "Let me know if you need anything else!\", "
                "\"remediation\": \"\"}\n```\n"
                "2. Updates: None\n"
                "   ```json\n"
                "{\"update_intent\": \"no_update_provided\", "
                "\"email_response\": \"Hi there,\\n\\nJust checking in on your ServiceNow ticket (ID: INC001). "
                "No new updates have been made yet. I'll keep you posted when something changes!\", "
                "\"remediation\": \"\"}\n```\n"
                "Output format:\n"
                "```json\n{\"update_intent\": \"<intent>\", \"email_response\": \"<response>\", \"remediation\": \"<remediation>\"}\n```"
            )

            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a helpful IT support assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=600
            )

            result = response.choices[0].message.content.strip()
            if result.startswith("```json") and result.endswith("```"):
                result = result[7:-3].strip()

            parsed_result = json.loads(result)
            parsed_result['remediation'] = remediation if remediation else parsed_result.get('remediation', '')
            logger.info(f"Analyzed ticket update intent for ticket ID={ticket_id}: {parsed_result['update_intent']}")
            return parsed_result
        except Exception as e:
            logger.error(f"Error analyzing ticket update for ticket ID={ticket_id}: {str(e)}")
            email_response = (
                f"Dear User,\n\nYour ServiceNow ticket (ID: {ticket_id}) "
                f"is currently in an unknown status. "
                "We encountered an issue processing the latest updates. Please contact IT Support for assistance."
            )
            return {
                "update_intent": "error",
                "email_response": email_response,
                "remediation": ""
            }
        
    async def process_admin_request(self, ticket_id: int, admin_request: str) -> dict:
        """Process an admin's request for a ticket summary or update."""
        try:
            # Fetch ticket from MongoDB
            ticket_record = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
            if not ticket_record:
                logger.error(f"No ticket found for ID={ticket_id}")
                return {
                    "summary_intent": "error",
                    "email_response": (
                        f"No ticket found for ID {ticket_id}. Please check the ID and try again."
                    )
                }

            # Assume UI request for /send-request endpoint
            summary_result = await self.generate_summary_response(ticket_record, admin_request, request_source="ui")
            logger.info(f"Processed admin request for ticket ID={ticket_id}: {summary_result['summary_intent']}")
            return summary_result
        except Exception as e:
            logger.error(f"Error processing admin request for ticket ID={ticket_id}: {str(e)}")
            return {
                "summary_intent": "error",
                "email_response": (
                    f"Error processing request for ticket #{ticket_id}: {str(e)}. "
                    f"Please try again or contact support."
                )
            }
    async def are_all_actions_completed(self, ticket: dict) -> bool:
        """
        Check if all actions (GitHub and AWS) in the ticket are completed.
        Args:
            ticket (dict): Ticket record from MongoDB.
        Returns:
            bool: True if all actions are completed and no pending actions remain, False otherwise.
        """
        github_actions = ticket.get("details", {}).get("github", [])
        aws_actions = ticket.get("details", {}).get("aws", [])
        pending_actions = ticket.get("pending_actions", False)

        # Check GitHub actions
        github_completed = all(
            action["status"] in ["completed", "revoked", "failed"]
            for action in github_actions
        )

        # Check AWS actions
        aws_completed = all(
            action["status"] in ["completed", "terminated", "failed"]
            for action in aws_actions
        )

        return github_completed and aws_completed and not pending_actions

    async def are_all_actions_completed(self, ticket: dict) -> bool:
        """
        Check if all actions (GitHub and AWS) in the ticket are completed.
        Args:
            ticket (dict): Ticket record from MongoDB.
        Returns:
            bool: True if all actions are completed and no pending actions remain, False otherwise.
        """
        github_actions = ticket.get("details", {}).get("github", [])
        aws_actions = ticket.get("details", {}).get("aws", [])
        pending_actions = ticket.get("pending_actions", False)

        # Check GitHub actions
        github_completed = all(
            action["status"] in ["completed", "revoked", "failed"]
            for action in github_actions
        )

        # Check AWS actions
        aws_completed = all(
            action["status"] in ["completed", "terminated", "failed"]
            for action in aws_actions
        )

        return github_completed and aws_completed and not pending_actions


    async def process_email(self, email: dict, broadcast, existing_ticket: dict = None, email_content: str = None) -> dict:
        """Process an email through the workflow: analyze, create/update ticket, perform actions, send reply."""
        try:
            email_id = email["id"]
            subject = email["subject"]
            body = email["body"]
            sender = email["from"]
            thread_id = email.get("threadId", email_id)
            attachments = email.get("attachments", [])
            is_follow_up = bool(existing_ticket)

            # Broadcast email detection
            await broadcast({
                "type": "email_detected",
                "email_id": email_id,
                "subject": subject,
                "sender": sender,
                "thread_id": thread_id
            })

            # Analyze intent
            intent_result = await self.analyze_intent(subject, body, attachments)
            intent = intent_result["intent"]
            ticket_description = intent_result["ticket_description"]
            pending_actions = intent_result["pending_actions"] or (existing_ticket.get("pending_actions", False) if is_follow_up else False)
            sub_intents = intent_result.get("sub_intents", [])
            enable_cloudwatch_monitoring = intent_result.get("enable_cloudwatch_monitoring", False)

            # Extract details based on intent
            details = {
                "repo_name": intent_result.get("repo_name", "unspecified"),
                "access_type": intent_result.get("access_type", "unspecified"),
                "github_username": intent_result.get("github_username", "unspecified"),
                "bucket_name": intent_result.get("bucket_name", "unspecified"),
                "region": intent_result.get("region", "us-east-1"),
                "acl": intent_result.get("acl", "unspecified"),
                "instance_type": intent_result.get("instance_type", "unspecified"),
                "ami_id": intent_result.get("ami_id", "unspecified"),
                "instance_id": intent_result.get("instance_id", "unspecified"),
                "username": intent_result.get("username", "unspecified"),
                "permission": intent_result.get("permission", "unspecified"),
                "file_name": intent_result.get("file_name", "unspecified"),
                "source_bucket": intent_result.get("source_bucket", "unspecified"),
                "destination_bucket": intent_result.get("destination_bucket", "unspecified"),
                "script_name": intent_result.get("script_name", "unspecified"),
                "file_content": intent_result.get("file_content", ""),
                "enable_cloudwatch_monitoring": enable_cloudwatch_monitoring,
                "log_group_name": intent_result.get("log_group_name", "EC2logs"),
                "monitor_interval": intent_result.get("monitor_interval", 5)
            }

            await broadcast({
                "type": "intent_analyzed",
                "email_id": email_id,
                "intent": intent,
                "pending_actions": pending_actions,
                "enable_cloudwatch_monitoring": enable_cloudwatch_monitoring,
                "thread_id": thread_id
            })

            # Start monitoring before actions for relevant intents
            monitor_task = None
            if (intent == "git_and_aws_intent" or intent == "aws_ec2_run_script") and enable_cloudwatch_monitoring and details["instance_id"] != "unspecified":
                logger.debug(f"Monitor plugin available before starting monitoring: {'monitor' in self.kernel.plugins}")
                if "monitor" in self.kernel.plugins:
                    logger.info(f"Starting CloudWatch monitoring for instance {details['instance_id']} after intent analysis")
                    try:
                        monitor_task = asyncio.create_task(
                            self.kernel.invoke(
                                self.kernel.plugins["monitor"]["start_monitoring"],
                                instance_id=details["instance_id"],
                                log_group_name=details.get("log_group_name", "EC2logs"),
                                interval=details.get("monitor_interval", 5),
                                region=details["region"],
                                email_id=email_id,
                                broadcast=broadcast
                            )
                        )
                        self.monitor_tasks[details["instance_id"]] = monitor_task
                        logger.info(f"Monitoring task created for instance {details['instance_id']} after intent analysis")
                        await broadcast({
                            "type": "monitoring_started",
                            "email_id": email_id,
                            "instance_id": details["instance_id"],
                            "message": f"Started CloudWatch monitoring for instance {details['instance_id']}",
                            "thread_id": thread_id
                        })
                    except Exception as e:
                        logger.error(f"Failed to start monitoring for instance {details['instance_id']} after intent analysis: {str(e)}")
                        await broadcast({
                            "type": "error",
                            "email_id": email_id,
                            "message": f"Failed to start CloudWatch monitoring: {str(e)}",
                            "thread_id": thread_id
                        })
                else:
                    logger.error("Monitor plugin not found in kernel.plugins")
                    await broadcast({
                        "type": "error",
                        "email_id": email_id,
                        "message": "Monitor plugin not found for CloudWatch monitoring",
                        "thread_id": thread_id
                    })

            # Handle non-intent emails
            if intent == "non_intent":
                logger.info(f"Non-intent email detected (ID={email_id}). Stopping workflow.")
                if is_follow_up:
                    email_chain_entry = {
                        "email_id": email_id,
                        "from": sender,
                        "subject": subject,
                        "body": body,
                        "timestamp": email.get("received", datetime.now().isoformat()),
                        "attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]
                    }
                    self.tickets_collection.update_one(
                        {"thread_id": thread_id},
                        {"$push": {"email_chain": email_chain_entry}}
                    )
                    # Update Milvus with the latest ticket data
                    updated_ticket = self.tickets_collection.find_one({"thread_id": thread_id})
                    if updated_ticket:
                        await self.send_to_milvus(updated_ticket)
                else:
                    ticket_record = {
                        "ado_ticket_id": None,
                        "servicenow_sys_id": None,
                        "sender": sender,
                        "subject": subject,
                        "thread_id": thread_id,
                        "email_id": email_id,
                        "ticket_title": "Non-intent email",
                        "ticket_description": ticket_description,
                        "email_timestamp": datetime.now().isoformat(),
                        "updates": [],
                        "email_chain": [{
                            "email_id": email_id,
                            "from": sender,
                            "subject": subject,
                            "body": body,
                            "timestamp": email.get("received", datetime.now().isoformat()),
                            "attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]
                        }],
                        "pending_actions": False,
                        "type_of_request": "non_intent",
                        "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]},
                        "in_milvus": False
                    }
                    self.tickets_collection.insert_one(ticket_record)
                    # No need to update Milvus for new non-intent tickets unless specified
                if monitor_task:
                    await self.stop_monitoring(details["instance_id"])
                    await broadcast({
                        "type": "monitoring_stopped",
                        "email_id": email_id,
                        "instance_id": details["instance_id"],
                        "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                        "thread_id": thread_id
                    })
                return {
                    "status": "success",
                    "intent": "non_intent",
                    "ado_ticket_id": existing_ticket["ado_ticket_id"] if is_follow_up else None,
                    "servicenow_sys_id": existing_ticket["servicenow_sys_id"] if is_follow_up else None,
                    "message": "Non-intent email processed; no further action taken",
                    "actions": [],
                    "pending_actions": False
                }

            # Handle request summary
            if intent == "request_summary" and is_follow_up:
                ticket_record = existing_ticket
                summary_result = await self.generate_summary_response(ticket_record, f"Subject: {subject}\nBody: {body}")
                email_response = summary_result["email_response"]

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=email_response,
                    thread_id=thread_id,
                    message_id=email_id,
                    attachments=attachments,
                    remediation=""
                )
                reply = reply_result.value if reply_result else None

                if reply:
                    email_chain_entry = {
                        "email_id": reply.get("message_id", str(uuid.uuid4())),
                        "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                        "subject": subject,
                        "body": email_response,
                        "timestamp": datetime.now().isoformat(),
                        "attachments": []
                    }
                    self.tickets_collection.update_one(
                        {"thread_id": thread_id},
                        {"$push": {"email_chain": email_chain_entry}}
                    )
                    # Update Milvus with the latest ticket data
                    updated_ticket = self.tickets_collection.find_one({"thread_id": thread_id})
                    if updated_ticket:
                        await self.send_to_milvus(updated_ticket)
                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id,
                        "ado_ticket_id": ticket_record["ado_ticket_id"],
                        "servicenow_sys_id": ticket_record["servicenow_sys_id"],
                        "message": f"Sent summary of ticket status for ADO ticket {ticket_record['ado_ticket_id']}",
                        "timestamp": datetime.now().isoformat()
                    })

                if monitor_task:
                    await self.stop_monitoring(details["instance_id"])
                    await broadcast({
                        "type": "monitoring_stopped",
                        "email_id": email_id,
                        "instance_id": details["instance_id"],
                        "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                        "thread_id": thread_id
                    })
                return {
                    "status": "success",
                    "ado_ticket_id": ticket_record["ado_ticket_id"],
                    "servicenow_sys_id": ticket_record["servicenow_sys_id"],
                    "intent": intent,
                    "summary_intent": summary_result["summary_intent"],
                    "actions": [],
                    "pending_actions": False
                }

            ado_ticket_id = existing_ticket["ado_ticket_id"] if is_follow_up else None
            servicenow_sys_id = existing_ticket["servicenow_sys_id"] if is_follow_up else None
            completed_actions = []
            action_result = None
            action_details = None

            completion_intents = [
                "github_revoke_access",
                "github_delete_repo",
                "aws_s3_delete_bucket",
                "aws_ec2_terminate_instance",
                "aws_iam_remove_user",
                "aws_iam_remove_user_permission"
            ]

            sender_username = sender.split('<')[0].strip() if '<' in sender else (sender.split('@')[0] if '@' in sender else sender)

            # Handle follow-up emails for actionable intents
            if is_follow_up and intent in [
                "github_access_request", "github_revoke_access", "github_create_repo", "github_commit_file", "github_delete_repo",
                "aws_s3_create_bucket", "aws_s3_delete_bucket", "aws_ec2_launch_instance", "aws_ec2_terminate_instance",
                "aws_iam_add_user", "aws_iam_remove_user", "aws_iam_add_user_permission", "aws_iam_remove_user_permission", "aws_ec2_run_script"
            ]:
                ado_ticket_id = existing_ticket["ado_ticket_id"]
                servicenow_sys_id = existing_ticket["servicenow_sys_id"]
                action_details = {
                    "request_type": intent,
                    "status": "pending",
                    "message": f"Processing {intent}"
                }
                if intent.startswith("github_"):
                    action_details.update({
                        "repo_name": details["repo_name"],
                        "username": details["github_username"],
                        "access_type": details["access_type"] if intent == "github_access_request" else "unspecified",
                        "file_name": details["file_name"] if intent == "github_commit_file" else "unspecified",
                        "file_content": details["file_content"] if intent == "github_commit_file" else ""
                    })
                elif intent.startswith("aws_s3_"):
                    action_details.update({
                        "bucket_name": details["bucket_name"],
                        "region": details["region"],
                        "acl": details["acl"] if intent == "aws_s3_create_bucket" else "unspecified"
                    })
                elif intent.startswith("aws_ec2_"):
                    action_details.update({
                        "instance_type": details["instance_type"],
                        "ami_id": details["ami_id"],
                        "instance_id": details["instance_id"],
                        "region": details["region"],
                        "repo_name": details["repo_name"],
                        "script_name": details["script_name"],
                        "source_bucket": details["source_bucket"],
                        "destination_bucket": details["destination_bucket"],
                        "logs": ""
                    })
                elif intent.startswith("aws_iam_"):
                    action_details.update({
                        "username": details["username"],
                        "permission": details["permission"] if "permission" in intent else "unspecified"
                    })

                update_operation = {
                    "$push": {
                        "details.aws" if intent.startswith("aws_") else "details.github": action_details,
                        "updates": {
                            "status": "Doing",
                            "comment": action_details["message"],
                            "revision_id": f"{intent.split('_')[1]}-{ado_ticket_id}-{len(existing_ticket.get('updates', [])) + 1}",
                            "email_sent": False,
                            "email_message_id": None,
                            "email_timestamp": datetime.now().isoformat()
                        }
                    },
                    "$set": {
                        "pending_actions": pending_actions
                    }
                }
                self.tickets_collection.update_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id}, update_operation)

                action_result = await self.perform_action(intent, details, broadcast=broadcast, email_id=email_id, thread_id=thread_id)
                action_details["status"] = action_result.get("status", "failed")
                action_details["message"] = action_result["message"]
                if intent == "aws_ec2_launch_instance" and action_result.get("logs"):
                    action_details["logs"] = action_result["logs"]
                completed_actions.append({"action": intent, "completed": action_result["success"]})

                if intent == "aws_ec2_run_script" and not action_result["success"]:
                    await broadcast({
                        "type": "script_execution_failed",
                        "email_id": email_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "success": False,
                        "message": action_result["message"],
                        "thread_id": thread_id
                    })

                if intent in completion_intents and action_result["success"]:
                    pending_actions = False
                    logger.info(f"Completion intent {intent} processed successfully for ticket ID={ado_ticket_id}/{servicenow_sys_id}. Setting pending_actions to False.")

                array_filter = {
                    "repo_name": details["repo_name"],
                    "username": details["github_username"],
                    "request_type": intent
                } if intent.startswith("github_") else {
                    "request_type": intent
                }
                update_operation = {
                    "$set": {
                        f"details.{'aws' if intent.startswith('aws_') else 'github'}.$[elem].status": action_details["status"],
                        f"details.{'aws' if intent.startswith('aws_') else 'github'}.$[elem].message": action_details["message"],
                        "pending_actions": pending_actions
                    },
                    "$push": {
                        "updates": {
                            "status": action_details["status"],
                            "comment": action_details["message"],
                            "revision_id": f"result-{ado_ticket_id}-{len(existing_ticket.get('updates', [])) + 2}",
                            "email_sent": False,
                            "email_message_id": None,
                            "email_timestamp": datetime.now().isoformat()
                        }
                    }
                }
                if intent == "aws_ec2_launch_instance" and action_result.get("logs"):
                    update_operation["$set"][f"details.aws.$[elem].logs"] = action_details["logs"]
                try:
                    self.tickets_collection.update_one(
                        {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                        update_operation,
                        array_filters=[{"elem.request_type": intent}]
                    )
                except Exception as e:
                    logger.error(f"Failed to update ticket {ado_ticket_id}/{servicenow_sys_id} for intent {intent}: {str(e)}")
                    raise ValueError(f"Ticket update failed: {str(e)}")

                await broadcast({
                    "type": "action_performed",
                    "email_id": email_id,
                    "ado_ticket_id": ado_ticket_id,
                    "servicenow_sys_id": servicenow_sys_id,
                    "success": action_result["success"],
                    "message": action_details["message"],
                    "thread_id": thread_id
                })

                updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                all_completed = await self.are_all_actions_completed(updated_ticket)
                ado_status = "Done" if all_completed else "Doing"
                servicenow_state = "Resolved" if all_completed else "In Progress"
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["ado"]["update_ticket"],
                        ticket_id=ado_ticket_id,
                        status=ado_status,
                        comment=action_result["message"]
                    )
                    await self.kernel.invoke(
                        self.kernel.plugins["servicenow"]["update_ticket"],
                        ticket_id=servicenow_sys_id,
                        state=servicenow_state,
                        comment=action_result["message"]
                    )
                except Exception as e:
                    logger.error(f"Failed to update tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                    raise ValueError(f"Ticket update failed: {str(e)}")

                # Send email reply for follow-up actionable intent
                email_response = f"Your request to {intent.replace('_', ' ')} has been processed.\nStatus: {action_details['status']}\nDetails: {action_details['message']}"
                if intent == "aws_ec2_launch_instance" and action_result.get("logs"):
                    email_response += f"\n\nEC2 Execution Logs:\n{action_result['logs']}"
                combined_body = f"Dear {sender_username},\n\n{email_response}\n\nBest regards,\nIT Support Agent"

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=combined_body,
                    thread_id=thread_id,
                    message_id=email_id,
                    attachments=attachments,
                    remediation=""
                )
                reply = reply_result.value if reply_result else None

                if reply:
                    email_chain_entry = {
                        "email_id": reply.get("message_id", str(uuid.uuid4())),
                        "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                        "subject": subject,
                        "body": combined_body,
                        "timestamp": datetime.now().isoformat(),
                        "attachments": []
                    }
                    self.tickets_collection.update_one(
                        {"thread_id": thread_id},
                        {"$push": {"email_chain": email_chain_entry}}
                    )
                    # Update Milvus with the latest ticket data
                    updated_ticket = self.tickets_collection.find_one({"thread_id": thread_id})
                    if updated_ticket:
                        await self.send_to_milvus(updated_ticket)
                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "message": f"Sent response for {intent.replace('_', ' ')} request: {action_details['status']} - {action_details['message']}",
                        "timestamp": datetime.now().isoformat()
                    })

                # Update Milvus with the latest ticket data
                await self.send_to_milvus(updated_ticket)

            # Handle git_and_aws_intent for follow-up
            elif is_follow_up and intent == "git_and_aws_intent":
                ado_ticket_id = existing_ticket["ado_ticket_id"]
                servicenow_sys_id = existing_ticket["servicenow_sys_id"]
                email_responses = []
                for sub_intent in sub_intents:
                    sub_intent_name = sub_intent["intent"]
                    sub_action_details = {
                        "request_type": sub_intent_name,
                        "status": "pending",
                        "message": f"Processing {sub_intent_name}"
                    }
                    if sub_intent_name == "github_create_repo":
                        sub_action_details.update({
                            "repo_name": details["repo_name"],
                            "username": details["github_username"]
                        })
                    elif sub_intent_name == "github_commit_file":
                        sub_action_details.update({
                            "repo_name": details["repo_name"],
                            "file_name": details["file_name"],
                            "file_content": details["file_content"]
                        })
                    elif sub_intent_name == "github_delete_repo":
                        sub_action_details.update({
                            "repo_name": details["repo_name"]
                        })
                    elif sub_intent_name == "aws_s3_create_bucket":
                        sub_action_details.update({
                            "bucket_name": details["bucket_name"],
                            "region": details["region"],
                            "acl": details["acl"]
                        })
                    elif sub_intent_name == "aws_s3_delete_bucket":
                        sub_action_details.update({
                            "bucket_name": details["bucket_name"],
                            "region": details["region"]
                        })
                    elif sub_intent_name == "aws_ec2_launch_instance":
                        sub_action_details.update({
                            "instance_type": details["instance_type"],
                            "ami_id": details["ami_id"],
                            "region": details["region"],
                            "repo_name": details["repo_name"],
                            "script_name": details["script_name"],
                            "source_bucket": details["source_bucket"],
                            "destination_bucket": details["destination_bucket"],
                            "logs": ""
                        })
                    elif sub_intent_name == "aws_ec2_terminate_instance":
                        sub_action_details.update({
                            "instance_id": details["instance_id"],
                            "region": details["region"]
                        })

                    update_operation = {
                        "$push": {
                            "details.aws" if sub_intent_name.startswith("aws_") else "details.github": sub_action_details,
                            "updates": {
                                "status": "Doing",
                                "comment": sub_action_details["message"],
                                "revision_id": f"{sub_intent_name.split('_')[1]}-{ado_ticket_id}-{len(existing_ticket.get('updates', [])) + 1}",
                                "email_sent": False,
                                "email_message_id": None,
                                "email_timestamp": datetime.now().isoformat()
                            }
                        },
                        "$set": {
                            "pending_actions": pending_actions
                        }
                    }
                    try:
                        self.tickets_collection.update_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id}, update_operation)
                    except Exception as e:
                        logger.error(f"Failed to update ticket {ado_ticket_id}/{servicenow_sys_id} for sub-intent {sub_intent_name}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                    sub_action_result = await self.perform_action(sub_intent_name, details, broadcast=broadcast, email_id=email_id, thread_id=thread_id)
                    sub_action_details["status"] = sub_action_result.get("status", "failed")
                    sub_action_details["message"] = sub_action_result["message"]
                    if sub_intent_name == "aws_ec2_launch_instance" and sub_action_result.get("logs"):
                        sub_action_details["logs"] = sub_action_result["logs"]
                    completed_actions.append({"action": sub_intent_name, "completed": sub_action_result["success"]})

                    # Collect email response for each sub-intent
                    sub_email_response = f"Sub-request to {sub_intent_name.replace('_', ' ')}:\nStatus: {sub_action_details['status']}\nDetails: {sub_action_details['message']}"
                    if sub_intent_name == "aws_ec2_launch_instance" and sub_action_result.get("logs"):
                        sub_email_response += f"\n\nEC2 Execution Logs:\n{sub_action_result['logs']}"
                    email_responses.append(sub_email_response)

                    if sub_intent_name == "aws_ec2_run_script" and not sub_action_result["success"]:
                        await broadcast({
                            "type": "script_execution_failed",
                            "email_id": email_id,
                            "ado_ticket_id": ado_ticket_id,
                            "servicenow_sys_id": servicenow_sys_id,
                            "success": False,
                            "message": sub_action_result["message"],
                            "thread_id": thread_id
                        })

                    if sub_intent_name in ["aws_ec2_run_script", "aws_ec2_launch_instance"] and sub_action_result.get("permission_fixed"):
                        await broadcast({
                            "type": "permission_fixed",
                            "email_id": email_id,
                            "ado_ticket_id": ado_ticket_id,
                            "servicenow_sys_id": servicenow_sys_id,
                            "message": sub_action_result.get("permission_message", "Permission issue fixed"),
                            "thread_id": thread_id
                        })

                    if sub_intent_name in completion_intents and sub_action_result["success"]:
                        pending_actions = False
                        logger.info(f"Completion sub-intent {sub_intent_name} processed successfully for ticket ID={ado_ticket_id}/{servicenow_sys_id}. Setting pending_actions to False.")

                    update_operation = {
                        "$set": {
                            f"details.{'aws' if sub_intent_name.startswith('aws_') else 'github'}.$[elem].status": sub_action_details["status"],
                            f"details.{'aws' if sub_intent_name.startswith('aws_') else 'github'}.$[elem].message": sub_action_details["message"],
                            "pending_actions": pending_actions
                        }
                    }
                    if sub_intent_name == "aws_ec2_launch_instance" and sub_action_result.get("logs"):
                        update_operation["$set"][f"details.aws.$[elem].logs"] = sub_action_details["logs"]
                    try:
                        self.tickets_collection.update_one(
                            {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                            update_operation,
                            array_filters=[{"elem.request_type": sub_intent_name}]
                        )
                    except Exception as e:
                        logger.error(f"Failed to update ticket {ado_ticket_id}/{servicenow_sys_id} for sub-intent result {sub_intent_name}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "success": sub_action_result["success"],
                        "message": sub_action_details["message"],
                        "thread_id": thread_id
                    })

                updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                all_completed = await self.are_all_actions_completed(updated_ticket)
                ado_status = "Done" if all_completed else "Doing"
                servicenow_state = "Resolved" if all_completed else "In Progress"
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["ado"]["update_ticket"],
                        ticket_id=ado_ticket_id,
                        status=ado_status,
                        comment="Processed combined GitHub and AWS actions"
                    )
                    await self.kernel.invoke(
                        self.kernel.plugins["servicenow"]["update_ticket"],
                        ticket_id=servicenow_sys_id,
                        state=servicenow_state,
                        comment="Processed combined GitHub and AWS actions"
                    )
                except Exception as e:
                    logger.error(f"Failed to update tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                    raise ValueError(f"Ticket update failed: {str(e)}")

                # Send email reply for git_and_aws_intent follow-up
                email_response = "\n\n".join(email_responses)
                combined_body = f"Dear {sender_username},\n\nYour combined GitHub and AWS requests have been processed:\n\n{email_response}\n\nBest regards,\nIT Support Agent"

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=combined_body,
                    thread_id=thread_id,
                    message_id=email_id,
                    attachments=attachments,
                    remediation=""
                )
                reply = reply_result.value if reply_result else None

                if reply:
                    email_chain_entry = {
                        "email_id": reply.get("message_id", str(uuid.uuid4())),
                        "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                        "subject": subject,
                        "body": combined_body,
                        "timestamp": datetime.now().isoformat(),
                        "attachments": []
                    }
                    self.tickets_collection.update_one(
                        {"thread_id": thread_id},
                        {"$push": {"email_chain": email_chain_entry}}
                    )
                    # Update Milvus with the latest ticket data
                    updated_ticket = self.tickets_collection.find_one({"thread_id": thread_id})
                    if updated_ticket:
                        await self.send_to_milvus(updated_ticket)
                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "message": f"Sent response for combined GitHub and AWS requests: processed {len(sub_intents)} sub-intents",
                        "timestamp": datetime.now().isoformat()
                    })

                # Update Milvus with the latest ticket data
                await self.send_to_milvus(updated_ticket)

            # Handle new email
            else:
                # Create ADO ticket
                ado_ticket_result = await self.kernel.invoke(
                    self.kernel.plugins["ado"]["create_ticket"],
                    title=subject,
                    description=ticket_description,
                    email_content=email_content,
                    attachments=attachments
                )
                if not ado_ticket_result or not ado_ticket_result.value:
                    logger.error(f"Failed to create ADO ticket for email ID={email_id}")
                    if monitor_task:
                        await self.stop_monitoring(details["instance_id"])
                        await broadcast({
                            "type": "monitoring_stopped",
                            "email_id": email_id,
                            "instance_id": details["instance_id"],
                            "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                            "thread_id": thread_id
                        })
                    return {"status": "error", "message": "ADO ticket creation failed", "actions": [], "pending_actions": False}

                ado_ticket_data = ado_ticket_result.value
                ado_ticket_id = ado_ticket_data["id"]
                ado_url = ado_ticket_data["url"]

                # Create ServiceNow ticket
                servicenow_ticket_result = await self.kernel.invoke(
                    self.kernel.plugins["servicenow"]["create_ticket"],
                    title=subject,
                    description=ticket_description,
                    email_content=email_content,
                    attachments=[a for a in attachments if isinstance(a, dict) and "path" in a and "filename" in a]
                )
                if not servicenow_ticket_result or not servicenow_ticket_result.value:
                    logger.error(f"Failed to create ServiceNow ticket for email ID={email_id}")
                    # Still proceed with ADO ticket if ServiceNow fails
                    servicenow_sys_id = None
                    servicenow_url = None
                else:
                    servicenow_ticket_data = servicenow_ticket_result.value
                    servicenow_sys_id = servicenow_ticket_data["sys_id"]
                    servicenow_url = servicenow_ticket_data["url"]

                await broadcast({
                    "type": "ticket_created",
                    "email_id": email_id,
                    "ado_ticket_id": ado_ticket_id,
                    "servicenow_sys_id": servicenow_sys_id,
                    "ado_url": ado_url,
                    "servicenow_url": servicenow_url,
                    "intent": intent,
                    "thread_id": thread_id
                })

                # Clean email body for comments
                cleaned_comments = BeautifulSoup(body, "html.parser").get_text().strip() if "<html>" in body.lower() else body.strip()

                # Initialize remediation for general_it_request
                remediation = ""

                # Handle general_it_request with Milvus search
                if intent == "general_it_request":
                    # Search Milvus for similar tickets
                    has_matches, matching_ticket = await self.search_milvus_for_solution(subject, ticket_description, cleaned_comments)
                    ticket_record = {
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "sender": sender,
                        "subject": subject,
                        "thread_id": thread_id,
                        "email_id": email_id,
                        "ticket_title": subject,
                        "ticket_description": ticket_description,
                        "email_timestamp": datetime.now().isoformat(),
                        "updates": [{
                            "status": "New",
                            "comment": cleaned_comments,
                            "revision_id": f"initial-{ado_ticket_id}-1",
                            "email_sent": False,
                            "email_message_id": None,
                            "email_timestamp": datetime.now().isoformat()
                        }],
                        "email_chain": [{
                            "email_id": email_id,
                            "from": sender,
                            "subject": subject,
                            "body": body,
                            "timestamp": email.get("received", datetime.now().isoformat()),
                            "attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]
                        }],
                        "pending_actions": pending_actions,
                        "type_of_request": intent,
                        "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]},
                        "in_milvus": has_matches
                    }

                    if has_matches:
                        # Extract and restructure remediation from matching ticket
                        remediation = await self.restructure_remediation_from_milvus(matching_ticket, sender_username)
                        ticket_record["remediation"] = remediation
                    else:
                        # Store ticket in Milvus if no match found
                        await self.send_to_milvus(ticket_record)

                    # Update ticket description for general_it_request
                    detailed_description = f"User {sender_username}: {ticket_description}"
                    ticket_record["details"]["general"] = [{
                        "request_type": "general_it_request",
                        "status": "pending",
                        "message": detailed_description,
                        "requester": sender_username
                    }]
                    ticket_record["ticket_description"] = detailed_description

                    # Store ticket in MongoDB
                    try:
                        self.tickets_collection.insert_one(ticket_record)
                    except Exception as e:
                        logger.error(f"Failed to insert ticket record for tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                        raise ValueError(f"Ticket insertion failed: {str(e)}")

                # Perform action for single intent
                elif intent != "git_and_aws_intent":
                    action_result = await self.perform_action(intent, details, broadcast=broadcast, email_id=email_id, thread_id=thread_id)
                    action_details = {
                        "request_type": intent,
                        "status": action_result.get("status", "failed"),
                        "message": action_result["message"]
                    }
                    if intent.startswith("github_"):
                        action_details.update({
                            "repo_name": details["repo_name"],
                            "username": details["github_username"],
                            "access_type": details["access_type"] if intent == "github_access_request" else "unspecified",
                            "file_name": details["file_name"] if intent == "github_commit_file" else "unspecified",
                            "file_content": details["file_content"] if intent == "github_commit_file" else ""
                        })
                    elif intent.startswith("aws_s3_"):
                        action_details.update({
                            "bucket_name": details["bucket_name"],
                            "region": details["region"],
                            "acl": details["acl"] if intent == "aws_s3_create_bucket" else "unspecified"
                        })
                    elif intent.startswith("aws_ec2_"):
                        action_details.update({
                            "instance_type": details["instance_type"],
                            "ami_id": details["ami_id"],
                            "instance_id": action_result.get("instance_id", details["instance_id"]),
                            "region": details["region"],
                            "repo_name": details["repo_name"],
                            "script_name": details["script_name"],
                            "source_bucket": details["source_bucket"],
                            "destination_bucket": details["destination_bucket"],
                            "logs": action_result.get("logs", "") if intent == "aws_ec2_launch_instance" else ""
                        })
                    elif intent.startswith("aws_iam_"):
                        action_details.update({
                            "username": details["username"],
                            "permission": details["permission"] if "permission" in intent else "unspecified"
                        })
                    completed_actions.append({"action": intent, "completed": action_result["success"]})

                    if intent == "aws_ec2_run_script" and not action_result["success"]:
                        await broadcast({
                            "type": "script_execution_failed",
                            "email_id": email_id,
                            "ado_ticket_id": ado_ticket_id,
                            "servicenow_sys_id": servicenow_sys_id,
                            "success": False,
                            "message": action_result["message"],
                            "thread_id": thread_id
                        })

                    if intent in ["aws_ec2_run_script", "aws_ec2_launch_instance"] and action_result.get("permission_fixed"):
                        await broadcast({
                            "type": "permission_fixed",
                            "email_id": email_id,
                            "ado_ticket_id": ado_ticket_id,
                            "servicenow_sys_id": servicenow_sys_id,
                            "message": action_result.get("permission_message", "Permission issue fixed"),
                            "thread_id": thread_id
                        })

                    try:
                        await self.kernel.invoke(
                            self.kernel.plugins["ado"]["update_ticket"],
                            ticket_id=ado_ticket_id,
                            status="Doing" if pending_actions else "Done",
                            comment=action_result["message"]
                        )
                        if servicenow_sys_id:
                            await self.kernel.invoke(
                                self.kernel.plugins["servicenow"]["update_ticket"],
                                ticket_id=servicenow_sys_id,
                                state="In Progress" if pending_actions else "Resolved",
                                comment=action_result["message"]
                            )
                    except Exception as e:
                        logger.error(f"Failed to update tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "success": action_result["success"],
                        "message": action_details["message"],
                        "thread_id": thread_id
                    })

                # Handle git_and_aws_intent for new email
                elif intent == "git_and_aws_intent":
                    for sub_intent in sub_intents:
                        sub_intent_name = sub_intent["intent"]
                        sub_action_result = await self.perform_action(sub_intent_name, details, broadcast=broadcast, email_id=email_id, thread_id=thread_id)
                        sub_action_details = {
                            "request_type": sub_intent_name,
                            "status": sub_action_result.get("status", "failed"),
                            "message": sub_action_result["message"]
                        }
                        if sub_intent_name == "github_create_repo":
                            sub_action_details.update({
                                "repo_name": details["repo_name"],
                                "username": details["github_username"]
                            })
                        elif sub_intent_name == "github_commit_file":
                            sub_action_details.update({
                                "repo_name": details["repo_name"],
                                "file_name": details["file_name"],
                                "file_content": details["file_content"]
                            })
                        elif sub_intent_name == "github_delete_repo":
                            sub_action_details.update({
                                "repo_name": details["repo_name"]
                            })
                        elif sub_intent_name == "aws_s3_create_bucket":
                            sub_action_details.update({
                                "bucket_name": details["bucket_name"],
                                "region": details["region"],
                                "acl": details["acl"]
                            })
                        elif sub_intent_name == "aws_s3_delete_bucket":
                            sub_action_details.update({
                                "bucket_name": details["bucket_name"],
                                "region": details["region"]
                            })
                        elif sub_intent_name == "aws_ec2_launch_instance":
                            sub_action_details.update({
                                "instance_type": details["instance_type"],
                                "ami_id": details["ami_id"],
                                "region": details["region"],
                                "repo_name": details["repo_name"],
                                "script_name": details["script_name"],
                                "source_bucket": details["source_bucket"],
                                "destination_bucket": details["destination_bucket"],
                                "logs": sub_action_result.get("logs", ""),
                                "instance_id": sub_action_result.get("instance_id", "unspecified")
                            })
                        elif sub_intent_name == "aws_ec2_terminate_instance":
                            sub_action_details.update({
                                "instance_id": details["instance_id"],
                                "region": details["region"]
                            })
                        completed_actions.append({"action": sub_intent_name, "completed": sub_action_result["success"]})

                        if sub_intent_name == "aws_ec2_run_script" and not sub_action_result["success"]:
                            await broadcast({
                                "type": "script_execution_failed",
                                "email_id": email_id,
                                "ado_ticket_id": ado_ticket_id,
                                "servicenow_sys_id": servicenow_sys_id,
                                "success": False,
                                "message": sub_action_result["message"],
                                "thread_id": thread_id
                            })

                        if sub_intent_name in ["aws_ec2_run_script", "aws_ec2_launch_instance"] and sub_action_result.get("permission_fixed"):
                            await broadcast({
                                "type": "permission_fixed",
                                "email_id": email_id,
                                "ado_ticket_id": ado_ticket_id,
                                "servicenow_sys_id": servicenow_sys_id,
                                "message": sub_action_result.get("permission_message", "Permission issue fixed"),
                                "thread_id": thread_id
                            })

                        try:
                            self.tickets_collection.update_one(
                                {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                                {
                                    "$push": {
                                        f"details.{'aws' if sub_intent_name.startswith('aws_') else 'github'}": sub_action_details,
                                        "updates": {
                                            "status": "Doing",
                                            "comment": sub_action_result["message"],
                                            "revision_id": f"{sub_intent_name.split('_')[1]}-{ado_ticket_id}-{len(completed_actions)}",
                                            "email_sent": False,
                                            "email_message_id": None,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    }
                                }
                            )
                        except Exception as e:
                            logger.error(f"Failed to update ticket {ado_ticket_id}/{servicenow_sys_id} for sub-intent {sub_intent_name}: {str(e)}")
                            raise ValueError(f"Ticket update failed: {str(e)}")

                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id,
                            "ado_ticket_id": ado_ticket_id,
                            "servicenow_sys_id": servicenow_sys_id,
                            "success": sub_action_result["success"],
                            "message": sub_action_details["message"],
                            "thread_id": thread_id
                        })

                # Update ticket in MongoDB (for non-general_it_request intents)
                if intent != "general_it_request":
                    ticket_record = {
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "sender": sender,
                        "subject": subject,
                        "thread_id": thread_id,
                        "email_id": email_id,
                        "ticket_title": subject,
                        "ticket_description": ticket_description,
                        "email_timestamp": datetime.now().isoformat(),
                        "updates": [],
                        "email_chain": [{
                            "email_id": email_id,
                            "from": sender,
                            "subject": subject,
                            "body": body,
                            "timestamp": email.get("received", datetime.now().isoformat()),
                            "attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]
                        }],
                        "pending_actions": pending_actions,
                        "type_of_request": intent,
                        "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]},
                        "in_milvus": False
                    }
                    if action_details:
                        ticket_record["details"]["aws" if intent.startswith("aws_") else "github"] = [action_details]
                    elif intent == "git_and_aws_intent":
                        ticket_record["details"]["github"] = [
                            d for d in completed_actions if d["action"].startswith("github_")
                        ]
                        ticket_record["details"]["aws"] = [
                            d for d in completed_actions if d["action"].startswith("aws_")
                        ]
                    try:
                        self.tickets_collection.insert_one(ticket_record)
                    except Exception as e:
                        logger.error(f"Failed to insert ticket record for tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                        raise ValueError(f"Ticket insertion failed: {str(e)}")

                # Send ticket to Milvus for non-general_it_request intents
                if intent != "general_it_request":
                    ticket_record = self.tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                    await self.send_to_milvus(ticket_record)

                if intent != "general_it_request":
                    updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                    all_completed = await self.are_all_actions_completed(updated_ticket)
                    ado_status = "Done" if all_completed else "Doing"
                    servicenow_state = "Resolved" if all_completed else "In Progress"

                    try:
                        await self.kernel.invoke(
                            self.kernel.plugins["ado"]["update_ticket"],
                            ticket_id=ado_ticket_id,
                            status=ado_status,
                            comment=action_result["message"] if action_result else "Processed request"
                        )
                        if servicenow_sys_id:
                            await self.kernel.invoke(
                                self.kernel.plugins["servicenow"]["update_ticket"],
                                ticket_id=servicenow_sys_id,
                                state=servicenow_state,
                                comment=action_result["message"] if action_result else "Processed request"
                            )
                    except Exception as e:
                        logger.error(f"Failed to update tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                if servicenow_sys_id:
                    try:
                        servicenow_updates_result = await self.kernel.invoke(
                            self.kernel.plugins["servicenow"]["get_ticket_updates"],
                            ticket_id=servicenow_sys_id
                        )
                        servicenow_updates = servicenow_updates_result.value if servicenow_updates_result else []
                    except Exception as e:
                        logger.error(f"Failed to fetch ServiceNow updates for sys_id={servicenow_sys_id}: {str(e)}")
                        servicenow_updates = []
                        await broadcast({
                            "type": "error",
                            "email_id": email_id,
                            "message": f"Failed to fetch ServiceNow updates: {str(e)}",
                            "thread_id": thread_id
                        })
                else:
                    logger.warning(f"No ServiceNow sys_id provided for email ID={email_id}")
                    servicenow_updates = []
                    await broadcast({
                        "type": "error",
                        "email_id": email_id,
                        "message": "No ServiceNow sys_id available for update fetching",
                        "thread_id": thread_id
                    })

                # Analyze ticket updates
                try:
                    update_result = await self.analyze_ticket_update(servicenow_sys_id, servicenow_updates, attachments)
                    email_response = update_result.get("email_response", "No updates available.")
                    existing_remediation = update_result.get("remediation", "")
                except Exception as e:
                    logger.error(f"Error analyzing ticket update for sys_id={servicenow_sys_id}: {str(e)}")
                    email_response = "Unable to process ticket updates at this time."
                    existing_remediation = ""
                    await broadcast({
                        "type": "error",
                        "email_id": email_id,
                        "message": f"Failed to analyze ticket updates: {str(e)}",
                        "thread_id": thread_id
                    })

                # Combine remediation from Milvus with existing remediation
                combined_remediation = existing_remediation
                if remediation:
                    combined_remediation = (
                        f"{existing_remediation}\n\n**While we work on resolving your issue, you can try these remediation steps retrieved from the knowledge base articles:**\n\n{remediation}"
                        if existing_remediation else
                        f"**While we work on resolving your issue, you can try these remediation steps retrieved from the knowledge base articles:**\n\n{remediation}"
                    )

                if intent == "git_and_aws_intent" or intent == "aws_ec2_launch_instance":
                    ticket_record = self.tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                    ec2_actions = [
                        action for action in ticket_record.get("details", {}).get("aws", [])
                        if action["request_type"] == "aws_ec2_launch_instance" and action.get("logs")
                    ]
                    if ec2_actions:
                        logs = ec2_actions[-1]["logs"]
                        email_response += f"\n\nEC2 Execution Logs:\n{logs}"

                # Combine email_response and remediation, add greeting and signature
                combined_body = f"Dear {sender_username},\n\n{email_response}"
                if combined_remediation:
                    combined_body += f"\n\n{combined_remediation}"
                combined_body += "\n\nBest regards,\nIT Support Agent"

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=combined_body,
                    thread_id=thread_id,
                    message_id=email_id,
                    attachments=attachments,
                    remediation=""
                )
                reply = reply_result.value if reply_result else None

                if reply:
                    email_chain_entry = {
                        "email_id": reply.get("message_id", str(uuid.uuid4())),
                        "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                        "subject": subject,
                        "body": combined_body,
                        "timestamp": datetime.now().isoformat(),
                        "attachments": []
                    }
                    try:
                        self.tickets_collection.update_one(
                            {"thread_id": thread_id},
                            {"$push": {"email_chain": email_chain_entry}}
                        )
                    except Exception as e:
                        logger.error(f"Failed to update email chain for tickets {ado_ticket_id}/{servicenow_sys_id}: {str(e)}")
                        raise ValueError(f"Email chain update failed: {str(e)}")

                    # Update Milvus after email chain update
                    updated_ticket = self.tickets_collection.find_one({"thread_id": thread_id})
                    if updated_ticket:
                        await self.send_to_milvus(updated_ticket)

                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id,
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "message": f"Sent response for {intent.replace('_', ' ')} request: ticket created and processed",
                        "timestamp": datetime.now().isoformat()
                    })

                    if monitor_task and intent != "general_it_request":
                        await self.stop_monitoring(details["instance_id"])
                        await broadcast({
                            "type": "monitoring_stopped",
                            "email_id": email_id,
                            "instance_id": details["instance_id"],
                            "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                            "thread_id": thread_id
                        })

                    return {
                        "status": "success",
                        "ado_ticket_id": ado_ticket_id,
                        "servicenow_sys_id": servicenow_sys_id,
                        "intent": intent,
                        "actions": completed_actions,
                        "pending_actions": pending_actions
                    }

            if monitor_task:
                await self.stop_monitoring(details["instance_id"])
                await broadcast({
                    "type": "monitoring_stopped",
                    "email_id": email_id,
                    "instance_id": details["instance_id"],
                    "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                    "thread_id": thread_id
                })

            return {
                "status": "success",
                "ado_ticket_id": ado_ticket_id,
                "servicenow_sys_id": servicenow_sys_id,
                "intent": intent,
                "actions": completed_actions,
                "pending_actions": pending_actions
            }

        except Exception as e:
            logger.error(f"Error processing email ID={email_id}: {str(e)}")
            if monitor_task and details.get("instance_id") != "unspecified":
                await self.stop_monitoring(details["instance_id"])
                await broadcast({
                    "type": "monitoring_stopped",
                    "email_id": email_id,
                    "instance_id": details["instance_id"],
                    "message": f"Stopped CloudWatch monitoring for instance {details['instance_id']}",
                    "thread_id": thread_id
                })
            await broadcast({
                "type": "error",
                "email_id": email_id,
                "message": str(e),
                "thread_id": thread_id
            })
            return {
                "status": "error",
                "intent": intent or "unknown",
                "ado_ticket_id": ado_ticket_id,
                "servicenow_sys_id": servicenow_sys_id,
                "message": f"Failed to process email: {str(e)}",
                "actions": completed_actions,
                "pending_actions": pending_actions
            }

    async def stop_monitoring(self, instance_id: str):
        """Stop monitoring for the specified instance."""
        try:
            logger.info(f"Stopping monitoring for instance {instance_id}")
            if instance_id in self.monitor_tasks:
                monitor_task = self.monitor_tasks[instance_id]
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    logger.info(f"Monitoring task for instance {instance_id} cancelled")
                del self.monitor_tasks[instance_id]
            
            # Invoke the monitor plugin's stop_monitoring function with broadcast
            if "monitor" in self.kernel.plugins:
                await self.kernel.invoke(
                    self.kernel.plugins["monitor"]["stop_monitoring"],
                    instance_id=instance_id,
                    broadcast=lambda msg: logger.info(f"Monitor broadcast: {msg}")
                )
            else:
                logger.error("Monitor plugin not found in kernel.plugins")
        except Exception as e:
            logger.error(f"Error stopping monitoring for instance {instance_id}: {str(e)}")
            raise