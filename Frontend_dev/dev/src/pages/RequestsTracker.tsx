import React, { useState, useEffect } from 'react';
import { useApp } from "@/contexts/AppContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

// Utility function to format time distance
const formatDistanceToNow = (date: Date, options?: { addSuffix?: boolean }) => {
  const now = new Date();
  const diffInMs = now.getTime() - date.getTime();
  const diffInMinutes = Math.floor(diffInMs / (1000 * 60));
  const diffInHours = Math.floor(diffInMs / (1000 * 60 * 60));
  const diffInDays = Math.floor(diffInMs / (1000 * 60 * 60 * 24));

  let result = '';
  if (diffInMinutes < 1) {
    result = 'just now';
  } else if (diffInMinutes < 60) {
    result = `${diffInMinutes} minute${diffInMinutes > 1 ? 's' : ''}`;
  } else if (diffInHours < 24) {
    result = `${diffInHours} hour${diffInHours > 1 ? 's' : ''}`;
  } else {
    result = `${diffInDays} day${diffInDays > 1 ? 's' : ''}`;
  }

  return options?.addSuffix ? `${result} ago` : result;
};

import { Button } from "@/components/ui/button";
import { Inbox, Send, Trash2, Archive, Star, Clock, Activity, AlertCircle, Loader2 } from "lucide-react";

interface BroadcastMessage {
  id: string;
  type: string;
  email_id?: string;
  thread_id?: string;
  intent?: string;
  ado_ticket_id?: string | number;
  servicenow_sys_id?: string;
  ado_url?: string;
  servicenow_url?: string;
  pending_actions?: boolean;
  timestamp: string;
  details: Record<string, any>;
  message?: string;
  subject?: string;
  sender?: string;
  is_valid_domain?: boolean;
  status?: string;
  comment?: string;
}

interface Cycle {
  email_id: string;
  thread_id?: string;
  messages: BroadcastMessage[];
  lastTimestamp: string;
  subject?: string;
  sender?: string;
  isCompleted: boolean;
  isActive: boolean;
  lastCompletionTimestamp?: string;
}

const messageTypeLabels: Record<string, string> = {
  email_detected: "Email Detected",
  intent_analyzed: "Intent Analyzed",
  ticket_created: "Ticket Created",
  action_performed: "Action Performed",
  email_reply: "Email Reply Sent",
  session: "Session Update",
  error: "Error",
  spam_alert: "Spam Alert",
  monitoring_started: "Monitoring Started",
  monitoring_stopped: "Monitoring Stopped",
  permission_fixed: "Permission Fixed",
  script_execution_failed: "Script Execution Failed",
  ticket_updated: "Ticket Updated",
};

const messageTypeColors: Record<string, string> = {
  email_detected: "bg-yellow-100 text-yellow-800",
  intent_analyzed: "bg-blue-100 text-blue-800",
  ticket_created: "bg-green-100 text-green-800",
  action_performed: "bg-teal-100 text-teal-800",
  email_reply: "bg-purple-100 text-purple-800",
  session: "bg-gray-100 text-gray-800",
  error: "bg-red-100 text-red-800",
  spam_alert: "bg-red-100 text-red-800",
  monitoring_started: "bg-indigo-100 text-indigo-800",
  monitoring_stopped: "bg-gray-100 text-gray-800",
  permission_fixed: "bg-green-100 text-green-800",
  script_execution_failed: "bg-red-100 text-red-800",
  ticket_updated: "bg-blue-100 text-blue-800",
};

const getMessageTypeLogo = (message: BroadcastMessage): string | null => {
  switch (message.type) {
    case "email_detected":
      return "https://logospng.org/download/microsoft-outlook/logo-microsoft-outlook-1024.png";
    case "intent_analyzed":
      return "https://img.freepik.com/premium-photo/friendly-looking-ai-agent-as-logo-white-background-style-raw-job-id-b7b07c82b6574fb8bb64985b261a_343960-69669.jpg";
    case "ticket_created":
    case "ticket_updated":
      return "https://th.bing.com/th/id/OIP.SMNthTKl4UDNMsEYDToSDgHaEK?w=1024&h=576&rs=1&pid=ImgDetMain";
    case "email_reply":
      return "https://1000logos.net/wp-content/uploads/2018/05/Gmail-Logo-500x281.jpg";
    case "action_performed":
      // Check if it's access-related action
      const messageText = message.message || "";
      if (messageText.includes("Pull access granted") || 
          messageText.includes("Push access granted") || 
          messageText.includes("Access revoked")) {
        return "https://th.bing.com/th/id/OIP.Vn8Aa5ypdPND2xyceZIAdAHaHS?rs=1&pid=ImgDetMain";
      }
      return null;
    default:
      return null;
  }
};

const getMessageDetails = (message: BroadcastMessage): string => {
  switch (message.type) {
    case "email_detected":
      return `Subject: ${message.subject || "No Subject"}, From: ${message.sender || "Unknown"}${
        message.is_valid_domain === false ? ' - <span class="text-red-600">UNAUTHORIZED DOMAIN</span>' : ""
      }`;
    case "intent_analyzed":
      return `Intent: ${message.intent || "Unknown"}${
        message.pending_actions !== undefined ? `, Pending Actions: ${message.pending_actions ? "Yes" : "No"}` : ""
      }`;
    case "ticket_created":
      return [
        message.ado_ticket_id &&
          `ADO Ticket ID: ${message.ado_ticket_id}${
            message.ado_url
              ? `, <a href="${message.ado_url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:underline">View in ADO</a>`
              : ""
          }`,
        message.servicenow_sys_id &&
          `ServiceNow ID: ${message.servicenow_sys_id}${
            message.servicenow_url
              ? `, <a href="${message.servicenow_url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:underline">View in ServiceNow</a>`
              : ""
          }`,
        message.intent && `Intent: ${message.intent}`,
      ]
        .filter(Boolean)
        .join("; ");
    case "action_performed":
      const actionLabels: Record<string, string> = {
        github_create_repo: "Created GitHub Repository",
        github_commit_file: "Committed File to Repository",
        github_delete_repo: "Deleted GitHub Repository",
        github_access_request: "Granted Repository Access",
        github_revoke_access: "Revoked Repository Access",
        aws_s3_create_bucket: "Created S3 Bucket",
        aws_s3_delete_bucket: "Deleted S3 Bucket",
        aws_ec2_launch_instance: "Launched EC2 Instance",
        aws_ec2_terminate_instance: "Terminated EC2 Instance",
        aws_iam_add_user: "Added IAM User",
        aws_iam_remove_user: "Removed IAM User",
        aws_iam_add_user_permission: "Added IAM User Permission",
        aws_iam_remove_user_permission: "Removed IAM User Permission",
        aws_ec2_run_script: "Executed Script on EC2 Instance",
      };
      const isPermissionAction =
        message.message?.toLowerCase().includes("permission") ||
        message.message?.toLowerCase().includes("policy") ||
        message.message?.toLowerCase().includes("role");
      const isFileCommit =
        message.message?.toLowerCase().includes("file") && message.message?.toLowerCase().includes("commit");
      const isPermissionFix = message.message?.toLowerCase().includes("fixed permission");
      const isS3BucketAction = message.message?.toLowerCase().includes("s3 bucket");
      const isScriptExecution =
        message.message?.toLowerCase().includes("script") && message.message?.toLowerCase().includes("executed");

      let actionLabel = "Performed Action";
      if (isPermissionAction) {
        actionLabel = "Permission Action";
      } else if (isFileCommit) {
        actionLabel = "File Committed";
      } else if (isPermissionFix) {
        actionLabel = "Permission Fixed";
      } else if (isS3BucketAction) {
        actionLabel = "S3 Bucket Action";
      } else if (isScriptExecution) {
        actionLabel = "Script Executed";
      } else if (message.intent && actionLabels[message.intent]) {
        actionLabel = actionLabels[message.intent];
      }

      const actionDetail = message.message || "Action completed";
      return [
        `${actionLabel}: ${actionDetail}`,
        message.ado_ticket_id && `ADO Ticket ID: ${message.ado_ticket_id}`,
        message.servicenow_sys_id && `ServiceNow ID: ${message.servicenow_sys_id}`,
      ]
        .filter(Boolean)
        .join("; ");
    case "email_reply":
      return `Thread ID: ${message.thread_id || "N/A"}, Email ID: ${message.email_id || "N/A"}`;
    case "session":
      return message.status ? `Status: ${message.status}` : "No status available";
    case "error":
    case "spam_alert":
      return message.message || "No details available";
    case "monitoring_started":
      return message.message || "Monitoring started";
    case "monitoring_stopped":
      return message.message || "Monitoring stopped";
    case "permission_fixed":
      return `Permission fixed: ${message.message || "Issue resolved"}`;
    case "script_execution_failed":
      return `Script execution failed: ${message.message || "Error occurred"}`;
    case "ticket_updated":
      return `Status: ${message.status || ""}, Comment: ${message.comment || "No comment"}`;
    default:
      return message.message || "No details available";
  }
};

const getCycleStatus = (cycle: Cycle): { status: string; color: string; icon: React.ReactNode } => {
  if (cycle.isCompleted) {
    return {
      status: "Completed",
      color: "text-green-600",
      icon: <div className="w-2 h-2 bg-green-500 rounded-full" />
    };
  } else if (cycle.isActive) {
    return {
      status: "In Progress",
      color: "text-blue-600",
      icon: <Loader2 size={12} className="animate-spin text-blue-500" />
    };
  } else {
    return {
      status: "Pending",
      color: "text-orange-600",
      icon: <div className="w-2 h-2 bg-orange-500 rounded-full" />
    };
  }
};

const getCyclePreview = (cycle: Cycle): string => {
  const latestMessage = cycle.messages[cycle.messages.length - 1];
  if (!latestMessage) return "No details available";
  
  const details = getMessageDetails(latestMessage).replace(/<[^>]*>/g, '');
  return details.length > 60 ? `${details.substring(0, 60)}...` : details;
};

export const RequestsTracker = () => {
  const { broadcastMessages } = useApp();
  const [cycles, setCycles] = useState<Cycle[]>([]);
  const [selectedCycle, setSelectedCycle] = useState<Cycle | null>(null);
  const [allMessages, setAllMessages] = useState<BroadcastMessage[]>([]);

  useEffect(() => {
    console.log('Broadcast messages received:', broadcastMessages);

    // Add new messages to allMessages
    setAllMessages((prev) => {
      const newMessages = broadcastMessages.filter(
        (msg) => !prev.some((existing) => existing.id === msg.id)
      );
      return [...prev, ...newMessages];
    });

    // Process all messages into cycles
    const combinedMessages = [...allMessages, ...broadcastMessages].reduce((acc, msg) => {
      if (!acc.find((m) => m.id === msg.id)) {
        acc.push(msg);
      }
      return acc;
    }, [] as BroadcastMessage[]);

    const groupedByThread: Record<string, Cycle> = {};
    const threadToCycleMap: Record<string, string> = {};

    combinedMessages.forEach((msg) => {
      let cycleKey: string;
      let cycleThreadId: string | undefined;

      // Determine which cycle this message belongs to
      if (msg.thread_id && threadToCycleMap[msg.thread_id]) {
        cycleKey = threadToCycleMap[msg.thread_id];
      } else if (msg.thread_id) {
        cycleKey = msg.thread_id;
        threadToCycleMap[msg.thread_id] = cycleKey;
        cycleThreadId = msg.thread_id;
      } else if (msg.email_id) {
        cycleKey = msg.email_id;
      } else {
        // Messages without email_id or thread_id are treated as system messages
        // Create a cycle for them based on message type or timestamp
        cycleKey = `system-${msg.type}-${msg.timestamp}`;
      }

      // Create cycle if it doesn't exist
      if (!groupedByThread[cycleKey]) {
        groupedByThread[cycleKey] = {
          email_id: msg.email_id || cycleKey,
          thread_id: cycleThreadId,
          messages: [],
          lastTimestamp: msg.timestamp,
          subject: msg.subject,
          sender: msg.sender,
          isCompleted: false,
          isActive: false,
        };
      }

      // Add message to cycle if not already present
      if (!groupedByThread[cycleKey].messages.some((existing) => existing.id === msg.id)) {
        groupedByThread[cycleKey].messages.push(msg);
      }

      // Update cycle metadata
      groupedByThread[cycleKey].lastTimestamp =
        msg.timestamp > groupedByThread[cycleKey].lastTimestamp ? msg.timestamp : groupedByThread[cycleKey].lastTimestamp;
      groupedByThread[cycleKey].subject = groupedByThread[cycleKey].subject || msg.subject;
      groupedByThread[cycleKey].sender = groupedByThread[cycleKey].sender || msg.sender;

      // Update thread mapping
      if (msg.thread_id && msg.email_id && !threadToCycleMap[msg.thread_id]) {
        threadToCycleMap[msg.thread_id] = cycleKey;
      }
    });

    // Determine cycle status with improved logic
    const processedCycles = Object.values(groupedByThread).map((cycle) => {
      // Sort messages by timestamp
      cycle.messages.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

      // Find completion indicators
      const completionMessages = cycle.messages.filter(msg => 
        msg.type === "email_reply" || 
        (msg.type === "action_performed" && 
         getMessageDetails(msg).toLowerCase().includes("access revoked")) ||
        msg.type === "error"
      );

      // Find the latest completion message timestamp
      let lastCompletionTimestamp: string | undefined;
      if (completionMessages.length > 0) {
        lastCompletionTimestamp = completionMessages
          .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0]
          .timestamp;
        cycle.lastCompletionTimestamp = lastCompletionTimestamp;
      }

      // Check if there are new messages after the last completion
      const hasNewMessagesAfterCompletion = lastCompletionTimestamp ? 
        cycle.messages.some(msg => new Date(msg.timestamp) > new Date(lastCompletionTimestamp!)) : 
        false;

      // Determine if cycle is completed
      const hasCompletionIndicator = completionMessages.length > 0;
      cycle.isCompleted = hasCompletionIndicator && !hasNewMessagesAfterCompletion;
      
      // Determine if cycle is currently active
      const lastActivityTime = new Date(cycle.lastTimestamp).getTime();
      const now = new Date().getTime();
      const timeDiffMinutes = (now - lastActivityTime) / (1000 * 60);
      
      // A cycle is active if:
      // 1. It's not completed, OR
      // 2. It was completed but has new messages after completion, AND
      // 3. Last activity was within 30 minutes
      cycle.isActive = (!cycle.isCompleted || hasNewMessagesAfterCompletion) && timeDiffMinutes < 30;

      return cycle;
    });

    // Sort cycles by timestamp (most recent first)
    const sortedCycles = processedCycles.sort((a, b) => 
      new Date(b.lastTimestamp).getTime() - new Date(a.lastTimestamp).getTime()
    );

    setCycles(sortedCycles);

    // Update selected cycle if it exists in the new cycles
    if (selectedCycle) {
      const updatedSelectedCycle = sortedCycles.find(
        cycle => cycle.email_id === selectedCycle.email_id || 
        (cycle.thread_id && cycle.thread_id === selectedCycle.thread_id)
      );
      if (updatedSelectedCycle) {
        setSelectedCycle(updatedSelectedCycle);
      }
    }

    console.log('Processed cycles:', sortedCycles);
  }, [broadcastMessages, allMessages, selectedCycle]);

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Main Content Area */}
      <div className="flex-1 flex">
        {/* Recent Activity List Pane (Cycle-based) */}
        <div className="w-80 bg-white border-r border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-800">Recent Activity</h2>
              <Activity size={20} className="text-gray-500" />
            </div>
            <p className="text-xs text-gray-500 mt-1">
              {cycles.length} cycle{cycles.length !== 1 ? 's' : ''}
            </p>
          </div>
          <ScrollArea className="flex-1">
            {cycles.length === 0 ? (
              <div className="p-4 text-center text-gray-500">
                <AlertCircle size={48} className="mx-auto mb-2 text-gray-300" />
                <p className="text-sm">No recent activity</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {cycles.map((cycle) => {
                  const status = getCycleStatus(cycle);
                  return (
                    <div
                      key={cycle.thread_id || cycle.email_id}
                      className={`p-4 cursor-pointer transition-colors hover:bg-gray-50 ${
                        selectedCycle?.email_id === cycle.email_id ? 'bg-blue-50 border-l-4 border-blue-500' : ''
                      } ${cycle.isActive ? 'bg-blue-25' : ''}`}
                      onClick={() => setSelectedCycle(cycle)}
                    >
                      <div className="flex justify-between items-start mb-1">
                        <h3 className="text-sm font-medium text-gray-900 truncate flex-1 mr-2">
                          {cycle.subject || `Request ${cycle.thread_id || cycle.email_id}`}
                        </h3>
                        <span className="text-xs text-gray-500 flex-shrink-0">
                          {formatDistanceToNow(new Date(cycle.lastTimestamp), { addSuffix: true })}
                        </span>
                      </div>
                      
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs text-gray-600">
                          {cycle.sender || 'System'} • {cycle.messages.length} message{cycle.messages.length !== 1 ? 's' : ''}
                        </p>
                        <div className="flex items-center gap-1">
                          {status.icon}
                          <span className={`text-xs ${status.color}`}>
                            {status.status}
                          </span>
                        </div>
                      </div>
                      
                      <p className="text-xs text-gray-500 truncate">
                        {getCyclePreview(cycle)}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </ScrollArea>
        </div>

        {/* Agent Activity Log Detail Pane */}
        <div className="flex-1 bg-white flex flex-col">
          {selectedCycle ? (
            <>
              <div className="p-4 border-b border-gray-200">
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-lg font-semibold text-gray-800">
                    {selectedCycle.subject || `Request ${selectedCycle.thread_id || selectedCycle.email_id}`}
                  </h2>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedCycle(null)}
                  >
                    Close
                  </Button>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-600">
                    {selectedCycle.sender || 'System'} • Updated {formatDistanceToNow(new Date(selectedCycle.lastTimestamp), { addSuffix: true })}
                  </p>
                  <div className="flex items-center gap-2">
                    {getCycleStatus(selectedCycle).icon}
                    <span className={`text-sm ${getCycleStatus(selectedCycle).color}`}>
                      {getCycleStatus(selectedCycle).status}
                    </span>
                  </div>
                </div>
              </div>
              <ScrollArea className="flex-1 p-4">
                <div className="space-y-4">
                  {selectedCycle.messages.map((message, index) => {
                    const logo = getMessageTypeLogo(message);
                    return (
                      <div key={message.id} className={`border-l-4 pl-4 py-2 ${
                        index === selectedCycle.messages.length - 1 && selectedCycle.isActive
                          ? 'border-blue-400 bg-blue-50' 
                          : 'border-gray-200'
                      }`}>
                        <div className="flex items-center gap-2 mb-2">
                          {logo && (
                            <img
                              src={logo}
                              alt={`${messageTypeLabels[message.type]} logo`}
                              className="h-6 w-6 object-contain"
                            />
                          )}
                          <Badge className={messageTypeColors[message.type] || "bg-gray-100 text-gray-800"}>
                            {messageTypeLabels[message.type] || message.type}
                          </Badge>
                          <span className="text-sm text-gray-500">
                            {formatDistanceToNow(new Date(message.timestamp), { addSuffix: true })}
                          </span>
                          {index === selectedCycle.messages.length - 1 && selectedCycle.isActive && (
                            <Badge variant="outline" className="text-blue-600 border-blue-300">
                              Latest
                            </Badge>
                          )}
                        </div>
                        <div
                          className="text-sm text-gray-700"
                          dangerouslySetInnerHTML={{ __html: getMessageDetails(message) }}
                        />
                      </div>
                    );
                  })}
                  
                  {selectedCycle.isActive && (
                    <div className="border-l-4 border-blue-400 pl-4 py-2 bg-blue-25">
                      <div className="flex items-center gap-2 mb-2">
                        <Loader2 size={16} className="animate-spin text-blue-500" />
                        <Badge variant="outline" className="text-blue-600 border-blue-300">
                          Processing...
                        </Badge>
                      </div>
                      <p className="text-sm text-blue-700">
                        Activity is in progress. New updates will appear here automatically.
                      </p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center py-12">
                <Activity size={64} className="mx-auto mb-4 text-gray-300" />
                <h3 className="text-lg font-medium text-gray-600 mb-2">Agent Activity Log</h3>
                <p className="text-gray-500">Select a cycle from Recent Activity to view details</p>
                <p className="text-sm text-gray-400 mt-1">
                  All messages in a cycle are grouped together like email threads
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RequestsTracker;