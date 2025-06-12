import { useState } from "react";
import { Ticket as TicketType, Event } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDistanceToNow, format } from "date-fns";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
import { useApp } from "@/contexts/AppContext";

const statusColors = {
  "new": "bg-blue-100 text-blue-800",
  "in-progress": "bg-amber-100 text-amber-800",
  "completed": "bg-green-100 text-green-800",
  "failed": "bg-red-100 text-red-800",
};

const agentTypeColors = {
  "autonomous": "bg-purple-100 text-purple-800",
  "semi-autonomous": "bg-indigo-100 text-indigo-800",
};

const eventTypeIcons = {
  "system": "🔄",
  "agent": "🤖",
  "supervisor": "👤",
  "email": "📧",
};

interface TicketDetailProps {
  ticket: TicketType;
}

export const TicketDetail: React.FC<TicketDetailProps> = ({ ticket }) => {
  const [comment, setComment] = useState("");
  const { toast } = useToast();
  const { updateTicketStatus } = useApp();

  const handleAddComment = () => {
    if (comment.trim()) {
      toast({
        title: "Comment Added",
        description: "Your comment has been added to the ticket.",
      });
      setComment("");
    }
  };

  const handleChangeStatus = (status: TicketType["status"]) => {
    updateTicketStatus(ticket.id, status);
    toast({
      title: "Status Updated",
      description: `Ticket status changed to ${status}.`,
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{ticket.ticket_title}</h1>
          <div className="flex flex-wrap gap-2 mt-2">
            <Badge className={statusColors[ticket.status]}>
              {ticket.status.charAt(0).toUpperCase() + ticket.status.slice(1)}
            </Badge>
            <Badge className={agentTypeColors[ticket.agentType]}>
              {ticket.agentType === "autonomous" ? "Autonomous" : "Semi-Autonomous"}
            </Badge>
            {ticket.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          {ticket.status !== "in-progress" && ticket.status !== "completed" && (
            <Button onClick={() => handleChangeStatus("in-progress")}>
              Start Processing
            </Button>
          )}
          {ticket.status === "in-progress" && (
            <>
              <Button onClick={() => handleChangeStatus("completed")}>
                Mark Completed
              </Button>
              <Button
                variant="destructive"
                onClick={() => handleChangeStatus("failed")}
              >
                Mark Failed
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Ticket Details</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="description">
              <TabsList className="mb-4">
                <TabsTrigger value="description">Description</TabsTrigger>
                <TabsTrigger value="actions">Actions</TabsTrigger>
                <TabsTrigger value="updates">Updates</TabsTrigger>
                <TabsTrigger value="email">Email Chain</TabsTrigger>
                <TabsTrigger value="comments">Comments</TabsTrigger>
              </TabsList>

              <TabsContent value="description" className="space-y-4">
                <Card>
                  <CardContent className="pt-6">
                    <h4 className="text-lg font-semibold mb-2">Description</h4>
                    <p className="text-sm">{ticket.ticket_description}</p>
                    <h4 className="text-lg font-semibold mt-4">Details</h4>
                    <p className="text-sm">Type: {ticket.type_of_request}</p>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="actions" className="space-y-4">
                <Card>
                  <CardContent className="pt-6">
                    {ticket.details?.github && (
                      <div className="mb-4">
                        <h4 className="text-lg font-semibold">GitHub Actions</h4>
                        <ul className="list-disc pl-5 text-sm">
                          {ticket.details.github.map((action, index) => (
                            <li key={index}>
                              {action.action
                                .replace("github_", "")
                                .replace("_", " ")
                                .toUpperCase()}
                              : {action.completed ? "Completed" : "Pending"}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {ticket.details?.aws && (
                      <div className="mb-4">
                        <h4 className="text-lg font-semibold">AWS Actions</h4>
                        <ul className="list-disc pl-5 text-sm">
                          {ticket.details.aws.map((action, index) => (
                            <li key={index}>
                              {action.action
                                .replace("aws_", "")
                                .replace("_", " ")
                                .toUpperCase()}
                              : {action.completed ? "Completed" : "Pending"}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {ticket.details?.attachments && (
                      <div>
                        <h4 className="text-lg font-semibold">Attachments</h4>
                        <ul className="list-disc pl-5 text-sm">
                          {ticket.details.attachments.map((attachment, index) => (
                            <li key={index}>
                              {attachment.filename} ({attachment.mimeType})
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="updates" className="space-y-4">
                <Card>
                  <CardContent className="pt-6">
                    {ticket.updates.length > 0 ? (
                      ticket.updates.map((update, index) => (
                        <div
                          key={index}
                          className="border-l-2 pl-4 pb-4 relative"
                        >
                          <div className="absolute -left-2 top-0 w-4 h-4 rounded-full bg-background border-2 border-primary"></div>
                          <p className="text-sm text-muted-foreground">
                            {format(
                              new Date(update.email_timestamp),
                              "MMM d, yyyy HH:mm:ss"
                            )}
                          </p>
                          <p className="font-medium">Status: {update.status}</p>
                          <p className="text-sm">Comment: {update.comment}</p>
                          <p className="text-sm">
                            Email Sent: {update.email_sent ? "Yes" : "No"}
                          </p>
                        </div>
                      ))
                    ) : (
                      <p className="text-muted-foreground">No updates available.</p>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="email" className="space-y-4">
                <Card>
                  <CardContent className="pt-6">
                    {ticket.email_chain.length > 0 ? (
                      ticket.email_chain.map((email, index) => (
                        <div key={index} className="border-l-2 pl-4 pb-4 relative">
                          <div className="absolute -left-2 top-0 w-4 h-4 rounded-full bg-background border-2 border-primary"></div>
                          <p className="text-sm font-medium">From: {email.from}</p>
                          <p className="text-sm font-medium">Subject: {email.subject}</p>
                          <p className="text-sm text-muted-foreground">
                            {format(
                              new Date(parseInt(email.timestamp)),
                              "MMM d, yyyy HH:mm:ss"
                            )}
                          </p>
                          <p className="text-sm mt-2">{email.body}</p>
                          {email.attachments?.length > 0 && (
                            <div className="mt-2">
                              <p className="text-sm font-medium">Attachments:</p>
                              <ul className="list-disc pl-5 text-sm">
                                {email.attachments.map((attachment, idx) => (
                                  <li key={idx}>
                                    {attachment.filename} ({attachment.mimeType})
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <p className="text-muted-foreground">No email chain available.</p>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="comments">
                <div className="space-y-4">
                  {ticket.comments.length > 0 ? (
                    ticket.comments.map((comment) => (
                      <div key={comment.id} className="bg-muted rounded-lg p-3">
                        <div className="flex justify-between">
                          <p className="font-medium">{comment.author}</p>
                          <p className="text-sm text-muted-foreground">
                            {format(
                              new Date(comment.timestamp),
                              "MMM d, yyyy HH:mm:ss"
                            )}
                          </p>
                        </div>
                        <p className="mt-1">{comment.content}</p>
                      </div>
                    ))
                  ) : (
                    <p className="text-muted-foreground">No comments yet.</p>
                  )}

                  <div className="space-y-2 pt-4 border-t">
                    <Textarea
                      placeholder="Add a comment..."
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                    />
                    <Button onClick={handleAddComment}>Add Comment</Button>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Requester</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full overflow-hidden">
                  {ticket.requester.avatar ? (
                    <img
                      src={ticket.requester.avatar}
                      alt={ticket.requester.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full bg-primary flex items-center justify-center text-primary-foreground">
                      {ticket.requester.name.charAt(0)}
                    </div>
                  )}
                </div>
                <div>
                  <p className="font-medium">{ticket.requester.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {ticket.requester.email}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Timestamps</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex justify-between">
                  <p className="text-sm text-muted-foreground">Created:</p>
                  <p className="text-sm">
                    {formatDistanceToNow(new Date(ticket.timestamps.created), {
                      addSuffix: true,
                    })}
                  </p>
                </div>

                {ticket.timestamps.started && (
                  <div className="flex justify-between">
                    <p className="text-sm text-muted-foreground">Started:</p>
                    <p className="text-sm">
                      {formatDistanceToNow(new Date(ticket.timestamps.started), {
                        addSuffix: true,
                      })}
                    </p>
                  </div>
                )}

                {ticket.timestamps.completed && (
                  <div className="flex justify-between">
                    <p className="text-sm text-muted-foreground">Completed:</p>
                    <p className="text-sm">
                      {formatDistanceToNow(new Date(ticket.timestamps.completed), {
                        addSuffix: true,
                      })}
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};