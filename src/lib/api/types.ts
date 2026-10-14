// Mirrors backend/app/schemas/* — keep in sync with the FastAPI models.

export type Role = "developer" | "admin" | "operator";

export interface User {
  id: string | null;
  username: string;
  role: Role | string;
  active: boolean;
  last_login_at: string | null;
}

export interface TokenResponse {
  status: string;
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Position {
  x: number;
  y: number;
  theta: number;
}

export interface Velocity {
  linear: number;
  angular: number;
}

/** Derived by the server (`backend/app/services/robot_status.py`). */
export type RobotStatus =
  | "offline"
  | "idle"
  | "moving"
  | "paused"
  | "awaiting_approval"
  | "stop_active"
  | "e_stopped"
  | "error";

export interface Robot {
  id: string;
  name: string;
  type: string;
  status: RobotStatus | string;
  battery: number;
  position: Position;
  capabilities: string[];
  mac_address: string | null;
  hostname: string | null;
  ip_address: string | null;
  approved: boolean;
  connected: boolean;
  /** Physical E-stop button is pressed on the robot. */
  stop_active: boolean;
  /** Software E-stop from the dashboard. */
  emergency_active: boolean;
  active_task_id: string | null;
  last_seen_at: string | null;
}

export interface RobotTelemetry {
  robot_id?: string;
  connected: boolean;
  status?: string;
  position: Position;
  velocity: Velocity;
  battery: number | null;
  nav: { status?: string; message?: string | null } | null;
  dock_state?: string | null;
  fork_height?: number | null;
  arm_state?: string | null;
  emergency_active?: boolean;
  stop_active?: boolean;
  safety_hold?: string | null;
  capabilities?: string[];
  topics?: Record<string, string>;
}

/** One entry of a `/telemetry/ws` frame. */
export interface TelemetrySample {
  robot_id: string;
  status?: string;
  position?: Position;
  velocity?: Velocity;
  battery?: number;
  nav?: RobotTelemetry["nav"];
  dock_state?: string | null;
  fork_height?: number | null;
  arm_state?: string | null;
  emergency_active?: boolean;
  stop_active?: boolean;
  at?: string;
}

export interface TelemetryFrame {
  type: "telemetry";
  robots: TelemetrySample[];
}

export interface RobotType {
  name: string;
  description: string;
  capabilities: string[];
  extends?: string | null;
  topics?: Record<string, { name: string; type: string }>;
}

export interface PendingRegistration {
  mac_address: string;
  hostname: string | null;
  ip_address: string | null;
  status?: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

/** A waypoint of the active graph. x/y are null when the graph has none. */
export interface Waypoint {
  id: number;
  name: string;
  x: number | null;
  y: number | null;
}

export interface WaypointList {
  version: number | null;
  waypoints: Waypoint[];
}

export type MissionMode = "continuous" | "step";

export type TaskStatus =
  "pending" | "running" | "paused" | "awaiting_approval" | "completed" | "failed" | "cancelled";

export interface Task {
  id: string;
  type: string;
  status: TaskStatus | string;
  robot_id: string | null;
  stops: string[];
  mode: MissionMode | string;
  repeats: number;
  completed_repeats: number;
  message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** In-memory progress served by the task engine (no database read). */
export interface TaskProgress {
  task_id: string;
  robot_id: string;
  leg: string | null;
  stops: string[];
  mode: MissionMode | string;
  cycle: number;
  stop_index: number;
  next_stop: string | null;
  completed_repeats: number;
  repeats: number;
  status: string;
  message?: string | null;
}

export interface MapMetadata {
  width: number;
  height: number;
  resolution: number;
  origin_x: number;
  origin_y: number;
}

/** `GET /fleet-files/map/preview` — the single fleet map. */
export interface MapPreview {
  version: number | null;
  image: string;
  metadata: MapMetadata | null;
}

export type FileKind = "graph" | "map";

export interface FileVersion {
  version: number;
  active: boolean;
  note: string;
  created_by: string;
  created_at: string | null;
  meta: Record<string, unknown>;
  files: { role: string; name: string; sha256: string; size: number }[];
}

export type FleetFilesOverview = Record<
  FileKind,
  { active: FileVersion | null; versions: FileVersion[] }
>;

export type SyncState = "in_sync" | "out_of_sync" | "failed" | "never" | "no_file";

export interface RobotFileStatus {
  robot_id: string;
  online: boolean;
  graph: FileSyncEntry;
  map: FileSyncEntry;
}

export interface FileSyncEntry {
  active_version: number | null;
  robot_version: number | null;
  sync: SyncState;
  last_status: string | null;
  error: string | null;
}

export interface FleetFilesStatus {
  active: Record<FileKind, number | null>;
  robots: RobotFileStatus[];
}

export interface PushResult {
  kind: FileKind;
  version: number;
  results: { robot_id: string; status: string; error: string | null }[];
}

export interface SystemInfo {
  environment: string;
  ros_enabled: boolean;
  ros_available: boolean;
  ros_error: string | null;
  ros_domain_id: number;
  connected_robots: string[];
  robot_types: string[];
  topics_file: string;
  telemetry_ws_interval_seconds: number;
  telemetry_stale_after_seconds: number;
}

export interface TopicsConfig {
  path: string;
  default_robot_type: string;
  fleet: Record<string, { name: string; type: string; qos: string }>;
  robot_types: Record<
    string,
    {
      description: string;
      extends: string | null;
      capabilities: string[];
      topics: Record<string, { name: string; type: string; qos: string }>;
    }
  >;
}
