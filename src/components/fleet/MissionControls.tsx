import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Square } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { TaskProgress } from "@/lib/api/types";

interface Props {
  robotId: string;
  progress: TaskProgress | null | undefined;
  /** Reason the robot is held by an E-stop, or null. */
  holdReason: string | null;
}

/**
 * THE one set of mission controls: Pause / Continue / Cancel.
 * Continue also means "go" when a move-on-click mission is waiting.
 */
export function MissionControls({ robotId, progress, holdReason }: Props) {
  const queryClient = useQueryClient();
  const act = useMutation({
    mutationFn: (action: "pause" | "resume" | "cancel") =>
      api.post(`/tasks/robot/${robotId}/${action}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.progress(robotId) }),
    onError: (error: Error) => toast.error(error.message),
  });

  if (!progress) {
    return <p className="text-sm text-muted-foreground">No mission running.</p>;
  }

  const waiting = progress.status === "awaiting_approval";
  const paused = progress.status === "paused";
  const total = progress.stops.length;

  return (
    <div className="space-y-3">
      <div className="text-sm">
        <p className="font-medium">
          {waiting
            ? `Waiting at ${progress.stops[(progress.stop_index + total - 1) % total] ?? "stop"}`
            : paused
              ? "Paused"
              : `Going to ${progress.leg ?? "…"}`}
        </p>
        <p className="text-xs text-muted-foreground">
          Round {Math.min(progress.cycle, progress.repeats)} of {progress.repeats}
          {progress.next_stop && ` · next: ${progress.next_stop}`}
          {" · "}
          {progress.mode === "step" ? "move on click" : "continuous"}
        </p>
        {progress.message && (
          <p className="mt-1 text-xs text-muted-foreground">{progress.message}</p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {waiting || paused ? (
          <Button
            onClick={() => act.mutate("resume")}
            disabled={act.isPending || Boolean(holdReason)}
          >
            <Play className="mr-1 size-4" aria-hidden />
            {waiting ? `Continue to ${progress.next_stop ?? "next stop"}` : "Continue"}
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => act.mutate("pause")} disabled={act.isPending}>
            <Pause className="mr-1 size-4" aria-hidden /> Pause
          </Button>
        )}
        <Button variant="outline" onClick={() => act.mutate("cancel")} disabled={act.isPending}>
          <Square className="mr-1 size-4" aria-hidden /> Cancel mission
        </Button>
      </div>
      {holdReason && (
        <p className="text-xs font-medium text-red-500">
          {holdReason}. The robot stays stopped until it is released and you press Continue.
        </p>
      )}
    </div>
  );
}
