import { Maximize2, Minimize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { MapPreview, Robot, Waypoint } from "@/lib/api/types";
import { statusInfo } from "@/lib/robot-status";
import { cn } from "@/lib/utils";

interface FleetMapProps {
  map?: MapPreview | null;
  robots: Robot[];
  waypoints?: Waypoint[];
  selectedId?: string | null;
  onSelect?: (robotId: string) => void;
  /** Click on a waypoint label (e.g. to fill the text box / add a stop). */
  onWaypointClick?: (name: string) => void;
  /** Waypoint names of the mission being built; drawn as numbered pins. */
  route?: string[];
  className?: string;
}

const FALLBACK = { width: 40, height: 40, resolution: 0.05, origin_x: -1, origin_y: -1 };
const MIN_ZOOM = 1;
const MAX_ZOOM = 14;

/**
 * The one fleet map. Zoom with the wheel or +/-, pan by dragging, expand to
 * fullscreen. Markers keep a constant on-screen size while the map scales.
 * Robots are coloured by status; a pressed E-stop button shows RED.
 */
export function FleetMap({
  map,
  robots,
  waypoints = [],
  selectedId,
  onSelect,
  onWaypointClick,
  route = [],
  className,
}: FleetMapProps) {
  const meta = map?.metadata ?? FALLBACK;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [view, setView] = useState({ z: 1, x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const drag = useRef<{ px: number; py: number; vx: number; vy: number; moved: boolean } | null>(
    null,
  );

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setBox({ w: rect.width, h: rect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // The unscaled stage = the map image fitted inside the container.
  const stage = useMemo(() => {
    const spanX = meta.width * meta.resolution || 1;
    const spanY = meta.height * meta.resolution || 1;
    const aspect = spanX / spanY || 1;
    let w = box.w;
    let h = box.w / aspect;
    if (h > box.h) {
      h = box.h;
      w = box.h * aspect;
    }
    return { w, h, spanX, spanY, offX: (box.w - w) / 2, offY: (box.h - h) / 2 };
  }, [meta, box]);

  const clamp = useCallback(
    (z: number, x: number, y: number) => {
      // Keep the stage covering the container once zoomed in.
      const minX = Math.min(0, box.w - stage.w * z - stage.offX * 2);
      const minY = Math.min(0, box.h - stage.h * z - stage.offY * 2);
      return { z, x: Math.max(minX, Math.min(0, x)), y: Math.max(minY, Math.min(0, y)) };
    },
    [box, stage],
  );

  const zoomAt = useCallback(
    (factor: number, cx: number, cy: number) => {
      setView((v) => {
        const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.z * factor));
        if (z === v.z) return v;
        // Keep the point under the cursor fixed.
        const sx = (cx - stage.offX - v.x) / v.z;
        const sy = (cy - stage.offY - v.y) / v.z;
        return clamp(z, cx - stage.offX - sx * z, cy - stage.offY - sy * z);
      });
    },
    [clamp, stage],
  );

  // Non-passive wheel listener so the page does not scroll while zooming.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.2 : 1 / 1.2, event.clientX - rect.left, event.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  const pos = (x: number, y: number) => ({
    left: `${((x - meta.origin_x) / stage.spanX) * 100}%`,
    top: `${(1 - (y - meta.origin_y) / stage.spanY) * 100}%`,
  });

  const unscale = { transform: `translate(-50%, -50%) scale(${1 / view.z})` };
  const routeIndex = new Map<string, number[]>();
  route.forEach((name, i) => routeIndex.set(name, [...(routeIndex.get(name) ?? []), i + 1]));
  const showAllLabels = view.z >= 2.2;

  return (
    <div
      ref={wrapRef}
      className={cn(
        "relative select-none overflow-hidden rounded-lg border border-border bg-muted/30",
        fullscreen && "rounded-none border-0 bg-background",
        className,
      )}
      style={{ touchAction: "none", cursor: view.z > 1 ? "grab" : "default" }}
      onPointerDown={(event) => {
        if ((event.target as HTMLElement).closest("button")) return;
        drag.current = {
          px: event.clientX,
          py: event.clientY,
          vx: view.x,
          vy: view.y,
          moved: false,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const d = drag.current;
        if (!d) return;
        const dx = event.clientX - d.px;
        const dy = event.clientY - d.py;
        if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
        setView((v) => clamp(v.z, d.vx + dx, d.vy + dy));
      }}
      onPointerUp={() => (drag.current = null)}
      onDoubleClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        zoomAt(2, event.clientX - rect.left, event.clientY - rect.top);
      }}
    >
      <div
        className="absolute left-0 top-0 origin-top-left"
        style={{
          width: stage.w,
          height: stage.h,
          marginLeft: stage.offX,
          marginTop: stage.offY,
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`,
        }}
      >
        {map?.image ? (
          <img
            src={`data:image/png;base64,${map.image}`}
            alt="Fleet map"
            className="h-full w-full [image-rendering:pixelated]"
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

        {waypoints.map((wp) => {
          if (wp.x == null || wp.y == null) return null;
          const numbers = routeIndex.get(wp.name);
          return (
            <button
              key={wp.id}
              type="button"
              title={wp.name}
              onClick={() => onWaypointClick?.(wp.name)}
              className="absolute z-10 flex flex-col items-center"
              style={{ ...pos(wp.x, wp.y), ...unscale }}
            >
              {numbers ? (
                <span className="flex min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground ring-2 ring-background">
                  {numbers.join(",")}
                </span>
              ) : (
                <span className="size-2 rounded-full bg-chart-2 ring-2 ring-background" />
              )}
              {(showAllLabels || numbers) && (
                <span className="mt-0.5 whitespace-nowrap rounded bg-background/80 px-1 text-[10px] font-medium">
                  {wp.name}
                </span>
              )}
            </button>
          );
        })}

        {robots.map((robot) => {
          const info = statusInfo(robot.status);
          const active = robot.id === selectedId;
          return (
            <button
              key={robot.id}
              type="button"
              onClick={() => onSelect?.(robot.id)}
              aria-label={`Robot ${robot.name}: ${info.label}`}
              aria-pressed={active}
              className="absolute z-20 flex flex-col items-center"
              style={{ ...pos(robot.position.x, robot.position.y), ...unscale }}
            >
              <span
                className={cn(
                  "relative flex size-4 items-center justify-center rounded-full ring-2 ring-background",
                  info.dot,
                  info.pulse && "animate-pulse",
                  active && "ring-4 ring-primary/50",
                )}
              >
                <span
                  className="absolute h-3 w-0.5 origin-bottom bg-background"
                  style={{ transform: `translateY(-50%) rotate(${-robot.position.theta}rad)` }}
                />
              </span>
              <span
                className={cn(
                  "mt-1 whitespace-nowrap rounded px-1 text-[10px] font-semibold",
                  robot.stop_active || robot.emergency_active
                    ? "bg-red-600 text-white"
                    : "bg-background/80",
                )}
              >
                {robot.name}
              </span>
            </button>
          );
        })}
      </div>

      <div className="absolute right-2 top-2 z-30 flex flex-col gap-1">
        <Button
          size="icon"
          variant="secondary"
          aria-label="Zoom in"
          onClick={() => zoomAt(1.5, box.w / 2, box.h / 2)}
        >
          <Plus className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="secondary"
          aria-label="Zoom out"
          onClick={() => zoomAt(1 / 1.5, box.w / 2, box.h / 2)}
        >
          <Minus className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="secondary"
          aria-label="Reset view"
          onClick={() => setView({ z: 1, x: 0, y: 0 })}
          disabled={view.z === 1}
        >
          <RotateCcw className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="secondary"
          aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          onClick={toggleFullscreen}
        >
          {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </div>

      {!map?.image && (
        <p className="absolute bottom-2 left-1/2 z-30 -translate-x-1/2 rounded bg-background/80 px-2 py-0.5 text-xs text-muted-foreground">
          No fleet map uploaded yet (Admin → Files)
        </p>
      )}
    </div>
  );
}
