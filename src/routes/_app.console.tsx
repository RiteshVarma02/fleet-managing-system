import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { OctagonX, Pause, Play, Plug, PlugZap, Square } from "lucide-react";
import { toast } from "sonner";

import { FleetMap } from "@/components/fleet/FleetMap";
import { BatteryPill, StatusBadge } from "@/components/fleet/RobotCard";
import { Joystick } from "@/components/fleet/Joystick";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api/client";
import {
  currentMapQuery,
  locationsQuery,
  promoteRobotMap,
  queryKeys,
  robotMapQuery,
  robotStatusQuery,
  robotsQuery,
  taskProgressQuery,
  tasksQuery,
} from "@/lib/api/queries";
import { useFleetTelemetry } from "@/lib/api/telemetry";
import { CapabilityPanel } from "@/components/fleet/CapabilityPanel";
import { cn } from "@/lib/utils";
import type { MapImage, MapMetadata } from "@/lib/api/types";

const EMPTY_METADATA: MapMetadata = {
  width: 0,
  height: 0,
  resolution: 0.05,
  origin_x: 0,
  origin_y: 0,
};

interface ConsoleSearch {
  robot?: string;
  pickup?: string;
  drop?: string;
}

export const Route = createFileRoute("/_app/console")({
  ssr: false,
  validateSearch: (search: Record<string, unknown>): ConsoleSearch => ({
    robot: typeof search.robot === "string" ? search.robot : undefined,
    pickup: typeof search.pickup === "string" ? search.pickup : undefined,
    drop: typeof search.drop === "string" ? search.drop : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Control Console — Robot Fleet Control" },
      {
        name: "description",
        content:
          "Operator console: select a robot, drive it with the teleop joystick and dispatch pick and drop missions.",
      },
      { property: "og:title", content: "Control Console — Robot Fleet Control" },
      {
        property: "og:description",
        content: "Teleoperate a robot and dispatch pick and drop missions.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ConsolePage,
});

function ConsolePage() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const queryClient = useQueryClient();

  // Live pose/battery/nav arrive on one shared socket instead of per-robot polls.
  const live = useFleetTelemetry();

  const { data: robots = [] } = useQuery(robotsQuery(live));
  const { data: map } = useQuery(currentMapQuery());
  const { data: locations = [] } = useQuery(locationsQuery());

  const selectedId = search.robot ?? robots[0]?.id ?? null;
  const robot = robots.find((item) => item.id === selectedId) ?? null;
  const online = robot?.status === "online";

  const { data: telemetry } = useQuery(robotStatusQuery(selectedId, live && online));
  const { data: robotMapData } = useQuery(robotMapQuery(selectedId, live));
  const { data: tasks = [] } = useQuery({
    ...tasksQuery(selectedId ?? undefined),
    enabled: Boolean(selectedId),
  });

  const robotMap = robotMapData?.available ? robotMapData : null;
  const displayMap: MapImage | null = robotMap
    ? {
        status: "success",
        image: robotMap.image ?? "",
        metadata: robotMap.metadata ?? EMPTY_METADATA,
      }
    : (map ?? null);

  const missionActive = Boolean(robot?.active_task_id);
  const { data: progress } = useQuery(taskProgressQuery(selectedId, missionActive));

  const setSearch = useCallback(
    (patch: Partial<ConsoleSearch>) => {
      navigate({
        to: "/console",
        search: (prev: ConsoleSearch) => ({ ...prev, ...patch }),
        replace: true,
      });
    },
    [navigate],
  );

  const position = telemetry?.position ?? robot?.position ?? { x: 0, y: 0, theta: 0 };
  const battery = telemetry?.battery ?? robot?.battery ?? 0;

  const mapRobots = useMemo(
    () =>
      robots.map((item) =>
        item.id === selectedId && telemetry ? { ...item, position: telemetry.position } : item,
      ),
    [robots, selectedId, telemetry],
  );

  const invalidateRobots = () => queryClient.invalidateQueries({ queryKey: queryKeys.robots });

  const connection = useMutation({
    mutationFn: (action: "connect" | "disconnect") =>
      api.post(`/robots/${action}`, { robot_id: selectedId }),
    onSuccess: (_data, action) => {
      toast.success(`Robot ${action}ed`);
      invalidateRobots();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const drive = useMutation({
    mutationFn: (payload: { linear: number; angular: number }) =>
      api.post("/robots/move", { robot_id: selectedId, ...payload }),
    onError: (error: Error) => toast.error(error.message),
  });

  const halt = useMutation({
    mutationFn: () => api.post("/robots/stop", { robot_id: selectedId }),
    onError: (error: Error) => toast.error(error.message),
  });

  const estop = useMutation({
    mutationFn: () => api.post("/robots/emergency-stop", { robot_id: selectedId }),
    onSuccess: () => toast.warning("Emergency stop sent"),
    onError: (error: Error) => toast.error(error.message),
  });

  const promote = useMutation({
    mutationFn: promoteRobotMap,
    onSuccess: () => {
      toast.success("Robot map promoted to fleet map");
      queryClient.invalidateQueries({ queryKey: queryKeys.currentMap });
      queryClient.invalidateQueries({ queryKey: queryKeys.maps });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const startMission = useMutation({
    mutationFn: () =>
      api.post("/tasks/pickdrop/start", {
        robot_id: selectedId,
        pickup_location_id: search.pickup,
        drop_location_id: search.drop,
        repeats: 1,
      }),
    onSuccess: () => {
      toast.success("Mission dispatched");
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const stopMission = useMutation({
    mutationFn: () => api.post("/tasks/pickdrop/stop", { robot_id: selectedId }),
    onSuccess: () => {
      toast.success("Mission stopped");
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const pauseMission = useMutation({
    mutationFn: (paused: boolean) =>
      api.post(paused ? "/tasks/pickdrop/resume" : "/tasks/pickdrop/pause", {
        robot_id: selectedId,
      }),
    onSuccess: (_data, paused) => {
      toast.success(paused ? "Mission resumed" : "Mission paused");
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="mx-auto grid w-full max-w-[1600px] gap-4 p-4 xl:grid-cols-[300px_minmax(0,1fr)_300px]">
      {/* Left: selection + mission */}
      <aside className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <Label
            htmlFor="robot-select"
            className="text-xs uppercase tracking-wide text-muted-foreground"
          >
            Active robot
          </Label>
          <Select
            value={selectedId ?? undefined}
            onValueChange={(value) => setSearch({ robot: value })}
          >
            <SelectTrigger id="robot-select" className="mt-2 w-full">
              <SelectValue placeholder="Select a robot" />
            </SelectTrigger>
            <SelectContent>
              {robots.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.name} · {item.status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="mt-3 flex gap-2">
            {online ? (
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                disabled={!selectedId}
                onClick={() => connection.mutate("disconnect")}
              >
                <PlugZap className="mr-1 size-4" /> Disconnect
              </Button>
            ) : (
              <Button
                size="sm"
                className="flex-1"
                disabled={!selectedId}
                onClick={() => connection.mutate("connect")}
              >
                <Plug className="mr-1 size-4" /> Connect
              </Button>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Pick &amp; drop
          </h2>
          <div className="space-y-3">
            <div>
              <Label className="text-xs text-muted-foreground">Pickup</Label>
              <Select value={search.pickup} onValueChange={(value) => setSearch({ pickup: value })}>
                <SelectTrigger className="mt-1 w-full">
                  <SelectValue placeholder="Select location" />
                </SelectTrigger>
                <SelectContent>
                  {locations.map((point) => (
                    <SelectItem key={point.id} value={point.id}>
                      {point.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Drop</Label>
              <Select value={search.drop} onValueChange={(value) => setSearch({ drop: value })}>
                <SelectTrigger className="mt-1 w-full">
                  <SelectValue placeholder="Select location" />
                </SelectTrigger>
                <SelectContent>
                  {locations.map((point) => (
                    <SelectItem key={point.id} value={point.id}>
                      {point.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                disabled={!selectedId || !search.pickup || !search.drop || startMission.isPending}
                onClick={() => startMission.mutate()}
              >
                <Play className="mr-1 size-4" /> Start
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!selectedId || pauseMission.isPending}
                onClick={() => pauseMission.mutate(progress?.status !== "paused")}
              >
                {progress?.status === "paused" ? (
                  <>
                    <Play className="mr-1 size-4" /> Resume
                  </>
                ) : (
                  <>
                    <Pause className="mr-1 size-4" /> Pause
                  </>
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!selectedId}
                onClick={() => stopMission.mutate()}
              >
                <Square className="mr-1 size-4" /> Stop
              </Button>
            </div>
          </div>
        </div>

        {progress && (
          <div className="rounded-lg border border-border bg-card p-4 text-sm">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Mission progress
            </h2>
            <p className="text-muted-foreground">
              <span className="text-foreground">{progress.leg ?? progress.status}</span> ·{" "}
              {progress.completed_repeats}/{progress.repeats} cycles
            </p>
          </div>
        )}

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Task log
          </h2>
          <ul className="space-y-2 text-sm">
            {tasks.slice(0, 6).map((task) => (
              <li key={task.id} className="flex justify-between gap-2">
                <span className="truncate">{task.type}</span>
                <span className="shrink-0 text-xs uppercase text-muted-foreground">
                  {task.status}
                </span>
              </li>
            ))}
            {tasks.length === 0 && (
              <li className="text-muted-foreground">No tasks for this robot.</li>
            )}
          </ul>
        </div>
      </aside>

      {/* Center: map */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {robotMap ? `${robot?.name ?? "Robot"}'s map` : "Fleet map"}
          </h2>
          <div className="flex items-center gap-2">
            {selectedId && !robotMap && (
              <span className="text-xs text-muted-foreground">No map yet for this robot</span>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={!robotMap || promote.isPending}
              onClick={() => promote.mutate({ robotId: selectedId })}
            >
              Use this robot&apos;s map as fleet map
            </Button>
          </div>
        </div>
        <FleetMap
          map={displayMap}
          robots={mapRobots}
          locations={locations}
          selectedId={selectedId}
          onSelect={(id) => setSearch({ robot: id })}
          className="aspect-[16/10] w-full"
        />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="X" value={position.x.toFixed(2)} />
          <Metric label="Y" value={position.y.toFixed(2)} />
          <Metric label="Heading" value={`${((position.theta * 180) / Math.PI).toFixed(1)}°`} />
          <Metric label="Linear" value={`${(telemetry?.velocity.linear ?? 0).toFixed(2)} m/s`} />
        </div>
      </section>

      {/* Right: manual control */}
      <aside className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="font-semibold">{robot?.name ?? "No robot"}</p>
              <p className="text-xs text-muted-foreground">{robot?.id ?? "—"}</p>
            </div>
            <StatusBadge status={robot?.status ?? "offline"} />
          </div>
          <div className="mb-4 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Battery</span>
            <BatteryPill level={Math.round(battery)} />
          </div>

          <Joystick
            disabled={!online}
            onCommand={(linear, angular) => drive.mutate({ linear, angular })}
            onRelease={() => {
              if (online) halt.mutate();
            }}
          />

          <Button
            variant="destructive"
            className={cn("mt-4 w-full gap-2")}
            disabled={!selectedId}
            onClick={() => estop.mutate()}
          >
            <OctagonX className="size-4" /> Emergency stop
          </Button>
        </div>

        <CapabilityPanel
          robotId={selectedId}
          capabilities={(robot?.capabilities as string[]) ?? []}
          telemetry={telemetry}
          disabled={!online}
        />
      </aside>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-sm">{value}</p>
    </div>
  );
}
