import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Send, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, downloadFile } from "@/lib/api/client";
import { fileStatusQuery, filesQuery, queryKeys } from "@/lib/api/queries";
import type { FileKind, FileSyncEntry, PushResult, SyncState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const SYNC: Record<SyncState, { label: string; tone: string }> = {
  in_sync: { label: "In sync", tone: "bg-chart-2/15 text-chart-2" },
  out_of_sync: { label: "Out of date", tone: "bg-amber-500/15 text-amber-500" },
  failed: { label: "Failed", tone: "bg-destructive/15 text-destructive" },
  never: { label: "Never sent", tone: "bg-muted text-muted-foreground" },
  no_file: { label: "No file", tone: "bg-muted text-muted-foreground" },
};

const TITLE: Record<FileKind, string> = { graph: "Waypoint graph (JSON)", map: "Fleet map" };

function SyncBadge({ entry }: { entry: FileSyncEntry }) {
  const info = SYNC[entry.sync];
  return (
    <span title={entry.error ?? undefined}>
      <Badge variant="outline" className={cn("border-transparent", info.tone)}>
        {info.label}
        {entry.robot_version != null && entry.sync !== "in_sync"
          ? ` (v${entry.robot_version})`
          : ""}
      </Badge>
    </span>
  );
}

function summarize(result: PushResult): string {
  const ok = result.results.filter((r) => r.status === "acked").length;
  const bad = result.results.filter((r) => r.status !== "acked");
  return (
    `${TITLE[result.kind]} v${result.version}: ${ok}/${result.results.length} robots updated` +
    (bad.length
      ? `. Not updated: ${bad.map((b) => `${b.robot_id} (${b.error ?? b.status})`).join(", ")}`
      : "")
  );
}

/** Upload/download/rollback the ONE graph and map, and push them to robots. */
export function FleetFilesPanel() {
  const queryClient = useQueryClient();
  const { data: files } = useQuery(filesQuery());
  const { data: status } = useQuery(fileStatusQuery());
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.files });
    queryClient.invalidateQueries({ queryKey: queryKeys.waypoints });
    queryClient.invalidateQueries({ queryKey: queryKeys.mapPreview });
  };

  const push = useMutation({
    mutationFn: ({ kind, robotIds }: { kind: FileKind; robotIds?: string[] }) =>
      api.post<PushResult>(`/fleet-files/${kind}/push`, { robot_ids: robotIds }),
    onSuccess: (result) => {
      const allOk = result.results.every((r) => r.status === "acked");
      (allOk ? toast.success : toast.warning)(summarize(result));
      queryClient.invalidateQueries({ queryKey: queryKeys.fileStatus });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activate = useMutation({
    mutationFn: ({ kind, version }: { kind: FileKind; version: number }) =>
      api.post(`/fleet-files/${kind}/versions/${version}/activate`),
    onSuccess: () => {
      toast.success("Version activated. Push it to send it to the robots.");
      refresh();
      queryClient.invalidateQueries({ queryKey: queryKeys.fileStatus });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="space-y-4">
      {(["graph", "map"] as FileKind[]).map((kind) => {
        const section = files?.[kind];
        const active = section?.active;
        return (
          <div key={kind} className="rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold">{TITLE[kind]}</h3>
                <p className="text-xs text-muted-foreground">
                  {active
                    ? `Active: v${active.version} · ${active.created_by} · ${active.created_at ? new Date(active.created_at).toLocaleString() : ""}`
                    : "Nothing uploaded yet."}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!active}
                  onClick={() =>
                    downloadFile(
                      `/fleet-files/${kind}/download`,
                      kind === "graph" ? "amr_path.json" : "fleet_map.zip",
                    ).catch((e: Error) => toast.error(e.message))
                  }
                >
                  <Download className="mr-1 size-4" aria-hidden /> Download
                </Button>
                <Button
                  size="sm"
                  disabled={!active || push.isPending}
                  onClick={() => push.mutate({ kind })}
                >
                  <Send className="mr-1 size-4" aria-hidden /> Send to all robots
                </Button>
              </div>
            </div>

            <UploadForm kind={kind} onDone={refresh} />

            {section && section.versions.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  History ({section.versions.length})
                </summary>
                <ul className="mt-2 space-y-1 text-sm">
                  {section.versions.map((v) => (
                    <li
                      key={v.version}
                      className="flex items-center justify-between gap-2 border-b border-border py-1 last:border-0"
                    >
                      <span className="truncate">
                        v{v.version} · {v.created_by}
                        {v.note && <span className="text-muted-foreground"> · {v.note}</span>}
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        {v.active ? (
                          <Badge
                            variant="outline"
                            className="border-transparent bg-chart-2/15 text-chart-2"
                          >
                            Active
                          </Badge>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => activate.mutate({ kind, version: v.version })}
                          >
                            Make active
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`Download v${v.version}`}
                          onClick={() =>
                            downloadFile(
                              `/fleet-files/${kind}/download?version=${v.version}`,
                              `${kind}_v${v.version}`,
                            ).catch((e: Error) => toast.error(e.message))
                          }
                        >
                          <Download className="size-4" />
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        );
      })}

      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-semibold">What each robot has</h3>
        {(!status || status.robots.length === 0) && (
          <p className="text-sm text-muted-foreground">No robots yet.</p>
        )}
        <ul className="space-y-2 text-sm">
          {status?.robots.map((robot) => (
            <li key={robot.robot_id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">
                {robot.robot_id}
                {!robot.online && (
                  <span className="ml-1 text-xs text-muted-foreground">(offline)</span>
                )}
              </span>
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">JSON</span>
                <SyncBadge entry={robot.graph} />
                <span className="text-xs text-muted-foreground">Map</span>
                <SyncBadge entry={robot.map} />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!robot.online || push.isPending}
                  onClick={async () => {
                    for (const kind of ["graph", "map"] as FileKind[]) {
                      if (robot[kind].active_version != null && robot[kind].sync !== "in_sync") {
                        await push
                          .mutateAsync({ kind, robotIds: [robot.robot_id] })
                          .catch(() => undefined);
                      }
                    }
                  }}
                >
                  Update
                </Button>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function UploadForm({ kind, onDone }: { kind: FileKind; onDone: () => void }) {
  const first = useRef<HTMLInputElement>(null);
  const second = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");

  const upload = useMutation({
    mutationFn: () => {
      const a = first.current?.files?.[0];
      const b = second.current?.files?.[0];
      if (!a || (kind === "map" && !b))
        throw new Error(
          kind === "map" ? "Choose the map .yaml and its image" : "Choose a JSON file",
        );
      const form = new FormData();
      if (kind === "graph") form.append("file", a);
      else {
        form.append("yaml_file", a);
        form.append("image_file", b as File);
      }
      form.append("note", note);
      return api.upload(`/fleet-files/${kind}`, form);
    },
    onSuccess: () => {
      toast.success(`${TITLE[kind]} uploaded. Send it to the robots when ready.`);
      if (first.current) first.current.value = "";
      if (second.current) second.current.value = "";
      setNote("");
      onDone();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        upload.mutate();
      }}
    >
      <label className="text-xs text-muted-foreground">
        {kind === "graph" ? "JSON file" : "Map .yaml"}
        <Input
          ref={first}
          type="file"
          accept={kind === "graph" ? ".json,application/json" : ".yaml,.yml"}
          className="mt-1 h-9"
        />
      </label>
      {kind === "map" && (
        <label className="text-xs text-muted-foreground">
          Map image (.pgm / .png)
          <Input ref={second} type="file" accept=".pgm,.png,.jpg,.jpeg,.bmp" className="mt-1 h-9" />
        </label>
      )}
      <label className="min-w-40 flex-1 text-xs text-muted-foreground">
        Note (optional)
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={300}
          className="mt-1 h-9"
        />
      </label>
      <Button type="submit" size="sm" disabled={upload.isPending}>
        <Upload className="mr-1 size-4" aria-hidden /> Upload
      </Button>
    </form>
  );
}
