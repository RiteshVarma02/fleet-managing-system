/**
 * Capability-aware command panel.
 *
 * The robot's `capabilities` list comes from the backend topic registry, so a
 * differential-drive bot never shows fork or gripper controls and the UI stays
 * correct when a new robot type is added server-side.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import type { RobotTelemetry } from "@/lib/api/types";

interface CapabilityPanelProps {
  robotId: string | null;
  capabilities: string[];
  telemetry?: RobotTelemetry | null;
  disabled?: boolean;
}

export function CapabilityPanel({
  robotId,
  capabilities,
  telemetry,
  disabled,
}: CapabilityPanelProps) {
  const has = (name: string) => capabilities.includes(name);
  const blocked = disabled || !robotId;

  const [forkHeight, setForkHeight] = useState("0.2");

  const command = useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> }) =>
      api.post(path, { robot_id: robotId, ...body }),
    onSuccess: () => toast.success("Command sent"),
    onError: (error: Error) => toast.error(error.message),
  });

  const send = (path: string, body: Record<string, unknown> = {}) => command.mutate({ path, body });

  if (!has("docking") && !has("fork_control") && !has("arm_control")) {
    return null;
  }

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Robot extras
      </h2>

      {has("docking") && (
        <section className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Docking {telemetry?.dock_state ? `· ${telemetry.dock_state}` : ""}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              className="flex-1"
              disabled={blocked}
              onClick={() => send("/robots/dock", { command: "dock" })}
            >
              Dock
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="flex-1"
              disabled={blocked}
              onClick={() => send("/robots/dock", { command: "undock" })}
            >
              Undock
            </Button>
          </div>
        </section>
      )}

      {has("fork_control") && (
        <section className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Fork{" "}
            {typeof telemetry?.fork_height === "number"
              ? `· ${telemetry.fork_height.toFixed(2)} m`
              : ""}
          </p>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label htmlFor="fork-height" className="text-[11px] text-muted-foreground">
                Height (m)
              </Label>
              <Input
                id="fork-height"
                inputMode="decimal"
                className="h-8"
                value={forkHeight}
                onChange={(event) => setForkHeight(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              disabled={blocked}
              onClick={() => send("/robots/fork", { height: Number(forkHeight) || 0 })}
            >
              Move fork
            </Button>
          </div>
        </section>
      )}

      {has("arm_control") && (
        <section className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Gripper {telemetry?.arm_state ? `· ${telemetry.arm_state}` : ""}
          </p>
          <div className="flex gap-2">
            {(["open", "close", "home"] as const).map((action) => (
              <Button
                key={action}
                size="sm"
                variant={action === "home" ? "secondary" : "outline"}
                className="flex-1 capitalize"
                disabled={blocked}
                onClick={() => send("/robots/gripper", { command: action })}
              >
                {action}
              </Button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
