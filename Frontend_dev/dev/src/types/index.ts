export type TicketStatus = 'new' | 'in-progress' | 'completed' | 'failed';
export type AgentType = 'autonomous' | 'semi-autonomous';
export type TicketPriority = 'low' | 'medium' | 'high' | 'critical';

export interface Event {
  id: string;
  timestamp: string;
  description: string;
  type: 'system' | 'agent' | 'supervisor' | 'email';
  details?: string;
}

export interface Ticket {
  id: string;
  ado_ticket_id?: string;
  servicenow_sys_id?: string;
  ticket_title: string; // Maps to subject
  ticket_description: string;
  sender: string;
  type_of_request: string;
  status: 'new' | 'in-progress' | 'completed' | 'failed';
  requester: { name: string; email: string; avatar?: string };
  emailContent: string;
  timestamps: {
    created: string;
    started?: string;
    completed?: string;
  };
  events: Event[];
  tags: string[];
  comments: Comment[];
  priority: 'low' | 'medium' | 'high' | 'critical';
  agentType: 'autonomous' | 'semi-autonomous';
  pending_actions?: boolean;
  updates: Array<{
    status: string;
    comment: string;
    email_timestamp: string;
    email_sent: boolean;
  }>;
  email_chain: Array<{
    from: string;
    subject: string;
    timestamp: string;
    body: string;
    attachments?: Array<{ filename: string; mimeType: string }>;
  }>;
  details?: {
    github?: Array<{ action: string; completed: boolean }>;
    aws?: Array<{ action: string; completed: boolean }>;
    attachments?: Array<{ filename: string; mimeType: string }>;
  };
}

export interface Comment {
  id: string;
  author: string;
  timestamp: string;
  content: string;
}


export interface MetricsData {
  totalTickets: number;
  newTickets: number;
  inProgressTickets: number;
  completedTickets: number;
  failedTickets: number;
  autonomousCount: number;
  semiAutonomousCount: number;
  ticketsOverTime: {
    date: string;
    count: number;
  }[];
  topCategories: {
    name: string;
    count: number;
  }[];
}

export interface AdminRequest {
  ticket_id?: string;
  request: string;
}

export interface BroadcastMessage {
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
}