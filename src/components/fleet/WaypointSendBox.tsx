import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { Waypoint } from "@/lib/api/types";

interface Props {
  robotId: string | null;
  value: string;
  onChange: (value: string) => void;
  waypoints: Waypoint[];
  /** Why sending is blocked (shown under the box); null = allowed. */
  blockedReason: string | null;
}

/** Type a waypoint name, press Send: the robot drives there. */
export function WaypointSendBox({ robotId, value, onChange, waypoints, blockedReason }: Props) {
  const listId = useId();
  const queryClient = useQueryClient();

  const send = useMutation({
    mutationFn: () => api.post("/tasks/waypoint", { robot_id: robotId, waypoint: value.trim() }),
    onSuccess: () => {
      toast.success(`${robotId} is going to ${value.trim()}`);
      if (robotId) queryClient.invalidateQueries({ queryKey: queryKeys.progress(robotId) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const disabled = !robotId || !value.trim() || Boolean(blockedReason) || send.isPending;

  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) send.mutate();
      }}
    >
      <div className="flex gap-2">
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          list={listId}
          placeholder="Waypoint name, e.g. WP_05"
          aria-label="Waypoint name"
          autoComplete="off"
        />
        <datalist id={listId}>
          {waypoints.map((wp) => (
            <option key={wp.id} value={wp.name} />
          ))}
        </datalist>
        <Button type="submit" disabled={disabled}>
          <Send className="mr-1 size-4" aria-hidden /> Send
        </Button>
      </div>
      {blockedReason && <p className="text-xs text-muted-foreground">{blockedReason}</p>}
    </form>
  );
}
