import { queryOptions } from "@tanstack/react-query";

import { api } from "./client";
import type {
  BridgeStatus,
  DomainInfo,
  LocationPoint,
  MapImage,
  MapSummary,
  PendingRegistration,
  Robot,
  RobotMap,
  RobotTelemetry,
  RobotType,
  SavedMap,
  SystemInfo,
  Task,
  TaskProgress,
  TaskRequest,
} from "./types";

/**
 * Polling budget.
 *
 * Live values (pose, battery, nav, dock/fork/arm) arrive on the single
 * `/telemetry/ws` socket, so when it is up the HTTP polls exist only as a
 * safety net and back off hard. `live` is the socket state from
 * `useFleetTelemetry`.
 *
 *   fleet list ....... 3s polling  →  30s when the socket is live
 *   telemetry ........ 1s polling  →  off when the socket is live
 *   tasks ............ 10s
 *   locations/maps ... on demand (invalidated after mutations)
 */
export const POLL = {
  fleet: 3_000,
  fleetLive: 30_000,
  telemetry: 1_000,
  tasks: 10_000,
  progress: 2_000,
  system: 30_000,
} as const;

export const queryKeys = {
  robots: ["robots"] as const,
  robotStatus: (id: string) => ["robots", id, "status"] as const,
  robotMap: (id: string) => ["robots", id, "map"] as const,
  robotTypes: ["robots", "types"] as const,
  bridges: ["robots", "bridges"] as const,
  domains: ["robots", "domains", "next"] as const,
  pendingRegistrations: ["robots", "registrations", "pending"] as const,
  locations: ["locations"] as const,
  tasks: (robotId?: string) => (robotId ? (["tasks", robotId] as const) : (["tasks"] as const)),
  taskProgress: (robotId: string) => ["tasks", "progress", robotId] as const,
  taskRequests: ["tasks", "requests", "unassigned"] as const,
  currentMap: ["maps", "current"] as const,
  maps: ["maps"] as const,
  systemInfo: ["system", "info"] as const,
};

export const robotsQuery = (live = false) =>
  queryOptions({
    queryKey: queryKeys.robots,
    queryFn: ({ signal }) => api.get<Robot[]>("/robots", signal),
    refetchInterval: live ? POLL.fleetLive : POLL.fleet,
    staleTime: 1_000,
  });

export const robotStatusQuery = (robotId: string | null, live = false) =>
  queryOptions({
    queryKey: queryKeys.robotStatus(robotId ?? "none"),
    queryFn: ({ signal }) => api.get<RobotTelemetry>(`/robots/${robotId}/status`, signal),
    enabled: Boolean(robotId),
    // The socket patches this cache entry in place; polling is the fallback.
    refetchInterval: robotId && !live ? POLL.telemetry : false,
    staleTime: 500,
  });

export const robotMapQuery = (robotId: string | null, live = false, fast = false) =>
  queryOptions({
    queryKey: queryKeys.robotMap(robotId ?? "none"),
    queryFn: ({ signal }) => api.get<RobotMap>(`/robots/${robotId}/map`, signal),
    enabled: Boolean(robotId),
    // While the telemetry socket is up (robot live / SLAM building), poll the
    // grid fast so the preview tracks the growing map; otherwise back off.
    refetchInterval: fast ? 2_000 : robotId && live ? POLL.progress : 10_000,
    staleTime: 1_000,
    retry: false,
  });

export const robotTypesQuery = () =>
  queryOptions({
    queryKey: queryKeys.robotTypes,
    queryFn: ({ signal }) => api.get<RobotType[]>("/robots/types", signal),
    // Static registry on the server — fetch once per session.
    staleTime: Infinity,
    gcTime: Infinity,
  });

export const bridgesQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.bridges,
    queryFn: ({ signal }) => api.get<BridgeStatus[]>("/robots/bridges", signal),
    refetchInterval: enabled ? 15_000 : false,
    staleTime: 10_000,
    enabled,
  });

export const nextDomainQuery = () =>
  queryOptions({
    queryKey: queryKeys.domains,
    queryFn: ({ signal }) => api.get<DomainInfo>("/robots/domains/next", signal),
    // Domain usage only changes on approve/reject/delete; a slow poll keeps
    // the pending panel's default fresh across several approvals.
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

export const pendingRegistrationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.pendingRegistrations,
    queryFn: ({ signal }) =>
      api.get<PendingRegistration[]>("/robots/registrations/pending", signal),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

export const locationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.locations,
    queryFn: ({ signal }) => api.get<LocationPoint[]>("/locations", signal),
    staleTime: 5 * 60_000,
  });

/** Save a named waypoint (map click → world coords). */
export const createLocation = (body: {
  name: string;
  x: number;
  y: number;
  theta?: number;
  map_name?: string | null;
}) => api.post<LocationPoint>("/locations", { theta: 0, ...body });

export const deleteLocation = (locationId: string) =>
  api.del<{ message: string }>(`/locations/${locationId}`);

export const tasksQuery = (robotId?: string, fast = false) =>
  queryOptions({
    queryKey: queryKeys.tasks(robotId),
    queryFn: ({ signal }) =>
      api.get<Task[]>(
        `/tasks?limit=50${robotId ? `&robot_id=${encodeURIComponent(robotId)}` : ""}`,
        signal,
      ),
    refetchInterval: fast ? 2_000 : POLL.tasks,
    staleTime: fast ? 1_000 : POLL.tasks - 1_000,
  });

export const taskProgressQuery = (robotId: string | null, active = false) =>
  queryOptions({
    queryKey: queryKeys.taskProgress(robotId ?? "none"),
    // Served from the task engine's memory — cheap enough to poll while a
    // mission is running, and disabled entirely when nothing is running.
    queryFn: ({ signal }) =>
      api.get<TaskProgress | null>(`/tasks/pickdrop/${robotId}/status`, signal),
    enabled: Boolean(robotId) && active,
    refetchInterval: active ? POLL.progress : false,
    staleTime: 1_000,
  });

/** Queued (possibly scheduled) unassigned requests awaiting a free robot. */
export const unassignedRequestsQuery = () =>
  queryOptions({
    queryKey: queryKeys.taskRequests,
    queryFn: ({ signal }) => api.get<TaskRequest[]>("/tasks/requests/unassigned", signal),
    refetchInterval: POLL.tasks,
    staleTime: POLL.tasks - 1_000,
  });

/** Queue unassigned work; `scheduledAt` defers scheduler pickup until then. */
export const createTaskRequest = (body: {
  type?: string;
  from_location_id: string;
  to_location_id: string;
  repeats: number;
  scheduled_at?: string | null;
}) =>
  api.post<TaskRequest>("/tasks/requests", {
    type: "pick_drop",
    ...body,
    scheduled_at: body.scheduled_at ?? undefined,
  });

/** Remove a queued request before the scheduler assigns it. */
export const cancelTaskRequest = (requestId: string) =>
  api.post<{ message: string }>(`/tasks/requests/${requestId}/cancel`);

export const currentMapQuery = () =>
  queryOptions({
    queryKey: queryKeys.currentMap,
    queryFn: ({ signal }) => api.get<MapImage>("/maps/current", signal),
    staleTime: 10_000,
    gcTime: 30 * 60_000,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchInterval: 30_000,
  });

export const mapsQuery = () =>
  queryOptions({
    queryKey: queryKeys.maps,
    queryFn: ({ signal }) => api.get<MapSummary[]>("/maps", signal),
    // The list is re-fetched after upload/activate/delete mutations.
    staleTime: 5 * 60_000,
  });

/** Mutation helpers — passed to `useMutation({ mutationFn })`. */
export const uploadMap = (formData: FormData) => api.upload<MapImage>("/maps/load", formData);

export const activateMap = (mapName: string) =>
  api.post<MapImage>("/maps/activate", { map_name: mapName });

export const promoteRobotMap = ({ robotId, mapName }: { robotId: string; mapName?: string }) =>
  api.post<MapImage>("/maps/from-robot", { robot_id: robotId, map_name: mapName });

/** Start SLAM on a robot (cartographer) so it can build a map of the facility. */
export const slamStart = ({ robotId, mapName }: { robotId: string; mapName?: string }) =>
  api.post<{ pid: number; map_name: string | null; robot_id: string }>("/maps/slam/start", {
    robot_id: robotId,
    map_name: mapName,
  });

/** Stop the running SLAM session on the selected robot. */
export const slamStop = () => api.post<{ message: string }>("/maps/slam/stop");

/** Persist a robot's captured grid as .pgm/.yaml/.png (build-map flow). */
export const saveFromRobot = ({ robotId, filename }: { robotId: string; filename: string }) =>
  api.post<SavedMap>("/maps/save-from-robot", { robot_id: robotId, filename });

/** Toggle forwarding the fleet's active /map down to a robot's Nav2. */
export const mapShareToggle = ({ robotId, enabled }: { robotId: string; enabled: boolean }) =>
  api.post<Robot>(`/robots/${robotId}/map-share`, { robot_id: robotId, enabled });

/** Cancel the active Nav2 goal outright — terminal state. */
export const cancelGoal = ({ robotId }: { robotId: string }) =>
  api.post<{ message: string }>("/robots/goal/cancel", { robot_id: robotId });

/** Pause the active Nav2 goal: action cancelled (robot stops) + goal remembered. */
export const pauseGoal = ({ robotId }: { robotId: string }) =>
  api.post<{ message: string }>("/robots/goal/pause", { robot_id: robotId });

/** Resume a paused goal by re-issuing it to Nav2. */
export const resumeGoal = ({ robotId }: { robotId: string }) =>
  api.post<{ message: string }>("/robots/goal/resume", { robot_id: robotId });

/** Pause the robot's running pick & drop mission (task stays alive). */
export const pauseMission = (robotId: string) =>
  api.post<{ message: string }>("/tasks/pickdrop/pause", { robot_id: robotId });

/** Resume the robot's paused pick & drop mission (goal re-issued). */
export const resumeMission = (robotId: string) =>
  api.post<{ message: string }>("/tasks/pickdrop/resume", { robot_id: robotId });

export const systemInfoQuery = () =>
  queryOptions({
    queryKey: queryKeys.systemInfo,
    queryFn: ({ signal }) => api.get<SystemInfo>("/system/info", signal),
    refetchInterval: POLL.system,
    staleTime: POLL.system - 1_000,
  });
