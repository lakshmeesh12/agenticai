
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppProvider } from "./contexts/AppContext";
import { useApp } from "./contexts/AppContext";
import { MainLayout } from "./components/layout/MainLayout";
import Index from "./pages/Index";
import TicketsPage from "./pages/TicketsPage";
import TicketDetailPage from "./pages/TicketDetailPage";
import ChatPage from "./pages/ChatPage";
import SettingsPage from "./pages/SettingsPage";
import { RequestsTracker } from "./pages/RequestsTracker"; // New import
import NotFound from "./pages/NotFound";
import NewTicketNotification from "./components/notifications/NewTicketNotification";

const queryClient = new QueryClient();

function AppRoutes() {
  const { showNewTicketNotification, setShowNewTicketNotification, currentNewTicket } = useApp();

  return (
    <>
      {showNewTicketNotification && currentNewTicket && (
        <NewTicketNotification 
          onClose={() => setShowNewTicketNotification(false)}
          ticket={currentNewTicket}
        />
      )}
      <MainLayout>
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/tickets" element={<TicketsPage />} />
          <Route path="/tickets/:id" element={<TicketDetailPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
          <Route path="/requests-tracker" element={<RequestsTracker />} />
        </Routes>
      </MainLayout>
    </>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <AppProvider>
        <Toaster />
        <Sonner position="top-right" />
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AppProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
