import { Battery, BatteryLow, Wifi, WifiOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Robot } from "@/lib/api/types";

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "online"
      ? "bg-chart-2/15 text-chart-2"
      : status === "error"
        ? "bg-destructive/15 text-destructive"
        : "bg-muted text-muted-foreground";
  return (
    <Badge variant="outline" className={cn("border-transparent uppercase tracking-wide", tone)}>
      {status}
    </Badge>
  );
}

export function BatteryPill({ level }: { level: number }) {
  const low = level <= 20;
  const Icon = low ? BatteryLow : Battery;
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm", low ? "text-destructive" : "text-foreground")}>
      <Icon className="size-4" aria-hidden />
      {level}%
    </span>
  );
}

interface RobotCardProps {
  robot: Robot;
  selected?: boolean;
  onSelect?: (id: string) => void;
  actions?: React.ReactNode;
}

export function RobotCard({ robot, selected, onSelect, actions }: RobotCardProps) {
  const online = robot.status === "online";
  return (
    <div
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={() => onSelect?.(robot.id)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onSelect(robot.id);
        }
      }}
      className={cn(
        "rounded-lg border border-border bg-card p-4 transition-colors",
        onSelect && "cursor-pointer hover:border-primary/60",
        selected && "border-primary ring-1 ring-primary/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold text-card-foreground">{robot.name}</p>
          <p className="truncate text-xs text-muted-foreground">{robot.id}</p>
        </div>
        <StatusBadge status={robot.status} />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs uppercase text-muted-foreground">Battery</dt>
          <dd>
            <BatteryPill level={robot.battery} />
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-muted-foreground">Link</dt>
          <dd className="inline-flex items-center gap-1">
            {online ? <Wifi className="size-4 text-chart-2" /> : <WifiOff className="size-4 text-muted-foreground" />}
            {robot.ip_address ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-muted-foreground">Position</dt>
          <dd className="font-mono text-xs">
            {robot.position.x.toFixed(2)}, {robot.position.y.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-muted-foreground">Heading</dt>
          <dd className="font-mono text-xs">{((robot.position.theta * 180) / Math.PI).toFixed(1)}°</dd>
        </div>
      </dl>

      {actions && <div className="mt-4 flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
