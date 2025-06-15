import { TicketsByStatusChart } from "@/components/dashboard/TicketsByStatusChart";
import { TicketsOverTimeChart } from "@/components/dashboard/TicketsOverTimeChart";
import { StatCard } from "@/components/dashboard/StatCard";
import { RecentTickets } from "@/components/dashboard/RecentTickets";
import { TopCategories } from "@/components/dashboard/TopCategories";
import { Archive, Check, Clock, AlertTriangle, Play, Users } from "lucide-react";
import { useApp } from "@/contexts/AppContext";
import { Component, ErrorInfo, ReactNode } from "react";
import Navbar from "@/components/layout/Navbar";

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
  const { metricsData } = useApp();

  const statusChartData = [
    { name: "New", value: metricsData.newTickets, color: "#3B82F6" },
    { name: "In Progress", value: metricsData.inProgressTickets, color: "#F59E0B" },
    { name: "Completed", value: metricsData.completedTickets, color: "#10B981" },
    { name: "Failed", value: metricsData.failedTickets, color: "#EF4444" },
  ];

  return (
    <div>
      <Navbar />
      <div className="p-6 space-y-6">
        <h1 className="text-3xl font-bold">Dashboard</h1>
        
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
    </div>
  );
};

export default Dashboard;