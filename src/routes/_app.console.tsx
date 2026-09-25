import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Clock,
  MapPin,
  OctagonX,
  Pause,
  Pencil,
  Play,
  Plug,
  PlugZap,
  Square,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { FleetMap } from "@/components/fleet/FleetMap";
import { BatteryPill, StatusBadge } from "@/components/fleet/RobotCard";
import { Joystick } from "@/components/fleet/Joystick";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  cancelTaskRequest,
  createLocation,
  createTaskRequest,
  currentMapQuery,
  deleteLocation,
  locationsQuery,
  mapsQuery,
  promoteRobotMap,
  queryKeys,
  robotMapQuery,
  robotStatusQuery,
  robotsQuery,
  taskProgressQuery,
  tasksQuery,
  unassignedRequestsQuery,
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
  // Use robot.active_task_id for fast polling (available immediately on dispatch)
  const missionActive = Boolean(robot?.active_task_id);
  const { data: tasks = [] } = useQuery({
    ...tasksQuery(selectedId ?? undefined, missionActive),
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

  // A running/paused task for this robot (e.g. started by the scheduler) counts
  // as an active mission too — otherwise the progress card stays hidden until
  // `robot.active_task_id` catches up (up to 30s behind on the socket).
  const taskActive =
    selectedId != null &&
    tasks.some(
      (task) =>
        task.robot_id === selectedId && (task.status === "running" || task.status === "paused"),
    );
  
  const showProgress = Boolean(robot?.active_task_id) || taskActive;
  const { data: progress } = useQuery(taskProgressQuery(selectedId, showProgress));

  // The robots list (and therefore active_task_id) can lag up to 30s behind
  // reality when the telemetry socket is live — far too slow for the progress
  // card. A successful dispatch flips this flag immediately so progress
  // polling starts at once; it clears when the engine reports no more progress.
  const [dispatched, setDispatched] = useState(false);
  useEffect(() => {
    if (progress === null) setDispatched(false);
  }, [progress]);
  useEffect(() => {
    if (robot?.active_task_id) setDispatched(false);
  }, [robot?.active_task_id]);

  const showProgressCard = Boolean(progress) || (dispatched && selectedId !== null);

  // --- Waypoints (map points) + scheduling state ---------------------------
  const [pointName, setPointName] = useState("");
  const [picking, setPicking] = useState(false);
  const [pickedPoint, setPickedPoint] = useState<{ x: number; y: number } | null>(null);
  const [repeats, setRepeats] = useState(1);
  const [scheduleAt, setScheduleAt] = useState("");

  const { data: maps = [] } = useQuery(mapsQuery());
  const activeMapName = maps.find((item) => item.active)?.name ?? null;
  const { data: queuedRequests = [] } = useQuery(unassignedRequestsQuery());

  const locationName = useCallback(
    (id: string | null) => locations.find((item) => item.id === id)?.name ?? id ?? "—",
    [locations],
  );

  // Human leg label: "Going to pickup · Dock A" instead of a bare name/status.
  const missionStatusLabel = useMemo(() => {
    if (!progress) return "";
    const leg = progress.leg;
    if (leg && search.pickup && leg === locationName(search.pickup)) {
      return `Going to pickup · ${leg}`;
    }
    if (leg && search.drop && leg === locationName(search.drop)) {
      return `Going to drop · ${leg}`;
    }
    if (leg) return `Navigating to ${leg}`;
    if (progress.status === "paused") return "Paused";
    return progress.status;
  }, [progress, search.pickup, search.drop, locationName]);

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
    onSuccess: () => toast.warning("Emergency stop sent — mission paused"),
    onError: (error: Error) => toast.error(error.message),
  });

  const releaseEstop = useMutation({
    mutationFn: () => api.post("/robots/emergency-release", { robot_id: selectedId }),
    onSuccess: () => toast.success("Emergency stop released"),
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

  const invalidateProgress = () => {
    if (selectedId) {
      queryClient.invalidateQueries({ queryKey: queryKeys.taskProgress(selectedId) });
    }
  };

  const startMission = useMutation({
    mutationFn: () =>
      api.post("/tasks/pickdrop/start", {
        robot_id: selectedId,
        pickup_location_id: search.pickup,
        drop_location_id: search.drop,
        repeats,
      }),
    onSuccess: () => {
      toast.success(`Mission dispatched (${repeats}×)`);
      setDispatched(true);
      invalidateProgress();
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const addPoint = useMutation({
    mutationFn: () =>
      createLocation({
        name: pointName.trim(),
        x: pickedPoint!.x,
        y: pickedPoint!.y,
        map_name: activeMapName,
      }),
    onSuccess: (saved) => {
      toast.success(`Waypoint "${saved.name}" saved`);
      setPointName("");
      setPickedPoint(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.locations });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const removePoint = useMutation({
    mutationFn: deleteLocation,
    onSuccess: () => {
      toast.success("Waypoint removed");
      queryClient.invalidateQueries({ queryKey: queryKeys.locations });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const scheduleRequest = useMutation({
    mutationFn: createTaskRequest,
    onSuccess: (created) => {
      const when = created.scheduled_at
        ? ` for ${new Date(created.scheduled_at).toLocaleString()}`
        : "";
      toast.success(`Mission queued${when} — a free robot is picked automatically`);
      queryClient.invalidateQueries({ queryKey: queryKeys.taskRequests });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const cancelRequest = useMutation({
    mutationFn: cancelTaskRequest,
    onSuccess: () => {
      toast.success("Queued mission cancelled");
      queryClient.invalidateQueries({ queryKey: queryKeys.taskRequests });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const stopMission = useMutation({
    mutationFn: () => api.post("/tasks/pickdrop/stop", { robot_id: selectedId }),
    onSuccess: () => {
      toast.success("Mission stopped");
      setDispatched(false);
      invalidateProgress();
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const pauseMission = useMutation({
    mutationFn: () =>
      api.post("/tasks/pickdrop/pause", { robot_id: selectedId }),
    onSuccess: () => {
      toast.success("Mission paused");
      invalidateProgress();
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const resumeMission = useMutation({
    mutationFn: () =>
      api.post("/tasks/pickdrop/resume", { robot_id: selectedId }),
    onSuccess: () => {
      toast.success("Mission resumed");
      invalidateProgress();
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(selectedId ?? undefined) });
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const emergencyStopAll = useMutation({
    mutationFn: () => api.post<{ message: string }>("/robots/emergency-stop-all", {}),
    onSuccess: (data) => toast.warning(data.message ?? "Emergency stop sent to all robots"),
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
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="repeats" className="text-xs text-muted-foreground">
                  Number of times
                </Label>
                <Input
                  id="repeats"
                  type="number"
                  min={1}
                  max={1000}
                  value={repeats}
                  onChange={(event) =>
                    setRepeats(Math.max(1, Math.min(1000, Number(event.target.value) || 1)))
                  }
                  className="mt-1 h-8"
                />
              </div>
              <div>
                <Label htmlFor="schedule-at" className="text-xs text-muted-foreground">
                  Run at (optional)
                </Label>
                <Input
                  id="schedule-at"
                  type="datetime-local"
                  value={scheduleAt}
                  onChange={(event) => setScheduleAt(event.target.value)}
                  className="mt-1 h-8"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                disabled={
                  !selectedId ||
                  !search.pickup ||
                  !search.drop ||
                  taskActive ||
                  startMission.isPending
                }
                onClick={() => startMission.mutate()}
              >
                <Play className="mr-1 size-4" /> Start
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  !selectedId ||
                  pauseMission.isPending ||
                  resumeMission.isPending
                }
                onClick={() => {
                  if (progress?.status === "paused") {
                    resumeMission.mutate();
                  } else {
                    pauseMission.mutate();
                  }
                }}
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
            <Button
              size="sm"
              variant="secondary"
              className="w-full"
              disabled={
                !search.pickup ||
                !search.drop ||
                !scheduleAt ||
                scheduleRequest.isPending
              }
              onClick={() =>
                scheduleRequest.mutate({
                  from_location_id: search.pickup!,
                  to_location_id: search.drop!,
                  repeats,
                  // datetime-local is local time; send UTC ISO for the backend.
                  scheduled_at: scheduleAt ? new Date(scheduleAt).toISOString() : null,
                })
              }
            >
              <Clock className="mr-1 size-4" />
              {scheduleAt ? `Schedule for ${new Date(scheduleAt).toLocaleString()}` : "Schedule (pick a time)"}
            </Button>
          </div>
        </div>

        {showProgressCard && (
          <div className="rounded-lg border border-border bg-card p-4 text-sm">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Mission progress
            </h2>
            {progress ? (
              <>
                <p className="text-muted-foreground">
                  <span
                    className={cn(
                      "font-medium",
                      progress.status === "paused"
                        ? "text-amber-500"
                        : progress.status === "running"
                          ? "text-foreground"
                          : "text-muted-foreground",
                    )}
                  >
                    {missionStatusLabel}
                  </span>{" "}
                  · cycle {progress.completed_repeats || 0}/{progress.repeats}
                </p>
                {progress.message && (
                  <p className="mt-1 text-xs text-muted-foreground">{progress.message}</p>
                )}
              </>
            ) : (
              <p className="text-muted-foreground">Dispatching mission…</p>
            )}
          </div>
        )}

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Map waypoints
          </h2>
          <div className="space-y-3">
            <div>
              <Label htmlFor="point-name" className="text-xs text-muted-foreground">
                Waypoint name
              </Label>
              <Input
                id="point-name"
                placeholder="e.g. Dock A"
                value={pointName}
                onChange={(event) => setPointName(event.target.value)}
                className="mt-1 h-8"
              />
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={picking ? "default" : "outline"}
                className="flex-1"
                disabled={!map || addPoint.isPending}
                onClick={() => {
                  setPicking((prev) => !prev);
                  if (picking) setPickedPoint(null);
                }}
              >
                <MapPin className="mr-1 size-4" />
                {picking ? "Click the map (toggle off when done)" : "Pick on map"}
              </Button>
              <Button
                size="sm"
                disabled={!pointName.trim() || !pickedPoint || addPoint.isPending}
                onClick={() => addPoint.mutate()}
              >
                <Pencil className="mr-1 size-4" /> Save
              </Button>
            </div>
            {pickedPoint && (
              <p className="text-xs text-muted-foreground">
                Picked: x={pickedPoint.x.toFixed(2)}, y={pickedPoint.y.toFixed(2)}
                {activeMapName ? ` · map: ${activeMapName}` : ""}
              </p>
            )}
            {!map && (
              <p className="text-xs text-muted-foreground">
                Load a fleet map first — waypoints need a coordinate system.
              </p>
            )}
            {locations.length > 0 && (
              <ul className="space-y-1 text-sm">
                {locations.map((point) => (
                  <li key={point.id} className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      <MapPin className="mr-1 inline size-3 text-chart-2" />
                      {point.name}
                    </span>
                    <button
                      type="button"
                      aria-label={`Delete ${point.name}`}
                      className="text-muted-foreground transition-colors hover:text-destructive"
                      onClick={() => removePoint.mutate(point.id)}
                    >
                      <X className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {queuedRequests.length > 0 && (
          <div className="rounded-lg border border-border bg-card p-4 text-sm">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Queued / scheduled missions
            </h2>
            <ul className="space-y-2">
              {queuedRequests.map((request) => (
                <li key={request.id} className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate">
                      {locationName(request.from_location_id)} →{" "}
                      {locationName(request.to_location_id)}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {request.repeats}× ·{" "}
                      {request.scheduled_at
                        ? `at ${new Date(request.scheduled_at).toLocaleString()}`
                        : "waiting for a free robot"}
                    </span>
                  </span>
                  <button
                    type="button"
                    aria-label="Cancel queued mission"
                    className="shrink-0 text-muted-foreground transition-colors hover:text-destructive"
                    onClick={() => cancelRequest.mutate(request.id)}
                  >
                    <X className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Task log
          </h2>
          <ul className="space-y-2 text-sm">
            {tasks.slice(0, 6).map((task) => (
              <li key={task.id} className="flex justify-between gap-2">
                <span className="min-w-0">
                  <span className="block truncate">{task.type}</span>
                  {(task.status === "failed" || task.status === "cancelled") && task.message && (
                    <span className="block truncate text-xs text-destructive">{task.message}</span>
                  )}
                </span>
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
          onMapClick={picking ? (point) => setPickedPoint(point) : undefined}
          pickingMode={picking}
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

          <div className="mb-2 flex items-center justify-between gap-2">
            <Button
              variant="destructive"
              className={cn("flex-1 gap-2")}
              disabled={!selectedId}
              onClick={() => estop.mutate()}
            >
              <OctagonX className="size-4" /> Emergency stop
            </Button>
            <Button
              variant="destructive"
              className="gap-2"
              disabled={emergencyStopAll.isPending}
              onClick={() => emergencyStopAll.mutate()}
              aria-label="Emergency stop all robots"
              title="Emergency stop all robots"
            >
              <OctagonX className="size-4" /> All
            </Button>
          </div>
          <Button
            variant="outline"
            className="w-full gap-2"
            disabled={!selectedId}
            onClick={() => releaseEstop.mutate()}
          >
            <Play className="size-4" /> Release emergency stop
          </Button>
          {telemetry?.emergency_active && (
            <p className="mt-2 text-center text-xs font-medium text-destructive">
              Emergency stop engaged
            </p>
          )}
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
