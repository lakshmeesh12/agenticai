from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from dotenv import load_dotenv
import os
import logging
import base64
import email.mime.text
import email.utils
from semantic_kernel.functions import kernel_function

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class EmailSenderPlugin:
    def __init__(self):
        self.sender = EmailSender()

    @kernel_function(
        description="Send a threaded reply email via Gmail.",
        name="send_reply"
    )
    async def send_reply(self, to: str, subject: str, body: str, thread_id: str, message_id: str) -> dict:
        """
        Send a reply email in an existing thread.
        Args:
            to (str): Recipient email address.
            subject (str): Email subject.
            body (str): Email body.
            thread_id (str): Gmail thread ID.
            message_id (str): Gmail message ID.
        Returns:
            dict: Sent message details or None if failed.
        """
        return self.sender.send_reply(to, subject, body, thread_id, message_id)

class EmailSender:
    def __init__(self):
        self.email_address = os.getenv("EMAIL_ADDRESS")
        self.service = None
        self._initialize_service()

    def _initialize_service(self):
        """Initialize Gmail API service."""
        try:
            SCOPES = ['https://www.googleapis.com/auth/gmail.send']
            creds = None
            token_path = 'token_send.json'

            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        'credentials.json', SCOPES)
                    creds = flow.run_local_server(port=0)
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())

            self.service = build('gmail', 'v1', credentials=creds)
            logger.info(f"Initialized Gmail send service for {self.email_address}")
        except Exception as e:
            logger.error(f"Failed to initialize Gmail send service: {str(e)}")
            raise

    def send_reply(self, to, subject, body, thread_id, message_id):
        """Send a reply email."""
        try:
            logger.info(f"Preparing reply: To={to}, Subject={subject}, ThreadID={thread_id}, MessageID={message_id}")
            logger.debug(f"Email body: {body}")

            message = email.mime.text.MIMEText(body)
            message['To'] = to
            message['Subject'] = f"Re: {subject}"
            message['From'] = self.email_address
            message['In-Reply-To'] = message_id
            message['References'] = message_id
            message['Message-ID'] = email.utils.make_msgid()
            message['Date'] = email.utils.formatdate(localtime=True)

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            message_body = {
                'raw': raw_message,
                'threadId': thread_id
            }

            sent_message = self.service.users().messages().send(
                userId='me',
                body=message_body
            ).execute()

            logger.info(f"Sent reply to {to} for thread {thread_id}: {sent_message['id']}")
            return sent_message
        except Exception as e:
            logger.error(f"Error sending reply to {to}: {str(e)}")
            return None