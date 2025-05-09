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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SKAgent:
    def __init__(self, kernel, tickets_collection: Collection):
        self.kernel = kernel
        self.tickets_collection = tickets_collection
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2023-05-15"
        )
        logger.info("Initialized SKAgent with AzureOpenAI client")

    async def analyze_intent(self, subject: str, body: str, attachments: list = None) -> dict:
        """Analyze email intent using Azure OpenAI, relying on contextual understanding."""
        try:
            # Clean HTML from body
            if "<html>" in body.lower():
                body = BeautifulSoup(body, "html.parser").get_text(separator=" ").strip()
            else:
                body = body.strip()

            logger.info(f"Analyzing intent - Subject: {subject}, Body: {body[:100]}..., Attachments={len(attachments or [])}")

            content = f"Subject: {subject}\nBody: {body}"
            if attachments:
                attachment_info = "\nAttachments: " + ", ".join(a['filename'] for a in attachments)
                content += attachment_info

            prompt = (
                "You are an IT support assistant analyzing an email to determine the user's intent based on its context and purpose, without relying on specific keywords. "
                "Classify the intent as one of: 'github_access_request', 'github_revoke_access', 'general_it_request', 'request_summary', or 'non_intent'. "
                "Understand the email's overall intent by evaluating whether it requests a specific, immediate IT action or is non-actionable (e.g., appreciation, acknowledgment, or vague future requests). "
                "Extract relevant details only for actionable intents. For 'general_it_request', include attachment details in the description if present. "
                "Extract the username or requester name from the sender address (before the @ symbol) if available. "
                "Rules:\n"
                "- Non-intent email:\n"
                "  - Intent: 'non_intent'.\n"
                "  - Applies to emails with no specific, immediate IT request, such as appreciation (e.g., 'thanks for your help'), acknowledgments, greetings, or vague requests for future updates (e.g., 'let me know if there are updates').\n"
                "  - Characteristics: No clear demand for action, no specific IT issue, or no immediate task (e.g., 'Thanks for your mail and please let me know once you have any updates' is non-intent as it’s an acknowledgment with a future-oriented request).\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'Non-actionable email (e.g., appreciation or generic message)'.\n"
                "  - No ADO ticket creation or update required.\n"
                "- Request summary:\n"
                "  - Intent: 'request_summary'.\n"
                "  - Applies to emails explicitly requesting a current status, summary, or details of a previous request (e.g., 'Can you provide a summary of the poc access request?' or 'What’s the status of my ticket?').\n"
                "  - Characteristics: Clear demand for information about an existing ticket or request.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'User requested summary of previous request'.\n"
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
                "- General IT request:\n"
                "  - Intent: 'general_it_request'.\n"
                "  - Applies to emails describing a specific IT issue or request not related to GitHub (e.g., 'I’m having VPN connection issues').\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: Create a specific, detailed description, e.g., 'User johndoe reports VPN connection error.' Include attachment details if present.\n"
                "- Unclear intent:\n"
                "  - Intent: 'error'.\n"
                "  - Applies when the email’s intent cannot be determined and is not clearly non-actionable.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'Unable to determine intent'.\n"
                "Return JSON: {'intent', 'ticket_description', 'actions', 'pending_actions', 'repo_name', 'access_type', 'github_username'}.\n"
                f"Email:\n{content}\n\n"
                "Examples:\n"
                "1. Subject: Request access to poc repo\nBody: Please grant read access to poc for testuser9731. I will let you know when to revoke.\n"
                "   ```json\n{\"intent\": \"github_access_request\", \"ticket_description\": \"Grant read access to poc for testuser9731\", \"actions\": [{\"action\": \"grant_access\", \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}], \"pending_actions\": true, \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}\n```\n"
                "2. Subject: Status of my request\nBody: Can you provide a summary of the poc access request?\n"
                "   ```json\n{\"intent\": \"request_summary\", \"ticket_description\": \"User requested summary of previous request\", \"actions\": [], \"pending_actions\": false, \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\"}\n```\n"
                "3. Subject: Thanks for your mail\nBody: Thanks for your mail and please let me know once you have any updates.\n"
                "   ```json\n{\"intent\": \"non_intent\", \"ticket_description\": \"Non-actionable email (e.g., appreciation or generic message)\", \"actions\": [], \"pending_actions\": false, \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\"}\n```\n"
                "4. Subject: VPN issue\nBody: I’m having trouble connecting to the VPN. Can you help?\n"
                "   ```json\n{\"intent\": \"general_it_request\", \"ticket_description\": \"User reports VPN connection error\", \"actions\": [], \"pending_actions\": false, \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\"}\n```\n"
                "5. Subject: Great job\nBody: Thanks for the quick response on my last request. Appreciate it!\n"
                "   ```json\n{\"intent\": \"non_intent\", \"ticket_description\": \"Non-actionable email (e.g., appreciation or generic message)\", \"actions\": [], \"pending_actions\": false, \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\"}\n```\n"
                "Output format:\n"
                "```json\n{\"intent\": \"<intent>\", \"ticket_description\": \"<description>\", \"actions\": [<action_objects>], \"pending_actions\": <bool>, \"repo_name\": \"<repo>\", \"access_type\": \"<pull|push|unspecified>\", \"github_username\": \"<username>\"}\n```"
            )

            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a precise IT support assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=500
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
                "repo_name": "unspecified",
                "access_type": "unspecified",
                "github_username": "unspecified"
            }

    async def generate_summary_response(self, ticket_record: dict, user_request: str, request_source: str = "email") -> dict:
        """Generate a summary or response based on the MongoDB ticket record, tailored for email or UI."""
        try:
            ticket_id = ticket_record.get("ado_ticket_id", "Unknown")
            subject = ticket_record.get("subject", "Unknown Request")
            email_chain = ticket_record.get("email_chain", [])
            updates = ticket_record.get("updates", [])
            details = ticket_record.get("details", {})

            # Prepare content for LLM
            email_chain_text = "\n".join(
                f"From: {e['from']}\nSubject: {e['subject']}\nTimestamp: {e['timestamp']}\nBody: {e['body']}\n"
                for e in email_chain
            )
            updates_text = "\n".join(
                f"Status: {u['status']}\nComment: {u['comment']}\nRevision: {u['revision_id']}\nTimestamp: {u['email_timestamp']}"
                for u in updates
            )
            details_text = json.dumps(details, indent=2)

            if request_source == "email":
                prompt = (
                    "You are an IT support assistant generating a concise, conversational email response summarizing a user's request. "
                    "The user has asked for a summary or details about a previous IT request, identified by a ticket record. "
                    "Use the provided ticket record (email chain, updates, and details) to create a natural, friendly email. "
                    "Include the ticket ID, a brief summary of the request, key actions taken with their timestamps, and current status. "
                    "Use timestamps from updates and email_chain to specify when key events occurred (e.g., access granted, revoked). "
                    "Do not mention analyzing the ticket record or the LLM process. "
                    "Keep the tone professional yet approachable, as if written by a real IT support agent named Agent. "
                    "Return JSON: {'summary_intent', 'email_response'}.\n\n"
                    f"User Request: {user_request}\n"
                    f"Ticket ID: {ticket_id}\n"
                    f"Subject: {subject}\n"
                    f"Email Chain:\n{email_chain_text}\n"
                    f"Updates:\n{updates_text}\n"
                    f"Details:\n{details_text}\n\n"
                    "Examples:\n"
                    "1. User Request: Can you give a quick summary of the poc access request?\n"
                    "   ```json\n{\"summary_intent\": \"summary_provided\", \"email_response\": \"Hi,\\n\\nThanks for reaching out! Here's a quick summary of your request (ticket #147):\\n\\n- Initial Request: You asked to grant read access to the 'poc' repo for testuser9731 on April 29, 2025, at 23:38:46.\\n- Actions Taken: Pull access was granted on April 29, 2025, at 23:38:52. You requested revocation on April 29, 2025, at 23:39:15, which was completed at 23:39:29.\\n- Current Status: The ticket is marked as done as of April 29, 2025, at 23:39:33.\\n\\nLet me know if you need more details!\\n\\nBest,\\nAgent\\nIT Support\"}\n```\n"
                    "Output format:\n"
                    "```json\n{\"summary_intent\": \"summary_provided\", \"email_response\": \"<response>\"}\n```"
                )
            else:  # request_source == "ui"
                prompt = (
                    "You are an IT support admin generating a concise summary of a ticket for an admin dashboard. "
                    "The admin has requested a summary or update about a previous IT request, identified by a ticket record. "
                    "Use the provided ticket record (email chain, updates, and details) to create a brief, professional summary. "
                    "Include the ticket ID, request type, key actions with timestamps, and current status in bullet points or raw text. "
                    "Use timestamps from updates and email_chain to specify when key events occurred (e.g., access granted, revoked). "
                    "Do not format as an email; the response should be formal and suitable for an IT admin reviewing ticket details. "
                    "Do not mention analyzing the ticket record or the LLM process. "
                    "Return JSON: {'summary_intent', 'email_response'} where 'email_response' is the summary text.\n\n"
                    f"User Request: {user_request}\n"
                    f"Ticket ID: {ticket_id}\n"
                    f"Subject: {subject}\n"
                    f"Email Chain:\n{email_chain_text}\n"
                    f"Updates:\n{updates_text}\n"
                    f"Details:\n{details_text}\n\n"
                    "Examples:\n"
                    "1. User Request: Can you give a quick summary of the poc access request?\n"
                    "   ```json\n{\"summary_intent\": \"summary_provided\", \"email_response\": \"Ticket #147 Summary:\\n- Request Type: GitHub Access\\n- Initial Request: Grant read access to 'poc' repo for testuser9731 on April 29, 2025, at 23:38:46.\\n- Actions: Pull access granted on April 29, 2025, at 23:38:52. Access revoked on April 29, 2025, at 23:39:29 after user request on April 29, 2025, at 23:39:15.\\n- Status: Done as of April 29, 2025, at 23:39:33.\"}\n```\n"
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
                max_tokens=300
            )

            result = response.choices[0].message.content.strip()
            if result.startswith("```json") and result.endswith("```"):
                result = result[7:-3].strip()

            parsed_result = json.loads(result)
            logger.info(f"Generated summary response for ticket ID={ticket_id} (source={request_source}): {parsed_result['summary_intent']}")
            return parsed_result
        except Exception as e:
            logger.error(f"Error generating summary for ticket ID={ticket_id}: {str(e)}")
            if request_source == "email":
                return {
                    "summary_intent": "error",
                    "email_response": (
                        f"Hi,\n\nI couldn't generate a summary for your request due to an issue. "
                        f"Please provide more details or contact IT support for assistance.\n\nBest,\nAgent\nIT Support"
                    )
                }
            else:
                return {
                    "summary_intent": "error",
                    "email_response": (
                        f"Error generating summary for ticket #{ticket_id}: {str(e)}. "
                        f"Please check the ticket details or contact support."
                    )
                }
    async def analyze_ticket_update(self, ticket_id: int, updates: list, attachments: list = None) -> dict:
        """Analyze ADO ticket updates and generate email response with remediation if attachments are present."""
        try:
            ticket_description = f"Ticket ID: {ticket_id} - IT support request"
            update_content = [
                f"Comment: {u['comment'] if u['comment'] else 'No comment provided.'}, Status: {u['status']}, Revision: {u['revision_id']}"
                for u in updates
            ]
            update_text = "\n".join(update_content)
            attachment_info = ""
            remediation = ""

            if attachments:
                attachment_info = f"Attachments: {', '.join(a['filename'] for a in attachments)}"
                remediation_prompt = (
                    "You are an IT support assistant generating troubleshooting steps based on image attachments. "
                    "Provide 3-5 concise, actionable steps to help the user troubleshoot the issue. "
                    "Format as a numbered list. "
                    f"Attachments: {', '.join(a['filename'] for a in attachments)}\n"
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
                "You are a helpful IT support admin writing a personalized email reply to a user. "
                "Create a natural, conversational response as if you're a real IT support person named Agent. "
                "Include ticket ID, current status, and key information from the updates. "
                "If attachments are present, mention they are included for reference. "
                "Sound friendly and helpful, use first-person, and vary your language. "
                "Keep it concise but complete. Mention ticket status in a casual way. "
                "Return JSON: {'update_intent', 'email_response', 'remediation'}.\n\n"
                f"Ticket Description: {ticket_description}\n"
                f"Updates:\n{update_text}\n"
                f"{attachment_info}\n\n"
                "Examples:\n"
                "1. Updates: Comment: Access granted, Status: Doing, Revision: 2\n"
                "   ```json\n{\"update_intent\": \"action_completed\", \"email_response\": \"Hi there,\\n\\nI've processed your request and granted the access you needed to the repository. Your ticket (#123) is still open as I'll need to revoke the access when you're done with your work - just let me know when that is.\\n\\nLet me know if you need anything else!\\n\\nThanks,\\nAgent\\nIT Support\", \"remediation\": \"\"}\n```\n"
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
                max_tokens=300
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
            status = updates[-1]['status'] if updates else "Unknown"
            email_response = (
                f"Dear User,\n\nYour ticket (ID: {ticket_id}) is currently in '{status}' status. "
                "We encountered an issue processing the latest update. Please contact IT support if needed.\n\n"
                "Best regards,\nIT Support Team"
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
        """Check if all GitHub actions in the ticket are completed and no pending actions remain."""
        github_actions = ticket.get("details", {}).get("github", [])
        pending_actions = ticket.get("pending_actions", False)
        actions_completed = all(action["status"] in ["completed", "revoked", "failed"] for action in github_actions)
        return actions_completed and not pending_actions

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
                "sender": sender
            })

            # Analyze intent
            intent_result = await self.analyze_intent(subject, body, attachments)
            intent = intent_result["intent"]
            ticket_description = intent_result["ticket_description"]
            actions = intent_result["actions"]
            pending_actions = intent_result["pending_actions"] or (existing_ticket.get("pending_actions", False) if is_follow_up else False)
            repo_name = intent_result.get("repo_name", "unspecified")
            access_type = intent_result.get("access_type", "unspecified")
            github_username = intent_result.get("github_username", "unspecified")

            await broadcast({
                "type": "intent_analyzed",
                "email_id": email_id,
                "intent": intent,
                "pending_actions": pending_actions
            })

            # Handle non-intent emails
            if intent == "non_intent":
                logger.info(f"Non-intent email detected (ID={email_id}). Stopping workflow.")
                # Update email_chain in existing ticket if follow-up
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
                return {
                    "status": "success",
                    "intent": "non_intent",
                    "ticket_id": existing_ticket["ado_ticket_id"] if is_follow_up else None,
                    "message": "Non-intent email processed; no further action taken",
                    "actions": [],
                    "pending_actions": False
                }

            if intent == "request_summary" and is_follow_up:
                # Handle summary request
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
                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id
                    })

                return {
                    "status": "success",
                    "ticket_id": ticket_record["ado_ticket_id"],
                    "intent": intent,
                    "summary_intent": summary_result["summary_intent"],
                    "actions": [],
                    "pending_actions": False
                }

            ticket_id = existing_ticket["ado_ticket_id"] if is_follow_up else None
            github_result = None
            completed_actions = []

            if is_follow_up and intent in ["github_access_request", "github_revoke_access"]:
                ticket_id = existing_ticket["ado_ticket_id"]
                github_details = {
                    "request_type": intent,
                    "repo_name": repo_name,
                    "username": github_username,
                    "access_type": access_type if intent == "github_access_request" else "unspecified",
                    "status": "pending",
                    "message": f"Processing {intent} for {github_username} on {repo_name}"
                }

                # Update ticket with new GitHub action
                update_operation = {
                    "$push": {
                        "details.github": github_details,
                        "updates": {
                            "status": "Doing",
                            "comment": github_details["message"],
                            "revision_id": f"git-{intent.split('_')[1]}-{ticket_id}-{len(existing_ticket.get('updates', [])) + 1}",
                            "email_sent": False,
                            "email_message_id": None,
                            "email_timestamp": datetime.now().isoformat()
                        }
                    },
                    "$set": {
                        "pending_actions": pending_actions
                    }
                }
                self.tickets_collection.update_one({"ado_ticket_id": ticket_id}, update_operation)

                # Perform GitHub action
                if intent == "github_access_request":
                    github_result = await self.kernel.invoke(
                        self.kernel.plugins["git"]["grant_repo_access"],
                        repo_name=repo_name,
                        github_username=github_username,
                        access_type=access_type
                    )
                    github_result = github_result.value if github_result else {"success": False, "message": "GitHub grant action failed"}
                    github_details["status"] = "completed" if github_result["success"] else "failed"
                    github_details["message"] = github_result["message"]
                    completed_actions.append({"action": "grant_access", "completed": github_result["success"]})
                else:  # github_revoke_access
                    github_result = await self.kernel.invoke(
                        self.kernel.plugins["git"]["revoke_repo_access"],
                        repo_name=repo_name,
                        github_username=github_username
                    )
                    github_result = github_result.value if github_result else {"success": False, "message": "GitHub revoke action failed"}
                    github_details["status"] = "revoked" if github_result["success"] else "failed"
                    github_details["message"] = github_result["message"]
                    completed_actions.append({"action": "revoke_access", "completed": github_result["success"]})
                    pending_actions = False  # Revocation completes the pending action

                # Update ticket with GitHub action result
                self.tickets_collection.update_one(
                    {"ado_ticket_id": ticket_id, "details.github": {"$elemMatch": {"repo_name": repo_name, "username": github_username, "request_type": intent}}},
                    {
                        "$set": {
                            "details.github.$[elem].status": github_details["status"],
                            "details.github.$[elem].message": github_details["message"],
                            "pending_actions": pending_actions
                        },
                        "$push": {
                            "updates": {
                                "status": github_details["status"],
                                "comment": github_details["message"],
                                "revision_id": f"git-result-{ticket_id}-{len(existing_ticket.get('updates', [])) + 2}",
                                "email_sent": False,
                                "email_message_id": None,
                                "email_timestamp": datetime.now().isoformat()
                            }
                        }
                    },
                    array_filters=[{"elem.repo_name": repo_name, "elem.username": github_username, "elem.request_type": intent}]
                )

                await broadcast({
                    "type": "github_action",
                    "email_id": email_id,
                    "ticket_id": ticket_id,
                    "success": github_result["success"],
                    "message": github_details["message"]
                })

                # Check if all actions are completed
                updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
                all_completed = await self.are_all_actions_completed(updated_ticket)
                ado_status = "Done" if all_completed else "Doing"

                # Update ADO ticket
                await self.kernel.invoke(
                    self.kernel.plugins["ado"]["update_ticket"],
                    ticket_id=ticket_id,
                    status=ado_status,
                    comment=github_details["message"]
                )

                # Send email reply
                updates_result = await self.kernel.invoke(
                    self.kernel.plugins["ado"]["get_ticket_updates"],
                    ticket_id=ticket_id
                )
                updates = updates_result.value if updates_result else []
                update_result = await self.analyze_ticket_update(ticket_id, updates, attachments)
                email_response = update_result["email_response"]
                remediation = update_result["remediation"]

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=email_response,
                    thread_id=thread_id,
                    message_id=email_id,
                    attachments=attachments,
                    remediation=remediation
                )
                reply = reply_result.value if reply_result else None

                if reply:
                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id
                    })

                return {
                    "status": "success",
                    "ticket_id": ticket_id,
                    "intent": intent,
                    "github": github_result,
                    "actions": completed_actions,
                    "pending_actions": pending_actions
                }

            # Handle new email
            ticket_result = await self.kernel.invoke(
                self.kernel.plugins["ado"]["create_ticket"],
                title=subject,
                description=ticket_description,
                email_content=email_content,
                attachments=attachments
            )
            if not ticket_result or not ticket_result.value:
                logger.error(f"Failed to create ticket for email ID={email_id}")
                return {"status": "error", "message": "Ticket creation failed"}

            ticket_data = ticket_result.value
            ticket_id = ticket_data["id"]
            ado_url = ticket_data["url"]

            await broadcast({
                "type": "ticket_created",
                "email_id": email_id,
                "ticket_id": ticket_id,
                "ado_url": ado_url,
                "intent": intent
            })

            github_details = None
            if intent == "github_access_request" and repo_name != "unspecified" and github_username != "unspecified":
                github_result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["grant_repo_access"],
                    repo_name=repo_name,
                    github_username=github_username,
                    access_type=access_type
                )
                github_result = github_result.value if github_result else {"success": False, "message": "GitHub action failed"}
                github_details = {
                    "request_type": intent,
                    "repo_name": repo_name,
                    "username": github_username,
                    "access_type": access_type,
                    "status": "completed" if github_result["success"] else "failed",
                    "message": github_result["message"]
                }
                completed_actions.append({"action": "grant_access", "completed": github_result["success"]})

                await self.kernel.invoke(
                    self.kernel.plugins["ado"]["update_ticket"],
                    ticket_id=ticket_id,
                    status="Doing" if pending_actions else "Done",
                    comment=github_result["message"]
                )

                await broadcast({
                    "type": "github_action",
                    "email_id": email_id,
                    "ticket_id": ticket_id,
                    "success": github_result["success"],
                    "message": github_result["message"]
                })

            # Update ticket in MongoDB
            ticket_record = {
                "ado_ticket_id": ticket_id,
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
                "type_of_request": "github" if intent.startswith("github_") else intent,
                "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]}
            }
            if github_details:
                ticket_record["details"]["github"] = [github_details]

            self.tickets_collection.insert_one(ticket_record)

            # Send email reply
            updates_result = await self.kernel.invoke(
                self.kernel.plugins["ado"]["get_ticket_updates"],
                ticket_id=ticket_id
            )
            updates = updates_result.value if updates_result else []
            update_result = await self.analyze_ticket_update(ticket_id, updates, attachments)
            email_response = update_result["email_response"]
            remediation = update_result["remediation"]

            reply_result = await self.kernel.invoke(
                self.kernel.plugins["email_sender"]["send_reply"],
                to=sender,
                subject=subject,
                body=email_response,
                thread_id=thread_id,
                message_id=email_id,
                attachments=attachments,
                remediation=remediation
            )
            reply = reply_result.value if reply_result else None

            if reply:
                await broadcast({
                    "type": "email_reply",
                    "email_id": email_id,
                    "thread_id": thread_id
                })

            return {
                "status": "success",
                "ticket_id": ticket_id,
                "intent": intent,
                "github": github_result,
                "actions": completed_actions,
                "pending_actions": pending_actions
            }
        except Exception as e:
            logger.error(f"Error processing email ID={email_id}: {str(e)}")
            return {"status": "error", "message": str(e)}