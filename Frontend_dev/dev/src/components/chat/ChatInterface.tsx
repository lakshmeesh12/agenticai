import { useState, useRef, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Send } from "lucide-react";
import { useApp } from "@/contexts/AppContext";
import { useToast } from "@/components/ui/use-toast";
import { sendRequest } from "@/lib/api";

interface Message {
  id: string;
  content: string;
  sender: "user" | "assistant";
  timestamp: Date;
}

export const ChatInterface = () => {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      content: "Hello! I'm your IT Support Assistant. How can I help you today? You can ask about ticket statuses, search for tickets, or request specific actions.",
      sender: "assistant",
      timestamp: new Date(),
    },
  ]);
  const { toast } = useToast();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      content: input,
      sender: "user",
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    try {
      // Parse input to extract ticket ID if present
      const ticketIdMatch = input.match(/(TKT-\d+|\d+)/i);
      const ticketId = ticketIdMatch ? ticketIdMatch[0] : undefined;

      // Send request to backend
      const response = await sendRequest({ ticket_id: ticketId, request: input });

      if (response.status === "success") {
        const assistantMessage: Message = {
          id: `assistant-${Date.now()}`,
          content: response.response,
          sender: "assistant",
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } else {
        throw new Error(response.message || "Failed to process request");
      }
    } catch (error) {
      toast({
        title: "Error",
        description: `Failed to process request: ${(error as Error).message}`,
        variant: "destructive",
      });
      const errorMessage: Message = {
        id: `assistant-${Date.now()}`,
        content: "Sorry, I couldn't process your request. Please try again or contact support.",
        sender: "assistant",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSend();
    }
  };

  return (
    <Card className="h-[calc(100vh-2rem)] flex flex-col">
      <CardContent className="p-4 flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto mb-4 pr-2">
          <div className="space-y-4">
            {messages.map((message) => (
              <div 
                key={message.id} 
                className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}
              >
                <div 
                  className={`max-w-[80%] rounded-lg p-3 ${
                    message.sender === "user" 
                      ? "bg-primary text-primary-foreground" 
                      : "bg-muted"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{message.content}</p>
                  <p className="text-xs opacity-70 mt-1">
                    {message.timestamp.toLocaleTimeString()}
                  </p>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message (e.g., 'Summarize tickets' or 'Status of TKT-1001')..."
            className="flex-1"
            onKeyPress={handleKeyPress}
          />
          <Button onClick={handleSend} size="icon">
            <Send size={18} />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};