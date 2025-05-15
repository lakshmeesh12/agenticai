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
from aws import AWSPlugin

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
        self.github_token = os.getenv("GITHUB_TOKEN")  # Load GITHUB_TOKEN
        if not self.github_token:
            logger.error("GITHUB_TOKEN not found in .env file")
        self.kernel.add_plugin(AWSPlugin(), plugin_name="aws")
        logger.info("Initialized SKAgent with AzureOpenAI client and AWS plugin")

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

            prompt = (
                "You are an IT support assistant analyzing an email to determine the user's intent based on its context and purpose, without relying solely on specific keywords. "
                "Classify the intent as one of: 'github_access_request', 'github_revoke_access', 'github_create_repo', 'github_commit_file', 'github_delete_repo', "
                "'aws_s3_create_bucket', 'aws_s3_delete_bucket', 'aws_ec2_launch_instance', 'aws_ec2_terminate_instance', 'aws_iam_add_user', 'aws_iam_remove_user', "
                "'aws_iam_add_user_permission', 'aws_iam_remove_user_permission', 'git_and_aws_intent', 'general_it_request', 'request_summary', or 'non_intent'. "
                "Understand the email's overall intent by evaluating whether it requests a specific, immediate IT action or is non-actionable (e.g., appreciation, acknowledgment). "
                "Extract relevant details for actionable intents. For 'general_it_request', include attachment details if present. "
                "Extract the username or requester name from the sender address (before the @ symbol) if available. "
                "For follow-up emails (e.g., subject starts with 'Re:'), prioritize intents related to previous requests in the thread. "
                "For emails with multiple GitHub and AWS actions, classify as 'git_and_aws_intent' with sub-intents. "
                "Include attachment file content in details for 'github_commit_file' sub-intent. "
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
                "  - Applies to emails requesting to launch an EC2 instance (e.g., 'Launch an EC2 instance with t3.micro in us-east-2, clone testing repo, run list_files.sh').\n"
                "  - Extract: instance_type (default 't2.micro' if unspecified), ami_id (default 'unspecified'), region (default 'us-east-1'), repo_name (if cloning), script_name (if running a script), source_bucket, destination_bucket (if applicable).\n"
                "  - Action: {'action': 'launch_instance', 'instance_type', 'ami_id', 'region', 'repo_name', 'script_name', 'source_bucket', 'destination_bucket'}.\n"
                "  - Pending actions: true (assumes potential future termination).\n"
                "  - Ticket description: e.g., 'Launch EC2 instance t3.micro in us-east-2, clone testing repo, run list_files.sh'.\n"
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
                "  - Applies to emails requesting multiple actions involving GitHub and AWS (e.g., 'Create a GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, launch EC2 instance').\n"
                "  - Extract: sub_intents (list of intents like 'github_create_repo', 'github_commit_file', 'aws_s3_create_bucket', 'aws_ec2_launch_instance'), with details for each.\n"
                "  - Actions: List of actions for each sub-intent.\n"
                "  - Pending actions: true if any sub-intent has pending actions (e.g., creation intents); false otherwise.\n"
                "  - Ticket description: e.g., 'Create GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, launch EC2 instance'.\n"
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
                "'bucket_name', 'region', 'acl', 'instance_type', 'ami_id', 'instance_id', 'username', 'permission', 'file_name', 'source_bucket', 'destination_bucket', 'script_name', 'file_content'}.\n"
                f"Email:\n{content}\n\n"
                "Examples:\n"
                "1. Subject: Request access to poc repo\nBody: Please grant read access to poc for testuser9731. I will let you know when to revoke.\n"
                "   ```json\n{\"intent\": \"github_access_request\", \"ticket_description\": \"Grant read access to poc for testuser9731\", \"actions\": [{\"action\": \"grant_access\", \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\"}], \"pending_actions\": true, \"sub_intents\": [], \"repo_name\": \"poc\", \"access_type\": \"pull\", \"github_username\": \"testuser9731\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "2. Subject: Create S3 bucket\nBody: Please create an S3 bucket named mybucket in us-west-2 with private access.\n"
                "   ```json\n{\"intent\": \"aws_s3_create_bucket\", \"ticket_description\": \"Create S3 bucket mybucket in us-west-2 with private access\", \"actions\": [{\"action\": \"create_bucket\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"private\"}], \"pending_actions\": true, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"private\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "3. Subject: Re: Create S3 bucket\nBody: Please delete the S3 bucket mybucket.\n"
                "   ```json\n{\"intent\": \"aws_s3_delete_bucket\", \"ticket_description\": \"Delete S3 bucket mybucket in us-west-2\", \"actions\": [{\"action\": \"delete_bucket\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\"}], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"mybucket\", \"region\": \"us-west-2\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "4. Subject: Create GitHub repo and AWS resources\nBody: Please create a private GitHub repository named 'testing' under my account (lakshmeesh12). I’ve attached a shell script, `list_files.sh`, which should be committed to the repository. Next, create an S3 bucket named 'audit-9731' in the us-east-2 region with private access. Finally, launch an EC2 instance in us-east-2 with instance type t3.micro and AMI ID ami-0c55b159cbfafe1f0. The instance should clone the 'testing' repository, run `list_files.sh` to list files from the existing S3 bucket 'lakshmeesh9731', and save the output to the 'audit-9731' bucket.\nAttachments: list_files.sh\nAttachment Content (list_files.sh): #!/bin/bash\naws s3 ls s3://lakshmeesh9731 > output.txt\naws s3 cp output.txt s3://audit-9731/output.txt\n"
                "   ```json\n{\"intent\": \"git_and_aws_intent\", \"ticket_description\": \"Create GitHub repo testing, commit list_files.sh, create S3 bucket audit-9731, launch EC2 instance in us-east-2\", \"actions\": [{\"action\": \"create_repo\", \"repo_name\": \"testing\", \"github_username\": \"lakshmeesh12\"}, {\"action\": \"commit_file\", \"repo_name\": \"testing\", \"file_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\"}, {\"action\": \"create_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\"}, {\"action\": \"launch_instance\", \"instance_type\": \"t3.micro\", \"ami_id\": \"ami-0c55b159cbfafe1f0\", \"region\": \"us-east-2\", \"repo_name\": \"testing\", \"script_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\"}], \"pending_actions\": true, \"sub_intents\": [{\"intent\": \"github_create_repo\", \"repo_name\": \"testing\", \"github_username\": \"lakshmeesh12\"}, {\"intent\": \"github_commit_file\", \"repo_name\": \"testing\", \"file_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\"}, {\"intent\": \"aws_s3_create_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\"}, {\"intent\": \"aws_ec2_launch_instance\", \"instance_type\": \"t3.micro\", \"ami_id\": \"ami-0c55b159cbfafe1f0\", \"region\": \"us-east-2\", \"repo_name\": \"testing\", \"script_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\"}], \"repo_name\": \"testing\", \"access_type\": \"unspecified\", \"github_username\": \"lakshmeesh12\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"private\", \"instance_type\": \"t3.micro\", \"ami_id\": \"ami-0c55b159cbfafe1f0\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"list_files.sh\", \"source_bucket\": \"lakshmeesh9731\", \"destination_bucket\": \"audit-9731\", \"script_name\": \"list_files.sh\", \"file_content\": \"#!/bin/bash\\naws s3 ls s3://lakshmeesh9731 > output.txt\\naws s3 cp output.txt s3://audit-9731/output.txt\"}\n```\n"
                "5. Subject: Re: Create GitHub repo and AWS resources\nBody: Please clean up the resources: delete the 'testing' repository, delete the 'audit-9731' bucket, and terminate the EC2 instance.\n"
                "   ```json\n{\"intent\": \"git_and_aws_intent\", \"ticket_description\": \"Delete GitHub repo testing, delete S3 bucket audit-9731, terminate EC2 instance\", \"actions\": [{\"action\": \"delete_repo\", \"repo_name\": \"testing\"}, {\"action\": \"delete_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\"}, {\"action\": \"terminate_instance\", \"instance_id\": \"unspecified\", \"region\": \"us-east-2\"}], \"pending_actions\": false, \"sub_intents\": [{\"intent\": \"github_delete_repo\", \"repo_name\": \"testing\"}, {\"intent\": \"aws_s3_delete_bucket\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\"}, {\"intent\": \"aws_ec2_terminate_instance\", \"instance_id\": \"unspecified\", \"region\": \"us-east-2\"}], \"repo_name\": \"testing\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"audit-9731\", \"region\": \"us-east-2\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "6. Subject: Status of my request\nBody: Can you provide a summary of my S3 bucket request?\n"
                "   ```json\n{\"intent\": \"request_summary\", \"ticket_description\": \"User requested summary of previous request\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "7. Subject: Thanks for your help\nBody: Thanks for creating the bucket. Appreciate it!\n"
                "   ```json\n{\"intent\": \"non_intent\", \"ticket_description\": \"Non-actionable email (e.g., appreciation or generic message)\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "8. Subject: VPN issue\nBody: I’m having trouble connecting to the VPN. Can you help?\n"
                "   ```json\n{\"intent\": \"general_it_request\", \"ticket_description\": \"User reports VPN connection error\", \"actions\": [], \"pending_actions\": false, \"sub_intents\": [], \"repo_name\": \"unspecified\", \"access_type\": \"unspecified\", \"github_username\": \"unspecified\", \"bucket_name\": \"unspecified\", \"region\": \"us-east-1\", \"acl\": \"unspecified\", \"instance_type\": \"unspecified\", \"ami_id\": \"unspecified\", \"instance_id\": \"unspecified\", \"username\": \"unspecified\", \"permission\": \"unspecified\", \"file_name\": \"unspecified\", \"source_bucket\": \"unspecified\", \"destination_bucket\": \"unspecified\", \"script_name\": \"unspecified\", \"file_content\": \"\"}\n```\n"
                "Output format:\n"
                "```json\n{\"intent\": \"<intent>\", \"ticket_description\": \"<description>\", \"actions\": [<action_objects>], \"pending_actions\": <bool>, \"sub_intents\": [<sub_intent_objects>], \"repo_name\": \"<repo>\", \"access_type\": \"<pull|push|unspecified>\", \"github_username\": \"<username>\", \"bucket_name\": \"<bucket>\", \"region\": \"<region>\", \"acl\": \"<acl>\", \"instance_type\": \"<type>\", \"ami_id\": \"<ami>\", \"instance_id\": \"<id>\", \"username\": \"<user>\", \"permission\": \"<permission>\", \"file_name\": \"<file>\", \"source_bucket\": \"<source>\", \"destination_bucket\": \"<dest>\", \"script_name\": \"<script>\", \"file_content\": \"<content>\"}\n```"
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
                "file_content": ""
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

    async def perform_action(self, intent: str, details: dict) -> dict:
        """Perform the action corresponding to the intent."""
        try:
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
                    github_token=self.github_token  # Pass GITHUB_TOKEN
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
            else:
                return {"success": False, "message": f"Unsupported intent: {intent}", "status": "failed"}
        except Exception as e:
            logger.error(f"Error performing action for intent {intent}: {str(e)}")
            return {"success": False, "message": f"Failed to perform action: {str(e)}", "status": "failed"}
        
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
            pending_actions = intent_result["pending_actions"] or (existing_ticket.get("pending_actions", False) if is_follow_up else False)
            sub_intents = intent_result.get("sub_intents", [])

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
                "file_content": intent_result.get("file_content", "")
            }

            await broadcast({
                "type": "intent_analyzed",
                "email_id": email_id,
                "intent": intent,
                "pending_actions": pending_actions
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
                else:
                    # Store non-intent email without creating a ticket
                    self.tickets_collection.insert_one({
                        "ado_ticket_id": None,
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
                        "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]}
                    })
                return {
                    "status": "success",
                    "intent": "non_intent",
                    "ticket_id": existing_ticket["ado_ticket_id"] if is_follow_up else None,
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
            completed_actions = []
            action_result = None
            action_details = None

            # Define intents that complete pending actions (e.g., revocation, deletion, termination)
            completion_intents = [
                "github_revoke_access",
                "github_delete_repo",
                "aws_s3_delete_bucket",
                "aws_ec2_terminate_instance",
                "aws_iam_remove_user",
                "aws_iam_remove_user_permission"
            ]

            # Handle follow-up emails for actionable intents
            if is_follow_up and intent in [
                "github_access_request", "github_revoke_access", "github_create_repo", "github_commit_file", "github_delete_repo",
                "aws_s3_create_bucket", "aws_s3_delete_bucket", "aws_ec2_launch_instance", "aws_ec2_terminate_instance",
                "aws_iam_add_user", "aws_iam_remove_user", "aws_iam_add_user_permission", "aws_iam_remove_user_permission"
            ]:
                ticket_id = existing_ticket["ado_ticket_id"]
                action_details = {
                    "request_type": intent,
                    "status": "pending",
                    "message": f"Processing {intent}"
                }

                # Populate action-specific details
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

                # Update ticket with new action
                update_operation = {
                    "$push": {
                        "details.aws" if intent.startswith("aws_") else "details.github": action_details,
                        "updates": {
                            "status": "Doing",
                            "comment": action_details["message"],
                            "revision_id": f"{intent.split('_')[1]}-{ticket_id}-{len(existing_ticket.get('updates', [])) + 1}",
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

                # Perform action
                action_result = await self.perform_action(intent, details)
                action_details["status"] = action_result.get("status", "failed")
                action_details["message"] = action_result["message"]
                if intent == "aws_ec2_launch_instance" and action_result.get("logs"):
                    action_details["logs"] = action_result["logs"]
                completed_actions.append({"action": intent, "completed": action_result["success"]})

                # Update pending_actions for completion intents
                if intent in completion_intents and action_result["success"]:
                    pending_actions = False
                    logger.info(f"Completion intent {intent} processed successfully for ticket ID={ticket_id}. Setting pending_actions to False.")

                # Update ticket with action result
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
                            "revision_id": f"result-{ticket_id}-{len(existing_ticket.get('updates', [])) + 2}",
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
                        {"ado_ticket_id": ticket_id, f"details.{'aws' if intent.startswith('aws_') else 'github'}": {"$elemMatch": array_filter}},
                        update_operation,
                        array_filters=[{"elem.request_type": intent}]
                    )
                except Exception as e:
                    logger.error(f"Failed to update ticket {ticket_id} for intent {intent}: {str(e)}")
                    raise ValueError(f"Ticket update failed: {str(e)}")

                await broadcast({
                    "type": "action_performed",
                    "email_id": email_id,
                    "ticket_id": ticket_id,
                    "success": action_result["success"],
                    "message": action_details["message"]
                })

                # Check if all actions are completed and update ADO ticket status
                updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
                all_completed = await self.are_all_actions_completed(updated_ticket)
                ado_status = "Done" if all_completed else "Doing"
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["ado"]["update_ticket"],
                        ticket_id=ticket_id,
                        status=ado_status,
                        comment=action_result["message"]
                    )
                except Exception as e:
                    logger.error(f"Failed to update ADO ticket {ticket_id}: {str(e)}")
                    raise ValueError(f"ADO ticket update failed: {str(e)}")

            # Handle git_and_aws_intent for follow-up
            elif is_follow_up and intent == "git_and_aws_intent":
                ticket_id = existing_ticket["ado_ticket_id"]
                for sub_intent in sub_intents:
                    sub_intent_name = sub_intent["intent"]
                    sub_action_details = {
                        "request_type": sub_intent_name,
                        "status": "pending",
                        "message": f"Processing {sub_intent_name}"
                    }
                    # Populate sub-intent details
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

                    # Update ticket
                    update_operation = {
                        "$push": {
                            "details.aws" if sub_intent_name.startswith("aws_") else "details.github": sub_action_details,
                            "updates": {
                                "status": "Doing",
                                "comment": sub_action_details["message"],
                                "revision_id": f"{sub_intent_name.split('_')[1]}-{ticket_id}-{len(existing_ticket.get('updates', [])) + 1}",
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
                        self.tickets_collection.update_one({"ado_ticket_id": ticket_id}, update_operation)
                    except Exception as e:
                        logger.error(f"Failed to update ticket {ticket_id} for sub-intent {sub_intent_name}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                    # Perform sub-intent action
                    sub_action_result = await self.perform_action(sub_intent_name, details)
                    sub_action_details["status"] = sub_action_result.get("status", "failed")
                    sub_action_details["message"] = sub_action_result["message"]
                    if sub_intent_name == "aws_ec2_launch_instance" and sub_action_result.get("logs"):
                        sub_action_details["logs"] = sub_action_result["logs"]
                    completed_actions.append({"action": sub_intent_name, "completed": sub_action_result["success"]})

                    # Update pending_actions for completion intents
                    if sub_intent_name in completion_intents and sub_action_result["success"]:
                        pending_actions = False
                        logger.info(f"Completion sub-intent {sub_intent_name} processed successfully for ticket ID={ticket_id}. Setting pending_actions to False.")

                    # Update ticket with sub-intent result
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
                            {"ado_ticket_id": ticket_id, f"details.{'aws' if sub_intent_name.startswith('aws_') else 'github'}": {"$elemMatch": {"request_type": sub_intent_name}}},
                            update_operation,
                            array_filters=[{"elem.request_type": sub_intent_name}]
                        )
                    except Exception as e:
                        logger.error(f"Failed to update ticket {ticket_id} for sub-intent result {sub_intent_name}: {str(e)}")
                        raise ValueError(f"Ticket update failed: {str(e)}")

                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id,
                        "ticket_id": ticket_id,
                        "success": sub_action_result["success"],
                        "message": sub_action_details["message"]
                    })

                # Check if all actions are completed and update ADO ticket status
                updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
                all_completed = await self.are_all_actions_completed(updated_ticket)
                ado_status = "Done" if all_completed else "Doing"
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["ado"]["update_ticket"],
                        ticket_id=ticket_id,
                        status=ado_status,
                        comment="Processed combined GitHub and AWS actions"
                    )
                except Exception as e:
                    logger.error(f"Failed to update ADO ticket {ticket_id}: {str(e)}")
                    raise ValueError(f"ADO ticket update failed: {str(e)}")

            # Handle new email
            else:
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

                # Perform action for single intent
                if intent != "git_and_aws_intent" and intent != "general_it_request":
                    action_result = await self.perform_action(intent, details)
                    action_details = {
                        "request_type": intent,
                        "status": action_result.get("status", "failed"),
                        "message": action_result["message"]
                    }
                    # Populate action-specific details
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

                    try:
                        await self.kernel.invoke(
                            self.kernel.plugins["ado"]["update_ticket"],
                            ticket_id=ticket_id,
                            status="Doing" if pending_actions else "Done",
                            comment=action_result["message"]
                        )
                    except Exception as e:
                        logger.error(f"Failed to update ADO ticket {ticket_id}: {str(e)}")
                        raise ValueError(f"ADO ticket update failed: {str(e)}")

                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id,
                        "ticket_id": ticket_id,
                        "success": action_result["success"],
                        "message": action_result["message"]
                    })

                # Handle git_and_aws_intent for new email
                elif intent == "git_and_aws_intent":
                    for sub_intent in sub_intents:
                        sub_intent_name = sub_intent["intent"]
                        sub_action_result = await self.perform_action(sub_intent_name, details)
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

                        # Store sub-intent details
                        try:
                            self.tickets_collection.update_one(
                                {"ado_ticket_id": ticket_id},
                                {
                                    "$push": {
                                        f"details.{'aws' if sub_intent_name.startswith('aws_') else 'github'}": sub_action_details,
                                        "updates": {
                                            "status": "Doing",
                                            "comment": sub_action_result["message"],
                                            "revision_id": f"{sub_intent_name.split('_')[1]}-{ticket_id}-{len(completed_actions)}",
                                            "email_sent": False,
                                            "email_message_id": None,
                                            "email_timestamp": datetime.now().isoformat()
                                        }
                                    }
                                }
                            )
                        except Exception as e:
                            logger.error(f"Failed to update ticket {ticket_id} for sub-intent {sub_intent_name}: {str(e)}")
                            raise ValueError(f"Ticket update failed: {str(e)}")

                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id,
                            "ticket_id": ticket_id,
                            "success": sub_action_result["success"],
                            "message": sub_action_result["message"]
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
                    "type_of_request": intent,
                    "details": {"attachments": [{"filename": a["filename"], "mimeType": a["mimeType"]} for a in attachments]}
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
                elif intent == "general_it_request":
                    sender_username = sender.split('@')[0] if '@' in sender else sender
                    detailed_description = ticket_description
                    if sender_username.lower() not in detailed_description.lower():
                        detailed_description = f"User {sender_username}: {detailed_description}"
                    ticket_record["details"]["general"] = [{
                        "request_type": "general_it_request",
                        "status": "pending",
                        "message": detailed_description,
                        "requester": sender_username
                    }]
                    ticket_record["ticket_description"] = detailed_description

                try:
                    self.tickets_collection.insert_one(ticket_record)
                except Exception as e:
                    logger.error(f"Failed to insert ticket record for ticket {ticket_id}: {str(e)}")
                    raise ValueError(f"Ticket insertion failed: {str(e)}")

                # Update ADO ticket status only for non-general_it_request intents
                if intent != "general_it_request":
                    updated_ticket = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
                    all_completed = await self.are_all_actions_completed(updated_ticket)
                    ado_status = "Done" if all_completed else "Doing"

                    try:
                        await self.kernel.invoke(
                            self.kernel.plugins["ado"]["update_ticket"],
                            ticket_id=ticket_id,
                            status=ado_status,
                            comment=action_result["message"] if action_result else "Processed request"
                        )
                    except Exception as e:
                        logger.error(f"Failed to update ADO ticket {ticket_id}: {str(e)}")
                        raise ValueError(f"ADO ticket update failed: {str(e)}")

                # Send email reply
                updates_result = await self.kernel.invoke(
                    self.kernel.plugins["ado"]["get_ticket_updates"],
                    ticket_id=ticket_id
                )
                updates = updates_result.value if updates_result else []
                update_result = await self.analyze_ticket_update(ticket_id, updates, attachments)
                email_response = update_result["email_response"]
                remediation = update_result["remediation"]

                # Include EC2 logs in email response if available
                if intent == "git_and_aws_intent" or intent == "aws_ec2_launch_instance":
                    ticket_record = self.tickets_collection.find_one({"ado_ticket_id": ticket_id})
                    ec2_actions = [
                        action for action in ticket_record.get("details", {}).get("aws", [])
                        if action["request_type"] == "aws_ec2_launch_instance" and action.get("logs")
                    ]
                    if ec2_actions:
                        logs = ec2_actions[-1]["logs"]
                        email_response += f"\n\nEC2 Execution Logs:\n{logs}"

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
                    email_chain_entry = {
                        "email_id": reply.get("message_id", str(uuid.uuid4())),
                        "from": os.getenv('EMAIL_ADDRESS', 'IT Support <support@quadranttechnologies.com>'),
                        "subject": subject,
                        "body": email_response,
                        "timestamp": datetime.now().isoformat(),
                        "attachments": []
                    }
                    try:
                        self.tickets_collection.update_one(
                            {"thread_id": thread_id},
                            {"$push": {"email_chain": email_chain_entry}}
                        )
                    except Exception as e:
                        logger.error(f"Failed to update email chain for ticket {ticket_id}: {str(e)}")
                        raise ValueError(f"Email chain update failed: {str(e)}")

                    await broadcast({
                        "type": "email_reply",
                        "email_id": email_id,
                        "thread_id": thread_id
                    })

                return {
                    "status": "success",
                    "ticket_id": ticket_id,
                    "intent": intent,
                    "actions": completed_actions,
                    "pending_actions": pending_actions
                }

        except Exception as e:
            logger.error(f"Error processing email ID={email_id}: {str(e)}")
            await broadcast({
                "type": "error",
                "email_id": email_id,
                "message": str(e)
            })
            return {
                "status": "error",
                "intent": intent or "unknown",
                "ticket_id": ticket_id,
                "message": f"Failed to process email: {str(e)}",
                "actions": completed_actions,
                "pending_actions": pending_actions
            }