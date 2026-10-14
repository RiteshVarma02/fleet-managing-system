import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Play, Plus, X } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { MissionMode, Waypoint } from "@/lib/api/types";

interface Props {
  robotId: string | null;
  stops: string[];
  onStopsChange: (stops: string[]) => void;
  repeats: number;
  onRepeatsChange: (n: number) => void;
  mode: MissionMode;
  onModeChange: (mode: MissionMode) => void;
  waypoints: Waypoint[];
  blockedReason: string | null;
}

/** Ordered stops (Plus button) x repeats, run continuously or one click at a time. */
export function MissionBuilder({
  robotId,
  stops,
  onStopsChange,
  repeats,
  onRepeatsChange,
  mode,
  onModeChange,
  waypoints,
  blockedReason,
}: Props) {
  const listId = useId();
  const queryClient = useQueryClient();
  const cleaned = stops.map((s) => s.trim());
  const valid = cleaned.length > 0 && cleaned.every(Boolean);

  const start = useMutation({
    mutationFn: () =>
      api.post("/tasks/missions", { robot_id: robotId, stops: cleaned, repeats, mode }),
    onSuccess: () => {
      toast.success(`Mission started on ${robotId}`);
      if (robotId) queryClient.invalidateQueries({ queryKey: queryKeys.progress(robotId) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const update = (i: number, value: string) =>
    onStopsChange(stops.map((s, idx) => (idx === i ? value : s)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= stops.length) return;
    const next = [...stops];
    [next[i], next[j]] = [next[j], next[i]];
    onStopsChange(next);
  };

  return (
    <div className="space-y-3">
      <datalist id={listId}>
        {waypoints.map((wp) => (
          <option key={wp.id} value={wp.name} />
        ))}
      </datalist>

      <ol className="space-y-2">
        {stops.map((stop, i) => (
          <li key={i} className="flex items-center gap-1">
            <span className="w-6 shrink-0 text-center text-xs font-semibold text-muted-foreground">
              {i + 1}
            </span>
            <Input
              value={stop}
              onChange={(event) => update(i, event.target.value)}
              list={listId}
              placeholder="Waypoint name"
              aria-label={`Stop ${i + 1}`}
              className="h-8"
              autoComplete="off"
            />
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              aria-label="Move up"
              disabled={i === 0}
              onClick={() => move(i, -1)}
            >
              <ArrowUp className="size-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              aria-label="Move down"
              disabled={i === stops.length - 1}
              onClick={() => move(i, 1)}
            >
              <ArrowDown className="size-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              aria-label={`Remove stop ${i + 1}`}
              onClick={() => onStopsChange(stops.filter((_, idx) => idx !== i))}
            >
              <X className="size-4" />
            </Button>
          </li>
        ))}
      </ol>

      <Button variant="outline" size="sm" onClick={() => onStopsChange([...stops, ""])}>
        <Plus className="mr-1 size-4" aria-hidden /> Add stop
      </Button>
      <p className="text-xs text-muted-foreground">
        Tip: click a waypoint on the map to add it as the next stop.
      </p>

      <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2">
        <Label htmlFor="repeats">Repeat</Label>
        <div className="flex items-center gap-2">
          <Input
            id="repeats"
            type="number"
            min={1}
            max={1000}
            value={repeats}
            onChange={(event) =>
              onRepeatsChange(Math.max(1, Math.min(1000, Number(event.target.value) || 1)))
            }
            className="h-8 w-24"
          />
          <span className="text-xs text-muted-foreground">times</span>
        </div>

        <Label>Mode</Label>
        <ToggleGroup
          type="single"
          value={mode}
          onValueChange={(value) => value && onModeChange(value as MissionMode)}
          variant="outline"
          size="sm"
          className="justify-start"
        >
          <ToggleGroupItem value="continuous">Move continuously</ToggleGroupItem>
          <ToggleGroupItem value="step">Move on click</ToggleGroupItem>
        </ToggleGroup>
      </div>

      <p className="text-xs text-muted-foreground">
        {mode === "continuous"
          ? "The robot goes from stop to stop without waiting."
          : "The robot stops at every stop and waits for you to press Continue."}
      </p>

      <Button
        className="w-full"
        disabled={!robotId || !valid || Boolean(blockedReason) || start.isPending}
        onClick={() => start.mutate()}
      >
        <Play className="mr-1 size-4" aria-hidden />
        Start mission ({cleaned.filter(Boolean).length} stops × {repeats})
      </Button>
      {blockedReason && <p className="text-xs text-muted-foreground">{blockedReason}</p>}
    </div>
  );
}
