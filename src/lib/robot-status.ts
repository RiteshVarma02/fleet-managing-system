import type { Robot } from "@/lib/api/types";

export interface StatusInfo {
  label: string;
  /** Tailwind classes for a badge. */
  badge: string;
  /** Tailwind background class for a map marker. */
  dot: string;
  pulse?: boolean;
}

const STATUS: Record<string, StatusInfo> = {
  offline: {
    label: "Offline",
    badge: "bg-muted text-muted-foreground",
    dot: "bg-muted-foreground",
  },
  idle: { label: "Idle", badge: "bg-chart-2/15 text-chart-2", dot: "bg-chart-2" },
  moving: { label: "Moving", badge: "bg-primary/15 text-primary", dot: "bg-primary" },
  paused: { label: "Paused", badge: "bg-amber-500/15 text-amber-500", dot: "bg-amber-500" },
  awaiting_approval: {
    label: "Waiting for click",
    badge: "bg-amber-500/15 text-amber-500",
    dot: "bg-amber-500",
    pulse: true,
  },
  stop_active: {
    label: "E-STOP (button)",
    badge: "bg-red-600 text-white",
    dot: "bg-red-600",
    pulse: true,
  },
  e_stopped: {
    label: "E-STOP (software)",
    badge: "bg-red-600 text-white",
    dot: "bg-red-600",
    pulse: true,
  },
  error: { label: "Error", badge: "bg-destructive/15 text-destructive", dot: "bg-destructive" },
};

export function statusInfo(status: string): StatusInfo {
  return (
    STATUS[status] ?? {
      label: status,
      badge: "bg-muted text-muted-foreground",
      dot: "bg-muted-foreground",
    }
  );
}

/** True when the robot must not move at all (any E-stop). */
export function isEstopped(robot: Pick<Robot, "stop_active" | "emergency_active">): boolean {
  return robot.stop_active || robot.emergency_active;
}
