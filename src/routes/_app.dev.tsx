import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Navigate } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { queryKeys, systemInfoQuery, topicsQuery } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/dev")({
  ssr: false,
  head: () => ({ meta: [{ title: "Developer — Robot Fleet Control" }] }),
  component: DevPage,
});

function DevPage() {
  const { isDeveloper, ready } = useAuth();
  const queryClient = useQueryClient();
  const { data: system } = useQuery(systemInfoQuery());
  const { data: topics } = useQuery(topicsQuery(isDeveloper));

  const reload = useMutation({
    mutationFn: () => api.post<{ reconnect_required?: string[] }>("/system/topics/reload"),
    onSuccess: (result) => {
      const stale = result?.reconnect_required ?? [];
      toast.success(
        stale.length
          ? `Topics reloaded. Reconnect these robots to use them: ${stale.join(", ")}`
          : "Topics reloaded",
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.topics });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (ready && !isDeveloper) return <Navigate to="/console" replace />;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Developer</h1>
          <p className="text-sm text-muted-foreground">
            Topics are defined in one file:{" "}
            <code>{topics?.path ?? "backend/config/fleet_topics.yaml"}</code>. Edit it, then reload.
          </p>
        </div>
        <Button onClick={() => reload.mutate()} disabled={reload.isPending}>
          <RefreshCw className="mr-1 size-4" aria-hidden /> Reload topics
        </Button>
      </div>

      {system && (
        <section className="rounded-lg border border-border bg-card p-4 text-sm">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            System
          </h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
            <dt className="text-muted-foreground">Environment</dt>
            <dd>{system.environment}</dd>
            <dt className="text-muted-foreground">ROS</dt>
            <dd>
              {system.ros_available
                ? "available"
                : `unavailable${system.ros_error ? `: ${system.ros_error}` : ""}`}
            </dd>
            <dt className="text-muted-foreground">ROS domain</dt>
            <dd>{system.ros_domain_id}</dd>
            <dt className="text-muted-foreground">Connected robots</dt>
            <dd>{system.connected_robots.join(", ") || "none"}</dd>
            <dt className="text-muted-foreground">Robot types</dt>
            <dd>{system.robot_types.join(", ")}</dd>
          </dl>
        </section>
      )}

      {topics && (
        <>
          <section className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Fleet-wide topics
            </h2>
            <TopicTable rows={Object.entries(topics.fleet)} />
          </section>
          {Object.entries(topics.robot_types).map(([name, spec]) => (
            <section key={name} className="rounded-lg border border-border bg-card p-4">
              <h2 className="text-sm font-semibold">
                {name}
                {name === topics.default_robot_type && (
                  <span className="ml-2 text-xs text-muted-foreground">(default)</span>
                )}
              </h2>
              <p className="mb-2 text-xs text-muted-foreground">
                {spec.description}
                {spec.extends && ` · extends ${spec.extends}`} · capabilities:{" "}
                {spec.capabilities.join(", ")}
              </p>
              <TopicTable rows={Object.entries(spec.topics)} />
            </section>
          ))}
        </>
      )}
    </div>
  );
}

function TopicTable({ rows }: { rows: [string, { name: string; type: string; qos: string }][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 pr-4">Logical name</th>
            <th className="pr-4">Topic</th>
            <th className="pr-4">Type</th>
            <th>QoS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([logical, t]) => (
            <tr key={logical} className="border-t border-border">
              <td className="py-1 pr-4 font-medium">{logical}</td>
              <td className="pr-4 font-mono">{t.name}</td>
              <td className="pr-4 font-mono text-muted-foreground">{t.type}</td>
              <td>{t.qos}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
