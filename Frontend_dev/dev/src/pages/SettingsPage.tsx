
import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";

const SettingsPage = () => {
  const [emailSettings, setEmailSettings] = useState({
    emailPollingEnabled: true,
    pollingInterval: 5,
    emailAddress: "it-support@company.com",
  });
  
  const [notificationSettings, setNotificationSettings] = useState({
    newTicketNotifications: true,
    statusChangeNotifications: true,
    failedProcessNotifications: true,
    emailNotifications: false,
  });
  
  const { toast } = useToast();
  
  const handleSave = () => {
    toast({
      title: "Settings Saved",
      description: "Your settings have been updated successfully.",
    });
  };
  
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Settings</h1>
      
      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="email">Email Integration</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
        </TabsList>
        
        <TabsContent value="general" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Agent Settings</CardTitle>
              <CardDescription>Configure how the agent processes support requests.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="auto-processing">Automatic Request Processing</Label>
                <Switch id="auto-processing" defaultChecked />
              </div>
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="error-retry">Auto-retry Failed Processes</Label>
                <Switch id="error-retry" defaultChecked />
              </div>
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="approval-workflow">Require Approvals for Semi-Autonomous Tasks</Label>
                <Switch id="approval-workflow" defaultChecked />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="email" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Email Integration</CardTitle>
              <CardDescription>Configure email-to-ticket conversion settings.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="email-polling">Email Polling</Label>
                <Switch 
                  id="email-polling" 
                  checked={emailSettings.emailPollingEnabled}
                  onCheckedChange={(checked) => setEmailSettings({...emailSettings, emailPollingEnabled: checked})}
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="polling-interval">Polling Interval (minutes)</Label>
                <Input 
                  id="polling-interval" 
                  type="number" 
                  min="1" 
                  max="60"
                  value={emailSettings.pollingInterval}
                  onChange={(e) => setEmailSettings({...emailSettings, pollingInterval: parseInt(e.target.value)})}
                  disabled={!emailSettings.emailPollingEnabled}
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="email-address">Support Email Address</Label>
                <Input 
                  id="email-address" 
                  value={emailSettings.emailAddress}
                  onChange={(e) => setEmailSettings({...emailSettings, emailAddress: e.target.value})}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        
        <TabsContent value="notifications" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Notification Settings</CardTitle>
              <CardDescription>Configure when and how you receive notifications.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="new-ticket-notif">New Ticket Notifications</Label>
                <Switch 
                  id="new-ticket-notif" 
                  checked={notificationSettings.newTicketNotifications}
                  onCheckedChange={(checked) => setNotificationSettings({
                    ...notificationSettings, 
                    newTicketNotifications: checked
                  })}
                />
              </div>
              
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="status-change-notif">Status Change Notifications</Label>
                <Switch 
                  id="status-change-notif" 
                  checked={notificationSettings.statusChangeNotifications}
                  onCheckedChange={(checked) => setNotificationSettings({
                    ...notificationSettings, 
                    statusChangeNotifications: checked
                  })}
                />
              </div>
              
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="failed-process-notif">Failed Process Notifications</Label>
                <Switch 
                  id="failed-process-notif" 
                  checked={notificationSettings.failedProcessNotifications}
                  onCheckedChange={(checked) => setNotificationSettings({
                    ...notificationSettings, 
                    failedProcessNotifications: checked
                  })}
                />
              </div>
              
              <div className="flex items-center justify-between space-x-2">
                <Label htmlFor="email-notif">Email Notifications</Label>
                <Switch 
                  id="email-notif" 
                  checked={notificationSettings.emailNotifications}
                  onCheckedChange={(checked) => setNotificationSettings({
                    ...notificationSettings, 
                    emailNotifications: checked
                  })}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      
      <div className="flex justify-end">
        <Button onClick={handleSave}>Save Settings</Button>
      </div>
    </div>
  );
};

export default SettingsPage;
