
import { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { Ticket } from "@/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDistanceToNow } from "date-fns";
import { Input } from "@/components/ui/input";
import { Search, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Link } from "react-router-dom";

const statusColors = {
  "new": "bg-blue-100 text-blue-800",
  "in-progress": "bg-amber-100 text-amber-800",
  "completed": "bg-green-100 text-green-800",
  "failed": "bg-red-100 text-red-800",
};

const agentTypeColors = {
  "autonomous": "bg-purple-100 text-purple-800",
  "semi-autonomous": "bg-indigo-100 text-indigo-800",
};

export const TicketsList = () => {
  const { tickets } = useApp();
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [agentFilter, setAgentFilter] = useState<string>("all");

  const filteredTickets = tickets.filter((ticket) => {
    // Apply search filter
    const matchesSearch =
      searchTerm === "" ||
      ticket.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      ticket.subject.toLowerCase().includes(searchTerm.toLowerCase()) ||
      ticket.requester.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      ticket.requester.email.toLowerCase().includes(searchTerm.toLowerCase());

    // Apply status filter
    const matchesStatus = statusFilter === "all" || ticket.status === statusFilter;

    // Apply agent filter
    const matchesAgent = agentFilter === "all" || ticket.agentType === agentFilter;

    return matchesSearch && matchesStatus && matchesAgent;
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search tickets..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10"
          />
        </div>
        <div className="flex gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="new">New</SelectItem>
              <SelectItem value="in-progress">In Progress</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
          
          <Select value={agentFilter} onValueChange={setAgentFilter}>
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="Agent Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="autonomous">Autonomous</SelectItem>
              <SelectItem value="semi-autonomous">Semi-Auto</SelectItem>
            </SelectContent>
          </Select>
          
          <Button variant="outline" size="icon" className="shrink-0">
            <Filter className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[100px]">ID</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Requester</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Agent Type</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Priority</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredTickets.length > 0 ? (
              filteredTickets.map((ticket) => (
                <TableRow key={ticket.id}>
                  <TableCell className="font-medium">
                    <Link to={`/tickets/${ticket.id}`} className="text-primary hover:underline">
                      {ticket.id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link to={`/tickets/${ticket.id}`} className="hover:underline">
                      {ticket.subject}
                    </Link>
                  </TableCell>
                  <TableCell>{ticket.requester.name}</TableCell>
                  <TableCell>
                    <Badge className={statusColors[ticket.status]}>
                      {ticket.status.charAt(0).toUpperCase() + ticket.status.slice(1)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge className={agentTypeColors[ticket.agentType]}>
                      {ticket.agentType === "autonomous" ? "Auto" : "Semi-Auto"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {formatDistanceToNow(new Date(ticket.timestamps.created), { addSuffix: true })}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge
                      variant={
                        ticket.priority === "critical"
                          ? "destructive"
                          : ticket.priority === "high"
                          ? "outline"
                          : "secondary"
                      }
                    >
                      {ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                  No tickets found matching your filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
};
