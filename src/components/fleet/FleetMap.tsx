import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { LocationPoint, MapImage, Robot } from "@/lib/api/types";

interface FleetMapProps {
  map?: MapImage | null;
  robots: Robot[];
  locations?: LocationPoint[];
  selectedId?: string | null;
  onSelect?: (robotId: string) => void;
  /**
   * When set, clicking the map converts the pixel into world coordinates
   * (metres on the occupancy grid) and reports it — used by "add waypoint".
   */
  onMapClick?: (point: { x: number; y: number }) => void;
  /** Visual crosshair hint while a map-click interaction is armed. */
  pickingMode?: boolean;
  className?: string;
}

const FALLBACK = { width: 40, height: 40, resolution: 0.05, origin_x: -1, origin_y: -1 };

/**
 * Occupancy-grid viewport with robot + waypoint overlays.
 *
 * The `<img>` uses `object-contain`, so the drawn image can be letterboxed
 * inside its container. Both the overlay markers and click→world conversion
 * are computed against the actual drawn rectangle (`object-contain` geometry),
 * which keeps clicks exactly where pins render.
 */
export function FleetMap({
  map,
  robots,
  locations = [],
  selectedId,
  onSelect,
  onMapClick,
  pickingMode,
  className,
}: FleetMapProps) {
  const meta = map?.metadata ?? FALLBACK;
  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setBox({ w: rect.width, h: rect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Drawn-image geometry (mirrors CSS object-contain).
  const geom = useMemo(() => {
    const spanX = meta.width * meta.resolution || 1;
    const spanY = meta.height * meta.resolution || 1;
    const imageAspect = spanX / spanY || 1;
    const w = box.w || 0;
    const h = box.h || 0;
    let drawW = w;
    let drawH = w / imageAspect;
    if (drawH > h) {
      drawH = h;
      drawW = h * imageAspect;
    }
    return {
      spanX,
      spanY,
      drawW,
      drawH,
      offX: (w - drawW) / 2,
      offY: (h - drawH) / 2,
    };
  }, [meta, box]);

  const project = useMemo(() => {
    const { spanX, spanY, drawW, drawH, offX, offY } = geom;
    return (x: number, y: number) => ({
      left: offX + ((x - meta.origin_x) / spanX) * drawW,
      top: offY + (1 - (y - meta.origin_y) / spanY) * drawH,
    });
  }, [geom, meta.origin_x, meta.origin_y]);

  function handleMapClick(event: React.MouseEvent<HTMLDivElement>) {
    if (!onMapClick || !map) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const { spanX, spanY, drawW, drawH, offX, offY } = geom;
    const px = event.clientX - rect.left - offX;
    const py = event.clientY - rect.top - offY;
    // Ignore clicks on the letterbox bars.
    if (px < 0 || py < 0 || px > drawW || py > drawH) return;
    onMapClick({
      x: meta.origin_x + (px / drawW) * spanX,
      y: meta.origin_y + (1 - py / drawH) * spanY,
    });
  }

  return (
    <div
      ref={containerRef}
      onClick={handleMapClick}
      className={cn(
        "relative overflow-hidden rounded-lg border border-border bg-muted/30",
        onMapClick && map && "cursor-crosshair",
        pickingMode && "ring-2 ring-primary/50",
        className,
      )}
    >
      {map && map.image ? (
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
          if (pos.left < -5 || pos.left > box.w + 5 || pos.top < -5 || pos.top > box.h + 5)
            return null;
          return (
            <div
              key={point.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${pos.left}px`, top: `${pos.top}px` }}
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
              onClick={(event) => {
                event.stopPropagation(); // don't fire the map-click handler
                onSelect?.(robot.id);
              }}
              className={cn(
                "pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 rounded-full transition-transform",
                onSelect ? "cursor-pointer hover:scale-110" : "cursor-default",
              )}
              style={{ left: `${pos.left}px`, top: `${pos.top}px` }}
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
