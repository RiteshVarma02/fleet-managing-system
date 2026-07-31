import { queryOptions } from "@tanstack/react-query";

import { api } from "./client";
import type {
  LocationPoint,
  MapImage,
  MapSummary,
  PendingRegistration,
  Robot,
  RobotTelemetry,
  SystemInfo,
  Task,
} from "./types";

/**
 * Polling budget (kept deliberately low — the fleet list is the only fast
 * poll, everything else is either event-driven or slow/static).
 *
 *   fleet list ............ 3s   (shared by every screen and the map)
 *   selected telemetry .... 1s   (only for the robot the operator drives)
 *   tasks ................. 10s
 *   locations / maps ...... on demand (invalidate after mutations)
 */
export const POLL = {
  fleet: 3_000,
  telemetry: 1_000,
  tasks: 10_000,
  system: 30_000,
} as const;

export const queryKeys = {
  robots: ["robots"] as const,
  robotStatus: (id: string) => ["robots", id, "status"] as const,
  pendingRegistrations: ["robots", "registrations", "pending"] as const,
  locations: ["locations"] as const,
  tasks: (robotId?: string) => (robotId ? (["tasks", robotId] as const) : (["tasks"] as const)),
  currentMap: ["maps", "current"] as const,
  maps: ["maps"] as const,
  systemInfo: ["system", "info"] as const,
};

export const robotsQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.robots,
    queryFn: ({ signal }) => api.get<Robot[]>("/robots", signal),
    refetchInterval: enabled ? POLL.fleet : false,
    staleTime: POLL.fleet - 500,
    enabled,
  });

export const robotStatusQuery = (robotId: string | null, live = true) =>
  queryOptions({
    queryKey: queryKeys.robotStatus(robotId ?? "none"),
    queryFn: ({ signal }) => api.get<RobotTelemetry>(`/robots/${robotId}/status`, signal),
    enabled: Boolean(robotId),
    refetchInterval: robotId && live ? POLL.telemetry : false,
    staleTime: 500,
  });

export const pendingRegistrationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.pendingRegistrations,
    queryFn: ({ signal }) => api.get<PendingRegistration[]>("/robots/registrations/pending", signal),
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
      api.get<Task[]>(`/tasks?limit=50${robotId ? `&robot_id=${encodeURIComponent(robotId)}` : ""}`, signal),
    refetchInterval: POLL.tasks,
    staleTime: POLL.tasks - 1_000,
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
