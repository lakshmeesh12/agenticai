import React, { useState, useEffect, useRef } from 'react';
import { useApp } from "@/contexts/AppContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Inbox, Send, Trash2, Archive, Star, Clock, Activity, AlertCircle, Loader2 } from "lucide-react";
import Navbar from "@/components/layout/Navbar";

// --- Utility functions and interfaces remain unchanged ---
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

interface Notification {
  id: string;
  message: BroadcastMessage;
}

// --- Existing utility functions (unchanged) ---
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
  email_detected: "bg-amber-100 text-amber-800",
  intent_analyzed: "bg-blue-100 text-blue-800",
  ticket_created: "bg-emerald-100 text-emerald-800",
  action_performed: "bg-teal-100 text-teal-800",
  email_reply: "bg-purple-100 text-purple-800",
  session: "bg-gray-100 text-gray-800",
  error: "bg-red-100 text-red-800",
  spam_alert: "bg-red-100 text-red-800",
  monitoring_started: "bg-indigo-100 text-indigo-800",
  monitoring_stopped: "bg-gray-100 text-gray-800",
  permission_fixed: "bg-emerald-100 text-emerald-800",
  script_execution_failed: "bg-red-100 text-red-800",
  ticket_updated: "bg-blue-100 text-blue-800",
};

const getMessageTypeLogo = (message: BroadcastMessage): string | null => {
  switch (message.type) {
    case "email_detected":
      return "https://logospng.org/download/microsoft-outlook/logo-microsoft-outlook-1024.png";
    case "intent_analyzed":
      return "https://img.freepik.com/premium-vector/ai-logo-template-vector-with-white-background_1023984-15069.jpg?w=360";
    case "ticket_created":
    case "ticket_updated":
      return "https://th.bing.com/th/id/OIP.SMNthTKl4UDNMsEYDToSDgHaEK?w=1024&h=576&rs=1&pid=ImgDetMain";
    case "email_reply":
      return "https://1000logos.net/wp-content/uploads/2018/05/Gmail-Logo-500x281.jpg";
    case "monitoring_started":
    case "monitoring_stopped":
      return "https://res.cloudinary.com/hy4kyit2a/f_auto,fl_lossy,q_70/learn/modules/monitoring-on-aws/monitor-your-architecture-with-amazon-cloudwatch/images/522c742e37be736db2af0f8a720b1c02_f-05-f-9-a-02-2-a-81-4-fa-3-b-651-412-e-2222-bd-08.png";
    case "action_performed":
      const messageText = message.message || "";
      if (messageText.toLowerCase().includes("s3 bucket")) {
        return "https://seekvectors.com/storage/images/072095bef5407decc46caf5ace643475.jpg";
      }
      if (messageText.toLowerCase().includes("script") && messageText.toLowerCase().includes("executed successfully")) {
        return "https://seekvectors.com/storage/images/072095bef5407decc46caf5ace643475.jpg";
      }
      if (
        messageText.toLowerCase().includes("repository") ||
        messageText.toLowerCase().includes("repo") ||
        (messageText.toLowerCase().includes("file") && messageText.toLowerCase().includes("commit"))
      ) {
        return "https://th.bing.com/th/id/OIP.Vn8Aa5ypdPND2xyceZIAdAHaHS?rs=1&pid=ImgDetMain";
      }
      if (
        messageText.includes("Pull access granted") ||
        messageText.includes("Push access granted") ||
        messageText.includes("Access revoked")
      ) {
        return "https://th.bing.com/th/id/OIP.Vn8Aa5ypdPND2xyceZIAdAHaHS?rs=1&pid=ImgDetMain";
      }
      if (
        messageText.toLowerCase().includes("permission") ||
        messageText.toLowerCase().includes("policy") ||
        messageText.toLowerCase().includes("role")
      ) {
        return "https://res.cloudinary.com/hy4kyit2a/f_auto,fl_lossy,q_70/learn/modules/monitoring-on-aws/monitor-your-architecture-with-amazon-cloudwatch/images/522c742e37be736db2af0f8a720b1c02_f-05-f-9-a-02-2-a-81-4-fa-3-b-651-412-e-2222-bd-08.png";
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
        message.is_valid_domain === false ? ' - <span class="text-red-600 font-medium">UNAUTHORIZED DOMAIN</span>' : ""
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
      return message.message || "No reply message available";
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
      color: "text-emerald-600",
      icon: <div className="w-2 h-2 bg-emerald-500 rounded-full" />
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
      color: "text-amber-600",
      icon: <div className="w-2 h-2 bg-amber-500 rounded-full" />
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
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [sidebarWidth, setSidebarWidth] = useState(350);
  const isResizing = useRef(false);

  // Handle sidebar resizing
  const handleMouseDown = (e: React.MouseEvent) => {
    isResizing.current = true;
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (isResizing.current) {
      const newWidth = e.clientX;
      if (newWidth >= 280 && newWidth <= 800) {
        setSidebarWidth(newWidth);
      }
    }
  };

  const handleMouseUp = () => {
    isResizing.current = false;
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', handleMouseUp);
  };

  // Load stored messages from localStorage
  useEffect(() => {
    const storedMessages = localStorage.getItem('activityMessages');
    if (storedMessages) {
      try {
        const parsedMessages = JSON.parse(storedMessages);
        setAllMessages(parsedMessages);
      } catch (error) {
        console.error('Error parsing stored messages:', error);
      }
    }
  }, []);

  // Save messages to localStorage
  useEffect(() => {
    if (allMessages.length > 0) {
      localStorage.setItem('activityMessages', JSON.stringify(allMessages));
    }
  }, [allMessages]);

  // Handle new broadcast messages and trigger notifications for email_detected
  useEffect(() => {
    const newMessages = broadcastMessages.filter(
      (msg) => !allMessages.some((existing) => existing.id === msg.id)
    );
    setAllMessages((prev) => [...prev, ...newMessages]);

    // Trigger notifications for new email_detected messages
    newMessages.forEach((msg) => {
      if (msg.type === 'email_detected') {
        const newNotification: Notification = { id: msg.id, message: msg };
        setNotifications((prev) => [...prev, newNotification]);

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
          setNotifications((prev) => prev.filter((n) => n.id !== msg.id));
        }, 5000);
      }
    });
  }, [broadcastMessages, allMessages]);

  // Handle cycle deletion
  const handleDeleteCycle = (cycleKey: string) => {
    setCycles((prevCycles) => {
      const updatedCycles = prevCycles.filter(
        (cycle) => (cycle.thread_id || cycle.email_id) !== cycleKey
      );
      setAllMessages((prevMessages) => {
        const updatedMessages = prevMessages.filter(
          (msg) => (msg.thread_id || msg.email_id) !== cycleKey
        );
        localStorage.setItem('activityMessages', JSON.stringify(updatedMessages));
        return updatedMessages;
      });
      if (selectedCycle && (selectedCycle.thread_id || selectedCycle.email_id) === cycleKey) {
        setSelectedCycle(null);
      }
      return updatedCycles;
    });
  };

  // Process cycles (unchanged)
  useEffect(() => {
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

      if (msg.thread_id && threadToCycleMap[msg.thread_id]) {
        cycleKey = threadToCycleMap[msg.thread_id];
      } else if (msg.thread_id) {
        cycleKey = msg.thread_id;
        threadToCycleMap[msg.thread_id] = cycleKey;
        cycleThreadId = msg.thread_id;
      } else if (msg.email_id) {
        cycleKey = msg.email_id;
      } else {
        cycleKey = `system-${msg.type}-${msg.timestamp}`;
      }

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

      if (!groupedByThread[cycleKey].messages.some((existing) => existing.id === msg.id)) {
        groupedByThread[cycleKey].messages.push(msg);
      }

      groupedByThread[cycleKey].lastTimestamp =
        msg.timestamp > groupedByThread[cycleKey].lastTimestamp ? msg.timestamp : groupedByThread[cycleKey].lastTimestamp;
      groupedByThread[cycleKey].subject = groupedByThread[cycleKey].subject || msg.subject;
      groupedByThread[cycleKey].sender = groupedByThread[cycleKey].sender || msg.sender;

      if (msg.thread_id && msg.email_id && !threadToCycleMap[msg.thread_id]) {
        threadToCycleMap[msg.thread_id] = cycleKey;
      }
    });

    const processedCycles = Object.values(groupedByThread).map((cycle) => {
      cycle.messages.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

      const completionMessages = cycle.messages.filter(msg =>
        msg.type === "email_reply" ||
        (msg.type === "action_performed" &&
          getMessageDetails(msg).toLowerCase().includes("access revoked")) ||
        msg.type === "error"
      );

      let lastCompletionTimestamp: string | undefined;
      if (completionMessages.length > 0) {
        lastCompletionTimestamp = completionMessages
          .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0]
          .timestamp;
        cycle.lastCompletionTimestamp = lastCompletionTimestamp;
      }

      const hasNewMessagesAfterCompletion = lastCompletionTimestamp ?
        cycle.messages.some(msg => new Date(msg.timestamp) > new Date(lastCompletionTimestamp!)) :
        false;

      const hasCompletionIndicator = completionMessages.length > 0;
      cycle.isCompleted = hasCompletionIndicator && !hasNewMessagesAfterCompletion;

      const lastActivityTime = new Date(cycle.lastTimestamp).getTime();
      const now = new Date().getTime();
      const timeDiffMinutes = (now - lastActivityTime) / (1000 * 60);

      cycle.isActive = (!cycle.isCompleted || hasNewMessagesAfterCompletion) && timeDiffMinutes < 30;

      return cycle;
    });

    const sortedCycles = processedCycles.sort((a, b) =>
      new Date(b.lastTimestamp).getTime() - new Date(a.lastTimestamp).getTime()
    );

    setCycles(sortedCycles);

    if (selectedCycle) {
      const updatedSelectedCycle = sortedCycles.find(
        cycle => cycle.email_id === selectedCycle.email_id ||
          (cycle.thread_id && cycle.thread_id === selectedCycle.thread_id)
      );
      if (updatedSelectedCycle) {
        setSelectedCycle(updatedSelectedCycle);
      }
    }
  }, [broadcastMessages, allMessages]);

  // Handle notification close
  const handleCloseNotification = (id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  return (
    <div className="flex flex-col h-screen bg-white">
      <Navbar />
      <div className="flex flex-1 overflow-hidden">
        {/* Recent Activity Pane */}
        <div
          className="bg-slate-50 border-r border-slate-200 flex flex-col shadow-lg"
          style={{ width: `${sidebarWidth}px`, minWidth: '280px', maxWidth: '800px' }}
        >
          <div className="p-4 border-b border-slate-200 bg-slate-100">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                <Activity size={20} className="text-blue-600" />
                Recent Activity
              </h2>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {cycles.length} active cycle{cycles.length !== 1 ? 's' : ''}
            </p>
          </div>
          <ScrollArea className="flex-1">
            {cycles.length === 0 ? (
              <div className="p-6 text-center text-gray-500">
                <AlertCircle size={48} className="mx-auto mb-3 text-gray-300" />
                <p className="text-sm font-medium">No recent activity</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-200">
                {cycles.map((cycle) => {
                  const status = getCycleStatus(cycle);
                  const cycleKey = cycle.thread_id || cycle.email_id;
                  return (
                    <div
                      key={cycleKey}
                      className={`p-4 flex justify-between items-start transition-all duration-200 hover:bg-blue-50 cursor-pointer ${selectedCycle?.email_id === cycle.email_id ? 'bg-blue-100 border-l-4 border-blue-600' : 'border-l-4 border-transparent'
                        } ${cycle.isActive ? 'bg-blue-50/50' : ''}`}
                      onClick={() => setSelectedCycle(cycle)}
                    >
                      <div className="flex-1 overflow-hidden pr-2">
                        <div className="flex justify-between items-start mb-1">
                          <h3 className="text-sm font-semibold text-gray-900 truncate flex-1 mr-2">
                            {cycle.subject || `Request ${cycleKey}`}
                          </h3>
                          <span className="text-xs text-gray-500 flex-shrink-0">
                            {formatDistanceToNow(new Date(cycle.lastTimestamp), { addSuffix: true })}
                          </span>
                        </div>
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-xs text-gray-600 truncate">
                            {cycle.sender || 'System'} • {cycle.messages.length} event{cycle.messages.length !== 1 ? 's' : ''}
                          </p>
                          <div className="flex items-center gap-1.5">
                            {status.icon}
                            <span className={`text-xs font-medium ${status.color}`}>
                              {status.status}
                            </span>
                          </div>
                        </div>
                        <p className="text-xs text-gray-500 truncate">
                          {getCyclePreview(cycle)}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteCycle(cycleKey);
                        }}
                        className="text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full w-8 h-8 flex-shrink-0"
                        title="Delete activity"
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </ScrollArea>
        </div>

        {/* Resize Handle */}
        <div
          className="w-1.5 bg-slate-200 hover:bg-blue-500 cursor-col-resize transition-colors duration-200"
          onMouseDown={handleMouseDown}
        />

        {/* Agent Activity Log Detail Pane */}
        <div className="flex-1 bg-white flex flex-col shadow-inner relative">
          {selectedCycle ? (
            <>
              <div className="p-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-xl font-semibold text-gray-900 truncate">
                    {selectedCycle.subject || `Request ${selectedCycle.thread_id || selectedCycle.email_id}`}
                  </h2>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDeleteCycle(selectedCycle.thread_id || selectedCycle.email_id)}
                      className="text-red-500 hover:text-red-700 border-red-200 hover:bg-red-50"
                    >
                      <Trash2 size={16} className="mr-2" />
                      Delete
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedCycle(null)}
                      className="text-gray-600 hover:text-gray-800 border-gray-200 hover:bg-gray-50"
                    >
                      Close
                    </Button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-600">
                    {selectedCycle.sender || 'System'} • Updated {formatDistanceToNow(new Date(selectedCycle.lastTimestamp), { addSuffix: true })}
                  </p>
                  <div className="flex items-center gap-2">
                    {getCycleStatus(selectedCycle).icon}
                    <span className={`text-sm font-medium ${getCycleStatus(selectedCycle).color}`}>
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
                      <div
                        key={message.id}
                        className={`border-l-4 pl-4 py-3 rounded-r-lg transition-all duration-200 ${index === selectedCycle.messages.length - 1 && selectedCycle.isActive
                            ? 'border-blue-500 bg-blue-50/50'
                            : 'border-gray-200 hover:bg-gray-50/50'
                          }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          {logo && (
                            <img
                              src={logo}
                              alt={`${messageTypeLabels[message.type]} logo`}
                              className="h-5 w-5 object-contain rounded"
                            />
                          )}
                          <Badge
                            className={`${messageTypeColors[message.type] || "bg-gray-100 text-gray-800"
                              } font-medium px-2 py-1 rounded-full`}
                          >
                            {messageTypeLabels[message.type] || message.type}
                          </Badge>
                          <span className="text-xs text-gray-500">
                            {formatDistanceToNow(new Date(message.timestamp), { addSuffix: true })}
                          </span>
                          {index === selectedCycle.messages.length - 1 && selectedCycle.isActive && (
                            <Badge variant="outline" className="text-blue-600 border-blue-300 font-medium">
                              Latest
                            </Badge>
                          )}
                        </div>
                        <div
                          className="text-sm text-gray-700 leading-relaxed"
                          dangerouslySetInnerHTML={{ __html: getMessageDetails(message) }}
                        />
                      </div>
                    );
                  })}
                  {selectedCycle.isActive && (
                    <div className="border-l-4 border-blue-500 pl-4 py-3 bg-blue-50/50 rounded-r-lg">
                      <div className="flex items-center gap-2 mb-2">
                        <Loader2 size={16} className="animate-spin text-blue-500" />
                        <Badge variant="outline" className="text-blue-600 border-blue-300 font-medium">
                          Processing...
                        </Badge>
                      </div>
                      <p className="text-sm text-blue-700 font-medium">
                        Activity is in progress. New updates will appear here automatically.
                      </p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center bg-gray-50">
              <div className="text-center py-12">
                <Activity size={64} className="mx-auto mb-4 text-gray-300" />
                <h3 className="text-xl font-semibold text-gray-700 mb-2">Agent Activity Log</h3>
                <p className="text-gray-500">Select a cycle from Recent Activity to view details</p>
                <p className="text-sm text-gray-400 mt-1">
                  All messages in a cycle are grouped together like email threads
                </p>
              </div>
            </div>
          )}

          {/* Notification Container */}
          <div className="fixed bottom-6 right-6 space-y-3 pointer-events-none">
            {notifications.map((notification) => (
              <div
                key={notification.id}
                className="pointer-events-auto bg-white rounded-lg shadow-2xl border border-gray-200 w-96 p-4 transform transition-all duration-300 ease-in-out animate-slide-in hover:scale-102"
              >
                <div className="flex items-start">
                  <img
                    src={getMessageTypeLogo(notification.message) || ""}
                    alt="Outlook Logo"
                    className="h-8 w-8 object-contain rounded mt-1"
                  />
                  <div className="ml-4 flex-1">
                    <div className="flex justify-between items-center mb-2">
                      <p className="text-base font-semibold text-gray-900">New Email Detected</p>
                      <button
                        onClick={() => handleCloseNotification(notification.id)}
                        className="text-gray-500 hover:text-gray-700 focus:outline-none rounded-full p-1 hover:bg-gray-100 transition-colors"
                        aria-label="Close notification"
                      >
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                    <p className="text-sm text-gray-600 truncate">From: {notification.message.sender || "Unknown"}</p>
                    <p className="text-sm text-gray-800 font-medium truncate mt-1">
                      {notification.message.subject || "No Subject"}
                    </p>
                    {notification.message.is_valid_domain === false && (
                      <p className="text-sm text-red-600 font-medium mt-1">UNAUTHORIZED DOMAIN</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Custom Animation Styles */}
      <style>{`
        @keyframes slide-in {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        .animate-slide-in {
          animation: slide-in 0.3s ease-out;
        }
        .hover\\:scale-102:hover {
          transform: scale(1.02);
        }
      `}</style>
    </div>
  );
};

export default RequestsTracker;