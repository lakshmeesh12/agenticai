import { TicketsList } from "@/components/tickets/TicketsList";
import { Button } from "@/components/ui/button";
import { ChevronLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useState, useEffect } from "react";
import { getRequestTypes } from "@/lib/api";
import { useToast } from "@/components/ui/use-toast";

const TicketsPage = () => {
  const navigate = useNavigate();
  const { tickets } = useApp();
  const [requestTypes, setRequestTypes] = useState<string[]>([]);
  const [selectedType, setSelectedType] = useState<string | null>('all');
  const { toast } = useToast();

  useEffect(() => {
    const fetchRequestTypes = async () => {
      try {
        const response = await getRequestTypes();
        if (response.status === 'success') {
          setRequestTypes(response.request_types);
        } else {
          throw new Error(response.message || 'Failed to fetch request types');
        }
      } catch (error) {
        toast({
          title: "Error",
          description: `Failed to fetch request types: ${(error as Error).message}`,
          variant: "destructive",
        });
      }
    };

    fetchRequestTypes();
  }, [toast]);

  const filteredTickets = selectedType && selectedType !== 'all'
    ? tickets.filter(t => t.type_of_request === selectedType)
    : tickets;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => navigate("/")}
          className="flex items-center gap-2"
        >
          <ChevronLeft className="h-4 w-4" /> Back to Dashboard
        </Button>
        <h1 className="text-3xl font-bold">Support Tickets</h1>
        <Select 
          value={selectedType || 'all'} 
          onValueChange={(value) => setSelectedType(value === 'all' ? null : value)}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Filter by Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            {requestTypes.map(type => (
              <SelectItem key={type} value={type}>{type}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <TicketsList tickets={filteredTickets} />
    </div>
  );
};

export default TicketsPage;