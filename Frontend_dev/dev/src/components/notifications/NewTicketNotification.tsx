
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Ticket } from "@/types";

interface NewTicketNotificationProps {
  onClose: () => void;
  ticket?: Ticket;
}

const NewTicketNotification: React.FC<NewTicketNotificationProps> = ({ onClose, ticket }) => {
  const [isVisible, setIsVisible] = useState(true);

  const handleClose = () => {
    setIsVisible(false);
    setTimeout(onClose, 300); // Allow animation to complete
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      handleClose();
    }, 10000); // Auto close after 10 seconds

    return () => clearTimeout(timer);
  }, []);

  if (!ticket) {
    return null;
  }

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 w-96 bg-card border shadow-lg rounded-lg p-4 transition-opacity duration-300 ${
        isVisible ? "opacity-100" : "opacity-0"
      } animate-scale-in`}
    >
      <div className="flex justify-between items-center mb-2">
        <h3 className="font-semibold text-card-foreground flex items-center">
          <span className="w-2 h-2 bg-secondary rounded-full mr-2"></span>
          New Ticket Received
        </h3>
        <Button variant="ghost" size="icon" onClick={handleClose} className="h-6 w-6">
          <X size={16} />
        </Button>
      </div>

      <div className="mb-4">
        <div className="space-y-2">
          <div className="text-sm">
            <span className="font-medium">Subject:</span> {ticket.subject}
          </div>
          <div className="text-sm">
            <span className="font-medium">From:</span> {ticket.requester.name} ({ticket.requester.email})
          </div>
          <div className="text-sm">
            <span className="font-medium">Intent:</span> {ticket.tags.join(", ")}
          </div>
          <div className="text-sm">
            <span className="font-medium">ID:</span> {ticket.id}
          </div>
          <div className="text-sm">
            <span className="font-medium">Priority:</span> 
            <Badge variant={
                ticket.priority === 'critical' ? 'destructive' : 
                ticket.priority === 'high' ? 'default' : 
                ticket.priority === 'medium' ? 'secondary' : 
                'outline'
              } 
              className="ml-2">
              {ticket.priority}
            </Badge>
          </div>
          <div className="text-sm line-clamp-2">
            <span className="font-medium">Email:</span> 
            <p className="text-muted-foreground text-xs mt-1">{ticket.emailContent.substring(0, 100)}...</p>
          </div>
        </div>
      </div>

      <div className="flex justify-end space-x-2">
        <Button variant="outline" size="sm" onClick={handleClose}>
          Ignore
        </Button>
        <Button asChild variant="default" size="sm">
          <Link to={`/tickets/${ticket.id}`} onClick={handleClose}>
            View
          </Link>
        </Button>
      </div>
    </div>
  );
};

export default NewTicketNotification;
