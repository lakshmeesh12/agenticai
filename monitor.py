import boto3
import time
import datetime
import asyncio
import re
import json
import logging
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)

class MonitorPlugin:
    """Plugin to monitor CloudWatch logs and automatically fix permission issues."""

    def __init__(self):
        self.is_running = False
        self.monitoring_tasks = {}
        self.retries = {}  # Store retry counts for each instance

    @kernel_function(
        description="Monitor CloudWatch logs for an EC2 instance and automatically fix permission issues",
        name="monitor_logs"
    )
    async def monitor_logs(self, instance_id: str, log_group_name: str, interval: int, logs_client=None, 
                          ec2_client=None, iam_client=None, fix_event=None, monitoring_flag=None, 
                          broadcast=None, email_id=None) -> dict:
        """
        Monitor CloudWatch logs for an EC2 instance and fix detected permission issues.
        
        Args:
            instance_id: The EC2 instance ID to monitor
            log_group_name: The CloudWatch log group name
            interval: How often to check for new logs (in seconds)
            logs_client: Optional pre-configured boto3 logs client
            ec2_client: Optional pre-configured boto3 EC2 client
            iam_client: Optional pre-configured boto3 IAM client
            fix_event: Optional asyncio Event to signal when a fix has been applied
            monitoring_flag: Optional async callable that returns whether monitoring should continue
            broadcast: Optional function to broadcast messages to the UI
            email_id: Optional email ID to associate with broadcasts
        
        Returns:
            A dictionary containing monitoring results
        """
        try:
            # Initialize AWS clients if not provided
            if not logs_client:
                logs_client = boto3.client('logs', region_name="us-east-2")
            if not ec2_client:
                ec2_client = boto3.client('ec2', region_name="us-east-2")
            if not iam_client:
                iam_client = boto3.client('iam', region_name="us-east-2")
            
            # Initialize timestamp to get logs from now onwards
            start_time = int(time.time() * 1000)
            
            logger.info(f"Started monitoring logs for instance {instance_id} in log group {log_group_name}")
            
            while True:
                # Check if we should continue monitoring
                if monitoring_flag and not await monitoring_flag():
                    logger.info(f"Stopping log monitoring for instance {instance_id} as flagged")
                    break
                
                # Get and process new logs
                start_time, fixed_permissions = await self._get_and_process_logs(
                    logs_client, ec2_client, iam_client, log_group_name, 
                    instance_id, start_time, fix_event, broadcast, email_id
                )
                
                # If permissions were fixed, notify via the event
                if fixed_permissions and fix_event:
                    logger.info(f"Permission fix applied for instance {instance_id}, signaling event")
                    if broadcast:
                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id or instance_id,
                            "success": True,
                            "message": f"Permission fix applied for instance {instance_id}"
                        })
                
                # Wait before checking again
                await asyncio.sleep(interval)
            
            logger.info(f"Monitoring stopped for instance {instance_id}")
            return {
                "success": True,
                "message": f"Monitoring completed for instance {instance_id}",
                "instance_id": instance_id
            }
            
        except asyncio.CancelledError:
            logger.info(f"Monitoring task for instance {instance_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Error monitoring logs for instance {instance_id}: {str(e)}")
            if broadcast:
                await broadcast({
                    "type": "error",
                    "email_id": email_id or instance_id,
                    "message": f"Failed to monitor logs: {str(e)}"
                })
            return {
                "success": False,
                "message": f"Failed to monitor logs: {str(e)}",
                "instance_id": instance_id
            }

    async def _get_and_process_logs(self, logs_client, ec2_client, iam_client, 
                                   log_group_name, instance_id, start_time, fix_event, 
                                   broadcast=None, email_id=None):
        """Get new logs from CloudWatch and process them for permission issues."""
        try:
            # Get log streams for this instance
            response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                logStreamNamePrefix=instance_id
            )
            
            latest_timestamp = start_time
            fixed_permissions = False
            
            # If no log streams found, return early
            if not response.get('logStreams'):
                return start_time, fixed_permissions
                
            # Process each log stream for the instance
            for stream in response['logStreams']:
                stream_name = stream['logStreamName']
                
                # Get log events from this stream
                log_response = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=stream_name,
                    startTime=start_time,
                    startFromHead=True
                )
                
                # Process each log event
                for event in log_response['events']:
                    timestamp = event['timestamp']
                    message = event['message']
                    
                    # Update the latest timestamp
                    latest_timestamp = max(latest_timestamp, timestamp + 1)
                    
                    # Check for permission issues and fix them
                    if await self._check_for_access_denied(message, instance_id, ec2_client, iam_client, broadcast, email_id):
                        fixed_permissions = True
                        logger.info(f"Fixed permission issue for instance {instance_id}")
                        if broadcast:
                            await broadcast({
                                "type": "action_performed",
                                "email_id": email_id or instance_id,
                                "success": True,
                                "message": f"Fixed permission issue for instance {instance_id}"
                            })
            
            return latest_timestamp, fixed_permissions
            
        except Exception as e:
            logger.error(f"Error getting logs for instance {instance_id}: {str(e)}")
            if broadcast:
                await broadcast({
                    "type": "error",
                    "email_id": email_id or instance_id,
                    "message": f"Error getting logs: {str(e)}"
                })
            return start_time, False

    async def _check_for_access_denied(self, message, instance_id, ec2_client, iam_client, broadcast=None, email_id=None):
        """Check if the log message contains AccessDenied errors and fix them if possible."""
        if "AccessDenied" in message and "is not authorized to perform" in message:
            # Extract the service and action from the error message
            service_match = re.search(r"perform: ([^:]+):([^\s]+)", message)
            resource_match = re.search(r"resource: \"([^\"]+)\"", message)
            
            if service_match and resource_match:
                service = service_match.group(1)
                action = service_match.group(2)
                resource = resource_match.group(1)
                
                logger.info(f"Detected permission error on instance {instance_id}:")
                logger.info(f"Service: {service}, Action: {action}, Resource: {resource}")
                if broadcast:
                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id or instance_id,
                        "success": True,
                        "message": f"Detected permission error on instance {instance_id}: Service: {service}, Action: {action}, Resource: {resource}"
                    })
                
                # Get the instance profile and role associated with the EC2 instance
                instance_profile_arn, role_name = self._get_instance_profile_and_role(instance_id, ec2_client, iam_client)
                
                # If we couldn't get the role name from the EC2 instance, try from the error message
                if not role_name:
                    role_arn_match = re.search(r"User: (arn:aws:[^:]+:[^:]+:[^:]+:assumed-role/([^/]+)/)", message)
                    role_name = role_arn_match.group(2) if role_arn_match else None
                
                if role_name:
                    logger.info(f"Found role: {role_name}")
                    if broadcast:
                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id or instance_id,
                            "success": True,
                            "message": f"Found role: {role_name} for instance {instance_id}"
                        })
                    # Create and attach a policy to fix the permission issue
                    return await self._create_policy_for_service_action(role_name, service, action, resource, iam_client, instance_id, broadcast, email_id)
                else:
                    logger.warning(f"Could not determine the IAM role to update for instance {instance_id}")
                    if broadcast:
                        await broadcast({
                            "type": "action_performed",
                            "email_id": email_id or instance_id,
                            "success": False,
                            "message": f"Could not determine the IAM role to update for instance {instance_id}"
                        })
            
        return False

    def _get_instance_profile_and_role(self, instance_id, ec2_client, iam_client):
        """Get the IAM instance profile and role name for the EC2 instance."""
        try:
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            if not response['Reservations'] or not response['Reservations'][0]['Instances']:
                logger.warning(f"Could not find EC2 instance {instance_id}")
                return None, None
            
            instance = response['Reservations'][0]['Instances'][0]
            if 'IamInstanceProfile' not in instance:
                logger.warning(f"EC2 instance {instance_id} does not have an IAM instance profile attached")
                return None, None
            
            instance_profile_arn = instance['IamInstanceProfile']['Arn']
            profile_name = instance_profile_arn.split('/')[-1]
            
            # Get the instance profile to find the associated role
            response = iam_client.get_instance_profile(InstanceProfileName=profile_name)
            if not response['InstanceProfile']['Roles']:
                logger.warning(f"Instance profile does not have any roles attached")
                return instance_profile_arn, None
            
            role_name = response['InstanceProfile']['Roles'][0]['RoleName']
            return instance_profile_arn, role_name
        
        except Exception as e:
            logger.error(f"Error getting instance profile: {str(e)}")
            return None, None

    async def _create_policy_for_service_action(self, role_name, service, action, resource_arn, iam_client, instance_id, broadcast=None, email_id=None):
        """Create and attach a policy to grant the required permission."""
        try:
            if not role_name:
                logger.warning("Cannot add permissions: No role name provided")
                if broadcast:
                    await broadcast({
                        "type": "action_performed",
                        "email_id": email_id or instance_id,
                        "success": False,
                        "message": "Cannot add permissions: No role name provided"
                    })
                return False
            
            # Create a policy document for the required permission
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
            
            # Create a policy name based on the service and action
            policy_name = f"{service}-{action}-{int(time.time())}"
            
            # Create the policy
            response = iam_client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description=f"Auto-generated policy to allow {service}:{action} on {resource_arn}"
            )
            
            policy_arn = response['Policy']['Arn']
            
            # Attach the policy to the role
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
            
            logger.info(f"Successfully created and attached policy '{policy_name}' to role '{role_name}'")
            logger.info(f"Added permission: {service}:{action} on {resource_arn}")
            if broadcast:
                await broadcast({
                    "type": "action_performed",
                    "email_id": email_id or instance_id,
                    "success": True,
                    "message": f"Successfully created and attached policy '{policy_name}' to role '{role_name}'"
                })
                await broadcast({
                    "type": "action_performed",
                    "email_id": email_id or instance_id,
                    "success": True,
                    "message": f"Added permission: {service}:{action} on {resource_arn}"
                })
            return True
        
        except Exception as e:
            logger.error(f"Error creating or attaching policy: {str(e)}")
            if broadcast:
                await broadcast({
                    "type": "action_performed",
                    "email_id": email_id or instance_id,
                    "success": False,
                    "message": f"Error creating or attaching policy: {str(e)}"
                })
            return False

    @kernel_function(
        description="Start background monitoring of CloudWatch logs for error detection and fixing",
        name="start_monitoring"
    )
    async def start_monitoring(self, instance_id: str, log_group_name: str = "EC2logs", 
                              interval: int = 5, region: str = "us-east-2", 
                              broadcast=None, email_id=None) -> dict:
        """
        Start background monitoring of CloudWatch logs for an EC2 instance.
        
        Args:
            instance_id: The EC2 instance ID to monitor
            log_group_name: The CloudWatch log group name
            interval: How often to check for new logs (in seconds)
            region: The AWS region
            broadcast: Optional function to broadcast messages to the UI
            email_id: Optional email ID to associate with broadcasts
        
        Returns:
            A dictionary indicating whether monitoring was started successfully
        """
        try:
            # If already monitoring this instance, return success
            if instance_id in self.monitoring_tasks and not self.monitoring_tasks[instance_id].done():
                return {
                    "success": True,
                    "message": f"Already monitoring instance {instance_id}",
                    "status": "monitoring"
                }
            
            # Setup AWS clients
            logs_client = boto3.client('logs', region_name=region)
            ec2_client = boto3.client('ec2', region_name=region)
            iam_client = boto3.client('iam', region_name=region)
            
            # Create event for signaling when a fix has been applied
            fix_event = asyncio.Event()
            
            # Start monitoring task
            self.is_running = True
            monitoring_flag = lambda: asyncio.to_thread(lambda: self.is_running)
            
            task = asyncio.create_task(
                self.monitor_logs(
                    instance_id, log_group_name, interval, 
                    logs_client, ec2_client, iam_client, fix_event, monitoring_flag, 
                    broadcast, email_id
                )
            )
            
            # Store the task for later reference
            self.monitoring_tasks[instance_id] = task
            self.retries[instance_id] = 0
            
            logger.info(f"Started monitoring task for instance {instance_id}")
            if broadcast:
                await broadcast({
                    "type": "monitoring_started",
                    "email_id": email_id or instance_id,
                    "instance_id": instance_id,
                    "message": f"Started CloudWatch monitoring for instance {instance_id}"
                })
            return {
                "success": True,
                "message": f"Started monitoring instance {instance_id} logs",
                "status": "monitoring"
            }
            
        except Exception as e:
            logger.error(f"Error starting monitoring for instance {instance_id}: {str(e)}")
            if broadcast:
                await broadcast({
                    "type": "error",
                    "email_id": email_id or instance_id,
                    "message": f"Failed to start monitoring: {str(e)}"
                })
            return {
                "success": False,
                "message": f"Failed to start monitoring: {str(e)}",
                "status": "failed"
            }

    @kernel_function(
        description="Stop background monitoring of CloudWatch logs",
        name="stop_monitoring"
    )
    async def stop_monitoring(self, instance_id: str = None) -> dict:
        """
        Stop background monitoring of CloudWatch logs.
        
        Args:
            instance_id: The EC2 instance ID to stop monitoring (None to stop all)
        
        Returns:
            A dictionary indicating whether monitoring was stopped successfully
        """
        try:
            if instance_id:
                # Stop monitoring for a specific instance
                if instance_id in self.monitoring_tasks:
                    task = self.monitoring_tasks[instance_id]
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    del self.monitoring_tasks[instance_id]
                    if instance_id in self.retries:
                        del self.retries[instance_id]
                    return {
                        "success": True,
                        "message": f"Stopped monitoring instance {instance_id}",
                        "status": "stopped"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Instance {instance_id} is not being monitored",
                        "status": "not_monitoring"
                    }
            else:
                # Stop all monitoring tasks
                self.is_running = False
                for inst_id, task in list(self.monitoring_tasks.items()):
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                self.monitoring_tasks.clear()
                self.retries.clear()
                return {
                    "success": True,
                    "message": "Stopped all monitoring tasks",
                    "status": "all_stopped"
                }
                
        except Exception as e:
            logger.error(f"Error stopping monitoring: {str(e)}")
            return {
                "success": False, 
                "message": f"Failed to stop monitoring: {str(e)}",
                "status": "error"
            }

    @kernel_function(
        description="Get the status of all monitoring tasks",
        name="get_monitoring_status"
    )
    def get_monitoring_status(self) -> dict:
        """
        Get the status of all monitoring tasks.
        
        Returns:
            A dictionary containing the status of all monitoring tasks
        """
        status = {}
        for instance_id, task in self.monitoring_tasks.items():
            status[instance_id] = {
                "running": not task.done(),
                "completed": task.done() and not task.cancelled(),
                "cancelled": task.cancelled() if task.done() else False,
                "retries": self.retries.get(instance_id, 0)
            }
        
        return {
            "success": True,
            "status": status,
            "count": len(status),
            "active": sum(1 for info in status.values() if info["running"])
        }