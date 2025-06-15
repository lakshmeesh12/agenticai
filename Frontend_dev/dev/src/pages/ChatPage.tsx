import { ChatInterface } from "@/components/chat/ChatInterface";
import { useToast } from "@/components/ui/use-toast";
import Navbar from "@/components/layout/Navbar";

const ChatPage = () => {
  const { toast } = useToast();

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Chat Assistant</h1>
      <p className="text-muted-foreground mb-4">Ask the assistant about tickets...</p>
      <ChatInterface />
    </div>
  );
};

export default ChatPage;