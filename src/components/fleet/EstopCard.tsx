import { useMutation, useQueryClient } from "@tanstack/react-query";
import { OctagonX, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { Robot } from "@/lib/api/types";

/**
 * Emergency stop for one robot. Separate from manual driving: while any
 * E-stop is on, the robot cannot be moved by anything, teleop included.
 */
export function EstopCard({ robot }: { robot: Robot }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.robots });
  const engage = useMutation({
    mutationFn: () => api.post("/robots/emergency-stop", { robot_id: robot.id }),
    onSuccess: () => {
      toast.warning(`E-stop engaged on ${robot.name}`);
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const release = useMutation({
    mutationFn: () => api.post("/robots/emergency-release", { robot_id: robot.id }),
    onSuccess: () => {
      toast.success("Software E-stop released. Press Continue to resume the mission.");
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="space-y-3">
      {robot.stop_active && (
        <p className="rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white">
          Physical E-stop button is pressed on the robot. Release it on the robot.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="destructive"
          onClick={() => engage.mutate()}
          disabled={engage.isPending || robot.emergency_active}
        >
          <OctagonX className="mr-1 size-4" aria-hidden /> E-STOP
        </Button>
        <Button
          variant="outline"
          onClick={() => release.mutate()}
          disabled={release.isPending || !robot.emergency_active}
        >
          <ShieldCheck className="mr-1 size-4" aria-hidden /> Release software E-stop
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {robot.emergency_active
          ? "Software E-stop is ON. Nothing can move this robot."
          : "While an E-stop is on, no command, including manual driving, can move the robot."}
      </p>
    </div>
  );
}
