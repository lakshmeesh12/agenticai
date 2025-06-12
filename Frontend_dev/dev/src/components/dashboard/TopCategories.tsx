
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface TopCategoriesProps {
  data: {
    name: string;
    count: number;
  }[];
  total: number;
}

export const TopCategories: React.FC<TopCategoriesProps> = ({ data, total }) => {
  return (
    <Card className="col-span-1">
      <CardHeader>
        <CardTitle>Top Categories</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {data.map((category) => {
            const percentage = Math.round((category.count / total) * 100);
            return (
              <div key={category.name} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{category.name}</span>
                  <span className="text-sm text-muted-foreground">
                    {category.count} ({percentage}%)
                  </span>
                </div>
                <Progress value={percentage} className="h-2" />
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
