import { queryOptions } from "@tanstack/react-query";

import { api } from "./client";
import type {
  FleetFilesOverview,
  FleetFilesStatus,
  MapPreview,
  PendingRegistration,
  Robot,
  RobotTelemetry,
  RobotType,
  SystemInfo,
  Task,
  TaskProgress,
  TopicsConfig,
  User,
  WaypointList,
} from "./types";

/**
 * Polling budget. Live values arrive on the single `/telemetry/ws` socket, so
 * the HTTP polls are a safety net that backs off while it is up.
 */
export const POLL = {
  fleet: 3_000,
  fleetLive: 30_000,
  telemetry: 1_000,
  tasks: 10_000,
  progress: 1_500,
  system: 30_000,
} as const;

export const queryKeys = {
  robots: ["robots"] as const,
  robotStatus: (id: string) => ["robots", id, "status"] as const,
  robotTypes: ["robots", "types"] as const,
  pendingRegistrations: ["robots", "registrations", "pending"] as const,
  waypoints: ["waypoints"] as const,
  tasks: (robotId?: string) => (robotId ? (["tasks", robotId] as const) : (["tasks"] as const)),
  progress: (robotId: string) => ["tasks", "progress", robotId] as const,
  mapPreview: ["fleet-files", "map-preview"] as const,
  files: ["fleet-files"] as const,
  fileStatus: ["fleet-files", "status"] as const,
  systemInfo: ["system", "info"] as const,
  topics: ["system", "topics"] as const,
  users: ["users"] as const,
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
    refetchInterval: robotId && !live ? POLL.telemetry : false,
    staleTime: 500,
  });

export const robotTypesQuery = () =>
  queryOptions({
    queryKey: queryKeys.robotTypes,
    queryFn: ({ signal }) => api.get<RobotType[]>("/robots/types", signal),
    staleTime: Infinity,
    gcTime: Infinity,
  });

export const pendingRegistrationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.pendingRegistrations,
    queryFn: ({ signal }) =>
      api.get<PendingRegistration[]>("/robots/registrations/pending", signal),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

/** Waypoints of the active graph JSON (the names robots can be sent to). */
export const waypointsQuery = () =>
  queryOptions({
    queryKey: queryKeys.waypoints,
    queryFn: ({ signal }) => api.get<WaypointList>("/waypoints", signal),
    staleTime: 60_000,
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

/** What the robot is doing right now (null when idle). Served from memory. */
export const progressQuery = (robotId: string | null) =>
  queryOptions({
    queryKey: queryKeys.progress(robotId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<TaskProgress | null>(`/tasks/robot/${robotId}/progress`, signal),
    enabled: Boolean(robotId),
    refetchInterval: POLL.progress,
    staleTime: 500,
  });

export const mapPreviewQuery = () =>
  queryOptions({
    queryKey: queryKeys.mapPreview,
    queryFn: ({ signal }) => api.get<MapPreview>("/fleet-files/map/preview", signal),
    staleTime: 60_000,
    gcTime: 30 * 60_000,
  });

export const filesQuery = () =>
  queryOptions({
    queryKey: queryKeys.files,
    queryFn: ({ signal }) => api.get<FleetFilesOverview>("/fleet-files", signal),
    staleTime: 10_000,
  });

export const fileStatusQuery = () =>
  queryOptions({
    queryKey: queryKeys.fileStatus,
    queryFn: ({ signal }) => api.get<FleetFilesStatus>("/fleet-files/status", signal),
    refetchInterval: 8_000,
    staleTime: 4_000,
  });

export const systemInfoQuery = () =>
  queryOptions({
    queryKey: queryKeys.systemInfo,
    queryFn: ({ signal }) => api.get<SystemInfo>("/system/info", signal),
    refetchInterval: POLL.system,
    staleTime: POLL.system - 1_000,
  });

export const topicsQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.topics,
    queryFn: ({ signal }) => api.get<TopicsConfig>("/system/topics", signal),
    enabled,
    staleTime: 10_000,
  });

export const usersQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.users,
    queryFn: ({ signal }) => api.get<User[]>("/users", signal),
    enabled,
  });
