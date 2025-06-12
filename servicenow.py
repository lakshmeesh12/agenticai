import os
from dotenv import load_dotenv
import logging
import requests
import datetime
import tempfile
import base64
import mimetypes
from semantic_kernel.functions import kernel_function
from pymongo import MongoClient
from tenacity import retry, stop_after_attempt, wait_fixed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class ServiceNowPlugin:
    def __init__(self):
        try:
            self.client = ServiceNowClient()
        except Exception as e:
            logger.error(f"Failed to initialize ServiceNow client: {str(e)}")
            self.client = None

    @kernel_function(description="Fetch all incidents in the ServiceNow instance.", name="get_all_incidents")
    async def get_all_incidents(self) -> list:
        if not self.client:
            logger.error("ServiceNow client not initialized")
            return []
        return self.client.get_all_incidents()

    @kernel_function(description="Create a new incident in ServiceNow with optional email and file attachments.", name="create_ticket")
    async def create_ticket(self, title: str, description: str, email_content: str = None, attachments: list = None) -> dict:
        if not self.client:
            logger.error("ServiceNow client not initialized")
            return None
        return self.client.create_ticket(title, description, email_content, attachments)

    @kernel_function(description="Update a ServiceNow incident with state and comment.", name="update_ticket")
    async def update_ticket(self, ticket_id: str, state: str, comment: str) -> dict:
        if not self.client:
            logger.error("ServiceNow client not initialized")
            return None
        return self.client.update_ticket(ticket_id, state, comment)

    @kernel_function(description="Fetch updates for a ServiceNow incident.", name="get_ticket_updates")
    async def get_ticket_updates(self, ticket_id: str) -> list:
        if not self.client:
            logger.error("ServiceNow client not initialized")
            return []
        return self.client.get_ticket_updates(ticket_id)

class ServiceNowClient:
    def __init__(self):
        self.instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        self.client_id = os.getenv("SERVICENOW_CLIENT_ID")
        self.client_secret = os.getenv("SERVICENOW_CLIENT_SECRET")
        self.username = os.getenv("SERVICENOW_USERNAME")
        self.password = os.getenv("SERVICENOW_PASSWORD")
        self.is_initialized = False
        self.access_token = None

        if not all([self.instance_url, self.client_id, self.client_secret, self.username, self.password]):
            logger.error("Missing ServiceNow credentials in .env file")
            return

        self._initialize_client()

    def _initialize_client(self):
        try:
            self.access_token = self._get_access_token()
            self.headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            self.is_initialized = True
            logger.info("Initialized ServiceNow client")
        except Exception as e:
            logger.error(f"ServiceNow client initialization failed: {str(e)}")
            self.is_initialized = False

    def _get_access_token(self):
        try:
            token_url = f"{self.instance_url.rstrip('/')}/oauth_token.do"
            data = {
                "grant_type": "password",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": self.username,
                "password": self.password,
                "scope": "incident.read incident.write sys_choice.read attachment.read attachment.write"  # Added attachment scopes
            }
            response = requests.post(token_url, data=data, timeout=10)
            if response.status_code == 401:
                logger.error("Unauthorized: Invalid ServiceNow credentials")
                raise ValueError("Invalid ServiceNow credentials")
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logger.error("No access token returned in response")
                raise ValueError("Failed to retrieve access token")
            return access_token
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error obtaining ServiceNow access token: {str(e)}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error obtaining ServiceNow access token: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error obtaining ServiceNow access token: {str(e)}")
            raise

    def _refresh_token_if_needed(self, response):
        if response.status_code in [401, 403]:
            logger.info("Attempting to refresh ServiceNow access token due to authorization error")
            try:
                self.access_token = self._get_access_token()
                self.headers["Authorization"] = f"Bearer {self.access_token}"
                logger.info("Access token refreshed successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to refresh access token: {str(e)}")
                return False
        return False

    def _get_valid_close_codes(self):
        """Fetch valid close_code values from ServiceNow choice list."""
        try:
            url = f"{self.instance_url.rstrip('/')}/api/now/table/sys_choice"
            params = {
                "sysparm_query": "name=incident^element=close_code",
                "sysparm_fields": "value,label"
            }
            response = requests.get(url, headers=self.headers, params=params)
            if self._refresh_token_if_needed(response):
                response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            choices = response.json().get("result", [])
            return [choice["value"] for choice in choices]
        except Exception as e:
            logger.error(f"Failed to fetch close_code choices: {str(e)}")
            return ["Solved (Permanently)", "Solved (Work Around)", "Not Solved (Not Reproducible)"]  # Fallback

    def _get_incident_state(self, ticket_id):
        """Fetch current state of an incident."""
        try:
            url = f"{self.instance_url.rstrip('/')}/api/now/table/incident/{ticket_id}"
            params = {"sysparm_fields": "state"}
            response = requests.get(url, headers=self.headers, params=params)
            if self._refresh_token_if_needed(response):
                response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json().get("result", {}).get("state", "1")
        except Exception as e:
            logger.error(f"Failed to fetch state for incident sys_id={ticket_id}: {str(e)}")
            return None

    def create_ticket(self, title, description, email_content=None, attachments=None):
        if not self.is_initialized:
            logger.error("ServiceNow client not initialized")
            return None
        try:
            url = f"{self.instance_url.rstrip('/')}/api/now/table/incident"
            payload = {
                "short_description": title,
                "description": description,
                "state": "1",  # New
                "urgency": "3",
                "impact": "3",
                "category": "inquiry"
            }
            response = requests.post(url, headers=self.headers, json=payload)
            if self._refresh_token_if_needed(response):
                response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            incident = response.json().get("result", {})
            ticket = {
                "sys_id": incident.get("sys_id"),
                "number": incident.get("number"),
                "url": f"{self.instance_url.rstrip('/')}/nav_to.do?uri=incident.do?sys_id={incident.get('sys_id')}",
                "attachments": []
            }
            logger.info(f"Created ServiceNow incident: sys_id={ticket['sys_id']}, Number={ticket['number']}")

            if email_content:
                attachment_url = self._upload_attachment(email_content, f"email_{ticket['sys_id']}.eml", is_eml=True, ticket_sys_id=ticket["sys_id"])
                if attachment_url:
                    ticket["attachments"].append({"filename": f"email_{ticket['sys_id']}.eml", "url": attachment_url})
                    logger.info(f"Attached email to ServiceNow incident: sys_id={ticket['sys_id']}")
                else:
                    logger.warning(f"Failed to attach email to ServiceNow incident: sys_id={ticket['sys_id']}")

            if attachments:
                for attachment in attachments:
                    if not isinstance(attachment, dict) or "path" not in attachment or "filename" not in attachment:
                        logger.error(f"Invalid attachment format: {attachment}")
                        continue
                    attachment_url = self._upload_attachment(
                        attachment["path"], attachment["filename"], is_eml=False, ticket_sys_id=ticket["sys_id"]
                    )
                    if attachment_url:
                        ticket["attachments"].append({"filename": attachment["filename"], "url": attachment_url})
                        logger.info(f"Attached {attachment['filename']} to ServiceNow incident: sys_id={ticket['sys_id']}")
                    else:
                        logger.warning(f"Failed to attach {attachment['filename']} to ServiceNow incident: sys_id={ticket['sys_id']}")

            return ticket
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error creating ServiceNow incident: {str(e)} - Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error creating ServiceNow incident: {str(e)}")
            return None

    def _upload_attachment(self, content, filename, is_eml=False, ticket_sys_id=None):
        if not self.is_initialized:
            logger.error("ServiceNow client not initialized")
            return None
        temp_file_path = None
        try:
            if is_eml:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".eml", mode='w', encoding='utf-8') as temp_file:
                    temp_file.write(content)
                    temp_file_path = temp_file.name
            else:
                temp_file_path = content

            if not os.path.exists(temp_file_path):
                logger.error(f"Attachment file {temp_file_path} does not exist")
                return None

            url = f"{self.instance_url.rstrip('/')}/api/now/attachment/file"
            params = {
                "table_name": "incident",
                "table_sys_id": ticket_sys_id,
                "file_name": filename
            }
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }

            # Determine MIME type and validate file extension
            mime_type = "message/rfc822" if is_eml else mimetypes.guess_type(filename)[0] or "application/octet-stream"
            allowed_extensions = {'.eml', '.png', '.jpg', '.jpeg', '.pdf', '.txt', '.doc', '.docx'}
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in allowed_extensions:
                logger.error(f"Unsupported file extension {file_ext} for attachment {filename}")
                return None

            with open(temp_file_path, 'rb') as file:
                files = {
                    "file": (filename, file, mime_type)
                }
                response = requests.post(
                    url, headers=headers, params=params, files=files, timeout=10
                )
                if response.status_code != 201:
                    logger.error(f"Failed to upload attachment {filename}: {response.status_code} {response.reason} - {response.text}")
                    return None
                response.raise_for_status()
                attachment = response.json().get("result", {})
                logger.info(f"Uploaded attachment: {filename} to incident sys_id={ticket_sys_id}")
                return attachment.get("download_link")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error uploading attachment {filename}: {str(e)} - Response: {e.response.text if e.response else 'No response'}")
            return None
        except Exception as e:
            logger.error(f"Error uploading attachment {filename}: {str(e)}")
            return None
        finally:
            if is_eml and temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    logger.info(f"Deleted temporary file: {temp_file_path}")
                except Exception as e:
                    logger.error(f"Error deleting temporary file {temp_file_path}: {str(e)}")

    def get_all_incidents(self):
        if not self.is_initialized:
            logger.error("ServiceNow client not initialized")
            return []
        try:
            url = f"{self.instance_url.rstrip('/')}/api/now/table/incident"
            params = {
                "sysparm_fields": "sys_id,number,state,short_description,sys_created_on,sys_updated_on",
                "sysparm_limit": 100
            }
            response = requests.get(url, headers=self.headers, params=params)
            if self._refresh_token_if_needed(response):
                response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            incidents = response.json().get("result", [])
            result = [
                {
                    "sys_id": inc["sys_id"],
                    "number": inc["number"],
                    "state": inc["state"],
                    "short_description": inc["short_description"],
                    "created": inc["sys_created_on"],
                    "updated": inc["sys_updated_on"]
                }
                for inc in incidents
            ]
            logger.info(f"Fetched {len(result)} ServiceNow incidents")
            return result
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error fetching ServiceNow incidents: {str(e)} - Response: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Error fetching ServiceNow incidents: {str(e)}")
            return []

    def get_ticket_updates(self, ticket_id):
        if not self.is_initialized:
            logger.error("ServiceNow client not initialized")
            return []
        try:
            updates = []
            client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
            db = client[os.getenv("DB_NAME", "your_database")]
            collection = db[os.getenv("COLLECTION_NAME", "tickets_collection")]
            ticket_record = collection.find_one({"servicenow_sys_id": ticket_id})
            last_fields = ticket_record.get("last_fields", {}) if ticket_record else {}

            # Check if incident exists
            url = f"{self.instance_url.rstrip('/')}/api/now/table/incident/{ticket_id}"
            params = {"sysparm_fields": "sys_id"}
            response = requests.get(url, headers=self.headers, params=params)
            if self._refresh_token_if_needed(response):
                response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 404:
                logger.warning(f"Incident sys_id={ticket_id} not found in ServiceNow")
                collection.update_one(
                    {"servicenow_sys_id": ticket_id},
                    {"$set": {"servicenow_sys_id": None}}
                )
                logger.info(f"Updated MongoDB: Removed invalid servicenow_sys_id={ticket_id}")
                client.close()
                return []

            # Fetch incident details
            params = {
                "sysparm_fields": "sys_id,state,work_notes,comments,sys_updated_on,caller_id,close_code,close_notes,short_description,priority,u_action,u_repository,u_request_type"
            }
            response = requests.get(url, headers=self.headers, params=params)
            if self._refresh_token_if_needed(response):
                response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            incident = response.json().get("result", {})

            # Fetch journal entries
            journal_url = f"{self.instance_url.rstrip('/')}/api/now/table/sys_journal_field"
            journal_params = {
                "sysparm_query": f"element_id={ticket_id}^element=comments^ORelement=work_notes",
                "sysparm_fields": "value,sys_created_on,element,sys_id"
            }
            journal_response = requests.get(journal_url, headers=self.headers, params=journal_params)
            if self._refresh_token_if_needed(journal_response):
                journal_response = requests.get(journal_url, headers=self.headers, params=journal_params)
            journal_response.raise_for_status()
            journal_entries = journal_response.json().get("result", [])

            # Fetch attachments
            attachment_url = f"{self.instance_url.rstrip('/')}/api/now/attachment"
            attachment_params = {"sysparm_query": f"table_sys_id={ticket_id}"}
            attachment_response = requests.get(attachment_url, headers=self.headers, params=attachment_params)
            if self._refresh_token_if_needed(attachment_response):
                attachment_response = requests.get(attachment_url, headers=self.headers, params=attachment_params)
            attachment_response.raise_for_status()
            attachments = [
                {"filename": att["file_name"], "url": att["download_link"]}
                for att in attachment_response.json().get("result", [])
            ]

            # Compare fields to detect changes
            fields_to_check = ["state", "caller_id", "close_code", "close_notes", "short_description", "priority", "u_action", "u_repository", "u_request_type"]
            current_fields = {
                "state": incident.get("state", ""),
                "caller_id": incident.get("caller_id", ""),
                "close_code": incident.get("close_code", ""),
                "close_notes": incident.get("close_notes", ""),
                "short_description": incident.get("short_description", ""),
                "priority": incident.get("priority", ""),
                "u_action": incident.get("u_action", ""),
                "u_repository": incident.get("u_repository", ""),
                "u_request_type": incident.get("u_request_type", "")
            }

            field_changes = []
            for field in fields_to_check:
                old_value = last_fields.get(field, "")
                new_value = current_fields[field]
                if old_value != new_value:
                    field_changes.append({
                        "field": field,
                        "old_value": old_value,
                        "new_value": new_value,
                        "sys_updated_on": incident["sys_updated_on"]
                    })

            # Add journal entries
            for entry in journal_entries:
                field_changes.append({
                    "field": entry["element"],
                    "old_value": "",
                    "new_value": entry["value"],
                    "sys_updated_on": entry["sys_created_on"],
                    "sys_id": entry["sys_id"]
                })

            # Create updates list
            for change in field_changes:
                updates.append({
                    "sys_id": incident.get("sys_id", ticket_id),
                    "field": change["field"],
                    "old_value": change.get("old_value", ""),
                    "new_value": change.get("new_value", ""),
                    "sys_updated_on": change["sys_updated_on"],
                    "attachments": attachments,
                    "source": "servicenow"
                })

            # Update MongoDB
            collection.update_one(
                {"servicenow_sys_id": ticket_id},
                {"$set": {"last_fields": current_fields}},
                upsert=True
            )
            client.close()

            logger.info(f"Fetched {len(updates)} updates for ServiceNow incident sys_id={ticket_id}")
            return updates
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error fetching updates for ServiceNow incident sys_id={ticket_id}: {str(e)} - Response: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Error fetching updates for ServiceNow incident sys_id={ticket_id}: {str(e)}")
            return []

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
    def update_ticket(self, ticket_id, state, comment):
        if not self.is_initialized:
            logger.error("ServiceNow client not initialized")
            raise ValueError("ServiceNow client not initialized")

        try:
            # Updated state map based on ServiceNow standards
            state_map = {
                "New": "1",
                "In Progress": "2",
                "On Hold": "3",
                "Resolved": "6",
                "Closed": "7"
            }
            state_code = state_map.get(state, "1")

            # Get current state to validate transition
            current_state = self._get_incident_state(ticket_id)
            logger.info(f"Current state for incident sys_id={ticket_id}: {current_state}")

            # Get valid close codes
            valid_close_codes = self._get_valid_close_codes()
            close_code = valid_close_codes[0] if valid_close_codes else "Solved (Permanently)"

            url = f"{self.instance_url.rstrip('/')}/api/now/table/incident/{ticket_id}"
            payload = {
                "state": state_code,
                "work_notes": comment,
                "close_notes": comment,
                "close_code": close_code,  # Try standard close_code
            }

            # First attempt with close_code
            response = requests.patch(url, headers=self.headers, json=payload)
            if self._refresh_token_if_needed(response):
                response = requests.patch(url, headers=self.headers, json=payload)

            if response.status_code == 403 and "Resolution code" in response.text:
                logger.info(f"Retrying update for sys_id={ticket_id} with resolution_code")
                # Second attempt with resolution_code
                payload["resolution_code"] = close_code
                del payload["close_code"]  # Remove close_code to avoid conflict
                response = requests.patch(url, headers=self.headers, json=payload)
                if self._refresh_token_if_needed(response):
                    response = requests.patch(url, headers=self.headers, json=payload)

            if response.status_code == 403:
                error_detail = response.json().get("error", {}).get("detail", "No error details provided")
                logger.error(f"403 Forbidden updating ServiceNow incident sys_id={ticket_id}: {response.text}")
                raise ValueError(f"403 Forbidden: {error_detail}")

            response.raise_for_status()
            incident = response.json().get("result", {})
            logger.info(f"Updated ServiceNow incident sys_id={ticket_id} with state={state}, comment={comment}, close_code={close_code}")
            return {
                "id": incident["sys_id"],
                "state": state,
                "comment": comment
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error updating ServiceNow incident sys_id={ticket_id}: {str(e)} - Response: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error updating ServiceNow incident sys_id={ticket_id}: {str(e)}")
            raise