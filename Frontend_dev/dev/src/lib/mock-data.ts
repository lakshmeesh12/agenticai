
import { Ticket, MetricsData } from '../types';

export const mockTickets: Ticket[] = [
  {
    id: "TKT-1001",
    subject: "GitHub Repository Access Request",
    requester: {
      name: "John Smith",
      email: "john.smith@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=John",
    },
    timestamps: {
      created: "2025-05-18T09:23:45Z",
      started: "2025-05-18T09:24:02Z",
      completed: "2025-05-18T09:31:15Z",
    },
    status: "completed",
    agentType: "autonomous",
    priority: "medium",
    emailContent: "Hello IT Support,\n\nI need access to the 'frontend-components' GitHub repository for my new project. My GitHub username is jsmith123.\n\nThanks,\nJohn",
    events: [
      {
        id: "evt-001",
        timestamp: "2025-05-18T09:23:45Z",
        description: "Email received and converted to ticket",
        type: "system",
      },
      {
        id: "evt-002",
        timestamp: "2025-05-18T09:24:02Z", 
        description: "Agent started processing ticket",
        type: "agent",
      },
      {
        id: "evt-003",
        timestamp: "2025-05-18T09:24:15Z",
        description: "Extracted GitHub username: jsmith123",
        type: "agent",
      },
      {
        id: "evt-004",
        timestamp: "2025-05-18T09:25:30Z",
        description: "Verified user identity in Active Directory",
        type: "agent",
      },
      {
        id: "evt-005",
        timestamp: "2025-05-18T09:26:45Z",
        description: "Added user to GitHub team 'frontend-developers'",
        type: "agent",
        details: "API Response: Successfully added user to team",
      },
      {
        id: "evt-006",
        timestamp: "2025-05-18T09:28:10Z",
        description: "Granted repository access to 'frontend-components'",
        type: "agent",
      },
      {
        id: "evt-007",
        timestamp: "2025-05-18T09:30:00Z",
        description: "Sent confirmation email to requester",
        type: "agent",
      },
      {
        id: "evt-008",
        timestamp: "2025-05-18T09:31:15Z",
        description: "Process completed successfully",
        type: "agent",
      },
    ],
    tags: ["github", "access-request", "repository"],
    comments: [],
  },
  {
    id: "TKT-1002",
    subject: "Software Installation Request for Adobe Creative Suite",
    requester: {
      name: "Emma Johnson",
      email: "emma.j@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Emma",
    },
    timestamps: {
      created: "2025-05-18T11:15:22Z",
      started: "2025-05-18T11:16:01Z",
    },
    status: "in-progress",
    agentType: "semi-autonomous",
    priority: "high",
    emailContent: "Hi IT Team,\n\nI need Adobe Creative Suite installed on my workstation for the new marketing project. This is approved by my manager Alex Rodriguez.\n\nThanks,\nEmma Johnson\nMarketing Department",
    events: [
      {
        id: "evt-101",
        timestamp: "2025-05-18T11:15:22Z",
        description: "Email received and converted to ticket",
        type: "system",
      },
      {
        id: "evt-102",
        timestamp: "2025-05-18T11:16:01Z",
        description: "Agent started processing ticket",
        type: "agent",
      },
      {
        id: "evt-103",
        timestamp: "2025-05-18T11:16:30Z",
        description: "Identified software: Adobe Creative Suite",
        type: "agent",
      },
      {
        id: "evt-104",
        timestamp: "2025-05-18T11:17:45Z",
        description: "Checked license availability: 3 licenses available",
        type: "agent",
      },
      {
        id: "evt-105",
        timestamp: "2025-05-18T11:19:20Z",
        description: "Budget approval required. Waiting for supervisor approval.",
        type: "agent",
      },
      {
        id: "evt-106",
        timestamp: "2025-05-18T11:35:15Z", 
        description: "Supervisor approved license allocation",
        type: "supervisor",
        details: "Approved by: IT Admin"
      },
      {
        id: "evt-107",
        timestamp: "2025-05-18T11:36:22Z",
        description: "Installation scheduled for workstation MKT-WS-042",
        type: "agent",
      },
    ],
    tags: ["software-installation", "adobe", "license"],
    comments: [
      {
        id: "cmt-001",
        author: "IT Admin",
        timestamp: "2025-05-18T11:40:30Z",
        content: "License allocated. Installation will be completed by EOD."
      }
    ],
  },
  {
    id: "TKT-1003",
    subject: "Password Reset Request",
    requester: {
      name: "Michael Chen",
      email: "m.chen@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Michael",
    },
    timestamps: {
      created: "2025-05-19T08:05:11Z",
      started: "2025-05-19T08:05:30Z",
      completed: "2025-05-19T08:08:45Z",
    },
    status: "completed",
    agentType: "autonomous",
    priority: "high",
    emailContent: "Hello,\n\nI forgot my password and need it reset ASAP. I have an important meeting in 15 minutes.\n\nRegards,\nMichael Chen",
    events: [
      {
        id: "evt-201",
        timestamp: "2025-05-19T08:05:11Z",
        description: "Email received and converted to ticket",
        type: "system",
      },
      {
        id: "evt-202",
        timestamp: "2025-05-19T08:05:30Z",
        description: "Agent started processing ticket",
        type: "agent",
      },
      {
        id: "evt-203",
        timestamp: "2025-05-19T08:05:45Z",
        description: "Identified request type: Password Reset",
        type: "agent",
      },
      {
        id: "evt-204",
        timestamp: "2025-05-19T08:06:20Z",
        description: "Verified user identity via secondary authentication",
        type: "agent",
      },
      {
        id: "evt-205",
        timestamp: "2025-05-19T08:07:10Z",
        description: "Generated temporary password",
        type: "agent",
      },
      {
        id: "evt-206",
        timestamp: "2025-05-19T08:07:30Z",
        description: "Sent temporary password to user's registered mobile",
        type: "agent",
      },
      {
        id: "evt-207",
        timestamp: "2025-05-19T08:08:45Z",
        description: "Process completed successfully",
        type: "agent",
      },
    ],
    tags: ["password-reset", "urgent", "completed"],
    comments: [],
  },
  {
    id: "TKT-1004",
    subject: "VPN Access Request",
    requester: {
      name: "Sarah Williams",
      email: "s.williams@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Sarah",
    },
    timestamps: {
      created: "2025-05-19T09:35:40Z",
      started: "2025-05-19T09:36:15Z",
    },
    status: "failed",
    agentType: "semi-autonomous",
    priority: "medium",
    emailContent: "Dear IT Support,\n\nI need VPN access set up for my upcoming business trip to London next week. I'll be there from May 25-30.\n\nBest regards,\nSarah Williams\nSales Department",
    events: [
      {
        id: "evt-301",
        timestamp: "2025-05-19T09:35:40Z",
        description: "Email received and converted to ticket",
        type: "system",
      },
      {
        id: "evt-302",
        timestamp: "2025-05-19T09:36:15Z",
        description: "Agent started processing ticket",
        type: "agent",
      },
      {
        id: "evt-303",
        timestamp: "2025-05-19T09:36:45Z",
        description: "Identified request: International VPN access",
        type: "agent",
      },
      {
        id: "evt-304",
        timestamp: "2025-05-19T09:37:30Z",
        description: "Checking security clearance for international access",
        type: "agent",
      },
      {
        id: "evt-305",
        timestamp: "2025-05-19T09:39:15Z",
        description: "Error: Unable to verify security clearance level",
        type: "agent",
        details: "Error code: SEC-143: User not found in security clearance database",
      },
      {
        id: "evt-306",
        timestamp: "2025-05-19T09:39:20Z",
        description: "Process failed - manual intervention required",
        type: "agent",
      },
    ],
    tags: ["vpn", "international", "failed"],
    comments: [
      {
        id: "cmt-101",
        author: "IT Admin",
        timestamp: "2025-05-19T10:15:22Z",
        content: "Need to verify with Security team why user is missing from clearance database."
      }
    ],
  },
  {
    id: "TKT-1005",
    subject: "New Email Distribution List Request",
    requester: {
      name: "Daniel Garcia",
      email: "d.garcia@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Daniel",
    },
    timestamps: {
      created: "2025-05-19T14:22:08Z",
    },
    status: "new",
    agentType: "semi-autonomous",
    priority: "low",
    emailContent: "Hello IT,\n\nCould you please create a new email distribution list for the Product Innovation team? We need it to include the following members:\n- myself\n- j.wilson@company.com\n- a.patel@company.com\n- r.thompson@company.com\n\nThe list should be named 'product-innovation'.\n\nThanks,\nDaniel Garcia\nProduct Manager",
    events: [
      {
        id: "evt-401",
        timestamp: "2025-05-19T14:22:08Z",
        description: "Email received and converted to ticket",
        type: "system",
      },
    ],
    tags: ["email", "distribution-list", "exchange"],
    comments: [],
  },
];

export const mockMetricsData: MetricsData = {
  totalTickets: 38,
  newTickets: 5,
  inProgressTickets: 12,
  completedTickets: 18,
  failedTickets: 3,
  autonomousCount: 22,
  semiAutonomousCount: 16,
  ticketsOverTime: [
    { date: "2025-05-13", count: 4 },
    { date: "2025-05-14", count: 6 },
    { date: "2025-05-15", count: 8 },
    { date: "2025-05-16", count: 7 },
    { date: "2025-05-17", count: 3 },
    { date: "2025-05-18", count: 5 },
    { date: "2025-05-19", count: 5 },
  ],
  topCategories: [
    { name: "Access Request", count: 12 },
    { name: "Software Installation", count: 8 },
    { name: "Password Reset", count: 7 },
    { name: "Network Issues", count: 5 },
    { name: "Email Configuration", count: 4 },
  ],
};

export const generateNewTicket = (id: string): Ticket => {
  return {
    id: id,
    subject: "New Hardware Request",
    requester: {
      name: "Alex Taylor",
      email: "a.taylor@company.com",
      avatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Alex",
    },
    timestamps: {
      created: new Date().toISOString(),
    },
    status: "new",
    agentType: "semi-autonomous",
    priority: "medium",
    emailContent: "Hi IT Team,\n\nI would like to request a new monitor for my workstation. My current one is showing display issues.\n\nThanks,\nAlex Taylor\nDevelopment Team",
    events: [
      {
        id: `evt-${id}-1`,
        timestamp: new Date().toISOString(),
        description: "Email received and converted to ticket",
        type: "system",
      },
    ],
    tags: ["hardware", "monitor", "request"],
    comments: [],
  };
};
