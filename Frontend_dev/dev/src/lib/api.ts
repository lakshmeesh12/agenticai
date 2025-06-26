import { AdminRequest, Ticket } from "../types";

const BASE_URL = "http://localhost:8000"; // Replace with your backend URL
const WS_URL = "ws://localhost:8000/ws"; // Replace with your WebSocket URL

// Interface for API responses
interface ApiResponse<T> {
  status: "success" | "error" | "info";
  message?: string;
  query?: string;
  response?: string;
  results?: string;
  detail?: string;
  [key: string]: any;
}

// HTTP request helper
async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
    const data = await response.json();
    return data;
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    return { status: "error", message: (error as Error).message };
  }
}

// WebSocket connection
let ws: WebSocket | null = null;
const wsListeners: ((data: any) => void)[] = [];

export function connectWebSocket(): WebSocket {
  if (ws && ws.readyState === WebSocket.OPEN) {
    return ws;
  }

  ws = new WebSocket(WS_URL);
  ws.onopen = () => console.log("WebSocket connected");
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    wsListeners.forEach((listener) => listener(data));
  };
  ws.onclose = () => console.log("WebSocket disconnected");
  ws.onerror = (error) => console.error("WebSocket error:", error);

  return ws;
}

export function addWebSocketListener(listener: (data: any) => void) {
  wsListeners.push(listener);
  return () => {
    const index = wsListeners.indexOf(listener);
    if (index !== -1) wsListeners.splice(index, 1);
  };
}

export function disconnectWebSocket() {
  if (ws) {
    ws.close();
    ws = null;
  }
}

// API functions
export async function runAgent(platforms: string[] = ["ado", "servicenow"]) {
  return fetchApi<{ session_id: string }>("/run-agent", {
    method: "POST",
    body: JSON.stringify({ platforms }),
  });
}

export async function stopAgent() {
  return fetchApi<void>("/stop-agent", { method: "GET" });
}

export async function getTickets() {
  return fetchApi<{ tickets: Ticket[] }>("/tickets", { method: "GET" });
}

export async function getTicketsByType(requestType: string) {
  return fetchApi<{ tickets: Ticket[] }>(`/tickets/by-type/${encodeURIComponent(requestType)}`, {
    method: "GET",
  });
}

export async function sendRequest(queryData: { query: string }) {
  return fetchApi<{ query: string; response: string; results: string }>("/send-request", {
    method: "POST",
    body: JSON.stringify(queryData),
  });
}

export async function getLogs() {
  return fetchApi<{ logs: string[] }>("/logs", { method: "GET" });
}

export async function getStatus() {
  return fetchApi<{ is_running: boolean; session_id: string | null }>("/status", {
    method: "GET",
  });
}

export async function getRequestTypes() {
  return fetchApi<{ request_types: string[] }>("/request-types", { method: "GET" });
}