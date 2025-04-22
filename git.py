import os
import logging
import requests
from dotenv import load_dotenv
from semantic_kernel.functions import kernel_function

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class GitPlugin:
    def __init__(self):
        self.client = GitClient()

    @kernel_function(
        description="Grant read (pull) or write (push) access to a GitHub repository.",
        name="grant_repo_access"
    )
    async def grant_repo_access(self, repo_name: str, github_username: str, access_type: str) -> dict:
        """
        Grant access to a GitHub repository.
        Args:
            repo_name (str): Repository name.
            github_username (str): GitHub username.
            access_type (str): Access type (pull or push).
        Returns:
            dict: {success: bool, message: str}.
        """
        success, message = self.client.grant_repo_access(repo_name, github_username, access_type)
        return {"success": success, "message": message}

    @kernel_function(
        description="Revoke access for a user from a GitHub repository.",
        name="revoke_repo_access"
    )
    async def revoke_repo_access(self, repo_name: str, github_username: str) -> dict:
        """
        Revoke access to a GitHub repository.
        Args:
            repo_name (str): Repository name.
            github_username (str): GitHub username.
        Returns:
            dict: {success: bool, message: str}.
        """
        success, message = self.client.revoke_repo_access(repo_name, github_username)
        return {"success": success, "message": message}

class GitClient:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_org = os.getenv("GITHUB_ORG", "LakshmeeshOrg")
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.supported_apps = ["github"]
        logger.info("Initialized GitClient for GitHub integration")

    def is_supported_app(self, app_name):
        """Check if the third-party app is supported."""
        return app_name.lower() in self.supported_apps

    def grant_repo_access(self, repo_name, github_username, access_type):
        """Grant read (pull) or write (push) access to a GitHub repository."""
        try:
            if access_type not in ["pull", "push"]:
                logger.error(f"Invalid access type: {access_type}. Must be 'pull' or 'push'.")
                return False, f"Invalid access type: {access_type}"

            repo_url = f"{self.base_url}/repos/{self.github_org}/{repo_name}"
            repo_response = requests.get(repo_url, headers=self.headers)
            if repo_response.status_code != 200:
                logger.error(f"Repository {repo_name} not found or inaccessible: {repo_response.text}")
                return False, f"Repository {repo_name} not found"

            collab_url = f"{self.base_url}/repos/{self.github_org}/{repo_name}/collaborators/{github_username}"
            payload = {"permission": access_type}
            response = requests.put(collab_url, headers=self.headers, json=payload)

            if response.status_code == 201 or response.status_code == 204:
                logger.info(f"Granted {access_type} access to {github_username} for repo {repo_name}")
                return True, f"{access_type.capitalize()} access granted to {github_username} for {repo_name}"
            else:
                logger.error(f"Failed to grant access: {response.text}")
                return False, f"Failed to grant access: {response.text}"
        except Exception as e:
            logger.error(f"Error granting repo access: {str(e)}")
            return False, f"Error granting access: {str(e)}"

    def revoke_repo_access(self, repo_name, github_username):
        """Revoke access for a user from a GitHub repository."""
        try:
            repo_url = f"{self.base_url}/repos/{self.github_org}/{repo_name}"
            repo_response = requests.get(repo_url, headers=self.headers)
            if repo_response.status_code != 200:
                logger.error(f"Repository {repo_name} not found or inaccessible: {repo_response.text}")
                return False, f"Repository {repo_name} not found"

            collab_url = f"{self.base_url}/repos/{self.github_org}/{repo_name}/collaborators/{github_username}"
            response = requests.delete(collab_url, headers=self.headers)

            if response.status_code == 204:
                logger.info(f"Revoked access for {github_username} from repo {repo_name}")
                return True, f"Access revoked for {github_username} from {repo_name}"
            else:
                logger.error(f"Failed to revoke access: {response.text}")
                return False, f"Failed to revoke access: {response.text}"
        except Exception as e:
            logger.error(f"Error revoking repo access: {str(e)}")
            return False, f"Error revoking access: {str(e)}"