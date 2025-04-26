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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
load_dotenv()

# Initialize MongoDB
mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client["email_agent"]
tickets_collection = db["tickets"]
tickets_collection.create_index("ado_ticket_id", unique=True)
tickets_collection.create_index("thread_id")
logger.info("Initialized MongoDB: email_agent.tickets")

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

async def process_emails():
    """Poll for new emails and process them."""
    kernel = Kernel()
    kernel.add_plugin(EmailReaderPlugin(), plugin_name="email_reader")
    kernel.add_plugin(EmailSenderPlugin(), plugin_name="email_sender")
    kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    kernel.add_plugin(GitPlugin(), plugin_name="git")
    agent = SKAgent(kernel)
    logger.info(f"Registered plugins: {list(kernel.plugins.keys())}")

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
                    temp_files = [a['path'] for a in attachments]  # Track temporary files
                    
                    # Check if email is part of an existing thread
                    existing_ticket = tickets_collection.find_one({"thread_id": thread_id})

                    # Skip if the email ID has already been processed
                    if existing_ticket and existing_ticket["email_id"] == email_id:
                        logger.info(f"Email ID={email_id} already processed, skipping.")
                        cleanup_temp_files(temp_files)
                        continue

                    # Construct email content for attachment (basic .eml format)
                    email_content = f"""From: {email.get('from', 'Unknown')}
Subject: {email['subject']}
Date: {email.get('received', datetime.now().isoformat())}
To: {os.getenv('EMAIL_ADDRESS', 'Unknown')}

{email['body']}
"""

                    # Broadcast: New email arrived
                    await broadcast({
                        "type": "email_detected",
                        "subject": email['subject'],
                        "sender": email.get("from", "Unknown"),
                        "email_id": email_id
                    })
                    logger.info(f"Processing email - Subject: {email['subject']}, From: {email.get('from', 'Unknown')}")

                    # Process email with SK agent
                    result = await agent.process_email(email, broadcast, existing_ticket, email_content)
                    logger.info(f"Agent result for email ID={email_id}: {result}")
                    
                    # Clean up temporary files
                    cleanup_temp_files(temp_files)
                    
                    if result["status"] == "success":
                        ticket_id = result["ticket_id"]
                        intent = result.get("intent", "general_it_request")
                        actions = result.get("actions", [])
                        pending_actions = result.get("pending_actions", False)
                        is_follow_up = bool(existing_ticket)

                        # For debugging - log available fields in result
                        logger.info(f"Available fields in result: {list(result.keys())}")

                        # Email intent analysis for GitHub details
                        email_intent_result = await agent.analyze_intent(email["subject"], email["body"], attachments)
                        logger.info(f"Email intent analysis for GitHub details: {email_intent_result}")
                        
                        # Extract GitHub details from the intent analysis
                        repo_name = email_intent_result.get("repo_name")
                        github_username = email_intent_result.get("github_username")
                        access_type = email_intent_result.get("access_type", "read")
                        
                        # If this is a new ticket (not a follow-up)
                        if not is_follow_up:
                            # IMPORTANT: Save the original message_id for threading
                            original_message_id = email_id
                            
                            # Store new ticket in MongoDB
                            ticket_record = {
                                "ado_ticket_id": ticket_id,
                                "sender": email.get("from", "Unknown"),
                                "subject": email["subject"],
                                "thread_id": thread_id,
                                "email_id": email_id,
                                "original_message_id": original_message_id,  # Store for threading
                                "ticket_description": email_intent_result.get("ticket_description", f"IT request for {email['subject']}"),
                                "email_timestamp": datetime.now().isoformat(),
                                "updates": [],
                                "actions": actions,
                                "pending_actions": pending_actions,
                                "type_of_request": "github" if intent.startswith("github_") else intent,
                                "details": {}  # Initialize empty details dictionary
                            }
                            
                            # Store attachments in ticket record
                            ticket_record["details"]["attachments"] = [
                                {"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments
                            ]
                            
                            # Handle GitHub specific fields if it's a GitHub access request
                            if intent == "github_access_request":
                                # Create GitHub details object with initial pending status
                                github_details = {
                                    "request_type": intent,
                                    "repo_name": repo_name if repo_name and repo_name != "unspecified" else "",
                                    "username": github_username if github_username and github_username != "unspecified" else "",
                                    "access_type": access_type if access_type and access_type != "unspecified" else "read",
                                    "status": "pending"
                                }
                                
                                # Store initial pending status in ticket record
                                ticket_record["details"]["github"] = [github_details]
                                
                                # Insert the ticket with pending status
                                tickets_collection.insert_one(ticket_record)
                                
                                # Now execute the GitHub action
                                git_result = await kernel.invoke(
                                    kernel.plugins["git"]["grant_repo_access"],
                                    repo_name=github_details["repo_name"],
                                    github_username=github_details["username"],
                                    access_type="pull" if github_details["access_type"] == "read" else github_details["access_type"]
                                )
                                
                                # Update MongoDB with the result of the GitHub action
                                new_status = "completed" if git_result.value["success"] else "failed"
                                tickets_collection.update_one(
                                    {"ado_ticket_id": ticket_id, "details.github.username": github_details["username"]},
                                    {
                                        "$set": {
                                            "details.github.$.status": new_status,
                                            "details.github.$.message": git_result.value["message"]
                                        }
                                    }
                                )
                                
                                # Log the result
                                logger.info(f"GitHub access request completed with status: {new_status}, message: {git_result.value['message']}")
                            
                            # Handle general IT request
                            elif intent == "general_it_request":
                                # Extract sender username 
                                sender_username = email.get("from", "Unknown").split('@')[0] if '@' in email.get("from", "Unknown") else "User"
                                
                                # Get the detailed description from intent analysis
                                detailed_description = email_intent_result.get("ticket_description", "")
                                
                                # Make sure the sender is mentioned in the description
                                if sender_username.lower() not in detailed_description.lower():
                                    detailed_description = f"User {sender_username}: {detailed_description}"
                                
                                # Create general IT request details with specific description
                                general_details = {
                                    "request_type": "general_it_request",
                                    "status": "pending",
                                    "message": detailed_description,
                                    "requester": sender_username
                                }
                                
                                # Store in ticket record
                                ticket_record["details"]["general"] = [general_details]
                                ticket_record["ticket_description"] = detailed_description  # Use the detailed description
                                
                                # Insert the ticket with pending status
                                tickets_collection.insert_one(ticket_record)
                                
                                # Log the result
                                logger.info(f"General IT request created with status: pending")
                                
                            # Broadcast: Ticket created
                            ado_url = f"https://dev.azure.com/{os.getenv('ADO_ORGANIZATION')}/{os.getenv('ADO_PROJECT')}/_workitems/edit/{ticket_id}"
                            await broadcast({
                                "type": "ticket_created",
                                "email_id": email_id,
                                "ticket_id": ticket_id,
                                "subject": email["subject"],
                                "intent": intent,
                                "request_type": intent,
                                "ado_url": ado_url
                            })
                        else:
                            # For follow-ups, retrieve the original message ID for proper threading
                            original_message_id = existing_ticket.get("original_message_id", existing_ticket.get("email_id"))
                            
                            # Handle follow-up emails based on intent
                            if intent.startswith("github_"):
                                # Common fields for both access and revoke operations
                                comment = ""
                                status = "pending"  # Start with pending status
                                github_details = {}
                                
                                # Specific handling based on intent type
                                if intent == "github_access_request":
                                    # Create GitHub details for additional access request
                                    github_details = {
                                        "request_type": intent,
                                        "repo_name": repo_name if repo_name and repo_name != "unspecified" else "",
                                        "username": github_username if github_username and github_username != "unspecified" else "",
                                        "access_type": access_type if access_type and access_type != "unspecified" else "read",
                                        "status": "pending"
                                    }
                                    comment = f"Processing GitHub access request for {github_username} to repo {repo_name}"
                                    
                                    # First update MongoDB with pending status
                                    update_operation = {
                                        "$push": {
                                            "updates": {
                                                "status": status,
                                                "comment": comment,
                                                "revision_id": f"git-{intent.split('_')[1]}-{ticket_id}-{len(existing_ticket.get('updates', []))+1}",
                                                "email_sent": False,
                                                "email_message_id": None,
                                                "email_timestamp": datetime.now().isoformat()
                                            }
                                        },
                                        "$set": {
                                            "actions": actions,
                                            "pending_actions": True
                                        }
                                    }
                                    
                                    # Add github details to MongoDB
                                    if "github" not in existing_ticket.get("details", {}):
                                        update_operation["$set"]["details.github"] = [github_details]
                                    else:
                                        update_operation["$push"]["details.github"] = github_details
                                    
                                    tickets_collection.update_one(
                                        {"ado_ticket_id": ticket_id},
                                        update_operation
                                    )
                                    
                                    # Execute GitHub action
                                    git_result = await kernel.invoke(
                                        kernel.plugins["git"]["grant_repo_access"],
                                        repo_name=github_details["repo_name"],
                                        github_username=github_details["username"],
                                        access_type="pull" if github_details["access_type"] == "read" else github_details["access_type"]
                                    )
                                    
                                    # Update MongoDB with the result
                                    new_status = "completed" if git_result.value["success"] else "failed"
                                    new_comment = git_result.value["message"]
                                    
                                    # Update the MongoDB record with action results
                                    tickets_collection.update_one(
                                        {"ado_ticket_id": ticket_id, "details.github.username": github_details["username"]},
                                        {
                                            "$set": {
                                                "details.github.$[elem].status": new_status,
                                                "details.github.$[elem].message": new_comment,
                                                "pending_actions": False  # No longer pending after action completes
                                            },
                                            "$push": {
                                                "updates": {
                                                    "status": new_status,
                                                    "comment": new_comment,
                                                    "revision_id": f"git-result-{ticket_id}-{len(existing_ticket.get('updates', []))+2}",
                                                    "email_sent": False,
                                                    "email_message_id": None,
                                                    "email_timestamp": datetime.now().isoformat()
                                                }
                                            }
                                        },
                                        array_filters=[{"elem.username": github_details["username"], "elem.request_type": intent}]
                                    )
                                    
                                    # Send email update
                                    update_body = f"Hi,\n\nI've processed your additional GitHub access request for {github_username} to {repo_name}. {new_comment}\n\nIf you need anything else, let me know!\n\nBest,\nAgent\nIT Support"
                                    email_result = await send_ticket_update_email(
                                        kernel,
                                        to=existing_ticket["sender"],
                                        subject=existing_ticket["subject"],
                                        body=update_body,
                                        thread_id=existing_ticket["thread_id"],
                                        message_id=original_message_id
                                    )
                                    
                                    # Update MongoDB to record email sent
                                    if email_result["message_id"]:
                                        tickets_collection.update_one(
                                            {"ado_ticket_id": ticket_id, "updates.revision_id": f"git-result-{ticket_id}-{len(existing_ticket.get('updates', []))}"},
                                            {
                                                "$set": {
                                                    "updates.$.email_sent": True,
                                                    "updates.$.email_message_id": email_result["message_id"]
                                                }
                                            }
                                        )
                                
                                elif intent == "github_revoke_access":
                                    # Similar approach for revoke operations
                                    github_details = {
                                        "request_type": intent,
                                        "repo_name": repo_name if repo_name and repo_name != "unspecified" else "",
                                        "username": github_username if github_username and github_username != "unspecified" else "",
                                        "access_type": access_type if access_type and access_type != "unspecified" else "read",
                                        "status": "pending"
                                    }
                                    comment = f"Processing access revocation for {github_username} from {repo_name}"
                                    
                                    # First update with pending status
                                    update_operation = {
                                        "$push": {
                                            "updates": {
                                                "status": status,
                                                "comment": comment,
                                                "revision_id": f"git-{intent.split('_')[1]}-{ticket_id}-{len(existing_ticket.get('updates', []))+1}",
                                                "email_sent": False,
                                                "email_message_id": None,
                                                "email_timestamp": datetime.now().isoformat()
                                            }
                                        },
                                        "$set": {
                                            "actions": actions,
                                            "pending_actions": True  # Set to true while in progress
                                        }
                                    }
                                    
                                    if "github" not in existing_ticket.get("details", {}):
                                        update_operation["$set"]["details.github"] = [github_details]
                                    else:
                                        update_operation["$push"]["details.github"] = github_details
                                    
                                    tickets_collection.update_one(
                                        {"ado_ticket_id": ticket_id},
                                        update_operation
                                    )
                                    
                                    # Execute the revoke action
                                    git_result = await kernel.invoke(
                                        kernel.plugins["git"]["revoke_repo_access"],
                                        repo_name=github_details["repo_name"],
                                        github_username=github_details["username"]
                                    )
                                    
                                    # Update MongoDB with result
                                    new_status = "revoked" if git_result.value["success"] else "failed"
                                    new_comment = git_result.value["message"]
                                    
                                    tickets_collection.update_one(
                                        {"ado_ticket_id": ticket_id, "details.github.username": github_details["username"]},
                                        {
                                            "$set": {
                                                "details.github.$[elem].status": new_status,
                                                "details.github.$[elem].message": new_comment,
                                                "pending_actions": False  # No longer pending
                                            },
                                            "$push": {
                                                "updates": {
                                                    "status": new_status,
                                                    "comment": new_comment,
                                                    "revision_id": f"git-result-{ticket_id}-{len(existing_ticket.get('updates', []))+2}",
                                                    "email_sent": False,
                                                    "email_message_id": None,
                                                    "email_timestamp": datetime.now().isoformat()
                                                }
                                            }
                                        },
                                        array_filters=[{"elem.username": github_details["username"], "elem.request_type": intent}]
                                    )
                                    
                                    # Send email update
                                    update_body = f"Hi,\n\nI've processed your request to revoke access for {github_username} from {repo_name}. {new_comment}\n\nIf you need anything else, let me know!\n\nBest,\nAgent\nIT Support"
                                    email_result = await send_ticket_update_email(
                                        kernel,
                                        to=existing_ticket["sender"],
                                        subject=existing_ticket["subject"],
                                        body=update_body,
                                        thread_id=existing_ticket["thread_id"],
                                        message_id=original_message_id
                                    )
                                    
                                    # Update MongoDB to record email sent
                                    if email_result["message_id"]:
                                        tickets_collection.update_one(
                                            {"ado_ticket_id": ticket_id, "updates.revision_id": f"git-result-{ticket_id}-{len(existing_ticket.get('updates', []))}"},
                                            {
                                                "$set": {
                                                    "updates.$.email_sent": True,
                                                    "updates.$.email_message_id": email_result["message_id"]
                                                }
                                            }
                                        )
                                
                                # Broadcast updated status
                                await broadcast({
                                    "type": "ticket_updated",
                                    "email_id": email_id,
                                    "ticket_id": ticket_id,
                                    "status": new_status,
                                    "request_type": intent,
                                    "comment": new_comment
                                })
                            elif intent == "general_it_request":
                                # Handle general IT request follow-up
                                status = "updated"
                                comment = f"Updated general IT request: {email['subject']}"
                                
                                # Create update operation
                                update_operation = {
                                    "$push": {
                                        "updates": {
                                            "status": status,
                                            "comment": comment,
                                            "revision_id": f"general-update-{ticket_id}-{len(existing_ticket.get('updates', []))+1}",
                                            "email_sent": False,
                                            "email_message_id": None,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    },
                                    "$set": {
                                        "actions": actions,
                                        "pending_actions": False
                                    }
                                }
                                
                                # Add general details to MongoDB if not exist
                                general_details = {
                                    "request_type": "general_it_request",
                                    "status": status,
                                    "message": comment
                                }
                                
                                if "general" not in existing_ticket.get("details", {}):
                                    update_operation["$set"]["details.general"] = [general_details]
                                else:
                                    update_operation["$push"]["details.general"] = general_details
                                
                                tickets_collection.update_one(
                                    {"ado_ticket_id": ticket_id},
                                    update_operation
                                )
                                
                                # Send email update
                                update_body = f"Hi,\n\nThanks for the update on your IT request (Ticket #{ticket_id}). We're still working on it and have noted your latest information: {comment}\n\nI'll keep you posted on our progress.\n\nBest,\nAgent\nIT Support"
                                email_result = await send_ticket_update_email(
                                    kernel,
                                    to=existing_ticket["sender"],
                                    subject=existing_ticket["subject"],
                                    body=update_body,
                                    thread_id=existing_ticket["thread_id"],
                                    message_id=original_message_id
                                )
                                
                                # Update MongoDB to record email sent
                                if email_result["message_id"]:
                                    tickets_collection.update_one(
                                        {"ado_ticket_id": ticket_id, "updates.revision_id": f"general-update-{ticket_id}-{len(existing_ticket.get('updates', []))}"},
                                        {
                                            "$set": {
                                                "updates.$.email_sent": True,
                                                "updates.$.email_message_id": email_result["message_id"]
                                            }
                                        }
                                    )
                                
                                # Broadcast updated status
                                await broadcast({
                                    "type": "ticket_updated",
                                    "email_id": email_id,
                                    "ticket_id": ticket_id,
                                    "status": status,
                                    "request_type": intent,
                                    "comment": comment
                                })
                                
                                logger.info(f"General IT request follow-up processed: {comment}")
                            else:
                                # Handle other non-GitHub follow-up intents
                                logger.info(f"Processing non-GitHub follow-up for intent: {intent}")
                                # Add logic for other intents if needed
                    else:
                        logger.error(f"Failed to process email ID={email_id}: {result['message']}")
                        await broadcast({
                            "type": "error",
                            "email_id": email_id,
                            "message": f"Failed to process email: {result['message']}"
                        })

            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in email processing loop: {str(e)}")
            await asyncio.sleep(10)

async def send_ticket_update_email(kernel, to, subject, body, thread_id, message_id):
    """Send an email update as a reply in the same thread as the original email."""
    try:
        # Add a context line to make it clear this is an update
        update_body = body
        
        email_result = await kernel.invoke(
            kernel.plugins["email_sender"]["send_reply"],
            to=to,
            subject=subject,
            body=update_body,
            thread_id=thread_id,
            message_id=message_id
        )
        
        logger.info(f"Sent email update to {to}, message_id: {email_result.value['message_id']}")
        return email_result.value
    except Exception as e:
        logger.error(f"Failed to send email update: {str(e)}")
        return {"message_id": None, "status": "failed"}

async def process_tickets():
    """Check for ADO ticket updates."""
    kernel = Kernel()
    kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    kernel.add_plugin(EmailSenderPlugin(), plugin_name="email_sender")
    agent = SKAgent(kernel)

    while is_running:
        try:
            logger.info(f"Checking for ADO ticket updates in session {session_id}...")
            tickets = tickets_collection.find()
            
            for ticket in tickets:
                ticket_id = ticket["ado_ticket_id"]
                update_result = await kernel.invoke(
                    kernel.plugins["ado"]["get_ticket_updates"],
                    ticket_id=ticket_id
                )
                updates = update_result.value if update_result else []
                ticket_data = ticket_info.get(ticket_id, {"last_revision_id": 0})
                last_revision_id = ticket_data["last_revision_id"]
                
                new_updates = [u for u in updates if u['revision_id'] > last_revision_id]
                
                if new_updates:
                    logger.info(f"Found {len(new_updates)} new updates for ticket ID={ticket_id}")
                    attachments = ticket.get("details", {}).get("attachments", [])
                    update_result = await agent.analyze_ticket_update(ticket_id, new_updates, attachments)
                    
                    if update_result["update_intent"] != "error":
                        sender = ticket.get('sender', 'Unknown')
                        subject = ticket.get('subject', f"Update for Ticket {ticket_id}")
                        thread_id = ticket.get('thread_id', str(uuid.uuid4()))
                        email_id = ticket.get('email_id', str(uuid.uuid4()))
                        
                        reply_result = await kernel.invoke(
                            self.kernel.plugins["email_sender"]["send_reply"],
                            to=sender,
                            subject=subject,
                            body=update_result["email_response"],
                            thread_id=thread_id,
                            message_id=email_id,
                            attachments=attachments,
                            remediation=update_result["remediation"]
                        )
                        email_status = bool(reply_result and reply_result.value)
                        email_message_id = reply_result.value.get("message_id") if reply_result and reply_result.value else None
                        
                        for update in new_updates:
                            tickets_collection.update_one(
                                {"ado_ticket_id": ticket_id},
                                {
                                    "$push": {
                                        "updates": {
                                            "comment": update["comment"] or "No comment provided",
                                            "status": update["status"],
                                            "revision_id": update["revision_id"],
                                            "email_sent": email_status,
                                            "email_message_id": email_message_id,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    }
                                },
                                upsert=True
                            )
                        
                        if email_status:
                            ticket_info[ticket_id] = {
                                "sender": sender,
                                "subject": subject,
                                "thread_id": thread_id,
                                "email_id": email_id,
                                "last_revision_id": max(u['revision_id'] for u in updates)
                            }
                            await broadcast({
                                "type": "email_reply",
                                "email_id": email_id,
                                "ticket_id": ticket_id,
                                "thread_id": thread_id,
                                "timestamp": datetime.now().isoformat()
                            })
                    else:
                        for update in new_updates:
                            tickets_collection.update_one(
                                {"ado_ticket_id": ticket_id},
                                {
                                    "$push": {
                                        "updates": {
                                            "comment": update["comment"] or "No comment provided",
                                            "status": update["status"],
                                            "revision_id": update["revision_id"],
                                            "email_sent": False,
                                            "email_message_id": None,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    }
                                },
                                upsert=True
                            )
                        ticket_info[ticket_id]["last_revision_id"] = max(u['revision_id'] for u in updates)
            
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in ticket processing loop: {str(e)}")
            await asyncio.sleep(10)

@app.get("/run-agent")
async def run_agent():
    """Start the email and ticket tracking agent."""
    global is_running, email_task, ticket_task, session_id, ticket_info
    if is_running:
        logger.info("Agent is already running.")
        return {"status": "info", "message": "Agent is already running"}
    
    logger.info("Starting email and ticket tracking agent...")
    session_id = str(uuid.uuid4())
    ticket_info = {}
    kernel = Kernel()
    kernel.add_plugin(ADOPlugin(), plugin_name="ado")
    work_items_result = await kernel.invoke(
        kernel.plugins["ado"]["get_all_work_items"]
    )
    work_items = work_items_result.value if work_items_result else []
    for work_item in work_items:
        ticket_id = work_item['id']
        updates_result = await kernel.invoke(
            kernel.plugins["ado"]["get_ticket_updates"],
            ticket_id=ticket_id
        )
        updates = updates_result.value if updates_result else []
        last_revision_id = max((u['revision_id'] for u in updates), default=0)
        ticket_record = tickets_collection.find_one({"ado_ticket_id": ticket_id})
        ticket_info[ticket_id] = {
            "sender": ticket_record.get('sender', 'Unknown') if ticket_record else 'Unknown',
            "subject": ticket_record.get('subject', f"Update for Ticket {ticket_id}") if ticket_record else f"Update for Ticket {ticket_id}",
            "thread_id": ticket_record.get('thread_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
            "email_id": ticket_record.get('email_id', str(uuid.uuid4())) if ticket_record else str(uuid.uuid4()),
            "last_revision_id": last_revision_id
        }
    is_running = True
    email_task = asyncio.create_task(process_emails())
    ticket_task = asyncio.create_task(process_tickets())
    
    await broadcast({"type": "session", "session_id": session_id, "status": "started"})
    return {"status": "success", "message": f"Agent started with session ID={session_id}"}

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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections."""
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    websocket_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        websocket_clients.remove(websocket)
    finally:
        logger.info("WebSocket connection closed")

async def broadcast(message):
    """Broadcast a message to all WebSocket connections."""
    logger.info(f"Broadcasting message: {message}")
    for client in websocket_clients:
        try:
            await client.send_json(message)
        except Exception as e:
            logger.error(f"Error broadcasting to WebSocket: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Email Agent API is running"}