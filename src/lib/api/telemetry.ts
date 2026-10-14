/**
 * Live telemetry over one WebSocket per browser tab.
 *
 * The backend already coalesces every robot into a single frame every
 * `TELEMETRY_WS_INTERVAL_SECONDS`, so a tab costs exactly one connection no
 * matter how many widgets read from it. Samples are merged into the existing
 * TanStack Query caches (`robots`, `robots/:id/status`) so components keep
 * using the same hooks and the HTTP polls can idle right down.
 *
 * A single module-level connection is shared through a subscriber set, and it
 * reconnects with capped exponential backoff. If the socket cannot be
 * established, `connected` stays false and the query hooks fall back to
 * polling — the UI degrades instead of going blank.
 */

import { useEffect, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { API_BASE, getAccessToken } from "./client";
import { queryKeys } from "./queries";
import type { Robot, RobotTelemetry, TelemetryFrame, TelemetrySample } from "./types";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

function socketUrl(): string {
  const base = API_BASE.startsWith("http") ? API_BASE : `${window.location.origin}${API_BASE}`;
  const url = new URL(`${base.replace(/\/$/, "")}/telemetry/ws`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const token = getAccessToken();
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

function applySamples(queryClient: QueryClient, samples: TelemetrySample[]) {
  if (samples.length === 0) return;

  const byId = new Map(samples.map((sample) => [sample.robot_id, sample]));

  queryClient.setQueryData<Robot[]>(queryKeys.robots, (previous) =>
    previous?.map((robot) => {
      const sample = byId.get(robot.id);
      if (!sample) return robot;
      return {
        ...robot,
        status: sample.status ?? robot.status,
        battery: sample.battery ?? robot.battery,
        position: sample.position ?? robot.position,
        stop_active: sample.stop_active ?? robot.stop_active,
        emergency_active: sample.emergency_active ?? robot.emergency_active,
        connected: (sample.status ?? robot.status) !== "offline",
      };
    }),
  );

  for (const sample of samples) {
    queryClient.setQueryData<RobotTelemetry>(queryKeys.robotStatus(sample.robot_id), (previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        connected: true,
        position: sample.position ?? previous.position,
        velocity: sample.velocity ?? previous.velocity,
        battery: sample.battery ?? previous.battery,
        nav: sample.nav ?? previous.nav,
        dock_state: sample.dock_state ?? previous.dock_state,
        fork_height: sample.fork_height ?? previous.fork_height,
        arm_state: sample.arm_state ?? previous.arm_state,
        emergency_active: sample.emergency_active ?? previous.emergency_active,
        stop_active: sample.stop_active ?? previous.stop_active,
        status: sample.status ?? previous.status,
      };
    });
  }
}

type Listener = (connected: boolean) => void;

let socket: WebSocket | null = null;
let listeners = new Set<Listener>();
let attempts = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let connected = false;
let client: QueryClient | null = null;

function notify(next: boolean) {
  connected = next;
  listeners.forEach((listener) => listener(next));
}

function open() {
  if (socket || typeof window === "undefined" || !getAccessToken()) return;

  let ws: WebSocket;
  try {
    ws = new WebSocket(socketUrl());
  } catch {
    scheduleReconnect();
    return;
  }
  socket = ws;

  ws.onopen = () => {
    attempts = 0;
    notify(true);
  };

  ws.onmessage = (event) => {
    if (!client) return;
    try {
      const frame = JSON.parse(event.data as string) as TelemetryFrame;
      if (frame?.type === "telemetry" && Array.isArray(frame.robots)) {
        applySamples(client, frame.robots);
      }
    } catch {
      /* ignore malformed frames — the next one is 500ms away */
    }
  };

  ws.onerror = () => ws.close();

  ws.onclose = () => {
    socket = null;
    notify(false);
    if (listeners.size > 0) scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempts, RECONNECT_MAX_MS);
  attempts += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (listeners.size > 0) open();
  }, delay);
}

function close() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  socket?.close();
  socket = null;
  attempts = 0;
  notify(false);
}

/** Drop the shared socket (called on logout so the next login re-authenticates). */
export function resetTelemetrySocket() {
  listeners = new Set();
  close();
}

/**
 * Subscribe this component to live telemetry. Returns whether the socket is
 * currently up so callers can decide to fall back to HTTP polling.
 */
export function useFleetTelemetry(enabled = true): boolean {
  const queryClient = useQueryClient();
  const [isConnected, setIsConnected] = useState(connected);

  useEffect(() => {
    if (!enabled) return;
    client = queryClient;

    const listener: Listener = setIsConnected;
    listeners.add(listener);
    setIsConnected(connected);
    open();

    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) close();
    };
  }, [enabled, queryClient]);

  return isConnected;
}
