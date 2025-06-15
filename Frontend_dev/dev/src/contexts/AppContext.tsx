import React, { createContext, useContext, useState, useEffect } from 'react';
import { Ticket, MetricsData, BroadcastMessage } from '@/types';
// import { useToast } from "@/components/ui/use-toast"; // REMOVE this import
import { getTickets, getStatus, connectWebSocket, addWebSocketListener } from '../lib/api';

interface CompletedCycle {
  email_id: string;
  messages: BroadcastMessage[];
  completedAt: string;
}

interface AppContextProps {
  tickets: Ticket[];
  metricsData: MetricsData;
  isAgentActive: boolean;
  showNewTicketNotification: boolean;
  currentNewTicket: Ticket | null;
  broadcastMessages: BroadcastMessage[];
  completedCycles: CompletedCycle[];
  setShowNewTicketNotification: (show: boolean) => void;
  setIsAgentActive: (active: boolean) => void;
  getTicketById: (id: string) => Ticket | undefined;
  updateTicketStatus: (id: string, status: Ticket['status']) => void;
}

const AppContext = createContext<AppContextProps | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [metricsData, setMetricsData] = useState<MetricsData>({
    totalTickets: 0,
    newTickets: 0,
    inProgressTickets: 0,
    completedTickets: 0,
    failedTickets: 0,
    autonomousCount: 0,
    semiAutonomousCount: 0,
    ticketsOverTime: [],
    topCategories: [],
  });
  const [isAgentActive, setIsAgentActive] = useState<boolean>(false);
  const [showNewTicketNotification, setShowNewTicketNotification] = useState<boolean>(false);
  const [currentNewTicket, setCurrentNewTicket] = useState<Ticket | null>(null);
  const [broadcastMessages, setBroadcastMessages] = useState<BroadcastMessage[]>([]);
  const [completedCycles, setCompletedCycles] = useState<CompletedCycle[]>([]);
  // const { toast } = useToast(); // REMOVE this line

  // Calculate metrics from tickets
  const calculateMetrics = (tickets: Ticket[]): MetricsData => {
    const now = new Date();
    const oneWeekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const ticketsLastWeek = tickets.filter(t => new Date(t.timestamps?.created || t.last_updated_on || now).getTime() >= oneWeekAgo.getTime());

    const metrics: MetricsData = {
      totalTickets: tickets.length,
      newTickets: tickets.filter(t => t.status === 'new').length,
      inProgressTickets: tickets.filter(t => t.status === 'in-progress').length,
      completedTickets: tickets.filter(t => t.status === 'completed').length,
      failedTickets: tickets.filter(t => t.status === 'failed').length,
      autonomousCount: tickets.filter(t => t.agentType === 'autonomous').length,
      semiAutonomousCount: tickets.filter(t => t.agentType === 'semi-autonomous').length,
      ticketsOverTime: Array.from({ length: 7 }, (_, i) => {
        const date = new Date(now.getTime() - (6 - i) * 24 * 60 * 60 * 1000);
        return {
          date: date.toISOString().split('T')[0],
          count: ticketsLastWeek.filter(t => {
            const created = new Date(t.timestamps?.created || t.last_updated_on || now).toISOString().split('T')[0];
            return created === date.toISOString().split('T')[0];
          }).length,
        };
      }),
      topCategories: Object.entries(
        ticketsLastWeek.reduce((acc, curr) => {
          const category = curr.type_of_request || 'Unknown';
          acc[category] = (acc[category] || 0) + 1;
          return acc;
        }, {} as Record<string, number>)
      )
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 5),
    };
    return metrics;
  };

  // Fetch backend tickets and status
  useEffect(() => {
  const fetchData = async () => {
    try {
      const [ticketsResponse, statusResponse] = await Promise.all([
        getTickets(),
        getStatus(),
      ]);

      if (ticketsResponse.status === 'success' && ticketsResponse.tickets) {
        const formattedTickets = ticketsResponse.tickets.map(ticket => ({
          ...ticket,
          id: ticket.ado_ticket_id || ticket.servicenow_sys_id || ticket.id || `TKT-${Date.now()}`,
          ado_ticket_id: ticket.ado_ticket_id,
          servicenow_sys_id: ticket.servicenow_sys_id,
          ticket_title: ticket.ticket_title || ticket.subject || 'No Subject',
          ticket_description: ticket.ticket_description || 'No description provided',
          sender: ticket.sender || 'Unknown',
          type_of_request: ticket.type_of_request || 'Unknown',
          status: ticket.status || 'new',
          requester: ticket.sender ? { name: ticket.sender, email: ticket.sender } : { name: 'Unknown', email: 'unknown@example.com' },
          emailContent: ticket.subject || '',
          timestamps: { created: ticket.last_updated_on || new Date().toISOString() },
          events: ticket.events || [],
          tags: ticket.tags || [],
          comments: ticket.comments || [],
          priority: ticket.priority || 'medium',
          agentType: ticket.agentType || 'semi-autonomous',
          pending_actions: ticket.pending_actions || false,
          updates: ticket.updates || [],
          email_chain: ticket.email_chain || [],
          details: ticket.details || {},
        }));
        setTickets(formattedTickets);
        setMetricsData(calculateMetrics(formattedTickets));
      } else {
        // toast({ // REMOVED
        //   title: "Error",
        //   description: "Failed to fetch tickets",
        //   variant: "destructive",
        // });
        console.error("Failed to fetch tickets"); // Replaced with console log
      }

      if (statusResponse.status === 'success') {
        setIsAgentActive(statusResponse.is_running);
      }
    } catch (error) {
      console.error('Error fetching data:', error);
      // toast({ // REMOVED
      //   title: "Error",
      //   description: "Failed to fetch initial data",
      //   variant: "destructive",
      // });
    }
  };

  fetchData();

    const ws = connectWebSocket();
    const unsubscribe = addWebSocketListener((data) => {
      console.log('WebSocket message received:', data);
      const message: BroadcastMessage = {
        id: `msg-${Date.now()}-${data.email_id || data.session_id || Math.random()}`,
        type: data.type,
        email_id: data.email_id,
        thread_id: data.thread_id,
        intent: data.intent,
        ado_ticket_id: data.ado_ticket_id,
        servicenow_sys_id: data.servicenow_sys_id,
        ado_url: data.ado_url,
        servicenow_url: data.servicenow_url,
        pending_actions: data.pending_actions,
        timestamp: new Date().toISOString(),
        details: { ...data },
        subject: data.subject,
        sender: data.sender,
        is_valid_domain: data.is_valid_domain,
        status: data.status,
        comment: data.comment,
        message: data.message,
      };

      // Add message to broadcastMessages
      setBroadcastMessages(prev => [message, ...prev].slice(0, 100));
      console.log('Broadcast message added:', message);

      if (data.type === 'session') {
        setIsAgentActive(data.status === 'started');
        // toast({ // REMOVED
        //   title: data.status === 'started' ? "Agent Started" : "Agent Stopped",
        //   description: `Session ID: ${data.session_id || 'N/A'}`,
        // });
        console.log(`Agent ${data.status === 'started' ? 'Started' : 'Stopped'}. Session ID: ${data.session_id || 'N/A'}`); // Replaced with console log
      } else if (data.type === 'ticket') {
        setTickets(prev => {
          const newTicket = {
            ...data.ticket,
            id: data.ticket.ado_ticket_id || data.ticket.servicenow_sys_id || data.ticket.id || `TKT-${Date.now()}`,
            status: data.ticket.status || 'new',
            requester: data.ticket.sender ? { name: data.ticket.sender, email: data.ticket.sender } : undefined,
            emailContent: data.ticket.subject || '',
            timestamps: { created: data.ticket.last_updated_on || new Date().toISOString() },
            events: data.ticket.events || [],
            tags: data.ticket.tags || [],
            comments: data.ticket.comments || [],
            priority: data.ticket.priority || 'medium',
            agentType: data.ticket.agentType || 'semi-autonomous',
            pending_actions: data.ticket.pending_actions || false,
            updates: data.ticket.updates || [],
            email_chain: data.ticket.email_chain || [],
            details: data.ticket.details || {},
          };
          const newTickets = [newTicket, ...prev.filter(t => t.ado_ticket_id !== newTicket.ado_ticket_id && t.servicenow_sys_id !== newTicket.servicenow_sys_id)];
          setMetricsData(calculateMetrics(newTickets));
          return newTickets;
        });
        setCurrentNewTicket(data.ticket);
        setShowNewTicketNotification(true);
        // toast({ // REMOVED
        //   title: "New Ticket Received",
        //   description: `Ticket: ${data.ticket.subject || 'No Subject'}`,
        // });
        console.log(`New Ticket Received: ${data.ticket.subject || 'No Subject'}`); // Replaced with console log
      } else if (['email_detected', 'intent_analyzed', 'ticket_created', 'action_performed', 'email_reply', 'monitoring_started', 'monitoring_stopped', 'permission_fixed', 'script_execution_failed'].includes(data.type)) {
        // toast({ // REMOVED
        //   title: messageTypeLabels[data.type] || data.type,
        //   description: `${data.subject || data.intent || data.message || 'Action processed'}`,
        // });
        console.log(`${messageTypeLabels[data.type] || data.type}: ${data.subject || data.intent || data.message || 'Action processed'}`); // Replaced with console log
      }
    });

    return () => {
      unsubscribe();
      ws.close();
    };
  }, [
    // toast // REMOVE this from dependency array
  ]);

  const getTicketById = (id: string) => {
    return tickets.find(ticket => ticket.id === id || ticket.ado_ticket_id === id || ticket.servicenow_sys_id === id);
  };

  const updateTicketStatus = (id: string, status: Ticket['status']) => {
    let updatedTickets: Ticket[] = []; // Temporary variable to hold the updated tickets

    setTickets(prev => {
      const newState = prev.map(ticket => {
        if (ticket.id === id || ticket.ado_ticket_id === id || ticket.servicenow_sys_id === id) {
          const statusEvent: Event = {
            id: `evt-status-${Date.now()}`,
            timestamp: new Date().toISOString(),
            description: `Ticket status changed to ${status}`,
            type: status === 'completed' ? 'agent' : 'supervisor',
          };

          const timestamps = { ...ticket.timestamps };
          if (status === 'in-progress' && !timestamps.started) {
            timestamps.started = new Date().toISOString();
          } else if (status === 'completed' && !timestamps.completed) {
            timestamps.completed = new Date().toISOString();
          }

          return {
            ...ticket,
            status,
            timestamps,
            events: [...(ticket.events || []), statusEvent],
          };
        }
        return ticket;
      });
      updatedTickets = newState; // Capture the new state for metrics calculation
      return newState;
    });

    // Calculate metrics based on the *updated* tickets array
    setMetricsData(calculateMetrics(updatedTickets));

    if (status === 'completed' || status === 'failed') {
      const ticket = updatedTickets.find(t => t.id === id || t.ado_ticket_id === id || t.servicenow_sys_id === id);
      // toast({ // REMOVED
      //   title: `Ticket ${status === 'completed' ? 'Completed' : 'Failed'}`,
      //   description: `${id}: ${ticket?.subject || 'No Subject'}`,
      //   variant: status === 'completed' ? 'default' : 'destructive',
      // });
      console.log(`Ticket ${status === 'completed' ? 'Completed' : 'Failed'}: ${id}: ${ticket?.subject || 'No Subject'}`); // Replaced with console log
    }
  };

  return (
    <AppContext.Provider
      value={{
        tickets,
        metricsData,
        isAgentActive,
        setIsAgentActive,
        showNewTicketNotification,
        setShowNewTicketNotification,
        currentNewTicket,
        broadcastMessages,
        completedCycles,
        getTicketById,
        updateTicketStatus,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};

const messageTypeLabels: Record<string, string> = {
  email_detected: "Email Detected",
  intent_analyzed: "Intent Analyzed",
  ticket_created: "Ticket Created",
  action_performed: "Action Performed",
  email_reply: "Email Reply Sent",
  monitoring_started: "Monitoring Started",
  monitoring_stopped: "Monitoring Stopped",
  permission_fixed: "Permission Fixed",
  script_execution_failed: "Script Execution Failed",
};