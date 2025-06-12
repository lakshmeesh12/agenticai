import { Ticket } from "@/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDistanceToNow } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Link } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";

const statusColors: Record<string, string> = {
  new: "bg-blue-100 text-blue-800",
  "in-progress": "bg-amber-100 text-amber-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  unknown: "bg-gray-100 text-gray-800",
};

const agentTypeColors: Record<string, string> = {
  autonomous: "bg-purple-100 text-purple-800",
  "semi-autonomous": "bg-indigo-100 text-indigo-800",
  unknown: "bg-gray-100 text-gray-800",
};

export const RecentTickets = () => {
  const { tickets } = useApp();
  // Sort by creation date and take the 5 most recent
  const recentTickets = tickets
    .sort((a, b) => {
      const dateA = new Date(a.timestamps?.created || a.last_updated_on || 0);
      const dateB = new Date(b.timestamps?.created || b.last_updated_on || 0);
      return dateB.getTime() - dateA.getTime();
    })
    .slice(0, 5);

  return (
    <Card className="col-span-3">
      <CardHeader>
        <CardTitle>Recent Tickets</CardTitle>
      </CardHeader>
      <CardContent>
        {recentTickets.length === 0 ? (
          <p className="text-muted-foreground">No recent tickets available.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Requester</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentTickets.map((ticket) => {
                const ticketId = ticket.id || ticket.ado_ticket_id || ticket.servicenow_sys_id || "Unknown";
                const status = ticket.status || "unknown";
                const agentType = ticket.agentType || "unknown";
                const requesterName = ticket.requester?.name || ticket.sender || "Unknown";
                const createdDate = ticket.timestamps?.created || ticket.last_updated_on || new Date().toISOString();

                return (
                  <TableRow key={ticketId}>
                    <TableCell className="font-medium">
                      <Link to={`/tickets/${ticketId}`} className="text-primary hover:underline">
                        {ticketId}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link to={`/tickets/${ticketId}`} className="hover:underline">
                        {ticket.subject || "No Subject"}
                      </Link>
                    </TableCell>
                    <TableCell>{requesterName}</TableCell>
                    <TableCell>
                      <Badge className={statusColors[status]}>
                        {status.charAt(0).toUpperCase() + status.slice(1)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={agentTypeColors[agentType]}>
                        {agentType === "autonomous" ? "Auto" : agentType === "semi-autonomous" ? "Semi-Auto" : "Unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {formatDistanceToNow(new Date(createdDate), { addSuffix: true })}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
};