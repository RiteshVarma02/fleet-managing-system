import { queryOptions } from "@tanstack/react-query";

import { api } from "./client";
import type {
  BridgeStatus,
  LocationPoint,
  MapImage,
  MapSummary,
  PendingRegistration,
  Robot,
  RobotTelemetry,
  RobotType,
  SystemInfo,
  Task,
  TaskProgress,
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
  robotTypes: ["robots", "types"] as const,
  bridges: ["robots", "bridges"] as const,
  pendingRegistrations: ["robots", "registrations", "pending"] as const,
  locations: ["locations"] as const,
  tasks: (robotId?: string) => (robotId ? (["tasks", robotId] as const) : (["tasks"] as const)),
  taskProgress: (robotId: string) => ["tasks", "progress", robotId] as const,
  currentMap: ["maps", "current"] as const,
  maps: ["maps"] as const,
  systemInfo: ["system", "info"] as const,
};

export const robotsQuery = (live = false) =>
  queryOptions({
    queryKey: queryKeys.robots,
    queryFn: ({ signal }) => api.get<Robot[]>("/robots", signal),
    refetchInterval: live ? POLL.fleetLive : POLL.fleet,
    staleTime: (live ? POLL.fleetLive : POLL.fleet) - 500,
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

export const tasksQuery = (robotId?: string) =>
  queryOptions({
    queryKey: queryKeys.tasks(robotId),
    queryFn: ({ signal }) =>
      api.get<Task[]>(
        `/tasks?limit=50${robotId ? `&robot_id=${encodeURIComponent(robotId)}` : ""}`,
        signal,
      ),
    refetchInterval: POLL.tasks,
    staleTime: POLL.tasks - 1_000,
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

export const currentMapQuery = () =>
  queryOptions({
    queryKey: queryKeys.currentMap,
    queryFn: ({ signal }) => api.get<MapImage>("/maps/current", signal),
    // The occupancy grid is large and changes rarely: fetch once per session
    // unless the operator explicitly reloads it.
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

export const mapsQuery = () =>
  queryOptions({
    queryKey: queryKeys.maps,
    queryFn: ({ signal }) => api.get<MapSummary[]>("/maps", signal),
    staleTime: 5 * 60_000,
  });

export const systemInfoQuery = () =>
  queryOptions({
    queryKey: queryKeys.systemInfo,
    queryFn: ({ signal }) => api.get<SystemInfo>("/system/info", signal),
    refetchInterval: POLL.system,
    staleTime: POLL.system - 1_000,
  });
