import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { CapabilityPanel } from "@/components/fleet/CapabilityPanel";
import { EstopCard } from "@/components/fleet/EstopCard";
import { FleetMap } from "@/components/fleet/FleetMap";
import { MissionBuilder } from "@/components/fleet/MissionBuilder";
import { MissionControls } from "@/components/fleet/MissionControls";
import { BatteryPill, RobotCard, StatusBadge } from "@/components/fleet/RobotCard";
import { TeleopCard } from "@/components/fleet/TeleopCard";
import { WaypointSendBox } from "@/components/fleet/WaypointSendBox";
import { mapPreviewQuery, progressQuery, robotsQuery, waypointsQuery } from "@/lib/api/queries";
import { useFleetTelemetry } from "@/lib/api/telemetry";
import type { MissionMode } from "@/lib/api/types";
import { isEstopped } from "@/lib/robot-status";

export const Route = createFileRoute("/_app/console")({
  ssr: false,
  validateSearch: (search: Record<string, unknown>): { robot?: string } =>
    typeof search.robot === "string" ? { robot: search.robot } : {},
  head: () => ({ meta: [{ title: "Operate — Robot Fleet Control" }] }),
  component: ConsolePage,
});

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ConsolePage() {
  const search = Route.useSearch();
  const live = useFleetTelemetry();
  const { data: robots = [], isLoading } = useQuery(robotsQuery(live));
  const { data: map } = useQuery(mapPreviewQuery());
  const { data: waypointList } = useQuery(waypointsQuery());
  const waypoints = waypointList?.waypoints ?? [];

  const [selectedId, setSelectedId] = useState<string | null>(search.robot ?? null);
  const [waypointText, setWaypointText] = useState("");
  const [stops, setStops] = useState<string[]>([""]);
  const [repeats, setRepeats] = useState(1);
  const [mode, setMode] = useState<MissionMode>("continuous");

  // Default to the first robot once the list arrives.
  useEffect(() => {
    if (!selectedId && robots.length > 0) setSelectedId(robots[0].id);
  }, [robots, selectedId]);

  const robot = robots.find((r) => r.id === selectedId) ?? null;
  const { data: progress } = useQuery(progressQuery(selectedId));

  const offline = !robot || robot.status === "offline";
  const estop = robot ? isEstopped(robot) : false;
  const holdReason = !robot
    ? null
    : robot.stop_active
      ? "Physical E-stop is pressed"
      : robot.emergency_active
        ? "Software E-stop is on"
        : null;
  const busy = Boolean(progress);
  const sendBlocked = !robot
    ? "Select a robot."
    : offline
      ? "Robot is offline."
      : estop
        ? `${holdReason}. The robot cannot move.`
        : busy
          ? "This robot already has a mission. Cancel it first."
          : null;

  // Map click: one place to build both the text-box value and mission stops.
  function onWaypointClick(name: string) {
    setWaypointText(name);
    setStops((current) => {
      const filled = current.filter((s) => s.trim());
      return [...filled, name];
    });
  }

  const route = stops.map((s) => s.trim()).filter(Boolean);

  return (
    <div className="mx-auto grid w-full max-w-[1700px] gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="space-y-4">
        <FleetMap
          map={map}
          robots={robots}
          waypoints={waypoints}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onWaypointClick={onWaypointClick}
          route={route}
          className="h-[62vh] min-h-[360px] w-full"
        />

        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {isLoading && <p className="text-sm text-muted-foreground">Loading robots…</p>}
          {!isLoading && robots.length === 0 && (
            <p className="text-sm text-muted-foreground">No robots yet. An admin can add them.</p>
          )}
          {robots.map((r) => (
            <RobotCard
              key={r.id}
              robot={r}
              selected={r.id === selectedId}
              onSelect={setSelectedId}
            />
          ))}
        </div>
      </div>

      <aside className="space-y-4">
        {robot ? (
          <>
            <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
              <div>
                <p className="text-lg font-semibold">{robot.name}</p>
                <p className="text-xs text-muted-foreground">{robot.id}</p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <StatusBadge status={robot.status} />
                <BatteryPill level={robot.battery} />
              </div>
            </div>

            <Section title="Go to waypoint">
              <WaypointSendBox
                robotId={selectedId}
                value={waypointText}
                onChange={setWaypointText}
                waypoints={waypoints}
                blockedReason={sendBlocked}
              />
            </Section>

            <Section title="Mission">
              <MissionBuilder
                robotId={selectedId}
                stops={stops}
                onStopsChange={setStops}
                repeats={repeats}
                onRepeatsChange={setRepeats}
                mode={mode}
                onModeChange={setMode}
                waypoints={waypoints}
                blockedReason={sendBlocked}
              />
            </Section>

            <Section title="Controls">
              <MissionControls robotId={robot.id} progress={progress} holdReason={holdReason} />
            </Section>

            <Section title="Emergency stop">
              <EstopCard robot={robot} />
            </Section>

            <Section title="Manual drive">
              <TeleopCard robot={robot} />
            </Section>

            <CapabilityPanel
              robotId={robot.id}
              capabilities={robot.capabilities}
              disabled={offline || estop}
            />
          </>
        ) : (
          <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
            Select a robot on the map or in the list.
          </p>
        )}
      </aside>
    </div>
  );
}
