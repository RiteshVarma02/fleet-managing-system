import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { Robot } from "@/lib/api/types";
import { Joystick } from "./Joystick";

/** Manual driving. Independent of the E-stop, but disabled while one is on. */
export function TeleopCard({ robot }: { robot: Robot }) {
  const blocked = robot.stop_active || robot.emergency_active || robot.status === "offline";
  const drive = useMutation({
    mutationFn: (v: { linear: number; angular: number }) =>
      api.post("/robots/move", { robot_id: robot.id, ...v }),
    onError: (error: Error) => toast.error(error.message),
  });
  const halt = useMutation({
    mutationFn: () => api.post("/robots/stop", { robot_id: robot.id }),
  });

  return (
    <div className="space-y-3">
      <Joystick
        disabled={blocked}
        onCommand={(linear, angular) => drive.mutate({ linear, angular })}
        onRelease={() => halt.mutate()}
        className="mx-auto"
      />
      <div className="flex items-center justify-between gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => halt.mutate()}
          disabled={robot.status === "offline"}
        >
          Stop moving
        </Button>
        <p className="text-xs text-muted-foreground">
          {blocked
            ? robot.status === "offline"
              ? "Robot is offline."
              : "Disabled: E-stop is on."
            : "Hold the pad to drive; release to stop."}
        </p>
      </div>
    </div>
  );
}
