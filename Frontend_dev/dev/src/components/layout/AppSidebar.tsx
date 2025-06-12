
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger
} from "@/components/ui/sidebar";
import { Database, MessageSquare, Settings, User, Archive } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useApp } from "@/contexts/AppContext";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function AppSidebar() {
  const { isAgentActive, setIsAgentActive } = useApp();
  const location = useLocation();
  
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="flex items-center justify-between p-4">
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 rounded-full bg-primary flex items-center justify-center text-primary-foreground font-bold">
            IT
          </div>
          <h1 className="text-xl font-bold">IT Agent</h1>
        </div>
        <SidebarTrigger />
      </SidebarHeader>
      
      <SidebarContent>
        <TooltipProvider delayDuration={300}>
          <SidebarMenu>
            <SidebarMenuItem>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SidebarMenuButton 
                    asChild 
                    tooltip="Dashboard"
                    isActive={location.pathname === "/"}
                  >
                    <Link to="/">
                      <Database size={24} />
                      <span>Dashboard</span>
                    </Link>
                  </SidebarMenuButton>
                </TooltipTrigger>
                <TooltipContent side="right">Dashboard</TooltipContent>
              </Tooltip>
            </SidebarMenuItem>
            
            <SidebarMenuItem>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SidebarMenuButton 
                    asChild 
                    tooltip="Tickets"
                    isActive={location.pathname.startsWith("/tickets")}
                  >
                    <Link to="/tickets">
                      <Archive size={24} />
                      <span>Tickets</span>
                    </Link>
                  </SidebarMenuButton>
                </TooltipTrigger>
                <TooltipContent side="right">Tickets</TooltipContent>
              </Tooltip>
            </SidebarMenuItem>
            
            <SidebarMenuItem>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SidebarMenuButton 
                    asChild 
                    tooltip="Chat Assistant"
                    isActive={location.pathname === "/chat"}
                  >
                    <Link to="/chat">
                      <MessageSquare size={24} />
                      <span>Chat Assistant</span>
                    </Link>
                  </SidebarMenuButton>
                </TooltipTrigger>
                <TooltipContent side="right">Chat Assistant</TooltipContent>
              </Tooltip>
            </SidebarMenuItem>
            
            <SidebarMenuItem>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SidebarMenuButton 
                    asChild 
                    tooltip="Settings"
                    isActive={location.pathname === "/settings"}
                  >
                    <Link to="/settings">
                      <Settings size={24} />
                      <span>Settings</span>
                    </Link>
                  </SidebarMenuButton>
                </TooltipTrigger>
                <TooltipContent side="right">Settings</TooltipContent>
              </Tooltip>
            </SidebarMenuItem>
          </SidebarMenu>
        </TooltipProvider>
      </SidebarContent>
      
      <SidebarFooter>
        <div className="px-4 py-2">
          <div className="flex items-center gap-2 p-2">
            <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center">
              <User size={24} className="p-1.5" />
            </div>
            <div className="text-sm">
              <p className="font-medium">IT Supervisor</p>
              <p className="text-muted-foreground text-xs">supervisor@company.com</p>
            </div>
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
