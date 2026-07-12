"use client";

import { Bell } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type NotificationItem, useMarkNotificationsRead, useNotifications } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const OP_LABEL: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=" };

function notificationText(n: NotificationItem): string {
  const p = n.payload as Record<string, unknown>;
  if (typeof p.metric === "string") {
    const metric = p.metric.replace(/_/g, " ");
    return `${metric} is ${p.value} (${OP_LABEL[String(p.op)] ?? p.op} ${p.threshold})`;
  }
  return "Alert triggered";
}

/** Bell with an unread badge; opens a dropdown of recent notifications and marks them read. */
export function NotificationBell() {
  const notes = useNotifications();
  const markRead = useMarkNotificationsRead();
  const items = notes.data ?? [];
  const unread = items.filter((n) => n.read_at == null).length;

  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (open && unread > 0) markRead.mutate();
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Notifications" className="relative">
          <Bell />
          {unread > 0 ? (
            <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
              {unread > 9 ? "9+" : unread}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">No notifications yet.</p>
        ) : (
          <ul className="max-h-80 overflow-auto">
            {items.map((n) => (
              <li
                key={n.id}
                className={cn("px-2 py-2 text-sm", n.read_at == null && "bg-muted/40")}
              >
                <p className="text-foreground/90">{notificationText(n)}</p>
                <p className="text-[11px] text-muted-foreground">
                  {new Date(n.created_at).toLocaleString()}
                </p>
              </li>
            ))}
          </ul>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
