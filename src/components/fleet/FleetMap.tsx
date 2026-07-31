import { useMemo } from "react";

import { cn } from "@/lib/utils";
import type { LocationPoint, MapImage, Robot } from "@/lib/api/types";

interface FleetMapProps {
  map?: MapImage | null;
  robots: Robot[];
  locations?: LocationPoint[];
  selectedId?: string | null;
  onSelect?: (robotId: string) => void;
  className?: string;
}

const FALLBACK = { width: 40, height: 40, resolution: 0.05, origin_x: -1, origin_y: -1 };

/**
 * Occupancy-grid viewport with robot + waypoint overlays.
 * Positions are computed in percentages so the map scales with its container
 * and no re-render loop is needed on resize.
 */
export function FleetMap({ map, robots, locations = [], selectedId, onSelect, className }: FleetMapProps) {
  const meta = map?.metadata ?? FALLBACK;

  const project = useMemo(() => {
    const spanX = meta.width * meta.resolution || 1;
    const spanY = meta.height * meta.resolution || 1;
    return (x: number, y: number) => ({
      left: ((x - meta.origin_x) / spanX) * 100,
      top: 100 - ((y - meta.origin_y) / spanY) * 100,
    });
  }, [meta]);

  return (
    <div className={cn("relative overflow-hidden rounded-lg border border-border bg-muted/30", className)}>
      {map ? (
        <img
          src={`data:image/png;base64,${map.image}`}
          alt="Occupancy grid of the current facility map"
          className="h-full w-full object-contain [image-rendering:pixelated]"
          draggable={false}
        />
      ) : (
        <div
          className="h-full w-full opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(to right, var(--color-border) 1px, transparent 1px), linear-gradient(to bottom, var(--color-border) 1px, transparent 1px)",
            backgroundSize: "32px 32px",
          }}
          aria-hidden
        />
      )}

      <div className="pointer-events-none absolute inset-0">
        {locations.map((point) => {
          const pos = project(point.x, point.y);
          if (pos.left < -5 || pos.left > 105 || pos.top < -5 || pos.top > 105) return null;
          return (
            <div
              key={point.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${pos.left}%`, top: `${pos.top}%` }}
            >
              <div className="size-2 rounded-full bg-chart-2 ring-2 ring-background" />
              <span className="mt-1 block whitespace-nowrap text-[10px] font-medium text-muted-foreground">
                {point.name}
              </span>
            </div>
          );
        })}

        {robots.map((robot) => {
          const pos = project(robot.position.x, robot.position.y);
          const active = robot.id === selectedId;
          return (
            <button
              key={robot.id}
              type="button"
              onClick={() => onSelect?.(robot.id)}
              className={cn(
                "pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 rounded-full transition-transform",
                onSelect ? "cursor-pointer hover:scale-110" : "cursor-default",
              )}
              style={{ left: `${pos.left}%`, top: `${pos.top}%` }}
              aria-label={`Robot ${robot.name}`}
              aria-pressed={active}
            >
              <span
                className={cn(
                  "relative flex size-4 items-center justify-center rounded-full ring-2 ring-background",
                  robot.status === "online"
                    ? "bg-primary"
                    : robot.status === "error"
                      ? "bg-destructive"
                      : "bg-muted-foreground",
                  active && "ring-4 ring-primary/40",
                )}
              >
                <span
                  className="absolute h-3 w-0.5 origin-bottom bg-background"
                  style={{ transform: `translateY(-50%) rotate(${-robot.position.theta}rad)` }}
                />
              </span>
              <span className="mt-1 block whitespace-nowrap rounded bg-background/80 px-1 text-[10px] font-semibold">
                {robot.name}
              </span>
            </button>
          );
        })}
      </div>

      {!map && (
        <p className="absolute bottom-2 left-1/2 -translate-x-1/2 text-xs text-muted-foreground">
          No live map available — showing relative positions
        </p>
      )}
    </div>
  );
}
