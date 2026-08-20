import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { CheckCircle2, FileUp, MapPinned, Play, Save, Share2, Square, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { FleetMap } from "@/components/fleet/FleetMap";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import {
  activateMap,
  currentMapQuery,
  mapShareToggle,
  mapsQuery,
  queryKeys,
  robotMapQuery,
  robotsQuery,
  saveFromRobot,
  slamStart,
  slamStop,
  uploadMap,
} from "@/lib/api/queries";
import type { MapDetail, MapImage, MapMetadata, MapSummary } from "@/lib/api/types";

const EMPTY_METADATA: MapMetadata = {
  width: 0,
  height: 0,
  resolution: 0.05,
  origin_x: 0,
  origin_y: 0,
};

export const Route = createFileRoute("/_app/maps")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Maps — Robot Fleet Control" },
      {
        name: "description",
        content: "Upload, activate and manage facility maps for the fleet.",
      },
      { property: "og:title", content: "Maps — Robot Fleet Control" },
      { property: "og:description", content: "Facility map management for the autonomous fleet." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MapsPage,
});

function MapsPage() {
  const queryClient = useQueryClient();
  const { data: maps = [] } = useQuery(mapsQuery());
  const { data: current } = useQuery(currentMapQuery());

  const invalidateMaps = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.maps });
    queryClient.invalidateQueries({ queryKey: queryKeys.currentMap });
  };

  const activate = useMutation({
    mutationFn: activateMap,
    onSuccess: () => {
      toast.success("Map activated");
      invalidateMaps();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: (name: string) => api.del(`/maps/${encodeURIComponent(name)}`),
    onSuccess: () => {
      toast.success("Map deleted");
      invalidateMaps();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activeMap: MapDetail | null = maps.find((map) => map.active) ?? null;

  return (
    <div className="mx-auto w-full max-w-[1400px] p-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Maps</h1>
          <p className="text-sm text-muted-foreground">
            Upload, activate and manage the facility map used across the fleet
          </p>
        </div>
        <UploadMapDialog onUploaded={invalidateMaps} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Current map
            </h2>
            {activeMap && (
              <Badge variant="secondary" className="gap-1">
                <CheckCircle2 className="size-3" />
                {activeMap.name} is active
              </Badge>
            )}
          </div>
          <CurrentMapPreview map={current} />
          <SlamPanel />
        </section>

        <aside className="space-y-4">
          <SavedMapsList
            maps={maps}
            activating={activate.isPending}
            removing={remove.isPending}
            onActivate={(name) => activate.mutate(name)}
            onDelete={(name) => remove.mutate(name)}
          />
          <RobotMapSharing />
        </aside>
      </div>
    </div>
  );
}

function CurrentMapPreview({ map }: { map?: MapImage | null }) {
  return (
    <FleetMap map={map ?? null} robots={[]} locations={[]} className="aspect-[16/10] w-full" />
  );
}

function SlamPanel() {
  const queryClient = useQueryClient();
  const { data: robots = [] } = useQuery(robotsQuery(false));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mapName, setMapName] = useState("new_map");
  const [building, setBuilding] = useState(false);
  const [savedName, setSavedName] = useState<string | null>(null);

  const selectedRobot = robots.find((robot) => robot.id === selectedId) ?? null;

  // While building, poll the robot's grid every 2s so the preview tracks the
  // growing map; outside a build session the 10s fallback keeps it fresh enough.
  const { data: robotMapData } = useQuery(robotMapQuery(selectedId, building));
  const robotMap = robotMapData?.available ? robotMapData : null;
  const displayMap: MapImage | null = robotMap
    ? {
        status: "success",
        image: robotMap.image ?? "",
        metadata: robotMap.metadata ?? EMPTY_METADATA,
      }
    : null;

  const mapRobots = useMemo(
    () => robots.filter((robot) => robot.id === selectedId),
    [robots, selectedId],
  );

  const invalidateMaps = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.maps });
    queryClient.invalidateQueries({ queryKey: queryKeys.currentMap });
  };

  const slam = useMutation({
    mutationFn: slamStart,
    onSuccess: () => {
      toast.success("SLAM started — drive the robot to build the map");
      setBuilding(true);
      setSavedName(null);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const stopSlam = useMutation({
    mutationFn: slamStop,
    onSuccess: () => {
      toast.success("SLAM stopped");
      setBuilding(false);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const save = useMutation({
    mutationFn: saveFromRobot,
    onSuccess: (data) => {
      toast.success(`Map '${data.name}' saved`);
      setSavedName(data.name);
      invalidateMaps();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activate = useMutation({
    mutationFn: activateMap,
    onSuccess: () => {
      toast.success("Map activated");
      invalidateMaps();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const name = mapName.trim() || `${selectedRobot?.id ?? "robot"}_map`;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Build map from robot
        </h2>
        {building && (
          <Badge className="gap-1">
            <span className="size-1.5 animate-pulse rounded-full bg-current" /> SLAM running
          </Badge>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div>
          <Label htmlFor="slam-robot" className="text-xs text-muted-foreground">
            Robot
          </Label>
          <Select value={selectedId ?? undefined} onValueChange={setSelectedId}>
            <SelectTrigger id="slam-robot" className="mt-1 w-full">
              <SelectValue placeholder="Select a robot" />
            </SelectTrigger>
            <SelectContent>
              {robots.map((robot) => (
                <SelectItem key={robot.id} value={robot.id}>
                  {robot.name} · {robot.status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-end gap-2">
          <Button
            size="sm"
            className="gap-2"
            disabled={!selectedId || slam.isPending || building}
            onClick={() => slam.mutate({ robotId: selectedId ?? "", mapName: name })}
          >
            <Play className="size-3" /> Start SLAM
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            disabled={!building || stopSlam.isPending}
            onClick={() => stopSlam.mutate()}
          >
            <Square className="size-3" /> Stop
          </Button>
        </div>
      </div>

      <div className="mt-3">
        <FleetMap
          map={displayMap}
          robots={mapRobots}
          locations={[]}
          className="aspect-[16/10] w-full"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          {selectedId
            ? robotMap
              ? `Live preview of ${selectedRobot?.name ?? selectedId}'s map`
              : "No map yet for this robot — start SLAM and drive around."
            : "Select a robot to preview and build its map."}
        </p>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
        <div>
          <Label htmlFor="slam-name" className="text-xs text-muted-foreground">
            Map name
          </Label>
          <Input
            id="slam-name"
            className="mt-1"
            value={mapName}
            onChange={(event) => setMapName(event.target.value)}
            placeholder="new_map"
          />
        </div>
        <div className="flex items-end gap-2">
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            disabled={!selectedId || !robotMap || save.isPending}
            onClick={() => save.mutate({ robotId: selectedId ?? "", filename: name })}
          >
            <Save className="size-3" /> Save map
          </Button>
          <Button
            size="sm"
            className="gap-2"
            disabled={!savedName || activate.isPending}
            onClick={() => activate.mutate(savedName ?? "")}
          >
            <CheckCircle2 className="size-3" /> Activate
          </Button>
        </div>
      </div>
    </div>
  );
}

function RobotMapSharing() {
  const queryClient = useQueryClient();
  const { data: robots = [] } = useQuery(robotsQuery(false));

  const toggle = useMutation({
    mutationFn: mapShareToggle,
    onSuccess: (_data, { enabled }) => {
      toast.success(enabled ? "Map sharing enabled" : "Map sharing disabled");
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Send map to robots
      </h2>
      <p className="mb-3 flex items-center gap-1 text-xs text-muted-foreground">
        <Share2 className="size-3" />
        Forward the fleet&apos;s active map down to a robot&apos;s Nav2.
      </p>
      {robots.length === 0 && (
        <p className="text-sm text-muted-foreground">No registered robots.</p>
      )}
      <ul className="space-y-2">
        {robots.map((robot) => (
          <li
            key={robot.id}
            className="flex items-center justify-between gap-2 rounded-md border border-border p-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{robot.name}</p>
              <p className="truncate text-xs text-muted-foreground">{robot.id}</p>
            </div>
            <Switch
              checked={robot.map_share_enabled}
              disabled={toggle.isPending}
              aria-label={`Send active map to ${robot.name}`}
              onCheckedChange={(checked) => toggle.mutate({ robotId: robot.id, enabled: checked })}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function SavedMapsList({
  maps,
  activating,
  removing,
  onActivate,
  onDelete,
}: {
  maps: MapSummary[];
  activating: boolean;
  removing: boolean;
  onActivate: (name: string) => void;
  onDelete: (name: string) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Saved maps ({maps.length})
      </h2>
      {maps.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No saved maps yet. Upload a map or build one from a robot.
        </p>
      )}
      <ul className="space-y-2">
        {maps.map((map) => (
          <li
            key={map.name}
            className="flex items-center justify-between gap-2 rounded-md border border-border p-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{map.name}</p>
              <p className="text-xs text-muted-foreground">
                {formatDate(map.modified_at)}
                {map.has_yaml && " · yaml"}
                {map.has_image && " · image"}
              </p>
            </div>
            {map.active ? (
              <Badge className="shrink-0 gap-1">
                <CheckCircle2 className="size-3" /> Active
              </Badge>
            ) : (
              <div className="flex shrink-0 gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={activating}
                  onClick={() => onActivate(map.name)}
                >
                  <Play className="size-3" /> Activate
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={removing}
                  aria-label={`Delete ${map.name}`}
                  onClick={() => onDelete(map.name)}
                >
                  <Trash2 className="size-3" />
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UploadMapDialog({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [resolution, setResolution] = useState("0.05");
  const [originX, setOriginX] = useState("0");
  const [originY, setOriginY] = useState("0");

  const upload = useMutation({
    mutationFn: uploadMap,
    onSuccess: () => {
      toast.success("Map uploaded and activated");
      setOpen(false);
      setFile(null);
      onUploaded();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const submit = () => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("resolution", resolution);
    form.append("origin_x", originX);
    form.append("origin_y", originY);
    upload.mutate(form);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="gap-2">
          <FileUp className="size-4" /> Upload map
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload a map</DialogTitle>
          <DialogDescription>
            PNG, PGM, JPEG or BMP. The uploaded map becomes the active fleet map and is published to
            ROS immediately.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="map-file">Map file</Label>
            <Input
              id="map-file"
              type="file"
              accept=".png,.pgm,.jpg,.jpeg,.bmp"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="h-auto py-2"
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <Label htmlFor="map-resolution">Resolution</Label>
              <Input
                id="map-resolution"
                inputMode="decimal"
                placeholder="0.05"
                value={resolution}
                onChange={(event) => setResolution(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="map-origin-x">Origin X</Label>
              <Input
                id="map-origin-x"
                inputMode="decimal"
                placeholder="0"
                value={originX}
                onChange={(event) => setOriginX(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="map-origin-y">Origin Y</Label>
              <Input
                id="map-origin-y"
                inputMode="decimal"
                placeholder="0"
                value={originY}
                onChange={(event) => setOriginY(event.target.value)}
              />
            </div>
          </div>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <MapPinned className="size-3" />
            Resolution in metres per pixel; origin in map coordinates.
          </p>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!file || upload.isPending}>
            {upload.isPending ? "Uploading…" : "Upload & activate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown date" : date.toLocaleString();
}
