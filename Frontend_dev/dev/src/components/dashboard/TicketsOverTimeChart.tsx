
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from "recharts";
import { format, parseISO } from "date-fns";

interface TicketsOverTimeChartProps {
  data: {
    date: string;
    count: number;
  }[];
}

export const TicketsOverTimeChart: React.FC<TicketsOverTimeChartProps> = ({ data }) => {
  return (
    <Card className="col-span-2">
      <CardHeader>
        <CardTitle>Tickets Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{
                top: 5,
                right: 30,
                left: 20,
                bottom: 5,
              }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis 
                dataKey="date" 
                tickFormatter={(value) => format(parseISO(value), "MMM dd")}
              />
              <YAxis />
              <Tooltip
                labelFormatter={(value) => format(parseISO(value), "MMMM d, yyyy")}
                formatter={(value) => [`${value} tickets`, "Count"]}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#6E59A5"
                strokeWidth={2}
                activeDot={{ r: 8 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};
