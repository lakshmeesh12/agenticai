import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import './App.css';

const App = () => {
  const [agentStatus, setAgentStatus] = useState('stopped');
  const [sessionId, setSessionId] = useState(null);
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [logs, setLogs] = useState([]);
  const [search, setSearch] = useState('');
  const [wsError, setWsError] = useState(null);
  const [modals, setModals] = useState([]);
  const [githubMetrics, setGithubMetrics] = useState({
    byRequestType: [],
    summary: { access: 0, revoke: 0, success: 0, pending: 0, failed: 0 }
  });

  // WebSocket connection with reconnection
  useEffect(() => {
    let ws;
    let reconnectAttempts = 0;
    const maxAttempts = 10;

    const connectWebSocket = () => {
      ws = new WebSocket('ws://localhost:8000/ws');
      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsError(null);
        reconnectAttempts = 0;
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        console.log('WebSocket message:', message);
        if (message.type === 'session') {
          setAgentStatus(message.status);
          setSessionId(message.session_id);
          const eventText = `Agent ${message.status} ${message.session_id ? `with session ID=${message.session_id}` : ''}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        } else if (message.type === 'email_detected') {
          setModals((prev) => {
            if (!prev.some((m) => m.email_id === message.email_id)) {
              return [
                ...prev,
                {
                  email_id: message.email_id,
                  steps: [{ status: 'New email arrived', details: `Subject: ${message.subject}, From: ${message.sender}` }],
                  show: true
                }
              ];
            }
            return prev;
          });
          const eventText = `New email: ${message.subject}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        } else if (message.type === 'intent_analyzed') {
          setModals((prev) =>
            prev.map((modal) =>
              modal.email_id === message.email_id
                ? {
                    ...modal,
                    steps: modal.steps.some((s) => s.status === 'Analyzing intent')
                      ? modal.steps
                      : [...modal.steps, { status: 'Analyzing intent', details: `Intent: ${message.intent}` }]
                  }
                : modal
            )
          );
          const eventText = `Analyzed intent: ${message.intent}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        } else if (message.type === 'ticket_created') {
          setModals((prev) =>
            prev.map((modal) =>
              modal.email_id === message.email_id
                ? {
                    ...modal,
                    steps: modal.steps.some((s) => s.status === 'Created ADO ticket')
                      ? modal.steps
                      : [
                          ...modal.steps,
                          {
                            status: 'Created ADO ticket',
                            details: `ID: ${message.ticket_id}, <a href="${message.ado_url}" target="_blank">View Ticket</a>`
                          }
                        ]
                  }
                : modal
            )
          );
          const eventText = `Created ADO ticket ID=${message.ticket_id} (${message.intent})`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        } else if (message.type === 'github_action') {
          setModals((prev) =>
            prev.map((modal) =>
              modal.email_id === message.email_id
                ? {
                    ...modal,
                    steps: modal.steps.some((s) => s.status === 'GitHub action')
                      ? modal.steps
                      : [
                          ...modal.steps,
                          {
                            status: 'GitHub action',
                            details: message.success ? `Completed: ${message.message}` : `Failed: ${message.message}`
                          }
                        ]
                  }
                : modal
            )
          );
          const eventText = `GitHub action for ticket ID=${message.ticket_id}: ${message.success ? 'Completed' : 'Failed'}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        } else if (message.type === 'ticket_updated') {
          setModals((prev) =>
            prev.map((modal) =>
              modal.email_id === message.email_id
                ? {
                    ...modal,
                    steps: modal.steps.some((s) => s.status === 'Updated work item')
                      ? modal.steps
                      : [
                          ...modal.steps,
                          {
                            status: 'Updated work item',
                            details: `Status: ${message.status}, Comment: ${message.comment}`
                          }
                        ]
                  }
                : modal
            )
          );
          const eventText = `Updated ticket ID=${message.ticket_id} to ${message.status}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
          setTickets((prev) =>
            prev.map((ticket) =>
              ticket.ado_ticket_id === message.ticket_id?.toString()
                ? {
                    ...ticket,
                    updates: [
                      ...ticket.updates,
                      {
                        status: message.status,
                        comment: message.comment || 'No comment provided',
                        revision_id: message.revision_id || `update-${Date.now()}`,
                        email_sent: false,
                        email_message_id: null,
                        email_timestamp: new Date().toISOString()
                      }
                    ]
                  }
                : ticket
            )
          );
        } else if (message.type === 'email_reply') {
          setModals((prev) =>
            prev.map((modal) =>
              modal.email_id === message.email_id
                ? {
                    ...modal,
                    steps: modal.steps.some((s) => s.status === 'Sent reply to user')
                      ? modal.steps
                      : [...modal.steps, { status: 'Sent reply to user', details: `Thread ID: ${message.thread_id}` }]
                  }
                : modal
            )
          );
          const eventText = `Sent email reply (thread_id=${message.thread_id})`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
          setTickets((prev) =>
            prev.map((ticket) =>
              ticket.email_id === message.email_id
                ? {
                    ...ticket,
                    updates: ticket.updates.map((update, index) =>
                      index === ticket.updates.length - 1
                        ? { ...update, email_sent: true, email_message_id: message.message_id || `reply-${Date.now()}` }
                        : update
                    )
                  }
                : ticket
            )
          );
        }
      };
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setWsError('WebSocket connection failed');
      };
      ws.onclose = () => {
        console.log('WebSocket disconnected');
        if (reconnectAttempts < maxAttempts) {
          reconnectAttempts++;
          setTimeout(connectWebSocket, 3000);
        } else {
          setWsError('WebSocket disconnected after max retries');
        }
      };
    };

    connectWebSocket();
    return () => ws && ws.close();
  }, []);

  // Fallback polling for session status
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await axios.get('http://localhost:8000/status');
        const newStatus = res.data.is_running ? 'started' : 'stopped';
        if (newStatus !== agentStatus || res.data.session_id !== sessionId) {
          setAgentStatus(newStatus);
          setSessionId(res.data.session_id);
          const eventText = `Agent ${newStatus} ${res.data.session_id ? `with session ID=${res.data.session_id}` : ''}`;
          setTimelineEvents((prev) => {
            if (!prev.some((e) => e.event === eventText)) {
              return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
            }
            return prev;
          });
        }
      } catch (error) {
        console.error('Error fetching status:', error);
        setWsError('');
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [agentStatus, sessionId]);

  // Process GitHub data for visualization
  useEffect(() => {
    const processGitHubData = () => {
      // Get all GitHub-related tickets
      const githubTickets = tickets.filter(ticket => ticket.type_of_request === 'github' && ticket.details && ticket.details.github);
      
      const typeMap = new Map();
      let accessCount = 0;
      let revokeCount = 0;
      let successCount = 0;
      let pendingCount = 0;
      let failedCount = 0;

      githubTickets.forEach(ticket => {
        if (!ticket.details || !ticket.details.github) return;
        
        ticket.details.github.forEach(request => {
          // Count by request type
          const requestType = request.request_type === 'github_access_request' ? 'Access' : 'Revoke';
          if (!typeMap.has(requestType)) {
            typeMap.set(requestType, { name: requestType, count: 0 });
          }
          typeMap.get(requestType).count += 1;
          
          // Update summary counts
          if (request.request_type === 'github_access_request') {
            accessCount++;
          } else if (request.request_type === 'github_revoke_access') {
            revokeCount++;
          }
          
          // Fix the status counting logic
          if (request.status === 'pending') {
            pendingCount++;
          } else if (request.status === 'completed' || request.status === 'revoked') {
            // Count both "completed" and "revoked" as success
            successCount++;
          } else if (request.status.includes('error') || request.status.includes('failed')) {
            failedCount++;
          } else {
            // Any other status also counted as failed for now
            failedCount++;
          }
        });
      });
      
      // Set the metrics state
      setGithubMetrics({
        byRequestType: Array.from(typeMap.values()),
        summary: {
          access: accessCount,
          revoke: revokeCount,
          success: successCount,
          pending: pendingCount,
          failed: failedCount
        }
      });
    };
    
    if (tickets && tickets.length > 0) {
      processGitHubData();
    }
  }, [tickets]);

  // Fetch tickets and logs
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [ticketsRes, logsRes] = await Promise.all([
          axios.get('http://localhost:8000/tickets'),
          axios.get('http://localhost:8000/logs')
        ]);
        console.log('Fetched tickets:', ticketsRes.data.tickets);
        setTickets(ticketsRes.data.tickets || []);
        setLogs(logsRes.data.logs || []);

        // Update timeline with ticket events, avoiding duplicates
        (ticketsRes.data.tickets || []).forEach((ticket) => {
          const ticketEvent = `Created ADO ticket ID=${ticket.ado_ticket_id}`;
          if (!timelineEvents.some((e) => e.event === ticketEvent)) {
            setTimelineEvents((prev) => [
              ...prev,
              { time: new Date().toLocaleTimeString(), event: ticketEvent }
            ]);
          }
          (ticket.updates || []).forEach((update) => {
            if (update.email_sent) {
              const replyEvent = `Sent email reply (thread_id=${ticket.thread_id})`;
              if (!timelineEvents.some((e) => e.event === replyEvent)) {
                setTimelineEvents((prev) => [
                  ...prev,
                  { time: new Date().toLocaleTimeString(), event: replyEvent }
                ]);
              }
            }
          });
        });
      } catch (error) {
        console.error('Error fetching data:', error);
        const errorEvent = `Error fetching data: ${error.message}`;
        setTimelineEvents((prev) => {
          if (!prev.some((e) => e.event === errorEvent)) {
            return [...prev, { time: new Date().toLocaleTimeString(), event: errorEvent }];
          }
          return prev;
        });
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [timelineEvents]);

  // Start or stop the agent
  const handleAgentToggle = async () => {
    try {
      const endpoint = agentStatus === 'stopped' ? '/run-agent' : '/stop-agent';
      const res = await axios.get(`http://localhost:8000${endpoint}`);
      const eventText = res.data.message;
      setTimelineEvents((prev) => {
        if (!prev.some((e) => e.event === eventText)) {
          return [...prev, { time: new Date().toLocaleTimeString(), event: eventText }];
        }
        return prev;
      });
    } catch (error) {
      console.error('Error toggling agent:', error);
      const errorEvent = `Error toggling agent: ${error.message}`;
      setTimelineEvents((prev) => {
        if (!prev.some((e) => e.event === errorEvent)) {
          return [...prev, { time: new Date().toLocaleTimeString(), event: errorEvent }];
        }
        return prev;
      });
    }
  };

  // Close a specific modal
  const closeModal = (email_id) => {
    setModals((prev) => prev.filter((modal) => modal.email_id !== email_id));
  };

  // Filter tickets based on search
  const filteredTickets = tickets.filter(
    (ticket) =>
      ticket.ado_ticket_id.toString().includes(search) ||
      (ticket.subject || '').toLowerCase().includes(search.toLowerCase())
  );

  // Colors for charts
  const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];
  
  // Custom formatter for the Legend labels
  const renderColorfulLegendText = (value, entry) => {
    const { color } = entry;
    return <span style={{ color }}>{value}</span>;
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <h1>IT Support Agent</h1>
        <nav>
          <button className="nav-link">Dashboard</button>
          <button className="nav-link">Logs</button>
        </nav>
      </header>

      {/* Modals for Workflow Notifications */}
      {modals.length > 0 && (
        <div className="modal-container">
          {modals.map((modal) => (
            <div
              key={modal.email_id}
              className="modal"
            >
              <div className="modal-content">
                <h3>Email Processing Workflow (Email ID: {modal.email_id})</h3>
                <ul>
                  {modal.steps.map((step, stepIndex) => (
                    <li key={stepIndex} className="modal-step">
                      <strong>{step.status}:</strong> <span dangerouslySetInnerHTML={{ __html: step.details }} />
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => closeModal(modal.email_id)}
                  className="modal-close"
                >
                  Close
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Main Content */}
      <div className="container">
        <div className="sidebar">
          {/* Process Timeline */}
          <div className="timeline">
            <h2>Process Timeline</h2>
            {wsError && <div className="log-error">{wsError}</div>}
            <div className="timeline-content">
              {timelineEvents.map((event, index) => (
                <div key={index} className="timeline-event">
                  <span className="timeline-time">{event.time}</span>
                  <span className="timeline-text">{event.event}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Logs Panel */}
          <div className="logs">
            <h2>Logs</h2>
            <div className="logs-content">
              {logs.map((log, index) => (
                <div key={index} className={log.includes('ERROR') ? 'log-error' : 'log-normal'}>
                  {log}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Dashboard */}
        <div className="dashboard">
          <h2>Dashboard</h2>
          <input
            type="text"
            placeholder="Search by Ticket ID or Subject"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search-input"
          />

          {/* GitHub Metrics Dashboard */}
          <div className="github-dashboard">
            <h3>GitHub Access Management Analytics</h3>
            <div className="github-charts">
              {/* Request Type Distribution */}
              <div className="chart-container">
                <h4>Request Distribution</h4>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={githubMetrics.byRequestType}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      outerRadius={70}
                      fill="#8884d8"
                      dataKey="count"
                      nameKey="name"
                    >
                      {githubMetrics.byRequestType.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend 
                      formatter={renderColorfulLegendText}
                      layout="horizontal"
                      verticalAlign="bottom"
                      align="center"
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="chart-legend">
                  <div className="legend-item">
                    <div className="legend-color" style={{ backgroundColor: '#0088FE' }}></div>
                    <span>Access: {githubMetrics.summary.access}</span>
                  </div>
                  <div className="legend-item">
                    <div className="legend-color" style={{ backgroundColor: '#00C49F' }}></div>
                    <span>Revoke: {githubMetrics.summary.revoke}</span>
                  </div>
                </div>
              </div>
              
              {/* Status Distribution */}
              <div className="chart-container">
                <h4>Request Status</h4>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'Success', value: githubMetrics.summary.success },
                        { name: 'Pending', value: githubMetrics.summary.pending },
                        { name: 'Failed', value: githubMetrics.summary.failed }
                      ]}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      outerRadius={70}
                      fill="#8884d8"
                      dataKey="value"
                      nameKey="name"
                    >
                      <Cell fill="#00C49F" />
                      <Cell fill="#FFBB28" />
                      <Cell fill="#FF8042" />
                    </Pie>
                    <Tooltip />
                    <Legend 
                      formatter={renderColorfulLegendText}
                      layout="horizontal"
                      verticalAlign="bottom"
                      align="center"
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="chart-legend">
                  <div className="legend-item">
                    <div className="legend-color" style={{ backgroundColor: '#00C49F' }}></div>
                    <span>Success: {githubMetrics.summary.success}</span>
                  </div>
                  <div className="legend-item">
                    <div className="legend-color" style={{ backgroundColor: '#FFBB28' }}></div>
                    <span>Pending: {githubMetrics.summary.pending}</span>
                  </div>
                  <div className="legend-item">
                    <div className="legend-color" style={{ backgroundColor: '#FF8042' }}></div>
                    <span>Failed: {githubMetrics.summary.failed}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Ticket Table */}
          <div className="ticket-table">
            <h3>Tickets</h3>
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {filteredTickets.map((ticket) => (
                  <tr key={ticket.ado_ticket_id}>
                    <td>{ticket.ado_ticket_id}</td>
                    <td>{ticket.subject || 'Untitled'}</td>
                    <td>{(ticket.updates && ticket.updates.length > 0) ? ticket.updates[ticket.updates.length - 1].status : 'New'}</td>
                    <td>{ticket.email_timestamp ? new Date(ticket.email_timestamp).toLocaleDateString() : 'N/A'}</td>
                    <td>{(ticket.updates && ticket.updates.length > 0) ? ticket.updates[ticket.updates.length - 1].email_timestamp.split('T')[0] : 'N/A'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Email Responses */}
          <div className="email-responses">
            <h3>Email Responses</h3>
            <ul>
              {filteredTickets
                .filter((ticket) => ticket.updates && ticket.updates.some((u) => u.email_sent))
                .map((ticket) => (
                  <li key={ticket.email_id}>
                    Thread ID: {ticket.thread_id}, Sent: {(ticket.updates.find((u) => u.email_sent) || {}).email_timestamp?.split('T')[1]?.split('.')[0] || 'N/A'}
                  </li>
                ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Agent Controls */}
      <div className="controls">
        <button
          onClick={handleAgentToggle}
          className={agentStatus === 'stopped' ? 'start-button' : 'stop-button'}
        >
          {agentStatus === 'stopped' ? 'Start Agent' : 'Stop Agent'}
        </button>
      </div>
    </div>
  );
};

export default App;