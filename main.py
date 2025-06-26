from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import logging
import asyncio
from datetime import datetime
import uuid
import json
import os
from dotenv import load_dotenv
from semantic_kernel import Kernel
from email_reader import EmailReaderPlugin
from email_sender import EmailSenderPlugin
from ado import ADOPlugin
from git import GitPlugin
from sk_agent import SKAgent
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, HTTPException
from pydantic import BaseModel
from aws import AWSPlugin
from monitor import MonitorPlugin 
from task_manager import TaskManager
from servicenow import ServiceNowPlugin
from typing import Optional, List, Dict
import hashlib
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from starlette.websockets import WebSocketState
from starlette.exceptions import WebSocketException
from typing import Set, Type
from qdrant import QdrantManager, start_qdrant_sync
from datetime import datetime, timedelta
from openai import AsyncOpenAI
import spacy
from nltk.corpus import stopwords
from spacy.lang.en.stop_words import STOP_WORDS
from motor.motor_asyncio import AsyncIOMotorClient
from langchain.agents import initialize_agent, AgentType, AgentExecutor
from langchain.memory import ConversationSummaryMemory
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import OpenAI
from langchain.prompts import PromptTemplate
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain.tools import BaseTool
from langchain_core.pydantic_v1 import BaseModel as LangChainBaseModel, Field
import dateparser
import openai

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("agent.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
load_dotenv()

OPEN_AI_KEY = os.getenv("OPEN_AI_KEY")

# Explicitly define websocket_clients as a Set[WebSocket]
websocket_clients: Set[WebSocket] = set()

# Initialize MongoDB
client = AsyncIOMotorClient(os.getenv("MONGODB_URL", "mongodb://localhost:27017/"))
mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client["email_agent"]
tickets_collection = db["tickets"]
conversation_collection = db["conversation_history"]
sync_metadata_collection = db["sync_metadata"]

# Create indexes with error handling
try:
    tickets_collection.create_index("ado_ticket_id", unique=True, sparse=True, name="ado_ticket_id_1")
    logger.info("Created sparse unique index on ado_ticket_id")
except Exception as e:
    logger.warning(f"Failed to create ado_ticket_id index: {str(e)}")

try:
    tickets_collection.create_index("servicenow_sys_id", unique=True, sparse=True, name="servicenow_sys_id_1")
    logger.info("Created sparse unique index on servicenow_sys_id")
except Exception as e:
    logger.warning(f"Failed to create servicenow_sys_id index: {str(e)}")

try:
    tickets_collection.create_index("thread_id", name="thread_id_1")
    logger.info("Created index on thread_id")
except Exception as e:
    logger.warning(f"Failed to create thread_id index: {str(e)}")

logger.info("Initialized MongoDB: email_agent.tickets")

openai_client = AsyncOpenAI(api_key=os.getenv("OPEN_AI_KEY"))
nlp = spacy.load("en_core_web_sm")
STOP_WORDS = set(stopwords.words("english"))

# Initialize QdrantManager
qdrant_manager = QdrantManager(tickets_collection, sync_metadata_collection)

# Global state
is_running = False
email_task = None
ticket_task = None
session_id = None
ticket_info = {}
websocket_clients = []

def cleanup_temp_files(temp_files):
    """Delete temporary files."""
    for file_path in temp_files:
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.info(f"Deleted temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error deleting temporary file {file_path}: {str(e)}")

async def process_emails(platforms: list[str] = ["ado", "servicenow"]):
    kernel = Kernel()
    kernel.add_plugin(EmailReaderPlugin(), plugin_name="email_reader")
    kernel.add_plugin(EmailSenderPlugin(), plugin_name="email_sender")
    if "ado" in platforms:
        kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    if "servicenow" in platforms:
        kernel.add_plugin(ServiceNowPlugin(), plugin_name="servicenow")
    kernel.add_plugin(GitPlugin(), plugin_name="git")
    kernel.add_plugin(AWSPlugin(), plugin_name="aws")
    kernel.add_plugin(MonitorPlugin(), plugin_name="monitor")
    agent = SKAgent(kernel, tickets_collection, platforms=platforms)
    logger.info(f"Registered plugins: {list(kernel.plugins.keys())}")
    logger.debug(f"Monitor plugin functions: {list(kernel.plugins['monitor'].functions.keys())}")

    valid_domain = "@quadranttechnologies.com"
    
    while is_running:
        try:
            logger.info("Checking for new unread emails...")
            email_result = await kernel.invoke(
                kernel.plugins["email_reader"]["fetch_new_emails"],
                limit=1
            )
            emails = email_result.value if email_result else []
            
            if not emails:
                logger.info("No new unread emails found.")
            else:
                for email in emails:
                    email_id = email["id"]
                    thread_id = email.get("threadId", email_id)
                    attachments = email.get("attachments", [])
                    temp_files = [a['path'] for a in attachments]
                    
                    sender_email = email.get("from", "")
                    is_valid_domain = valid_domain in sender_email
                    
                    if not is_valid_domain:
                        logger.warning(f"Unauthorized email from {sender_email}")
                        await broadcast({
                            "type": "spam_alert",
                            "email_id": email_id,
                            "subject": email['subject'],
                            "sender": sender_email,
                            "message": f"Email rejected: Sender not from authorized domain"
                        })
                        cleanup_temp_files(temp_files)
                        continue
                    
                    logger.info(f"Processing email - Subject: {email['subject']}, From: {sender_email}")

                    existing_ticket = tickets_collection.find_one({"thread_id": thread_id})

                    if existing_ticket and email_id in [e["email_id"] for e in existing_ticket.get("email_chain", [])]:
                        logger.info(f"Email ID={email_id} already in email_chain, skipping.")
                        cleanup_temp_files(temp_files)
                        continue

                    email_content = f"""From: {sender_email}
Subject: {email['subject']}
Date: {email.get('received', datetime.now().isoformat())}
To: {os.getenv('EMAIL_ADDRESS', 'Unknown')}

{email['body']}
"""

                    email_intent_result = await agent.analyze_intent(email["subject"], email["body"], attachments)
                    intent = email_intent_result.get("intent", "general_it_request")
                    logger.info(f"Email intent analysis: {email_intent_result}")

                    email_chain_entry = {
                        "email_id": email_id,
                        "from": sender_email,
                        "subject": email["subject"],
                        "body": email["body"],
                        "timestamp": email.get("received", datetime.now().isoformat()),
                        "attachments": [
                            {"filename": a["filename"], "mimeType": a["mimeType"]} 
                            for a in attachments
                        ]
                    }

                    if intent == "non_intent":
                        logger.info(f"Non-intent email detected (ID={email_id}). Adding to email_chain and stopping processing.")
                        if existing_ticket:
                            tickets_collection.update_one(
                                {"thread_id": thread_id},
                                {"$push": {"email_chain": email_chain_entry}}
                            )
                        else:
                            ticket_record = {
                                "platform": platforms,
                                "sender": sender_email,
                                "subject": email["subject"],
                                "thread_id": thread_id,
                                "email_id": email_id,
                                "ticket_title": "Non-intent email",
                                "ticket_description": email_intent_result["ticket_description"],
                                "email_timestamp": datetime.now().isoformat(),
                                "updates": [],
                                "email_chain": [email_chain_entry],
                                "pending_actions": False,
                                "type_of_request": "non_intent",
                                "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]},
                                "status": "Non-intent"  # Added status field
                            }
                            # Dynamically add platform-specific fields
                            if "ado" in platforms:
                                ticket_record["ado_ticket_id"] = None
                            if "servicenow" in platforms:
                                ticket_record["servicenow_sys_id"] = None
                            
                            try:
                                tickets_collection.insert_one(ticket_record)
                            except Exception as e:
                                logger.error(f"Failed to insert non-intent ticket: {str(e)}")
                                await broadcast({
                                    "type": "error",
                                    "email_id": email_id,
                                    "message": f"Failed to store non-intent ticket: {str(e)}"
                                })
                        cleanup_temp_files(temp_files)
                        continue

                    if intent == "request_summary":
                        if not existing_ticket:
                            logger.warning(f"No existing ticket found for thread_id={thread_id} for summary request")
                            await broadcast({
                                "type": "error",
                                "email_id": email_id,
                                "message": "No existing ticket found for summary request"
                            })
                            email_response = (
                                f"Hi,\n\nI couldn't find an existing request associated with this thread. "
                                f"Please provide the ticket ID or more details, and I'll be happy to assist!\n\nBest,\nAgent\nIT Support"
                            )
                            reply_result = await kernel.invoke(
                                kernel.plugins["email_sender"]["send_reply"],
                                to=sender_email,
                                subject=email["subject"],
                                body=email_response,
                                thread_id=thread_id,
                                message_id=email_id,
                                attachments=attachments,
                                remediation=""
                            )
                            email_status = bool(reply_result and reply_result.value)
                            email_message_id = reply_result.value.get("message_id") if reply_result and reply_result.value else str(uuid.uuid4())

                            if email_status:
                                reply_chain_entry = {
                                    "email_id": email_message_id,
                                    "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                                    "subject": email["subject"],
                                    "body": email_response,
                                    "timestamp": datetime.now().isoformat(),
                                    "attachments": []
                                }
                                ticket_record = {
                                    "platform": platforms,
                                    "sender": sender_email,
                                    "subject": email["subject"],
                                    "thread_id": thread_id,
                                    "email_id": email_id,
                                    "ticket_title": "Summary Request",
                                    "ticket_description": "User requested summary but no ticket found",
                                    "email_timestamp": datetime.now().isoformat(),
                                    "updates": [],
                                    "pending_actions": False,
                                    "type_of_request": "request_summary",
                                    "details": {},
                                    "status": "No Ticket Found"  # Added status field
                                }
                                # Dynamically add platform-specific fields
                                if "ado" in platforms:
                                    ticket_record["ado_ticket_id"] = None
                                if "servicenow" in platforms:
                                    ticket_record["servicenow_sys_id"] = None
                                
                                try:
                                    tickets_collection.update_one(
                                        {"thread_id": thread_id},
                                        {
                                            "$set": ticket_record,
                                            "$push": {
                                                "email_chain": {
                                                    "$each": [email_chain_entry, reply_chain_entry]
                                                }
                                            }
                                        },
                                        upsert=True
                                    )
                                    await broadcast({
                                        "type": "email_reply",
                                        "email_id": email_id,
                                        "thread_id": thread_id,
                                        "message": "Sent response indicating no existing ticket found for summary request",
                                        "timestamp": datetime.now().isoformat()
                                    })
                                except Exception as e:
                                    logger.error(f"Failed to insert summary request ticket: {str(e)}")
                                    await broadcast({
                                        "type": "error",
                                        "email_id": email_id,
                                        "message": f"Failed to store summary request ticket: {str(e)}"
                                    })
                            cleanup_temp_files(temp_files)
                            continue

                        summary_result = await agent.generate_summary_response(existing_ticket, email_content, request_source="email")
                        email_response = summary_result["email_response"]

                        reply_result = await kernel.invoke(
                            kernel.plugins["email_sender"]["send_reply"],
                            to=sender_email,
                            subject=email["subject"],
                            body=email_response,
                            thread_id=thread_id,
                            message_id=email_id,
                            attachments=attachments,
                            remediation=""
                        )
                        email_status = bool(reply_result and reply_result.value)
                        email_message_id = reply_result.value.get("message_id") if reply_result and reply_result.value else str(uuid.uuid4())

                        if email_status:
                            reply_chain_entry = {
                                "email_id": email_message_id,
                                "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                                "subject": email["subject"],
                                "body": email_response,
                                "timestamp": datetime.now().isoformat(),
                                "attachments": []
                            }
                            try:
                                tickets_collection.update_one(
                                    {"thread_id": thread_id},
                                    {
                                        "$push": {
                                            "email_chain": {
                                                "$each": [email_chain_entry, reply_chain_entry]
                                            }
                                        },
                                        "$set": {
                                            "status": existing_ticket.get("status", "Unknown")  # Preserve existing status
                                        }
                                    }
                                )
                                await broadcast({
                                    "type": "email_reply",
                                    "email_id": email_id,
                                    "thread_id": thread_id,
                                    "message": "Sent summary of ticket status",
                                    "timestamp": datetime.now().isoformat()
                                })
                            except Exception as e:
                                logger.error(f"Failed to update ticket with summary reply: {str(e)}")
                                await broadcast({
                                    "type": "error",
                                    "email_id": email_id,
                                    "message": f"Failed to update ticket with summary reply: {str(e)}"
                                })
                        cleanup_temp_files(temp_files)
                        continue

                    result = await agent.process_email(email, broadcast, existing_ticket, email_content)
                    logger.info(f"Agent result for email ID={email_id}: {result}")
                    
                    cleanup_temp_files(temp_files)
                    
                    if result["status"] == "success":
                        ado_ticket_id = result.get("ado_ticket_id") if "ado" in platforms else None
                        servicenow_sys_id = result.get("servicenow_sys_id") if "servicenow" in platforms else None
                        intent = result.get("intent", "general_it_request")
                        pending_actions = result.get("pending_actions", False)
                        is_follow_up = bool(existing_ticket)
                        ticket_status = result.get("ticket_status", "Pending")  # Get status from result

                        repo_name = email_intent_result.get("repo_name")
                        github_username = email_intent_result.get("github_username")
                        access_type = email_intent_result.get("access_type", "read")
                        ticket_title = email_intent_result.get("ticket_title", email["subject"])
                        ticket_description = email_intent_result.get("ticket_description", f"IT request for {email['subject']}")

                        if not is_follow_up:
                            ticket_record = {
                                "platform": platforms,
                                "sender": sender_email,
                                "subject": email["subject"],
                                "thread_id": thread_id,
                                "email_id": email_id,
                                "ticket_title": ticket_title,
                                "ticket_description": ticket_description,
                                "email_timestamp": datetime.now().isoformat(),
                                "updates": [],
                                "email_chain": [email_chain_entry],
                                "pending_actions": pending_actions,
                                "type_of_request": "github" if intent.startswith("github_") else intent,
                                "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]},
                                "last_fields": {},
                                "status": ticket_status  # Added status field
                            }
                            # Dynamically add platform-specific fields
                            if "ado" in platforms and ado_ticket_id:
                                ticket_record["ado_ticket_id"] = ado_ticket_id
                            if "servicenow" in platforms and servicenow_sys_id:
                                ticket_record["servicenow_sys_id"] = servicenow_sys_id
                            
                            if intent == "github_access_request":
                                github_details = {
                                    "request_type": intent,
                                    "repo_name": repo_name if repo_name and repo_name != "unspecified" else "",
                                    "username": github_username if github_username and github_username != "unspecified" else "",
                                    "access_type": access_type if access_type and access_type != "unspecified" else "read",
                                    "status": "completed" if result.get("github", {}).get("success") else "failed",
                                    "message": result.get("github", {}).get("message", "GitHub access request initiated")
                                }
                                ticket_record["details"]["github"] = [github_details]
                            elif intent == "general_it_request":
                                sender_username = sender_email.split('@')[0] if '@' in sender_email else sender_email
                                detailed_description = ticket_description
                                if sender_username.lower() not in detailed_description.lower():
                                    detailed_description = f"User {sender_username}: {detailed_description}"
                                general_details = {
                                    "request_type": "general_it_request",
                                    "status": ticket_status,  # Use ticket_status
                                    "message": detailed_description,
                                    "requester": sender_username
                                }
                                ticket_record["details"]["general"] = [general_details]
                                ticket_record["ticket_description"] = detailed_description
                            
                            try:
                                tickets_collection.insert_one(ticket_record)
                                ado_url = f"https://dev.azure.com/{os.getenv('ADO_ORGANIZATION')}/{os.getenv('ADO_PROJECT')}/_workitems/edit/{ado_ticket_id}" if ado_ticket_id else None
                                servicenow_url = f"{os.getenv('SERVICENOW_INSTANCE_URL')}/nav_to.do?uri=incident.do?sys_id={servicenow_sys_id}" if servicenow_sys_id else None
                                await broadcast({
                                    "type": "ticket_created",
                                    "email_id": email_id,
                                    "platform": platforms,
                                    "ado_ticket_id": ado_ticket_id,
                                    "servicenow_sys_id": servicenow_sys_id,
                                    "subject": email["subject"],
                                    "intent": intent,
                                    "request_type": intent,
                                    "ado_url": ado_url,
                                    "servicenow_url": servicenow_url,
                                    "status": ticket_status  # Broadcast status
                                })
                            except Exception as e:
                                logger.error(f"Failed to insert ticket for email ID={email_id}: {str(e)}")
                                continue
                        else:
                            if intent.startswith("github_"):
                                updated_ticket = tickets_collection.find_one({
                                    "$or": [
                                        {"ado_ticket_id": ado_ticket_id, "platform": {"$in": ["ado", ["ado", "servicenow"]]}} if ado_ticket_id else {},
                                        {"servicenow_sys_id": servicenow_sys_id, "platform": {"$in": ["servicenow", ["ado", "servicenow"]]}} if servicenow_sys_id else {}
                                    ]
                                })
                                all_completed = await agent.are_all_actions_completed(updated_ticket)
                                ado_status = "Done" if all_completed else "Doing"
                                servicenow_state = "Resolved" if all_completed else "In Progress"
                                ticket_status = ado_status if ado_ticket_id else servicenow_state
                                
                                platform_value = "both" if len(platforms) > 1 else platforms[0]
                                update_operation = {
                                    "$push": {
                                        "email_chain": email_chain_entry,
                                        "updates": {
                                            "comment": f"Processed {intent} for {github_username} on {repo_name}",
                                            "status": ticket_status,  # Update status
                                            "platform": platform_value,
                                            "revision_id": f"git-{intent.split('_')[1]}-{ado_ticket_id or servicenow_sys_id}-{len(updated_ticket.get('updates', [])) + 1}",
                                            "email_sent": False,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    },
                                    "$set": {
                                        "pending_actions": pending_actions,
                                        "status": ticket_status  # Set ticket status
                                    }
                                }
                                try:
                                    tickets_collection.update_one(
                                        {
                                            "$or": [
                                                {"ado_ticket_id": ado_ticket_id, "platform": {"$in": ["ado", ["ado", "servicenow"]]}} if ado_ticket_id else {},
                                                {"servicenow_sys_id": servicenow_sys_id, "platform": {"$in": ["servicenow", ["ado", "servicenow"]]}} if servicenow_sys_id else {}
                                            ]
                                        },
                                        update_operation
                                    )
                                    
                                    if ado_ticket_id and "ado" in platforms:
                                        await kernel.invoke(
                                            kernel.plugins["ado"]["update_ticket"],
                                            ticket_id=ado_ticket_id,
                                            status=ado_status,
                                            comment=f"Processed {intent} for {github_username} on {repo_name}"
                                        )
                                    if servicenow_sys_id and "servicenow" in platforms:
                                        await kernel.invoke(
                                            kernel.plugins["servicenow"]["update_ticket"],
                                            ticket_id=servicenow_sys_id,
                                            state=servicenow_state,
                                            comment=f"Processed {intent} for {github_username} on {repo_name}"
                                        )
                                    
                                    await broadcast({
                                        "type": "ticket_updated",
                                        "email_id": email_id,
                                        "platform": platforms,
                                        "ado_ticket_id": ado_ticket_id,
                                        "servicenow_sys_id": servicenow_sys_id,
                                        "thread_id": thread_id,
                                        "status": ticket_status,  # Broadcast status
                                        "request_type": intent,
                                        "comment": f"Processed {intent} for {github_username} on {repo_name}"
                                    })
                                except Exception as e:
                                    logger.error(f"Failed to update ticket for email ID={email_id}: {str(e)}")
                                    await broadcast({
                                        "type": "error",
                                        "email_id": email_id,
                                        "platform": platforms,
                                        "message": f"Failed to update ticket: {str(e)}"
                                    })
                            elif intent == "general_it_request":
                                status = "updated"
                                comment = f"Updated general IT request: {email['subject']}"
                                platform_value = "both" if len(platforms) > 1 else platforms[0]
                                ticket_status = status
                                
                                update_operation = {
                                    "$push": {
                                        "updates": {
                                            "comment": comment,
                                            "status": ticket_status,
                                            "platform": platform_value,
                                            "revision_id": f"general-update-{ado_ticket_id or servicenow_sys_id}-{len(existing_ticket.get('updates', [])) + 1}",
                                            "email_sent": False,
                                            "email_timestamp": datetime.now().isoformat()
                                        },
                                        "email_chain": email_chain_entry
                                    },
                                    "$set": {
                                        "pending_actions": False,
                                        "status": ticket_status  # Set ticket status
                                    }
                                }
                                
                                general_details = {
                                    "request_type": "general_it_request",
                                    "status": ticket_status,
                                    "message": comment
                                }
                                
                                if "general" not in existing_ticket.get("details", {}):
                                    update_operation["$set"]["details.general"] = [general_details]
                                else:
                                    update_operation["$push"]["details.general"] = general_details
                                
                                try:
                                    tickets_collection.update_one(
                                        {
                                            "$or": [
                                                {"ado_ticket_id": ado_ticket_id, "platform": {"$in": ["ado", ["ado", "servicenow"]]}} if ado_ticket_id else {},
                                                {"servicenow_sys_id": servicenow_sys_id, "platform": {"$in": ["servicenow", ["ado", "servicenow"]]}} if servicenow_sys_id else {}
                                            ]
                                        },
                                        update_operation
                                    )
                                    
                                    await broadcast({
                                        "type": "ticket_updated",
                                        "email_id": email_id,
                                        "platform": platforms,
                                        "ado_ticket_id": ado_ticket_id,
                                        "servicenow_sys_id": servicenow_sys_id,
                                        "thread_id": thread_id,
                                        "status": ticket_status,
                                        "request_type": intent,
                                        "comment": comment
                                    })
                                except Exception as e:
                                    logger.error(f"Failed to update ticket for email ID={email_id}: {str(e)}")
                                    await broadcast({
                                        "type": "error",
                                        "email_id": email_id,
                                        "platform": platforms,
                                        "message": f"Failed to update ticket: {str(e)}"
                                    })
                    else:
                        logger.error(f"Failed to process email ID={email_id}: {result['message']}")
                        await broadcast({
                            "type": "error",
                            "email_id": email_id,
                            "platform": platforms,
                            "message": f"Failed to process email: {result['message']}"
                        })

            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Error in email processing loop: {str(e)}")
            await asyncio.sleep(20)

async def process_tickets(agent: SKAgent, platforms: list[str]):
    kernel = Kernel()
    if "ado" in platforms:
        kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    if "servicenow" in platforms:
        kernel.add_plugin(ServiceNowPlugin(), plugin_name="servicenow")
    kernel.add_plugin(EmailSenderPlugin(), plugin_name="email_sender")

    while is_running:
        try:
            logger.info(f"Checking for ticket updates in session {session_id} for platforms {platforms}...")
            tickets = tickets_collection.find()
            
            for ticket in tickets:
                ado_ticket_id = ticket.get("ado_ticket_id") if "ado" in platforms else None
                servicenow_sys_id = ticket.get("servicenow_sys_id") if "servicenow" in platforms else None
                if not ado_ticket_id and not servicenow_sys_id:
                    continue
                
                ado_new_updates = []
                servicenow_new_updates = []
                
                # Check ADO updates if selected
                if ado_ticket_id and "ado" in platforms:
                    ado_update_result = await kernel.invoke(
                        kernel.plugins["ado"]["get_ticket_updates"],
                        ticket_id=ado_ticket_id
                    )
                    ado_updates = ado_update_result.value if ado_update_result else []
                    ado_ticket_data = ticket_info.get(ado_ticket_id, {"last_revision_id": 0})
                    ado_last_revision_id = ado_ticket_data["last_revision_id"]
                    ado_new_updates = [u for u in ado_updates if u['revision_id'] > ado_last_revision_id]
                
                # Check ServiceNow updates if selected
                if servicenow_sys_id and "servicenow" in platforms:
                    servicenow_update_result = await kernel.invoke(
                        kernel.plugins["servicenow"]["get_ticket_updates"],
                        ticket_id=servicenow_sys_id
                    )
                    servicenow_updates = servicenow_update_result.value if servicenow_update_result else []
                    servicenow_ticket_data = ticket_info.get(servicenow_sys_id, {"last_updated_on": ""})
                    servicenow_last_updated_on = servicenow_ticket_data["last_updated_on"]
                    servicenow_new_updates = [
                        u for u in servicenow_updates 
                        if u["sys_updated_on"] > servicenow_last_updated_on
                    ]
                    logger.debug(f"ServiceNow updates for sys_id={servicenow_sys_id}: {servicenow_new_updates}")
                
                if ado_new_updates or servicenow_new_updates:
                    logger.info(f"Found {len(ado_new_updates)} ADO updates and {len(servicenow_new_updates)} ServiceNow updates for ticket ADO={ado_ticket_id}/SN={servicenow_sys_id}")
                    attachments = ticket.get("details", {}).get("attachments", [])
                    
                    update_operations = []
                    email_status = False
                    email_message_id = None
                    email_chain_entry = None
                    ticket_status = ticket.get("status", "Unknown")

                    # Deduplicate ServiceNow updates by content hash
                    existing_update_hashes = [u.get("update_hash") for u in ticket.get("updates", []) if u.get("update_hash")]
                    new_updates_to_process = []
                    for update in servicenow_new_updates:
                        update_content = f"{update['field']}:{update['old_value']}:{update['new_value']}:{update['sys_updated_on']}"
                        update_hash = hashlib.md5(update_content.encode()).hexdigest()
                        if update_hash not in existing_update_hashes:
                            new_updates_to_process.append(update)
                            update["update_hash"] = update_hash
                            if update["field"] == "state":
                                ticket_status = update["new_value"]

                    # Update ticket_status for ADO updates
                    for update in ado_new_updates:
                        ticket_status = update["status"]

                    # Analyze and send email
                    if new_updates_to_process or ado_new_updates:
                        update_result = await agent.analyze_ticket_update(
                            servicenow_sys_id or ado_ticket_id,
                            ado_updates=ado_new_updates,
                            servicenow_updates=new_updates_to_process,
                            attachments=attachments
                        )
                        
                        if update_result["update_intent"] != "error":
                            sender = ticket.get('sender', 'Unknown')
                            subject = ticket.get('subject', f"Update for ServiceNow Ticket SN={servicenow_sys_id}")
                            thread_id = ticket.get('thread_id', str(uuid.uuid4()))
                            email_id = str(uuid.uuid4())
                            
                            existing_email_ids = [e["email_id"] for e in ticket.get("email_chain", [])]
                            if email_id not in existing_email_ids:
                                reply_result = await kernel.invoke(
                                    kernel.plugins["email_sender"]["send_reply"],
                                    to=sender,
                                    subject=subject,
                                    body=update_result["email_response"],
                                    thread_id=thread_id,
                                    message_id=email_id,
                                    attachments=attachments,
                                    remediation=update_result["remediation"]
                                )
                                email_status = bool(reply_result and reply_result.value)
                                email_message_id = reply_result.value.get("message_id") if reply_result and reply_result.value else email_id
                                
                                email_chain_entry = {
                                    "email_id": email_message_id,
                                    "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                                    "subject": subject,
                                    "body": update_result["email_response"],
                                    "timestamp": datetime.now().isoformat(),
                                    "attachments": [
                                        {"filename": a["filename"], "mimeType": a["mimeType"]} 
                                        for a in attachments
                                    ]
                                }
                                
                                if email_status:
                                    await broadcast({
                                        "type": "email_reply",
                                        "email_id": email_message_id,
                                        "ado_ticket_id": ado_ticket_id,
                                        "servicenow_sys_id": servicenow_sys_id,
                                        "thread_id": thread_id,
                                        "message": f"Sent update notification for ticket ADO={ado_ticket_id}/SN={servicenow_sys_id}: {update_result.get('summary', 'Ticket status updated')}",
                                        "timestamp": datetime.now().isoformat()
                                    })
                    
                    # Store ADO updates
                    for update in ado_new_updates:
                        update_operation = {
                            "$push": {
                                "updates": {
                                    "source": "ado",
                                    "comment": update["comment"] or "No comment provided",
                                    "status": update["status"],
                                    "revision_id": update["revision_id"],
                                    "email_sent": False,
                                    "email_message_id": None,
                                    "email_timestamp": datetime.now().isoformat()
                                }
                            },
                            "$set": {
                                "status": update["status"]  # Update ticket status
                            }
                        }
                        update_operations.append(update_operation)
                    
                    # Store ServiceNow updates
                    for update in new_updates_to_process:
                        update_operation = {
                            "$push": {
                                "updates": {
                                    "source": "servicenow",
                                    "field": update["field"],
                                    "old_value": update["old_value"],
                                    "new_value": update["new_value"],
                                    "sys_updated_on": update["sys_updated_on"],
                                    "update_hash": update["update_hash"],
                                    "email_sent": email_status,
                                    "email_message_id": email_message_id if email_status else None,
                                    "email_timestamp": datetime.now().isoformat()
                                }
                            },
                            "$set": {
                                "status": ticket_status  # Update ticket status
                            }
                        }
                        update_operations.append(update_operation)
                    
                    if email_status and email_chain_entry and email_message_id not in existing_email_ids:
                        update_operations.append({
                            "$push": {
                                "email_chain": email_chain_entry
                            }
                        })
                    
                    # Apply update operations
                    for operation in update_operations:
                        try:
                            tickets_collection.update_one(
                                {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                                operation,
                                upsert=True
                            )
                        except Exception as e:
                            logger.error(f"Failed to apply update operation for ticket ADO={ado_ticket_id}/SN={servicenow_sys_id}: {str(e)}")
                            await broadcast({
                                "type": "error",
                                "email_id": email_id,
                                "message": f"Failed to update ticket: {str(e)}",
                                "thread_id": thread_id
                            })
                    
                    # Update ticket_info
                    ticket_key = ado_ticket_id or servicenow_sys_id
                    ticket_info[ticket_key] = ticket_info.get(ticket_key, {})
                    if ado_new_updates:
                        ticket_info[ticket_key]["last_revision_id"] = max(u['revision_id'] for u in ado_new_updates)
                    if new_updates_to_process:
                        ticket_info[ticket_key]["last_updated_on"] = max(u["sys_updated_on"] for u in new_updates_to_process)
                    ticket_info[ticket_key].update({
                        "sender": ticket.get('sender', 'Unknown'),
                        "subject": ticket.get('subject', f"Update for ServiceNow Ticket SN={servicenow_sys_id}"),
                        "thread_id": ticket.get('thread_id', str(uuid.uuid4())),
                        "email_id": email_message_id if email_status else ticket.get('email_id', str(uuid.uuid4())),
                        "status": ticket_status  # Update ticket_info status
                    })
                    
                    # Update Milvus
                    updated_ticket = tickets_collection.find_one({"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id})
                    if updated_ticket:
                        await agent.send_to_milvus(updated_ticket)
                        tickets_collection.update_one(
                            {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                            {"$set": {"in_milvus": True}},
                            upsert=True
                        )
                
                elif not ticket.get("in_milvus", False):
                    await agent.send_to_milvus(ticket)
                    tickets_collection.update_one(
                        {"ado_ticket_id": ado_ticket_id, "servicenow_sys_id": servicenow_sys_id},
                        {"$set": {"in_milvus": True}},
                        upsert=True
                    )
            
            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Error in ticket processing loop: {str(e)}")
            await broadcast({
                "type": "error",
                "email_id": str(uuid.uuid4()),
                "message": f"Ticket processing error: {str(e)}",
                "thread_id": str(uuid.uuid4())
            })
            await asyncio.sleep(20)

class RunAgentRequest(BaseModel):
    platforms: list[str] = ["ado", "servicenow"]

@app.post("/run-agent")
async def run_agent(request: RunAgentRequest):
    global is_running, email_task, ticket_task, qdrant_task, session_id, ticket_info
    if is_running:
        logger.info("Agent is already running.")
        return {"status": "info", "message": "Agent is already running"}
    
    # Validate platforms
    valid_platforms = {"ado", "servicenow"}
    platforms = [p.lower() for p in request.platforms if p.lower() in valid_platforms]
    if not platforms:
        platforms = ["ado", "servicenow"]  # Default to both if invalid or empty
    
    logger.info(f"Starting email and ticket tracking agent for platforms {platforms}...")
    session_id = str(uuid.uuid4())
    ticket_info = {}
    kernel = Kernel()
    if "ado" in platforms:
        kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    if "servicenow" in platforms:
        kernel.add_plugin(ServiceNowPlugin(), plugin_name="servicenow")
    
    # Initialize agent with platforms
    agent = SKAgent(kernel, tickets_collection, platforms=platforms)
    
    # Fetch existing tickets for selected platforms
    if "ado" in platforms:
        work_items_result = await kernel.invoke(
            kernel.plugins["ado"]["get_all_work_items"]
        )
        work_items = work_items_result.value if work_items_result else []
        for work_item in work_items:
            ado_ticket_id = work_item['id']
            updates_result = await kernel.invoke(
                kernel.plugins["ado"]["get_ticket_updates"],
                ticket_id=ado_ticket_id
            )
            updates = updates_result.value if updates_result else []
            last_revision_id = max((u['revision_id'] for u in updates), default=0)
            ticket_record = tickets_collection.find_one({"ado_ticket_id": ado_ticket_id})
            ticket_info[ado_ticket_id] = {
                "sender": ticket_record.get('sender', 'Unknown') if ticket_record else 'Unknown',
                "subject": ticket_record.get("subject", f"Update for Ticket {ado_ticket_id}") if ticket_record else f"Update for Ticket {ado_ticket_id}",
                "thread_id": ticket_record.get('thread_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
                "email_id": ticket_record.get('email_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
                "last_revision_id": last_revision_id,
                "last_updated_on": ""
            }
    
    if "servicenow" in platforms:
        incidents_result = await kernel.invoke(
            kernel.plugins["servicenow"]["get_all_incidents"]
        )
        incidents = incidents_result.value if incidents_result else []
        for incident in incidents:
            servicenow_sys_id = incident['sys_id']
            updates_result = await kernel.invoke(
                kernel.plugins["servicenow"]["get_ticket_updates"],
                ticket_id=servicenow_sys_id
            )
            updates = updates_result.value if updates_result else []
            last_updated_on = max((u['sys_updated_on'] for u in updates), default="") if updates else ""
            ticket_record = tickets_collection.find_one({"servicenow_sys_id": servicenow_sys_id})
            ticket_info[servicenow_sys_id] = {
                "sender": ticket_record.get('sender', 'Unknown') if ticket_record else 'Unknown',
                "subject": ticket_record.get("subject", f"Update for Ticket {servicenow_sys_id}") if ticket_record else f"Update for Ticket {servicenow_sys_id}",
                "thread_id": ticket_record.get('thread_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
                "email_id": ticket_record.get('email_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
                "last_revision_id": 0,
                "last_updated_on": last_updated_on
            }

    is_running = True
    email_task = asyncio.create_task(process_emails(platforms))
    ticket_task = asyncio.create_task(process_tickets(agent, platforms))
    qdrant_task = asyncio.create_task(start_qdrant_sync(tickets_collection))
    
    await broadcast({"type": "session", "session_id": session_id, "status": "started"})
    return {"status": "success", "message": f"Agent started with session ID: {session_id} for platforms: {platforms}"}

class UserQuery(BaseModel):
    query: str

async def preprocess_query(query: str) -> Dict:
    try:
        normalized_query = query.lower().replace("git hub", "github").replace("aws request", "aws")
        doc = nlp(normalized_query)
        tokens = [token.lemma_ for token in doc if token.text not in STOP_WORDS and not token.is_punct]
        query_for_embedding = " ".join(tokens + [ent.text for ent in doc.ents])

        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
                    You are an AI agent (lakshmeesh777@gmail.com) handling ticket queries. Classify the intent(s) of a user query with a hierarchical structure (parent.child) based on the ticket data structure:
                    - platform: Infrastructure platform (servicenow, ado, jira)
                    - sender: Email of the user who raised the ticket
                    - subject: Email subject
                    - thread_id: Email chain ID
                    - email_id: Unique email ID
                    - ticket_title: Agent-created ticket title
                    - ticket_description: Agent-created ticket description
                    - email_timestamp: Email receipt time
                    - updates: Array of ticket updates
                      - source: Platform (servicenow, ado, jira)
                      - field: Updated field (e.g., work_notes, close_notes, state)
                      - new_value: Work notes or comment added
                      - comment: Same as new_value (work notes)
                      - sys_updated_on: Update timestamp
                      - email_sent: Whether an email was sent for the update
                    - email_chain: Array of emails
                      - email_id: Unique ID
                      - from: Sender (user or agent: lakshmeesh777@gmail.com)
                      - subject: Email subject
                      - body: Email content
                      - timestamp: Email sent time
                    - pending_actions: Boolean indicating pending tasks
                    - type_of_request: Request type (e.g., github_access_request, incident)
                    - details: Action-specific details (e.g., username, repo_name)
                    - status: Ticket status (1=New, 2=In Progress, 6=Resolved)

                    Intents (parent.child):
                    - info.overview: General ticket details (title, description, sender, type_of_request)
                    - info.status: Current ticket status (top-level status field)
                    - update.last_update: Most recent update (new_value or comment)
                    - update.timeline: Chronological updates (new_value, comment, sys_updated_on)
                    - update.work_notes: Work notes (new_value or comment where field is work_notes/close_notes)
                    - email.last_email: Most recent email from email_chain
                    - email.user_email: Most recent email from user (not lakshmeesh777@gmail.com)
                    - email.agent_email: Most recent email from lakshmeesh777@gmail.com
                    - email.email_thread: Full email chain
                    - action.access: Details from details field (e.g., username, repo_name)
                    - action.pending_actions: Status of pending_actions
                    - actor.sender: Ticket sender
                    - actor.assignee: Users in updates.assigned_to
                    - analytical.count_updates: Number of updates
                    - analytical.count_emails: Number of emails
                    - analytical.count_tickets: Count of tickets matching query criteria (e.g., type_of_request, keywords)
                    - comparative.compare_updates: Compare updates across tickets or within a ticket
                    - platform_specific.platform_filter: Filter by platform

                    Only set 'types' to a valid type_of_request (e.g., github_access_request) if explicitly mentioned in the query. Return JSON:
                    {
                        "intents": ["parent.child1", "parent.child2"],
                        "types": ["valid_type_of_request"],
                        "entities": {"ticket_id": "value", "username": "value", "platform": "value", "time_qualifier": "value", "keywords": ["value1", "value2"]}
                    }
                    """
                },
                {"role": "user", "content": normalized_query}
            ]
        )
        intent_data = json.loads(response.choices[0].message.content)
        intents = intent_data.get("intents", ["info.overview"])
        types = intent_data.get("types", [])
        entities = intent_data.get("entities", {})
        # Detect count queries
        if any(word in normalized_query for word in ["how many", "count", "number of"]) and "ticket" in normalized_query:
            intents = ["analytical.count_tickets"]
            entities["keywords"] = tokens  # Capture tokens as keywords for filtering
        logger.info(f"Intents: {intents}, Types: {types}, Entities: {entities}")
        return {
            "query_for_embedding": query_for_embedding,
            "intents": intents,
            "types": types,
            "entities": entities
        }
    except Exception as e:
        logger.error(f"Failed to preprocess query: {str(e)}")
        return {"query_for_embedding": query.lower(), "intents": ["info.overview"], "types": [], "entities": {}}

async def generate_response(intent: str, ticket: Dict, entities: Dict, results: List[Dict] = None) -> str:
    ticket_id = ticket.get("ado_ticket_id", ticket.get("servicenow_sys_id", "N/A")) if ticket else "N/A"
    title = ticket.get("ticket_title", "N/A") if ticket else "N/A"
    description = ticket.get("ticket_description", "N/A") if ticket else "N/A"
    request_type = ticket.get("type_of_request", "N/A") if ticket else "N/A"
    sender = ticket.get("sender", "N/A") if ticket else "N/A"
    updates = ticket.get("updates", []) if ticket else []
    email_chain = ticket.get("email_chain", []) if ticket else []
    details = ticket.get("details", {}) if ticket else {}
    status = ticket.get("status", "N/A") if ticket else "N/A"
    status_map = {"1": "New", "2": "In Progress", "6": "Resolved"}

    def format_timestamp(timestamp: str) -> str:
        try:
            if isinstance(timestamp, str) and timestamp.startswith("1750"):
                return "June 21, 2025 (approx.)"
            return datetime.fromisoformat(timestamp.replace("Z", "")).strftime("%B %d, %Y, at %H:%M:%S")
        except:
            return timestamp

    if intent == "info.overview":
        return (
            f"Hey there! Ticket {ticket_id} is titled '{title}'. It was raised by {sender} to {description.lower()}. "
            f"It's a {request_type} request, currently in '{status_map.get(status, 'Unknown')}' status. "
            f"I've tracked {len(updates)} updates and {len(email_chain)} emails. "
            f"Want me to dive into the timeline, work notes, or specific actions?"
        )
    elif intent == "info.status":
        return (
            f"Ticket {ticket_id} is currently '{status_map.get(status, 'Unknown')}'. "
            f"Raised by {sender} for {description.lower()} ({request_type}), "
            f"it was last updated on {format_timestamp(updates[-1].get('sys_updated_on', 'N/A')) if updates else 'N/A'}. "
            f"Need the full history or specific details?"
        )
    elif intent == "update.last_update":
        if not updates:
            return f"No updates found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        latest_update = max(updates, key=lambda x: x.get("sys_updated_on", ""))
        comment = latest_update.get("new_value", latest_update.get("comment", "No comment provided"))
        return (
            f"For ticket {ticket_id}, the latest update I made was on {format_timestamp(latest_update.get('sys_updated_on', 'N/A'))}. "
            f"I noted: '{comment}'. This is for {title} ({request_type}) raised by {sender}. "
            f"Want the full timeline or more details?"
        )
    elif intent == "update.timeline":
        if not updates:
            return f"No updates found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        timeline = sorted(updates, key=lambda x: x.get("sys_updated_on", ""))
        response = f"Here's the full timeline for ticket {ticket_id} ({title}):\n"
        for update in timeline:
            comment = update.get("new_value", update.get("comment", "No comment provided"))
            timestamp = format_timestamp(update.get("sys_updated_on", "N/A"))
            source = update.get("source", "N/A")
            response += f"- {timestamp}: {source.capitalize()} update: '{comment}'.\n"
        return response + f"\nThis ticket was raised by {sender} for {description.lower()}."
    elif intent == "update.work_notes":
        work_notes = [
            u for u in updates 
            if u.get("field") in ["work_notes", "close_notes"] and u.get("new_value", "").strip()
        ]
        if not work_notes:
            return f"No work notes found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        latest_note = max(
            work_notes,
            key=lambda x: (x.get("sys_updated_on", ""), x.get("field") == "work_notes")
        )
        comment = latest_note.get("new_value", "No comment provided")
        return (
            f"The latest work note for ticket {ticket_id} was added on {format_timestamp(latest_note.get('sys_updated_on', 'N/A'))}. "
            f"I noted: '{comment}'. This is for {title} ({request_type}) raised by {sender}. "
            f"Need the full list of work notes or other details?"
        )
    elif intent == "email.last_email":
        if not email_chain:
            return f"No emails found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        latest_email = max(email_chain, key=lambda x: x.get("timestamp", ""))
        from_addr = latest_email.get("from", "N/A")
        subject = latest_email.get("subject", "N/A")
        timestamp = format_timestamp(latest_email.get("timestamp", "N/A"))
        body = latest_email.get("body", "N/A")[:100] + "..." if len(latest_email.get("body", "")) > 100 else latest_email.get("body", "N/A")
        sender_type = "me (your AI agent)" if "lakshmeesh777@gmail.com" in from_addr else "the user"
        return (
            f"The latest email for ticket {ticket_id} was sent on {timestamp}. "
            f"From: {sender_type}, Subject: '{subject}'. Body: {body} "
            f"This is part of a {request_type} request by {sender}. Need the full email thread?"
        )
    elif intent == "email.user_email":
        user_emails = [e for e in email_chain if "lakshmeesh777@gmail.com" not in e.get("from", "")]
        if not user_emails:
            return f"No user emails found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        latest_email = max(user_emails, key=lambda x: x.get("timestamp", ""))
        subject = latest_email.get("subject", "N/A")
        timestamp = format_timestamp(latest_email.get("timestamp", "N/A"))
        body = latest_email.get("body", "N/A")[:100] + "..." if len(latest_email.get("body", "")) > 100 else latest_email.get("body", "N/A")
        return (
            f"The latest user email for ticket {ticket_id} was sent on {timestamp}. "
            f"From: the user, Subject: '{subject}'. Body: {body} "
            f"This is part of a {request_type} request by {sender}. Need the full email thread?"
        )
    elif intent == "email.agent_email":
        agent_emails = [e for e in email_chain if "lakshmeesh777@gmail.com" in e.get("from", "")]
        if not agent_emails:
            return f"No emails from me found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        latest_email = max(agent_emails, key=lambda x: x.get("timestamp", ""))
        subject = latest_email.get("subject", "N/A")
        timestamp = format_timestamp(latest_email.get("timestamp", "N/A"))
        body = latest_email.get("body", "N/A")[:100] + "..." if len(latest_email.get("body", "")) > 100 else latest_email.get("body", "N/A")
        return (
            f"The latest email I sent for ticket {ticket_id} was on {timestamp}. "
            f"Subject: '{subject}'. Body: {body}\n"
            f"This is part of a {request_type} request by {sender}. Need the full email thread?"
        )
    elif intent == "email.email_thread":
        if not email_chain:
            return f"No emails found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        response = f"Email thread for ticket {ticket_id} ({title}):\n"
        for email in sorted(email_chain, key=lambda x: x.get("timestamp", "")):
            from_addr = email.get("from", "N/A")
            subject = email.get("subject", "N/A")
            timestamp = format_timestamp(email.get("timestamp", "N/A"))
            body = email.get("body", "N/A")[:100] + "..." if len(email.get("body", "")) > 100 else email.get("body", "N/A")
            sender_type = "me (your AI agent)" if "lakshmeesh777@gmail.com" in from_addr else "the user"
            response += f"- {timestamp}: From {sender_type}, Subject: '{subject}'. Body: {body}\n"
        return response + f"\nTotal emails: {len(email_chain)}. Want a specific email's full content?"
    elif intent == "action.access":
        platform_details = next((v for k, v in details.items() if isinstance(v, list)), "")
        if not platform_details:
            return f"No access details found for ticket {ticket_id}. It's a {request_type} request by {sender}."
        response = f"Access actions for ticket {ticket_id} ({title}):\n"
        for action in platform_details:
            action_type = action.get("request_type", "N/A").capitalize()
            status = action.get("status", "N/A")
            message = action.get("message", "N/A")
            username = action.get("username", "N/A")
            resource = action.get("repo_name", action.get("instance_id", "N/A"))
            response += f"- {action_type}: {status} for {username} on {resource}. Note: '{message}'.\n"
        return response + f"\nRaised by {sender} for {description.lower()}."
    elif intent == "action.pending_actions":
        pending = ticket.get("pending_actions", False)
        return (
            f"Ticket {ticket_id} has {'pending' if pending else 'no pending'} actions. "
            f"It's a {request_type} request by {sender}, currently {status_map.get(status, 'Unknown')}. "
            f"Want to see the latest updates or actions?"
        )
    elif intent == "actor.sender":
        return (
            f"Ticket {ticket_id} ({title}) was raised by {sender} for {description}. "
            f"It's a {request_type} request, currently {status_map.get(status, 'unknown')}. "
            f"Need details on other folks involved?"
        )
    elif intent == "actor.assignee":
        actors = set([u.get("assigned_to", "") for u in updates if u.get("assigned_to")])
        return (
            f"Ticket {ticket_id} ({title}) involves: {', '.join(actors) if actors else 'just me, the AI agent!'}. "
            f"Raised by {sender} for {description.lower()} ({request_type}). Need more specifics?"
        )
    elif intent == "analytical.count_updates":
        return (
            f"Ticket {ticket_id} has {len(updates)} updates. "
            f"It's a {request_type} request by {sender}, currently {status_map.get(status, 'Unknown')}. "
            f"Want the full timeline?"
        )
    elif intent == "analytical.count_emails":
        return (
            f"Ticket {ticket_id} has {len(email_chain)} emails. "
            f"It's a {request_type} request by {sender}, currently {status_map.get(status, 'Unknown')}. "
            f"Want the email thread?"
        )
    elif intent == "analytical.count_tickets":
        if not results:
            return "No tickets found matching your query."
        keywords = entities.get("keywords", [])
        return (
            f"I found {len(results)} tickets related to {', '.join(keywords) if keywords else 'your query'}. "
            f"Want a list of ticket IDs or more details?"
        )
    elif intent == "comparative.compare_updates":
        if not updates:
            return f"No updates to compare for ticket {ticket_id}. It's a {request_type} request by {sender}."
        response = f"Updates for ticket {ticket_id} ({title}):\n"
        for update in sorted(updates, key=lambda x: x.get("sys_updated_on", "")):
            comment = update.get("new_value", update.get("comment", "No comment"))
            timestamp = format_timestamp(update.get("sys_updated_on", "N/A"))
            response += f"- {timestamp}: Note: '{comment}'.\n"
        return response + f"\nTracks {description.lower()}."
    elif intent == "platform_specific.platform_filter":
        platform = entities.get("platform", ticket.get("platform", ["N/A"])[0]) if ticket else "N/A"
        return (
            f"Ticket {ticket_id} on {platform.capitalize()} is titled '{title}'. "
            f"Raised by {sender} for {description.lower()} ({request_type}), it's currently {status_map.get(status, 'Unknown')}. "
            f"I've got {len(updates)} updates and {len(email_chain)} emails. Want specifics?"
        )
    return f"Sorry, I couldn't process that request for ticket {ticket_id}. It's a {request_type} request by {sender}. Try asking for its status, details, or timeline!"

@app.post("/send-request")
async def send_request(user_query: UserQuery):
    try:
        query = user_query.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        preprocessed = await preprocess_query(query)
        logger.info(f"Preprocessed: {preprocessed}")

        db = client["your_db"]
        qdrant_manager = QdrantManager(db["tickets"], db["sync_metadata"])

        filters = {}
        if preprocessed["types"] and preprocessed["types"] != ["type_of_request"]:
            filters["type_of_request"] = {"$in": preprocessed["types"]}
        if "platform" in preprocessed["entities"]:
            filters["platform"] = preprocessed["entities"]["platform"]
        if "username" in preprocessed["entities"]:
            filters["sender"] = {"$regex": preprocessed["entities"]["username"], "$options": "i"}
        if "time_qualifier" in preprocessed["entities"] and preprocessed["entities"]["time_qualifier"] == "currently":
            filters["status"] = "2"  # In Progress

        # Consolidate ticket_id filters
        ticket_id = preprocessed["entities"].get("ticket_id")
        if ticket_id:
            filters["$or"] = [
                {"servicenow_sys_id": ticket_id},
                {"ado_ticket_id": ticket_id}
            ]

        results = await qdrant_manager.search_qdrant(preprocessed["query_for_embedding"], limit=5, filters=filters)
        # Filter results by score only if no ticket_id is provided
        filtered_results = results if ticket_id else [r for r in results if r.get("score", 0.0) > 0.2]

        # Fallback to MongoDB if Qdrant returns no results for a specific ticket_id
        if not filtered_results and ticket_id:
            ticket = tickets_collection.find_one({
                "$or": [
                    {"servicenow_sys_id": ticket_id},
                    {"ado_ticket_id": ticket_id}
                ]
            })
            if ticket:
                filtered_results = [{"payload": ticket, "score": 1.0}]

        response_text = ""
        if not filtered_results:
            response_text = "Sorry, I couldn't find any tickets matching your query. Could you provide more details, like a ticket ID or platform?"
        else:
            # Handle count_tickets intent
            if preprocessed["intents"] == ["analytical.count_tickets"]:
                response_text = await generate_response(
                    "analytical.count_tickets",
                    None,  # No single ticket needed
                    preprocessed["entities"],
                    results=filtered_results
                )
            else:
                ticket = filtered_results[0]["payload"]
                intents = preprocessed["intents"]
                response_text = f"Hey! For ticket {ticket.get('ado_ticket_id', ticket.get('servicenow_sys_id', 'N/A'))}:\n\n"
                for intent in intents:
                    intent_name = intent.replace('_', ' ').replace('.', ' ').title()
                    response_text += f"{intent_name}:\n"
                    response_text += await generate_response(intent, ticket, preprocessed["entities"]) + "\n"

        response = {
            "status": "success",
            "query": query,
            "response": response_text.strip(),
            "results": "" if len(filtered_results) == 0 else "Success"
        }
        return response
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync-servicenow")
async def sync_servicenow():
    try:
        db = client["tickets"]
        qdrant_manager = QdrantManager(db["tickets"], db["sync_metadata"])
        result = await qdrant_manager.sync_servicenow_incidents()
        return result
    except Exception as e:
        logger.error(f"Failed to sync ServiceNow incidents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class AdminRequest(BaseModel):
    ticket_id: int
    request: str

class AdminRequest(BaseModel):
    # Change ticket_id to Optional[str] to match frontend and allow missing field
    ticket_id: Optional[str] = None
    request: str
 
def get_ticket_counts():
    new_tickets = tickets_collection.count_documents({"updates.status": "To Do"})
    in_progress_tickets = tickets_collection.count_documents({"updates.status": "In Progress"})
    completed_tickets = tickets_collection.count_documents({"updates.status": "Done"}) + tickets_collection.count_documents({"updates.status": "Closed"})
    failed_tickets = tickets_collection.count_documents({"updates.status": "Failed"})
    return {
        "new": new_tickets,
        "in_progress": in_progress_tickets,
        "completed": completed_tickets,
        "failed": failed_tickets
    }


 
 
@app.get("/stop-agent")
async def stop_agent():
    """Stop the email and ticket tracking agent."""
    global is_running, email_task, ticket_task, session_id, ticket_info
    if not is_running:
        logger.info("Agent is not running.")
        return {"status": "info", "message": "Agent is not running"}
    
    logger.info(f"Stopping agent for session {session_id}...")
    is_running = False
    if email_task:
        email_task.cancel()
    if ticket_task:
        ticket_task.cancel()
    email_task = None
    ticket_task = None
    session_id = None
    ticket_info = {}
    await broadcast({"type": "session", "session_id": None, "status": "stopped"})
    return {"status": "success", "message": "Agent stopped"}

@app.get("/tickets")
async def get_tickets():
    """Get all tickets from MongoDB."""
    try:
        tickets = list(tickets_collection.find({}, {"_id": 0}))
        logger.info(f"Returning {len(tickets)} tickets from /tickets endpoint")
        return {"status": "success", "tickets": tickets}
    except Exception as e:
        logger.error(f"Error fetching tickets: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/tickets/by-type/{request_type}")
async def get_tickets_by_type(request_type: str):
    """Get tickets filtered by request type."""
    try:
        tickets = list(tickets_collection.find({"type_of_request": request_type}, {"_id": 0}))
        logger.info(f"Returning {len(tickets)} tickets of type {request_type}")
        return {"status": "success", "tickets": tickets}
    except Exception as e:
        logger.error(f"Error fetching tickets by type: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/logs")
async def get_logs():
    """Get recent logs from agent.log."""
    try:
        with open("agent.log", "r") as f:
            logs = f.readlines()[-50:]  # Last 50 lines
        return {"status": "success", "logs": logs}
    except Exception as e:
        logger.error(f"Error fetching logs: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/status")
async def get_status():
    """Get the current status of the agent."""
    return {"status": "success", "is_running": is_running, "session_id": session_id}

@app.get("/request-types")
async def get_request_types():
    """Get all distinct request types in the system."""
    try:
        distinct_types = tickets_collection.distinct("type_of_request")
        return {"status": "success", "request_types": distinct_types}
    except Exception as e:
        logger.error(f"Error fetching request types: {str(e)}")
        return {"status": "error", "message": str(e)}

# Heartbeat interval and timeout settings
HEARTBEAT_INTERVAL = 30  # seconds
WEBSOCKET_TIMEOUT = 3600  # 1 hour
MAX_CLIENTS = 100  # Limit number of concurrent clients

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections with heartbeat and robust error handling."""
    global websocket_clients
    try:
        if len(websocket_clients) >= MAX_CLIENTS:
            logger.warning(f"Max clients ({MAX_CLIENTS}) reached, rejecting connection from {websocket.client}")
            await websocket.close(code=1011)  # Server overloaded
            return

        await websocket.accept()
        logger.info(f"WebSocket connection accepted: {websocket.client}")

        if not isinstance(websocket_clients, set):
            logger.error(f"websocket_clients is not a set, found type: {type(websocket_clients)}")
            websocket_clients = set()
            logger.info("Reinitialized websocket_clients as set")

        websocket_clients.add(websocket)

        # Send initial ping to confirm connection
        await websocket.send_json({"type": "ping"})
        
        while True:
            try:
                async def heartbeat():
                    while websocket.client_state == WebSocketState.CONNECTED:
                        try:
                            await websocket.send_json({"type": "ping"})
                            logger.debug("Sent heartbeat ping")
                            await asyncio.sleep(HEARTBEAT_INTERVAL)
                        except Exception as e:
                            logger.warning(f"Heartbeat failed: {str(e)}")
                            break

                heartbeat_task = asyncio.create_task(heartbeat())

                data = await asyncio.wait_for(websocket.receive_text(), timeout=WEBSOCKET_TIMEOUT)
                logger.debug(f"Received WebSocket message: {data}")
                if data == "pong":
                    logger.debug("Received pong response")
                
            except asyncio.TimeoutError:
                logger.warning("WebSocket receive timeout, sending ping to check connection")
                await websocket.send_json({"type": "ping"})
                continue
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected normally")
                break
            except WebSocketException as e:
                logger.error(f"WebSocket protocol error: {str(e)}")
                break
            except Exception as e:
                logger.error(f"Unexpected WebSocket error: {str(e)}")
                break
            finally:
                if 'heartbeat_task' in locals():
                    heartbeat_task.cancel()
                    
    except Exception as e:
        logger.error(f"WebSocket connection setup error: {str(e)}")
    finally:
        if isinstance(websocket_clients, set):
            websocket_clients.discard(websocket)
        else:
            logger.error(f"Cannot discard client, websocket_clients is {type(websocket_clients)}")
        logger.info("WebSocket connection cleaned up")

async def broadcast(message):
    """Broadcast a message to all WebSocket connections with robust error handling."""
    if not websocket_clients:
        logger.debug("No WebSocket clients to broadcast to")
        return

    logger.info(f"Broadcasting message: {message}")
    clients_to_remove = set()

    if not isinstance(websocket_clients, set):
        logger.error(f"websocket_clients is not a set in broadcast, found type: {type(websocket_clients)}")
        return

    for client in websocket_clients.copy():
        try:
            if client.client_state != WebSocketState.CONNECTED:
                logger.debug(f"Client {client.client} is not connected, marking for removal")
                clients_to_remove.add(client)
                continue

            await client.send_json(message)
            logger.debug(f"Message sent successfully to client {client.client}")

        except WebSocketDisconnect:
            logger.info(f"Client {client.client} disconnected during broadcast")
            clients_to_remove.add(client)
        except WebSocketException as e:
            logger.info(f"WebSocket protocol error during broadcast: {str(e)}")
            clients_to_remove.add(client)
        except RuntimeError as e:
            if "close message has been sent" in str(e) or "WebSocket is not connected" in str(e):
                logger.info(f"Attempted to send to closed WebSocket {client.client}")
                clients_to_remove.add(client)
            else:
                logger.error(f"Runtime error broadcasting to WebSocket {client.client}: {str(e)}")
                clients_to_remove.add(client)
        except Exception as e:
            logger.error(f"Unexpected error broadcasting to WebSocket {client.client}: {str(e)}")
            clients_to_remove.add(client)

    if clients_to_remove:
        websocket_clients.difference_update(clients_to_remove)
        logger.info(f"Removed {len(clients_to_remove)} disconnected clients")

@app.on_event("startup")
async def startup_event():
    """Log server startup and verify websocket_clients type."""
    global websocket_clients
    logger.info("WebSocket server started with heartbeat interval %s seconds and timeout %s seconds", 
                HEARTBEAT_INTERVAL, WEBSOCKET_TIMEOUT)
    if not isinstance(websocket_clients, set):
        logger.error(f"websocket_clients is not a set at startup, found type: {type(websocket_clients)}")
        websocket_clients = set()
        logger.info("Initialized websocket_clients as set")

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully close all WebSocket connections on shutdown."""
    global websocket_clients
    logger.info("Shutting down WebSocket server")
    for client in websocket_clients.copy():
        try:
            if client.client_state == WebSocketState.CONNECTED:
                await client.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket client {client.client}: {str(e)}")
        finally:
            websocket_clients.discard(client)
    logger.info("All WebSocket connections closed")

@app.get("/")
async def root():
    return {"message": "Email Agent API is running"}