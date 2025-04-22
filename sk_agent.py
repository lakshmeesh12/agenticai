import os
import logging
import json
from semantic_kernel import Kernel
from openai import AzureOpenAI
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SKAgent:
    def __init__(self, kernel: Kernel):
        self.kernel = kernel
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2023-05-15"
        )
        logger.info("Initialized SKAgent with AzureOpenAI client")

    async def analyze_intent(self, subject: str, body: str) -> dict:
        """Analyze email intent using Azure OpenAI."""
        try:
            # Clean HTML from body
            if "<html>" in body.lower():
                body = BeautifulSoup(body, "html.parser").get_text(separator=" ").strip()
            else:
                body = body.strip()

            logger.info(f"Analyzing intent - Subject: {subject}, Body: {body[:100]}...")

            content = f"Subject: {subject}\nBody: {body}"

            prompt = (
                "You are an IT support assistant analyzing an email to determine the user's intent. "
                "Classify the intent as 'github_access_request', 'github_revoke_access', or 'general_it_request'. "
                "Determine if the request is a single action or involves multiple/pending actions. "
                "Rules:\n"
                "- GitHub access request:\n"
                "  - Intent: 'github_access_request'.\n"
                "  - Extract: repo_name, access_type ('pull' for read, 'push' for write, 'unspecified' if unclear), github_username.\n"
                "  - Action: {'action': 'grant_access', 'repo_name', 'access_type', 'github_username'}.\n"
                "  - Pending actions: true if phrases like 'I will let you know', 'once work is completed', 'revoke later' are present; false otherwise.\n"
                "  - Ticket description: e.g., 'Grant read access to poc for testuser9731'.\n"
                "- GitHub access revocation:\n"
                "  - Intent: 'github_revoke_access'.\n"
                "  - Extract: repo_name, github_username.\n"
                "  - Action: {'action': 'revoke_access', 'repo_name', 'github_username'}.\n"
                "  - Pending actions: false (revocation typically completes the request).\n"
                "  - Ticket description: e.g., 'Revoke access to poc for testuser9731'.\n"
                "- Other IT support action:\n"
                "  - Intent: 'general_it_request'.\n"
                "  - Actions: [] (no specific actions).\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: Summarize issue, e.g., 'Resolve VPN connection issue'.\n"
                "- Unclear intent:\n"
                "  - Intent: 'error'.\n"
                "  - Actions: [].\n"
                "  - Pending actions: false.\n"
                "  - Ticket description: 'Unable to determine intent'.\n"
                "Return JSON: {'intent', 'ticket_description', 'actions', 'pending_actions', 'repo_name', 'access_type', 'github_username'}.\n"
                "The 'actions' list contains action objects. For single-action requests, include one action. For multi-action, include all actions.\n\n"
                f"Email:\n{content}\n\n"
                "Examples:\n"
                "1. Subject: Request access to poc repo\nBody: Grant read access to poc. Username: testuser9731.\n"
                "   ```json\n{\"intent\": \"github_access_request\", \"ticket_description\": \"Grant read access to poc for testuser9731\", \"actions\": [{\"action\": \"grant_access\", \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}], \"pending_actions\": false, \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}\n```\n"
                "2. Subject: Grant access to poc\nBody: Please grant read access to poc for testuser9731. I will let you know when to revoke access.\n"
                "   ```json\n{\"intent\": \"github_access_request\", \"ticket_description\": \"Grant read access to poc for testuser9731\", \"actions\": [{\"action\": \"grant_access\", \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}, {\"action\": \"revoke_access\", \"repo_name\": \"poc\", \"github_username\": \"testuser9731\"}], \"pending_actions\": true, \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}\n```\n"
                "3. Subject: Revoke access to poc repo\nBody: Work is done. Revoke testuser9731 access to poc.\n"
                "   ```json\n{\"intent\": \"github_revoke_access\", \"ticket_description\": \"Revoke access to poc for testuser9731\", \"actions\": [{\"action\": \"revoke_access\", \"repo_name\": \"poc\", \"github_username\": \"testuser9731\"}], \"pending_actions\": false, \"repo_name\": \"poc\", \"access_type\": \"unspecified\", \"github_username\": \"testuser9731\"}\n```\n"
                "4. Subject: VPN issue\nBody: Can’t connect to VPN. Error: Invalid settings.\n"
                "   ```json\n{\"intent\": \"general_it_request\", \"ticket_description\": \"Resolve VPN connection issue\", \"actions\": [], \"pending_actions\": false, \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\"}\n```\n"
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
                "pending_actions": false,
                "repo_name": "unspecified",
                "access_type": "unspecified",
                "github_username": "unspecified"
            }

    async def analyze_ticket_update(self, ticket_id: int, updates: list) -> dict:
        """Analyze ADO ticket updates and generate email response."""
        try:
            ticket_description = f"Ticket ID: {ticket_id} - IT support request"
            update_content = [
                f"Comment: {u['comment'] if u['comment'] else 'No comment provided.'}, Status: {u['status']}, Revision: {u['revision_id']}"
                for u in updates
            ]
            update_text = "\n".join(update_content)

            prompt = (
                "You are an IT support assistant analyzing Azure DevOps ticket updates. "
                "Determine the intent of the updates (e.g., 'action_completed', 'additional_info_needed', 'issue_closed', 'access_revoked'). "
                "Generate a polite email response addressing 'Dear User', including ticket ID, status, and comments. "
                "If no comment, mention status change. For 'access_revoked', confirm access removal. "
                "Return JSON: {'update_intent', 'email_response'}.\n\n"
                f"Ticket Description: {ticket_description}\n"
                f"Updates:\n{update_text}\n\n"
                "Examples:\n"
                "1. Updates: Comment: Access granted, Status: Doing, Revision: 2\n"
                "   ```json\n{\"update_intent\": \"action_completed\", \"email_response\": \"Dear User,\\n\\nYour ticket (ID: {ticket_id}) has been updated. Access to the repository has been granted. Current status: Doing. Please inform us when the work is complete to revoke access.\\n\\nBest regards,\\nIT Support Team\"}\n```\n"
                "2. Updates: Comment: Access revoked for testuser9731, Status: Done, Revision: 3\n"
                "   ```json\n{\"update_intent\": \"access_revoked\", \"email_response\": \"Dear User,\\n\\nYour ticket (ID: {ticket_id}) has been updated. Access for testuser9731 has been revoked. Current status: Done.\\n\\nBest regards,\\nIT Support Team\"}\n```\n"
                "3. Updates: Comment: No comment provided., Status: Done, Revision: 1\n"
                "   ```json\n{\"update_intent\": \"issue_closed\", \"email_response\": \"Dear User,\\n\\nYour ticket (ID: {ticket_id}) has been resolved. Current status: Done.\\n\\nBest regards,\\nIT Support Team\"}\n```\n"
                "Output format:\n"
                "```json\n{\"update_intent\": \"<intent>\", \"email_response\": \"<response>\"}\n```"
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
                "email_response": email_response
            }

    async def process_email(self, email: dict, broadcast, existing_ticket: dict = None) -> dict:
        """Process an email through the workflow: analyze, create/update ticket, perform actions, send reply."""
        try:
            email_id = email["id"]
            subject = email["subject"]
            body = email["body"]
            sender = email["from"]
            thread_id = email.get("threadId", email_id)
            is_follow_up = bool(existing_ticket)

            # Broadcast email detection
            await broadcast({
                "type": "email_detected",
                "email_id": email_id,
                "subject": subject,
                "sender": sender
            })

            # Analyze intent
            intent_result = await self.analyze_intent(subject, body)
            intent = intent_result["intent"]
            ticket_description = intent_result["ticket_description"]
            actions = intent_result["actions"]
            pending_actions = intent_result["pending_actions"]
            repo_name = intent_result.get("repo_name", "unspecified")
            access_type = intent_result.get("access_type", "unspecified")
            github_username = intent_result.get("github_username", "unspecified")

            await broadcast({
                "type": "intent_analyzed",
                "email_id": email_id,
                "intent": intent,
                "pending_actions": pending_actions
            })

            if intent == "github_revoke_access" and is_follow_up:
                # Handle follow-up email to revoke access
                ticket_id = existing_ticket["ado_ticket_id"]
                github_result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["revoke_repo_access"],
                    repo_name=repo_name,
                    github_username=github_username
                )
                github_result = github_result.value if github_result else {"success": False, "message": "GitHub revoke action failed"}
                status = "Done"  # Revocation typically completes all actions
                comment = github_result["message"]

                await self.kernel.invoke(
                    self.kernel.plugins["ado"]["update_ticket"],
                    ticket_id=ticket_id,
                    status=status,
                    comment=comment
                )

                await broadcast({
                    "type": "github_action",
                    "email_id": email_id,
                    "ticket_id": ticket_id,
                    "success": github_result["success"],
                    "message": github_result["message"]
                })

                # Analyze ticket updates and send reply
                updates_result = await self.kernel.invoke(
                    self.kernel.plugins["ado"]["get_ticket_updates"],
                    ticket_id=ticket_id
                )
                updates = updates_result.value if updates_result else []
                update_result = await self.analyze_ticket_update(ticket_id, updates)
                email_response = update_result["email_response"]

                reply_result = await self.kernel.invoke(
                    self.kernel.plugins["email_sender"]["send_reply"],
                    to=sender,
                    subject=subject,
                    body=email_response,
                    thread_id=thread_id,
                    message_id=email_id
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
                    "github": github_result,
                    "actions": [{"action": "revoke_access", "completed": github_result["success"]}],
                    "pending_actions": False
                }

            # Handle new email
            # Create ADO ticket
            ticket_result = await self.kernel.invoke(
                self.kernel.plugins["ado"]["create_ticket"],
                title=subject,
                description=ticket_description
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

            github_result = None
            completed_actions = []
            if intent == "github_access_request" and repo_name != "unspecified" and github_username != "unspecified":
                github_result = await self.kernel.invoke(
                    self.kernel.plugins["git"]["grant_repo_access"],
                    repo_name=repo_name,
                    github_username=github_username,
                    access_type=access_type
                )
                github_result = github_result.value if github_result else {"success": False, "message": "GitHub action failed"}
                status = "Done" if not pending_actions else "Doing"
                comment = github_result["message"]
                completed_actions.append({"action": "grant_access", "completed": github_result["success"]})

                await self.kernel.invoke(
                    self.kernel.plugins["ado"]["update_ticket"],
                    ticket_id=ticket_id,
                    status=status,
                    comment=comment
                )

                await broadcast({
                    "type": "github_action",
                    "email_id": email_id,
                    "ticket_id": ticket_id,
                    "success": github_result["success"],
                    "message": github_result["message"]
                })
            else:
                # Update ticket for general IT request
                status = "To Do"
                comment = "Ticket created for general IT request"
                await self.kernel.invoke(
                    self.kernel.plugins["ado"]["update_ticket"],
                    ticket_id=ticket_id,
                    status=status,
                    comment=comment
                )

            # Analyze ticket updates and send reply
            updates_result = await self.kernel.invoke(
                self.kernel.plugins["ado"]["get_ticket_updates"],
                ticket_id=ticket_id
            )
            updates = updates_result.value if updates_result else []
            update_result = await self.analyze_ticket_update(ticket_id, updates)
            email_response = update_result["email_response"]

            reply_result = await self.kernel.invoke(
                self.kernel.plugins["email_sender"]["send_reply"],
                to=sender,
                subject=subject,
                body=email_response,
                thread_id=thread_id,
                message_id=email_id
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