import boto3
import logging
import base64
import os
from semantic_kernel.functions import kernel_function
from datetime import time
import time
import re 
import json
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

class AWSPlugin:
    def __init__(self):
        self.session = boto3.Session()

    @kernel_function(
        description="Create an S3 bucket",
        name="create_bucket"
    )
    async def create_bucket(self, bucket_name: str, region: str = "us-east-1", acl: str = "private") -> dict:
        try:
            s3_client = self.session.client('s3', region_name=region)
            create_params = {"Bucket": bucket_name, "ACL": acl}
            if region != "us-east-1":
                create_params["CreateBucketConfiguration"] = {"LocationConstraint": region}
            s3_client.create_bucket(**create_params)
            logger.info(f"Created S3 bucket {bucket_name} in {region} with ACL {acl}")
            return {"success": True, "message": f"S3 bucket {bucket_name} created successfully"}
        except Exception as e:
            logger.error(f"Error creating S3 bucket {bucket_name}: {str(e)}")
            return {"success": False, "message": f"Failed to create S3 bucket: {str(e)}"}

    @kernel_function(
        description="Delete an S3 bucket",
        name="delete_bucket"
    )
    async def delete_bucket(self, bucket_name: str, region: str = "us-east-1") -> dict:
        try:
            s3_client = self.session.client('s3', region_name=region)
            response = s3_client.list_objects_v2(Bucket=bucket_name)
            if 'Contents' in response:
                s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': [{'Key': obj['Key']} for obj in response['Contents']]})
            s3_client.delete_bucket(Bucket=bucket_name)
            logger.info(f"Deleted S3 bucket {bucket_name} in {region}")
            return {"success": True, "message": f"S3 bucket {bucket_name} deleted successfully"}
        except Exception as e:
            logger.error(f"Error deleting S3 bucket {bucket_name}: {str(e)}")
            return {"success": False, "message": f"Failed to delete S3 bucket: {str(e)}"}


    @kernel_function(
        description="Launch an EC2 instance with user data to clone a repository, run a script, and send logs to CloudWatch and S3",
        name="launch_instance"
    )
    async def launch_instance(self, instance_type: str, ami_id: str = "ami-060988b0dff2faa7c", region: str = "us-east-2", repo_name: str = None, script_name: str = None, github_token: str = None, source_bucket: str = None, destination_bucket: str = None, enable_cloudwatch_logs: bool = True) -> dict:
        try:
            ec2_client = self.session.client('ec2', region_name=region)
            user_data = None
            logs = "No logs captured"
            if repo_name and script_name:
                github_token = github_token or os.getenv("GITHUB_TOKEN")
                if not github_token:
                    raise ValueError("GITHUB_TOKEN must be provided in arguments or .env")
                github_username = os.getenv("GITHUB_USERNAME", "lakshmeesh12")
                repo_url = f"https://{github_token}@github.com/{github_username}/{repo_name}.git"
                cloudwatch_config = """{
        "agent": {
            "metrics_collection_interval": 60,
            "logfile": "/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log"
        },
        "logs": {
            "logs_collected": {
                "files": {
                    "collect_list": [
                        {
                            "file_path": "/var/log/user-data.log",
                            "log_group_name": "EC2logs",
                            "log_stream_name": "{instance_id}",
                            "timezone": "UTC"
                        }
                    ]
                }
            }
        }
    }
    """
                user_data_script = f"""#!/bin/bash
set -e
LOG_FILE=/var/log/user-data.log
exec > >(tee -a $LOG_FILE) 2>&1
echo "Starting user data script at $(date)"
echo "Debug: Verifying network connectivity"
ping -c 4 google.com
if [ $? -ne 0 ]; then
    echo "Warning: No internet connectivity"
fi
echo "Debug: Checking yum lock"
for i in {{1..5}}; do
    if [ -f /var/run/yum.pid ]; then
        echo "Yum lock detected, waiting..."
        sleep 5
    else
        break
    fi
done
if [ -f /var/run/yum.pid ]; then
    echo "Yum lock persists, killing process"
    sudo kill -9 $(cat /var/run/yum.pid)
    sudo rm -f /var/run/yum.pid
fi
echo "Debug: Checking yum repo availability"
yum repolist
echo "Debug: Verifying IAM role"
curl http://169.254.169.254/latest/meta-data/iam/info
sudo yum update -y
sudo yum install -y git aws-cli
if [ $? -ne 0 ]; then
    echo "Failed to install git or aws-cli"
    exit 1
fi
"""
                if enable_cloudwatch_logs:
                    user_data_script += f"""
echo "Installing CloudWatch agent via yum"
sudo yum install -y amazon-cloudwatch-agent
if [ $? -ne 0 ]; then
    echo "yum install amazon-cloudwatch-agent failed, attempting RPM download"
    wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm -O /tmp/amazon-cloudwatch-agent.rpm
    if [ $? -ne 0 ]; then
        echo "Warning: Failed to download CloudWatch agent RPM"
    else
        sudo rpm -U /tmp/amazon-cloudwatch-agent.rpm
        if [ $? -ne 0 ]; then
            echo "Warning: Failed to install CloudWatch agent via RPM"
        fi
    fi
else
    echo "Verifying CloudWatch agent installation"
    if [ -f /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
        echo "CloudWatch agent binary found"
        echo "Configuring CloudWatch agent"
        sudo mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
        cat <<EOF > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
{cloudwatch_config}
EOF
        sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s
        if [ $? -ne 0 ]; then
            echo "Warning: Failed to start CloudWatch agent"
            cat /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log >> $LOG_FILE
        else
            echo "CloudWatch agent started successfully"
            sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -m ec2 -a status >> $LOG_FILE
        fi
    else
        echo "Warning: CloudWatch agent binary not found"
    fi
fi
"""
                user_data_script += f"""
echo "Cloning repository {repo_url}"
git clone {repo_url} /home/ec2-user/repo
if [ $? -ne 0 ]; then
    echo "Failed to clone repository"
    exit 1
fi
cd /home/ec2-user/repo
echo "Setting executable permissions for {script_name}"
chmod +x {script_name}
if [ $? -ne 0 ]; then
    echo "Failed to set permissions for {script_name}"
    exit 1
fi
echo "Executing {script_name}"
./{script_name}
if [ $? -ne 0 ]; then
    echo "Failed to execute {script_name}"
    exit 1
fi
echo "User data script completed successfully at $(date)"
aws s3 cp $LOG_FILE s3://{destination_bucket}/user-data.log
if [ $? -ne 0 ]; then
    echo "Failed to upload user-data.log to s3://{destination_bucket}"
    exit 1
fi
"""
                user_data = base64.b64encode(user_data_script.encode()).decode()

            run_instances_params = {
                "ImageId": ami_id,
                "InstanceType": instance_type,
                "MinCount": 1,
                "MaxCount": 1,
                "UserData": user_data,
                "NetworkInterfaces": [{
                    "AssociatePublicIpAddress": True,
                    "DeviceIndex": 0,
                    "SubnetId": "subnet-0a11ce8f41536f694",
                    "Groups": ["sg-0ee1c5b9f81013732"]
                }]
            }

            key_pair = os.getenv("EC2_KEY_PAIR", "my-key-pair")
            try:
                ec2_client.describe_key_pairs(KeyNames=[key_pair])
                run_instances_params["KeyName"] = key_pair
            except ec2_client.exceptions.ClientError as e:
                logger.warning(f"Key pair '{key_pair}' does not exist in region {region}: {str(e)}")

            if source_bucket or destination_bucket or enable_cloudwatch_logs:
                iam_role_arn = os.getenv("EC2_IAM_ROLE_ARN", "arn:aws:iam::296062547225:instance-profile/EC2CloudWatchLoggingRole")
                logger.info(f"Using IAM role ARN: {iam_role_arn}")
                run_instances_params["IamInstanceProfile"] = {
                    "Arn": iam_role_arn
                }

            response = ec2_client.run_instances(**run_instances_params)
            instance_id = response['Instances'][0]['InstanceId']
            logger.info(f"Launched EC2 instance {instance_id} with type {instance_type} in {region}")
            return {
                "success": True,
                "message": f"EC2 instance {instance_id} launched successfully",
                "instance_id": instance_id,
                "logs": logs
            }
        except Exception as e:
            logger.error(f"Error launching EC2 instance: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to launch EC2 instance: {str(e)}",
                "instance_id": None,
                "logs": logs
            }

    async def format_timestamp(self, timestamp_ms):
        """Convert a millisecond timestamp to a human-readable format."""
        timestamp_sec = timestamp_ms / 1000.0
        dt = datetime.fromtimestamp(timestamp_sec)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    async def get_instance_profile_and_role(self, ec2_client, iam_client, instance_id):
        """Get the IAM instance profile and role name for the EC2 instance."""
        try:
            logger.debug(f"Fetching instance profile for {instance_id}")
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            if not response['Reservations'] or not response['Reservations'][0]['Instances']:
                logger.error(f"Could not find EC2 instance {instance_id}")
                return None, None
            
            instance = response['Reservations'][0]['Instances'][0]
            if 'IamInstanceProfile' not in instance:
                logger.error(f"EC2 instance {instance_id} does not have an IAM instance profile attached")
                return None, None
            
            instance_profile_arn = instance['IamInstanceProfile']['Arn']
            
            response = iam_client.get_instance_profile(InstanceProfileName=instance_profile_arn.split('/')[-1])
            if not response['InstanceProfile']['Roles']:
                logger.error(f"Instance profile does not have any roles attached")
                return instance_profile_arn, None
            
            role_name = response['InstanceProfile']['Roles'][0]['RoleName']
            logger.debug(f"Found role {role_name} for instance {instance_id}")
            return instance_profile_arn, role_name
        
        except Exception as e:
            logger.error(f"Error getting instance profile for {instance_id}: {str(e)}")
            return None, None

    async def create_policy_for_service_action(self, iam_client, role_name, service, action, resource_arn):
        """Create and attach a policy to grant the required permission."""
        try:
            if not role_name:
                logger.error("Cannot add permissions: No role name provided")
                return False
            
            policy_document = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": f"{service}:{action}",
                        "Resource": resource_arn
                    }
                ]
            }
            
            policy_name = f"{service}-{action}-{int(time.time())}"
            logger.debug(f"Creating policy {policy_name}")
            
            response = iam_client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description=f"Auto-generated policy to allow {service}:{action} on {resource_arn}"
            )
            
            policy_arn = response['Policy']['Arn']
            
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
            
            logger.info(f"✅ Successfully created and attached policy '{policy_name}' to role '{role_name}'")
            logger.info(f"✅ Added permission: {service}:{action} on {resource_arn}")
            logger.warning("⚠️ Note: It may take a few minutes for the IAM permission changes to propagate")
            return True
        
        except Exception as e:
            logger.error(f"Error creating or attaching policy: {str(e)}")
            return False

    async def check_for_access_denied(self, message, instance_id, ec2_client, iam_client, fix_event):
        """Check if the log message contains AccessDenied errors and fix them."""
        if "AccessDenied" in message:
            service_match = re.search(r"perform: ([^:]+):([^\s]+)|calling the ([^\s]+) operation", message)
            resource_match = re.search(r"resource: \"([^\"]+)\"", message)
            
            if service_match and resource_match:
                service = service_match.group(1) or (service_match.group(3).split('V2')[0] if service_match.group(3) else None)
                action = service_match.group(2) or (service_match.group(3) if service_match.group(3) else None)
                resource = resource_match.group(1)
                
                logger.warning(f"🔴 DETECTED PERMISSION ERROR:\n   - Service: {service}\n   - Action: {action}\n   - Resource: {resource}")
                
                role_arn_match = re.search(r"User: (arn:aws:[^:]+:[^:]+:[^:]+:assumed-role/([^/]+)/)", message)
                external_role_name = role_arn_match.group(2) if role_arn_match else None
                
                logger.info(f"🔧 Attempting to fix permission issue automatically...")
                instance_profile_arn, role_name = await self.get_instance_profile_and_role(ec2_client, iam_client, instance_id)
                
                if not role_name and external_role_name:
                    role_name = external_role_name
                
                if role_name:
                    logger.info(f"🔍 Found role: {role_name}")
                    success = await self.create_policy_for_service_action(iam_client, role_name, service, action, resource)
                    if success:
                        fix_event.set()
                        await asyncio.sleep(60)  # Wait for IAM propagation
                    else:
                        logger.error("Failed to auto-fix permissions.")
                else:
                    logger.error("Could not determine the IAM role to update.")
                return True
        return False

    async def get_new_logs(self, logs_client, log_group_name, instance_id, start_time, ec2_client, iam_client, fix_event):
        """Get new log events from CloudWatch Logs."""
        try:
            logger.debug(f"Fetching logs for {log_group_name}/{instance_id} from {start_time}")
            response = logs_client.filter_log_events(
                logGroupName=log_group_name,
                logStreamNamePrefix=instance_id,
                startTime=start_time,
                interleaved=True
            )
            logger.debug(f"Retrieved {len(response.get('events', []))} log events")
            
            events = response.get('events', [])
            latest_timestamp = start_time
            
            for event in events:
                timestamp = event['timestamp']
                message = event['message']
                
                human_time = await self.format_timestamp(timestamp)
                logger.info(f"[{human_time}] {message}")
                
                await self.check_for_access_denied(message, instance_id, ec2_client, iam_client, fix_event)
                
                latest_timestamp = max(latest_timestamp, timestamp + 1)
            
            return latest_timestamp
        
        except Exception as e:
            logger.error(f"Error fetching logs for {log_group_name}/{instance_id}: {str(e)}")
            return start_time

    async def monitor_logs(self, instance_id: str, log_group_name: str, interval: int, logs_client, ec2_client, iam_client, fix_event, is_running):
        """Monitor CloudWatch logs in the background."""
        try:
            logger.debug(f"Starting log monitoring for instance {instance_id}")
            start_time = int(time.time() * 1000) - 60000
            logger.info(f"Starting to monitor logs for instance {instance_id} in log group {log_group_name}...")
            logger.info("Auto-fix for permission issues is ENABLED.")
            
            while is_running():
                start_time = await self.get_new_logs(logs_client, log_group_name, instance_id, start_time, ec2_client, iam_client, fix_event)
                await asyncio.sleep(interval)
            
            logger.info(f"Monitoring stopped for instance {instance_id}")
        
        except Exception as e:
            logger.error(f"Error in log monitoring for {instance_id}: {str(e)}")

    async def run_ssm_command(self, ssm_client, instance_id, command_script, script_name, repo_name):
        """Run the SSM command and return the result."""
        for attempt in range(3):
            try:
                response = ssm_client.send_command(
                    InstanceIds=[instance_id],
                    DocumentName="AWS-RunShellScript",
                    Parameters={
                        "commands": [command_script],
                        "workingDirectory": ["/home/ec2-user"],
                        "executionTimeout": ["1800"]
                    },
                    TimeoutSeconds=1800,
                    Comment=f"Run {script_name} from {repo_name} on instance {instance_id}"
                )
                return response['Command']['CommandId']
            except ssm_client.exceptions.ClientError as e:
                if attempt < 2:
                    logger.warning(f"SSM command failed, retrying... Error: {str(e)}")
                    await asyncio.sleep(10)
                else:
                    raise e
        raise Exception("Failed to send SSM command after 3 attempts")

    async def wait_for_ssm_result(self, ssm_client, command_id, instance_id, script_name):
        """Wait for the SSM command result."""
        await asyncio.sleep(15)
        for _ in range(120):
            try:
                result = ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )
                if result['Status'] in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                    logs = result.get('StandardOutputContent', '') + result.get('StandardErrorContent', '')
                    if "AccessDenied" in logs or "is not authorized to perform" in logs or f"Script {script_name} failed with exit code" in logs:
                        logger.error(f"Script {script_name} failed with error: {logs}")
                        return {
                            "success": False,
                            "message": f"Script {script_name} failed on instance {instance_id}: AccessDenied or non-zero exit code",
                            "logs": logs,
                            "status": "pending"
                        }
                    if result['Status'] != 'Success':
                        logger.error(f"SSM command failed with status {result['Status']}: {logs}")
                        return {
                            "success": False,
                            "message": f"Script {script_name} failed on instance {instance_id}: {result['StatusDetails']}",
                            "logs": logs,
                            "status": "failed"
                        }
                    logger.info(f"Script {script_name} executed successfully on instance {instance_id}")
                    return {
                        "success": True,
                        "message": f"Script {script_name} executed successfully on instance {instance_id}",
                        "logs": logs,
                        "status": "completed"
                    }
            except ssm_client.exceptions.InvocationDoesNotExist:
                await asyncio.sleep(10)
                continue
        logs = "No logs captured"
        return {
            "success": False,
            "message": f"Timeout waiting for SSM command {command_id} on instance {instance_id}",
            "logs": logs,
            "status": "failed"
        }

    @kernel_function(
        description="Run a script on an existing EC2 instance using AWS SSM, store logs, and upload to S3",
        name="run_script"
    )
    async def run_script(self, instance_id: str, region: str = "us-east-2", repo_name: str = None, script_name: str = None, github_token: str = None, github_username: str = None, source_bucket: str = None, destination_bucket: str = None, enable_cloudwatch_logs: bool = True, enable_cloudwatch_monitoring: bool = False, log_group_name: str = "EC2logs", monitor_interval: int = 5, broadcast=None, email_id=None) -> dict:
        try:
            logger.debug(f"Starting run_script for instance {instance_id}")
            ec2_client = self.session.client('ec2', region_name=region)
            ssm_client = self.session.client('ssm', region_name=region)
            logs_client = self.session.client('logs', region_name=region) if enable_cloudwatch_logs else None
            iam_client = self.session.client('iam', region_name=region) if enable_cloudwatch_monitoring else None
            logs = "No logs captured"

            logger.info(f"Validating instance {instance_id}")
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            if not response['Reservations']:
                return {
                    "success": False,
                    "message": f"Instance {instance_id} does not exist in account or region {region}",
                    "instance_id": instance_id,
                    "logs": logs,
                    "status": "failed"
                }
            instance = response['Reservations'][0]['Instances'][0]
            state = instance['State']['Name']
            if state != 'running':
                return {
                    "success": False,
                    "message": f"Instance {instance_id} is in state {state}, expected 'running'",
                    "instance_id": instance_id,
                    "logs": logs,
                    "status": "failed"
                }
            
            expected_role_arn = os.getenv("EC2_IAM_ROLE_ARN", None)
            if not expected_role_arn:
                logger.warning("EC2_IAM_ROLE_ARN not set in environment, skipping IAM role validation")
            else:
                iam_profile = instance.get('IamInstanceProfile', {}).get('Arn', '')
                if expected_role_arn not in iam_profile:
                    logger.error(f"Instance {instance_id} is using IAM role {iam_profile}, expected {expected_role_arn}")
                    return {
                        "success": False,
                        "message": f"Instance {instance_id} is using incorrect IAM role {iam_profile}, expected {expected_role_arn}",
                        "instance_id": instance_id,
                        "logs": logs,
                        "status": "failed"
                    }

            logger.info(f"Checking SSM connectivity for instance {instance_id}")
            ssm_response = ssm_client.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            if not ssm_response['InstanceInformationList']:
                return {
                    "success": False,
                    "message": f"Instance {instance_id} is not managed by SSM or SSM agent is not running",
                    "instance_id": instance_id,
                    "logs": logs,
                    "status": "failed"
                }
            ssm_status = ssm_response['InstanceInformationList'][0]['PingStatus']
            if ssm_status != 'Online':
                return {
                    "success": False,
                    "message": f"Instance {instance_id} SSM status is {ssm_status}, expected 'Online'",
                    "instance_id": instance_id,
                    "logs": logs,
                    "status": "failed"
                }

            if not (repo_name and script_name):
                return {
                    "success": False,
                    "message": "repo_name and script_name are required",
                    "instance_id": instance_id,
                    "logs": logs,
                    "status": "failed"
                }

            github_token = github_token or os.getenv("GITHUB_TOKEN")
            if not github_token:
                raise ValueError("GITHUB_TOKEN must be provided in arguments or .env")
            
            username = github_username or os.getenv("GITHUB_USERNAME") or os.getenv("GITHUB_ORG")
            if not username:
                raise ValueError("GitHub username must be provided in arguments or as GITHUB_USERNAME or GITHUB_ORG in .env")
            logger.info(f"Using GitHub username: {username}")
            repo_url = f"https://{github_token}@github.com/{username}/{repo_name}.git"

            command_script = f"""#!/bin/bash
    set -e
    LOG_FILE=/var/log/user-data.log
    exec > >(tee -a $LOG_FILE) 2>&1
    echo "Starting script execution at $(date)"
    echo "Debug: Verifying network connectivity"
    ping -c 4 google.com
    if [ $? -ne 0 ]; then
        echo "Warning: No internet connectivity"
    fi
    echo "Debug: Checking SSM agent status"
    sudo systemctl status amazon-ssm-agent
    echo "Debug: Checking yum lock"
    for i in {{1..5}}; do
        if [ -f /var/run/yum.pid ]; then
            echo "Yum lock detected, waiting..."
            sleep 5
        else
            break
        fi
    done
    if [ -f /var/run/yum.pid ]; then
        echo "Yum lock persists, killing process"
        sudo kill -9 $(cat /var/run/yum.pid)
        sudo rm -f /var/run/yum.pid
    fi
    echo "Debug: Checking yum repo availability"
    yum repolist
    echo "Debug: Verifying IAM role"
    curl http://169.254.169.254/latest/meta-data/iam/info
    sudo yum install -y git aws-cli
    if [ $? -ne 0 ]; then
        echo "Failed to install git or aws-cli"
        exit 1
    fi
    echo "Assuming CloudWatch agent is already configured"
    echo "Cloning repository {repo_url}"
    rm -rf /home/ec2-user/repo
    git clone {repo_url} /home/ec2-user/repo
    if [ $? -ne 0 ]; then
        echo "Failed to clone repository"
        exit 1
    fi
    cd /home/ec2-user/repo
    echo "Setting executable permissions for {script_name}"
    chmod +x {script_name}
    if [ $? -ne 0 ]; then
        echo "Failed to set permissions for {script_name}"
        exit 1
    fi
    echo "Executing {script_name}"
    ./{script_name}
    SCRIPT_EXIT_CODE=$?
    if [ $SCRIPT_EXIT_CODE -ne 0 ]; then
        echo "Script {script_name} failed with exit code $SCRIPT_EXIT_CODE"
        exit 1
    fi
    echo "Script execution completed successfully at $(date)"
    aws s3 cp $LOG_FILE s3://{destination_bucket}/user-data.log
    if [ $? -ne 0 ]; then
        echo "Failed to upload user-data.log to s3://{destination_bucket}"
        exit 1
    fi
    """

            # Initialize monitoring variables
            monitor_task = None
            fix_event = asyncio.Event() if enable_cloudwatch_monitoring else None

            max_attempts = 3
            attempt = 1
            retry_delay = 20  # seconds

            while attempt <= max_attempts:
                # Run the SSM command
                command_id = await self.run_ssm_command(ssm_client, instance_id, command_script, script_name, repo_name)
                logger.info(f"Sent SSM command {command_id} to instance {instance_id}, attempt {attempt}")

                # Wait for the result and capture logs
                result = await self.wait_for_ssm_result(ssm_client, command_id, instance_id, script_name)
                logs = result.get("logs", "No logs captured")

                # Log the script execution result immediately to ensure logs appear first
                logger.info(f"Script execution attempt {attempt} for {script_name} on instance {instance_id}:\n{logs}")

                # **New**: Broadcast script failure with logs if the attempt failed
                if not result["success"] and broadcast and email_id:
                    logger.error(f"Script {script_name} failed with error: {logs}")
                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id,
                        "success": False,
                        "message": f"Script {script_name} failed with error: {logs}"
                    })

                # Start monitoring only after the first attempt's logs are captured
                if enable_cloudwatch_monitoring and attempt == 1 and not monitor_task:
                    logger.info(f"Starting CloudWatch monitoring for instance {instance_id} after first script execution attempt")
                    try:
                        monitor_result = await self.kernel.invoke(
                            self.kernel.plugins["monitor"]["start_monitoring"],
                            instance_id=instance_id,
                            log_group_name=log_group_name,
                            interval=monitor_interval,
                            region=region
                        )
                        if not monitor_result.value["success"]:
                            logger.warning(f"Failed to start monitoring: {monitor_result.value['message']}")
                        else:
                            monitor_task = True  # Flag to indicate monitoring has started
                    except Exception as e:
                        logger.error(f"Error starting monitoring: {str(e)}")
                        if broadcast and email_id:
                            await broadcast({
                                "type": "action_performed",
                                "email_id": email_id,
                                "success": False,
                                "message": f"Error starting monitoring: {str(e)}"
                            })

                if result["success"]:
                    if enable_cloudwatch_monitoring and monitor_task:
                        # Stop monitoring since the script was successful
                        try:
                            await self.kernel.invoke(
                                self.kernel.plugins["monitor"]["stop_monitoring"],
                                instance_id=instance_id
                            )
                        except Exception as e:
                            logger.error(f"Error stopping monitoring: {str(e)}")
                            if broadcast and email_id:
                                await broadcast({
                                    "type": "action_performed",
                                    "email_id": email_id,
                                    "success": False,
                                    "message": f"Error stopping monitoring: {str(e)}"
                                })
                    
                    return {
                        "success": True,
                        "message": f"Script {script_name} executed successfully on instance {instance_id}",
                        "instance_id": instance_id,
                        "logs": logs,
                        "status": "completed"
                    }
                
                if attempt < max_attempts:
                    logger.info(f"Script execution failed (attempt {attempt}/{max_attempts}), waiting {retry_delay} seconds before retry")
                    # Wait for the retry delay or until the fix_event is set
                    try:
                        if enable_cloudwatch_monitoring and monitor_task:
                            # Wait for permission fix or timeout
                            await asyncio.wait_for(fix_event.wait(), timeout=retry_delay)
                            logger.info("Permission fix detected, retrying script immediately")
                            fix_event.clear()
                        else:
                            # Just wait for the retry delay
                            await asyncio.sleep(retry_delay)
                    except asyncio.TimeoutError:
                        # Timeout expired, continue with retry
                        pass
                
                attempt += 1
            
            # If we get here, all retries failed
            if enable_cloudwatch_monitoring and monitor_task:
                # Stop monitoring since we've reached max retries
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["monitor"]["stop_monitoring"],
                        instance_id=instance_id
                    )
                except Exception as e:
                    logger.error(f"Error stopping monitoring: {str(e)}")
                    if broadcast and email_id:
                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id,
                            "success": False,
                            "message": f"Error stopping monitoring: {str(e)}"
                        })
            
            return {
                "success": False,
                "message": f"Script {script_name} failed after {max_attempts} attempts",
                "instance_id": instance_id,
                "logs": logs,
                "status": "failed"
            }

        except Exception as e:
            logger.error(f"Error running script on instance {instance_id}: {str(e)}")
            
            # Stop monitoring in case of unexpected error
            if enable_cloudwatch_monitoring and monitor_task:
                try:
                    await self.kernel.invoke(
                        self.kernel.plugins["monitor"]["stop_monitoring"],
                        instance_id=instance_id
                    )
                except Exception as monitor_e:
                    logger.error(f"Error stopping monitoring: {str(monitor_e)}")
                    if broadcast and email_id:
                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id,
                            "success": False,
                            "message": f"Error stopping monitoring: {str(monitor_e)}"
                        })
            
            return {
                "success": False,
                "message": f"Failed to run script on instance {instance_id}: {str(e)}",
                "instance_id": instance_id,
                "logs": logs,
                "status": "failed"
            }
        
    @kernel_function(
        description="Terminate an EC2 instance",
        name="terminate_instance"
    )
    async def terminate_instance(self, instance_id: str, region: str = "us-east-1") -> dict:
        try:
            ec2_client = self.session.client('ec2', region_name=region)
            ec2_client.terminate_instances(InstanceIds=[instance_id])
            logger.info(f"Terminated EC2 instance {instance_id} in {region}")
            return {"success": True, "message": f"EC2 instance {instance_id} terminated successfully"}
        except Exception as e:
            logger.error(f"Error terminating EC2 instance {instance_id}: {str(e)}")
            return {"success": False, "message": f"Failed to terminate EC2 instance: {str(e)}"}

    @kernel_function(
        description="Add an IAM user",
        name="add_user"
    )
    async def add_user(self, username: str) -> dict:
        try:
            iam_client = self.session.client('iam')
            iam_client.create_user(UserName=username)
            logger.info(f"Created IAM user {username}")
            return {"success": True, "message": f"IAM user {username} created successfully"}
        except Exception as e:
            logger.error(f"Error creating IAM user {username}: {str(e)}")
            return {"success": False, "message": f"Failed to create IAM user: {str(e)}"}

    @kernel_function(
        description="Remove an IAM user",
        name="remove_user"
    )
    async def remove_user(self, username: str) -> dict:
        try:
            iam_client = self.session.client('iam')
            iam_client.delete_user(UserName=username)
            logger.info(f"Removed IAM user {username}")
            return {"success": True, "message": f"IAM user {username} removed successfully"}
        except Exception as e:
            logger.error(f"Error removing IAM user {username}: {str(e)}")
            return {"success": False, "message": f"Failed to remove IAM user: {str(e)}"}

    @kernel_function(
        description="Add permission to an IAM user",
        name="add_user_permission"
    )
    async def add_user_permission(self, username: str, permission: str) -> dict:
        try:
            iam_client = self.session.client('iam')
            iam_client.attach_user_policy(
                UserName=username,
                PolicyArn=permission
            )
            logger.info(f"Added permission {permission} to IAM user {username}")
            return {"success": True, "message": f"Permission {permission} added to IAM user {username}"}
        except Exception as e:
            logger.error(f"Error adding permission to IAM user {username}: {str(e)}")
            return {"success": False, "message": f"Failed to add permission: {str(e)}"}

    @kernel_function(
        description="Remove permission from an IAM user",
        name="remove_user_permission"
    )
    async def remove_user_permission(self, username: str, permission: str) -> dict:
        try:
            iam_client = self.session.client('iam')
            iam_client.detach_user_policy(
                UserName=username,
                PolicyArn=permission
            )
            logger.info(f"Removed permission {permission} from IAM user {username}")
            return {"success": True, "message": f"Permission {permission} removed from IAM user {username}"}
        except Exception as e:
            logger.error(f"Error removing permission from IAM user {username}: {str(e)}")
            return {"success": False, "message": f"Failed to remove permission: {str(e)}"}