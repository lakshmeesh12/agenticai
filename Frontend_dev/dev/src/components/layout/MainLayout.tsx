
import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "./AppSidebar";
import { useApp } from "@/contexts/AppContext";

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const { showNewTicketNotification, setShowNewTicketNotification, currentNewTicket } = useApp();
  
  return (
    <SidebarProvider defaultOpen={true}>
      <div className="min-h-screen flex w-full relative bg-background">
        <AppSidebar />
        <main className="flex-1 p-0 pl-0 overflow-auto">
          <div className="container mx-auto py-6 max-w-7xl">
            {children}
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
