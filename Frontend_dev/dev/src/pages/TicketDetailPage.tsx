
import { useParams, useNavigate } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import { TicketDetail } from "@/components/tickets/TicketDetail";
import { Button } from "@/components/ui/button";
import { ChevronLeft } from "lucide-react";
import Navbar from "@/components/layout/Navbar";

const TicketDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const { getTicketById } = useApp();
  const navigate = useNavigate();
  
  const ticket = getTicketById(id || "");
  
  if (!ticket) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh]">
        <h2 className="text-2xl font-bold mb-2">Ticket Not Found</h2>
        <p className="text-muted-foreground mb-4">The ticket you're looking for doesn't exist.</p>
        <Button onClick={() => navigate("/tickets")}>Back to Tickets</Button>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      <Button 
        variant="outline" 
        size="sm" 
        onClick={() => navigate("/tickets")}
        className="mb-4"
      >
        <ChevronLeft className="h-4 w-4 mr-1" /> Back to Tickets
      </Button>
      
      <TicketDetail ticket={ticket} />
    </div>
  );
};

export default TicketDetailPage;
