// Mirrors backend/app/schemas/* — keep in sync with the FastAPI models.

export type Role = "admin" | "operator";

export interface User {
  username: string;
  role: Role | string;
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

export type RobotStatus = "online" | "offline" | "error" | "busy" | string;

/** Logical robot capabilities declared by `app/ros/topics_registry.py`. */
export type Capability =
  | "movement"
  | "navigation"
  | "telemetry"
  | "emergency"
  | "docking"
  | "fork_control"
  | "arm_control";

export interface Robot {
  id: string;
  name: string;
  type: string;
  status: RobotStatus;
  battery: number;
  position: Position;
  capabilities: Capability[] | string[];
  mac_address: string | null;
  hostname: string | null;
  ip_address: string | null;
  ros_domain_id: number | null;
  approved: boolean;
  connected: boolean;
  active_task_id: string | null;
  last_seen_at: string | null;
}

export interface NavStatus {
  state?: string;
  distance_remaining?: number;
  goal?: Position | null;
  message?: string | null;
}

export interface RobotTelemetry {
  robot_id?: string;
  connected: boolean;
  position: Position;
  velocity: Velocity;
  battery: number;
  nav: NavStatus | null;
  dock_state?: string | null;
  fork_height?: number | null;
  arm_state?: string | null;
  emergency_active?: boolean;
  capabilities?: string[];
}

/** One entry of a `/telemetry/ws` frame. */
export interface TelemetrySample {
  robot_id: string;
  status?: RobotStatus;
  position?: Position;
  velocity?: Velocity;
  battery?: number;
  nav?: NavStatus | null;
  dock_state?: string | null;
  fork_height?: number | null;
  arm_state?: string | null;
  emergency_active?: boolean;
  updated_at?: string;
}

export interface TelemetryFrame {
  type: "telemetry";
  robots: TelemetrySample[];
}

export interface RobotType {
  name: string;
  description: string;
  capabilities: string[];
}

export interface BridgeStatus {
  robot_id: string;
  running: boolean;
  restarts: number;
  config_path: string | null;
}

export interface PendingRegistration {
  mac_address: string;
  hostname: string | null;
  ip_address: string | null;
  status?: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface LocationPoint {
  id: string;
  name: string;
  x: number;
  y: number;
  theta: number;
  map_name: string | null;
  created_at: string | null;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | string;

export interface Task {
  id: string;
  type: string;
  status: TaskStatus;
  robot_id: string | null;
  from_location_id: string | null;
  to_location_id: string | null;
  repeats: number;
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

export interface MapImage {
  status: string;
  image: string;
  metadata: MapMetadata;
}

export interface MapSummary {
  name: string;
  modified_at: string;
  has_yaml: boolean;
  has_image: boolean;
}

export interface SystemInfo {
  environment: string;
  ros_enabled: boolean;
  ros_available: boolean;
  ros_error: string | null;
  ros_domain_id: number;
  connected_robots: string[];
  robot_types: string[];
  slam_running: boolean;
  domain_bridge_enabled: boolean;
  bridges: BridgeStatus[];
  telemetry_ws_interval_seconds: number;
}
