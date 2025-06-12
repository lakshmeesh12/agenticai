import { TicketsByStatusChart } from "@/components/dashboard/TicketsByStatusChart";
import { TicketsOverTimeChart } from "@/components/dashboard/TicketsOverTimeChart";
import { StatCard } from "@/components/dashboard/StatCard";
import { RecentTickets } from "@/components/dashboard/RecentTickets";
import { TopCategories } from "@/components/dashboard/TopCategories";
import { Archive, Check, Clock, AlertTriangle, Play, Users } from "lucide-react";
import { useApp } from "@/contexts/AppContext";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { runAgent, stopAgent } from "@/lib/api";
import { Component, ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(_: Error): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

const Dashboard = () => {
  const { metricsData, isAgentActive, setIsAgentActive } = useApp();
  const { toast } = useToast();

  const handleAgentToggle = async (checked: boolean) => {
    setIsAgentActive(checked);
    try {
      const response = checked ? await runAgent() : await stopAgent();
      if (response.status === 'success' || response.status === 'info') {
        toast({
          title: checked ? "Agent Started" : "Agent Stopped",
          description: response.message,
        });
      } else {
        throw new Error(response.message);
      }
    } catch (error) {
      setIsAgentActive(!checked); // Revert on error
      toast({
        title: "Error",
        description: `Failed to ${checked ? 'start' : 'stop'} agent: ${(error as Error).message}`,
        variant: "destructive",
      });
    }
  };

  const statusChartData = [
    { name: "New", value: metricsData.newTickets, color: "#3B82F6" },
    { name: "In Progress", value: metricsData.inProgressTickets, color: "#F59E0B" },
    { name: "Completed", value: metricsData.completedTickets, color: "#10B981" },
    { name: "Failed", value: metricsData.failedTickets, color: "#EF4444" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <div className="flex items-center space-x-2 bg-sidebar-accent p-2 rounded-md">
          <Label htmlFor="agent-switch" className="text-sm font-medium">Agent Active</Label>
          <Switch
            id="agent-switch"
            checked={isAgentActive}
            onCheckedChange={handleAgentToggle}
            aria-label="Toggle agent"
          />
        </div>
      </div>
      
      <div className="grid gap-6 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Tickets"
          value={metricsData.totalTickets}
          icon={<Archive size={16} />}
        />
        <StatCard
          title="Completed"
          value={metricsData.completedTickets}
          icon={<Check size={16} />}
          trend={{ value: 12, isPositive: true }}
          description="from last week"
        />
        <StatCard
          title="In Progress"
          value={metricsData.inProgressTickets}
          icon={<Clock size={16} />}
        />
        <StatCard
          title="Failed"
          value={metricsData.failedTickets}
          icon={<AlertTriangle size={16} />}
          trend={{ value: 5, isPositive: false }}
          description="from last week"
        />
      </div>
      
      <div className="grid gap-6 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Autonomous Processes"
          value={metricsData.autonomousCount}
          icon={<Play size={16} />}
          className="col-span-1 md:col-span-1 lg:col-span-2"
        />
        <StatCard
          title="Semi-Autonomous Processes"
          value={metricsData.semiAutonomousCount}
          icon={<Users size={16} />}
          className="col-span-1 md:col-span-1 lg:col-span-2"
        />
      </div>
      
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-3">
        <TicketsOverTimeChart data={metricsData.ticketsOverTime} />
        <TicketsByStatusChart data={statusChartData} />
      </div>
      
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-4">
        <ErrorBoundary
          fallback={<p className="text-red-500">Error loading recent tickets. Please try again later.</p>}
        >
          <RecentTickets />
        </ErrorBoundary>
        <TopCategories data={metricsData.topCategories} total={metricsData.totalTickets} />
      </div>
    </div>
  );
};

export default Dashboard;