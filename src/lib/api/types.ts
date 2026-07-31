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

export interface Robot {
  id: string;
  name: string;
  type: string;
  status: RobotStatus;
  battery: number;
  position: Position;
  mac_address: string | null;
  hostname: string | null;
  ip_address: string | null;
  approved: boolean;
  last_seen_at: string | null;
}

export interface RobotTelemetry {
  connected: boolean;
  position: Position;
  velocity: Velocity;
  battery: number;
  nav: unknown;
}

export interface PendingRegistration {
  mac_address: string;
  hostname: string | null;
  ip_address: string | null;
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

export type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled" | string;

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
  connected_robots: string[];
  slam_running: boolean;
}
