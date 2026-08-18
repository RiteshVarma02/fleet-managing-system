import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { CheckCircle2, CircleSlash, Plug, PlugZap, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { FleetMap } from "@/components/fleet/FleetMap";
import { RobotCard } from "@/components/fleet/RobotCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import {
  bridgesQuery,
  currentMapQuery,
  locationsQuery,
  pendingRegistrationsQuery,
  queryKeys,
  robotTypesQuery,
  robotsQuery,
  tasksQuery,
} from "@/lib/api/queries";
import { useFleetTelemetry } from "@/lib/api/telemetry";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/lib/auth";
import type { BridgeStatus, Robot } from "@/lib/api/types";


export const Route = createFileRoute("/_app/fleet")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Fleet Monitor — Robot Fleet Control" },
      {
        name: "description",
        content: "Administrator view of every robot: live positions, battery, connectivity, tasks and pending registrations.",
      },
      { property: "og:title", content: "Fleet Monitor — Robot Fleet Control" },
      { property: "og:description", content: "Administrator view of every robot in the autonomous fleet." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: FleetMonitorPage,
});

function FleetMonitorPage() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);

  // One socket for the whole tab; the fleet poll drops to 30s while it is up.
  const live = useFleetTelemetry();

  const { data: robots = [], isLoading } = useQuery(robotsQuery(live));
  const { data: map } = useQuery(currentMapQuery());
  const { data: locations = [] } = useQuery(locationsQuery());
  const { data: tasks = [] } = useQuery(tasksQuery());
  const { data: pending = [] } = useQuery({ ...pendingRegistrationsQuery(), enabled: isAdmin });
  const { data: bridges = [] } = useQuery(bridgesQuery(isAdmin));


  const invalidateRobots = () => queryClient.invalidateQueries({ queryKey: queryKeys.robots });

  const connection = useMutation({
    mutationFn: ({ robotId, action }: { robotId: string; action: "connect" | "disconnect" }) =>
      api.post<Robot>(`/robots/${action}`, { robot_id: robotId }),
    onSuccess: (_result, variables) => {
      toast.success(`${variables.robotId} ${variables.action}ed`);
      invalidateRobots();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const removeRobot = useMutation({
    mutationFn: (robotId: string) => api.del(`/robots/${robotId}`),
    onSuccess: () => {
      toast.success("Robot removed");
      invalidateRobots();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const summary = useMemo(() => {
    const online = robots.filter((robot) => robot.status === "online").length;
    const errored = robots.filter((robot) => robot.status === "error").length;
    const battery = robots.length
      ? Math.round(robots.reduce((total, robot) => total + robot.battery, 0) / robots.length)
      : 0;
    const running = tasks.filter((task) => task.status === "running").length;
    return { online, errored, battery, running };
  }, [robots, tasks]);

  return (
    <div className="mx-auto w-full max-w-[1600px] p-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Fleet monitor</h1>
          <p className="text-sm text-muted-foreground">Live overview of every registered robot</p>
        </div>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Robots" value={robots.length} />
          <Stat label="Online" value={summary.online} tone="text-chart-2" />
          <Stat label="Faults" value={summary.errored} tone={summary.errored ? "text-destructive" : undefined} />
          <Stat label="Avg battery" value={`${summary.battery}%`} />
        </dl>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="space-y-4">
          <FleetMap
            map={map}
            robots={robots}
            locations={locations}
            selectedId={selected}
            onSelect={setSelected}
            className="aspect-[16/10] w-full"
          />

          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {isLoading && <p className="text-sm text-muted-foreground">Loading fleet…</p>}
            {!isLoading && robots.length === 0 && (
              <p className="text-sm text-muted-foreground">No robots registered yet.</p>
            )}
            {robots.map((robot) => (
              <RobotCard
                key={robot.id}
                robot={robot}
                selected={robot.id === selected}
                onSelect={setSelected}
                actions={
                  <>
                    {robot.status === "online" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={(event) => {
                          event.stopPropagation();
                          connection.mutate({ robotId: robot.id, action: "disconnect" });
                        }}
                      >
                        <PlugZap className="mr-1 size-4" /> Disconnect
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation();
                          connection.mutate({ robotId: robot.id, action: "connect" });
                        }}
                      >
                        <Plug className="mr-1 size-4" /> Connect
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={(event) => {
                        event.stopPropagation();
                        navigate({ to: "/console", search: { robot: robot.id } });
                      }}
                    >
                      Operate
                    </Button>
                    {isAdmin && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Remove ${robot.name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          removeRobot.mutate(robot.id);
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </>
                }
              />
            ))}
          </div>
        </section>

        <aside className="space-y-4">
          {isAdmin && <PendingPanel registrations={pending} />}
          {isAdmin && <BridgePanel bridges={bridges} />}



          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Recent tasks ({summary.running} running)
            </h2>
            <ul className="space-y-2 text-sm">
              {tasks.slice(0, 8).map((task) => (
                <li key={task.id} className="flex items-center justify-between gap-2 border-b border-border pb-2 last:border-0">
                  <span className="truncate">
                    <span className="font-medium">{task.type}</span>{" "}
                    <span className="text-muted-foreground">{task.robot_id ?? "unassigned"}</span>
                  </span>
                  <span className="shrink-0 text-xs uppercase text-muted-foreground">{task.status}</span>
                </li>
              ))}
              {tasks.length === 0 && <li className="text-muted-foreground">No tasks yet.</li>}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={`text-lg font-semibold ${tone ?? ""}`}>{value}</dd>
    </div>
  );
}

function BridgePanel({ bridges }: { bridges: BridgeStatus[] }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Domain bridges ({bridges.filter((bridge) => bridge.running).length}/{bridges.length})
      </h2>
      {bridges.length === 0 && (
        <p className="text-sm text-muted-foreground">No bridge processes running.</p>
      )}
      <ul className="space-y-2 text-sm">
        {bridges.map((bridge) => (
          <li key={bridge.robot_id} className="flex items-center justify-between gap-2">
            <span className="truncate font-medium">{bridge.robot_id}</span>
            <span
              className={`shrink-0 text-xs uppercase ${bridge.running ? "text-chart-2" : "text-destructive"}`}
            >
              {bridge.running ? "up" : "down"}
              {bridge.restarts > 0 && ` · ${bridge.restarts} restarts`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface Draft {
  name: string;
  type: string;
}

function PendingPanel({
  registrations,
}: {
  registrations: { mac_address: string; hostname: string | null; ip_address: string | null }[];
}) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  // Static registry — one request per session, so the picker always matches
  // the robot types the backend can actually compose.
  const { data: robotTypes = [] } = useQuery(robotTypesQuery());
  const defaultType = robotTypes[0]?.name ?? "differential_drive";

  const draftFor = (mac: string): Draft => drafts[mac] ?? { name: "", type: defaultType };
  const patch = (mac: string, changes: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [mac]: { ...draftFor(mac), ...changes } }));

  const approve = useMutation({
    mutationFn: ({ mac, draft }: { mac: string; draft: Draft }) =>
      api.post("/robots/registrations/approve", {
        mac_address: mac,
        custom_name: draft.name,
        robot_type: draft.type,
      }),
    onSuccess: () => {
      toast.success("Robot approved");
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingRegistrations });
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
      queryClient.invalidateQueries({ queryKey: queryKeys.bridges });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const reject = useMutation({
    mutationFn: (mac: string) => api.post("/robots/registrations/reject", { mac_address: mac }),
    onSuccess: () => {
      toast.success("Registration rejected");
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingRegistrations });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Pending registrations ({registrations.length})
      </h2>
      {registrations.length === 0 && (
        <p className="text-sm text-muted-foreground">No robots awaiting approval.</p>
      )}
      <ul className="space-y-3">
        {registrations.map((registration) => {
          const draft = draftFor(registration.mac_address);
          return (
            <li key={registration.mac_address} className="rounded-md border border-border p-3">
              <p className="font-mono text-xs">{registration.mac_address}</p>
              <p className="text-xs text-muted-foreground">
                {registration.hostname ?? "unknown host"} · {registration.ip_address ?? "no ip"}
              </p>
              <div className="mt-2 space-y-2">
                <Input
                  aria-label={`Name for ${registration.mac_address}`}
                  placeholder="Robot name"
                  value={draft.name}
                  onChange={(event) =>
                    patch(registration.mac_address, { name: event.target.value })
                  }
                  className="h-8"
                />
                <div className="flex gap-2">
                  <Select
                    value={draft.type}
                    onValueChange={(value) => patch(registration.mac_address, { type: value })}
                  >
                    <SelectTrigger
                      className="h-8 flex-1"
                      aria-label={`Robot type for ${registration.mac_address}`}
                    >
                      <SelectValue placeholder="Robot type" />
                    </SelectTrigger>
                    <SelectContent>
                      {robotTypes.map((type) => (
                        <SelectItem key={type.name} value={type.name}>
                          {type.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    aria-label={`Approve ${registration.mac_address}`}
                    disabled={!draft.name.trim() || approve.isPending}
                    onClick={() =>
                      approve.mutate({
                        mac: registration.mac_address,
                        draft: { ...draft, name: draft.name.trim() },
                      })
                    }
                  >
                    <CheckCircle2 className="size-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Reject registration"
                    onClick={() => reject.mutate(registration.mac_address)}
                  >
                    <CircleSlash className="size-4" />
                  </Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

