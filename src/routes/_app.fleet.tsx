import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Plug, PlugZap, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { AddRobotCard, PendingCard, UsersCard } from "@/components/fleet/AdminPanels";
import { FleetFilesPanel } from "@/components/fleet/FleetFilesPanel";
import { FleetMap } from "@/components/fleet/FleetMap";
import { RobotCard } from "@/components/fleet/RobotCard";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api/client";
import {
  mapPreviewQuery,
  queryKeys,
  robotsQuery,
  tasksQuery,
  waypointsQuery,
} from "@/lib/api/queries";
import { useFleetTelemetry } from "@/lib/api/telemetry";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/fleet")({
  ssr: false,
  head: () => ({ meta: [{ title: "Fleet admin — Robot Fleet Control" }] }),
  component: FleetAdminPage,
});

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={`text-lg font-semibold ${tone ?? ""}`}>{value}</dd>
    </div>
  );
}

function FleetAdminPage() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const live = useFleetTelemetry();

  const { data: robots = [], isLoading } = useQuery(robotsQuery(live));
  const { data: map } = useQuery(mapPreviewQuery());
  const { data: waypointList } = useQuery(waypointsQuery());
  const { data: tasks = [] } = useQuery(tasksQuery());

  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.robots });
  const connection = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "connect" | "disconnect" }) =>
      api.post(`/robots/${action}`, { robot_id: id }),
    onSuccess: refresh,
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/robots/${id}`),
    onSuccess: () => {
      toast.success("Robot removed");
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const summary = useMemo(() => {
    const count = (f: (s: string) => boolean) => robots.filter((r) => f(r.status)).length;
    return {
      online: count((s) => s !== "offline"),
      moving: count((s) => s === "moving"),
      stopped: robots.filter((r) => r.stop_active || r.emergency_active).length,
      error: count((s) => s === "error"),
    };
  }, [robots]);

  return (
    <div className="mx-auto w-full max-w-[1700px] p-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Fleet admin</h1>
          <p className="text-sm text-muted-foreground">Robots, files and accounts</p>
        </div>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="Robots" value={robots.length} />
          <Stat label="Online" value={summary.online} tone="text-chart-2" />
          <Stat label="Moving" value={summary.moving} />
          <Stat
            label="E-stopped"
            value={summary.stopped}
            tone={summary.stopped ? "text-red-500" : undefined}
          />
          <Stat
            label="Faults"
            value={summary.error}
            tone={summary.error ? "text-destructive" : undefined}
          />
        </dl>
      </div>

      <Tabs defaultValue="robots">
        <TabsList>
          <TabsTrigger value="robots">Robots</TabsTrigger>
          <TabsTrigger value="files">JSON &amp; map files</TabsTrigger>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
        </TabsList>

        <TabsContent value="robots" className="mt-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <section className="space-y-4">
              <FleetMap
                map={map}
                robots={robots}
                waypoints={waypointList?.waypoints}
                selectedId={selected}
                onSelect={setSelected}
                className="h-[55vh] min-h-[340px] w-full"
              />
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {isLoading && <p className="text-sm text-muted-foreground">Loading fleet…</p>}
                {!isLoading && robots.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No robots yet. Add one on the right.
                  </p>
                )}
                {robots.map((robot) => (
                  <RobotCard
                    key={robot.id}
                    robot={robot}
                    selected={robot.id === selected}
                    onSelect={setSelected}
                    actions={
                      <>
                        {robot.connected ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={(e) => {
                              e.stopPropagation();
                              connection.mutate({ id: robot.id, action: "disconnect" });
                            }}
                          >
                            <PlugZap className="mr-1 size-4" /> Disconnect
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              connection.mutate({ id: robot.id, action: "connect" });
                            }}
                          >
                            <Plug className="mr-1 size-4" /> Connect
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={(e) => {
                            e.stopPropagation();
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
                            onClick={(e) => {
                              e.stopPropagation();
                              remove.mutate(robot.id);
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
              <PendingCard />
              <AddRobotCard />
              <section className="rounded-lg border border-border bg-card p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  Recent missions
                </h2>
                <ul className="space-y-2 text-sm">
                  {tasks.slice(0, 8).map((task) => (
                    <li
                      key={task.id}
                      className="flex items-center justify-between gap-2 border-b border-border pb-2 last:border-0"
                    >
                      <span className="truncate">
                        <span className="font-medium">{task.robot_id ?? "unassigned"}</span>{" "}
                        <span className="text-muted-foreground">
                          {task.stops.join(" → ")}
                          {task.repeats > 1 && ` ×${task.repeats}`}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs uppercase text-muted-foreground">
                        {task.status.replace("_", " ")}
                      </span>
                    </li>
                  ))}
                  {tasks.length === 0 && (
                    <li className="text-muted-foreground">No missions yet.</li>
                  )}
                </ul>
              </section>
            </aside>
          </div>
        </TabsContent>

        <TabsContent value="files" className="mt-4 max-w-4xl">
          <FleetFilesPanel />
        </TabsContent>

        <TabsContent value="accounts" className="mt-4 max-w-xl">
          <UsersCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}
