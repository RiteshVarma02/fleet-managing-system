import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";
import { Bot, LogOut, OctagonX, ShieldCheck, UserCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { queryKeys, systemInfoQuery } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app")({
  ssr: false,
  component: AppLayout,
});

function AppLayout() {
  const { ready, isAuthenticated, isAdmin, user, logout } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  useEffect(() => {
    if (ready && !isAuthenticated) navigate({ to: "/login", replace: true });
  }, [ready, isAuthenticated, navigate]);

  const { data: system } = useQuery({ ...systemInfoQuery(), enabled: isAuthenticated });

  const stopAll = useMutation({
    mutationFn: () => api.post<{ message: string }>("/robots/emergency-stop-all"),
    onSuccess: (result) => {
      toast.warning(result?.message ?? "Emergency stop broadcast");
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (!ready || !isAuthenticated) return <div className="min-h-screen bg-background" />;

  const navItems = isAdmin
    ? [
        { to: "/fleet", label: "Fleet monitor", icon: ShieldCheck },
        { to: "/console", label: "Control console", icon: UserCog },
      ]
    : [{ to: "/console", label: "Control console", icon: UserCog }];

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-border bg-card px-4">
        <Link to={isAdmin ? "/fleet" : "/console"} className="flex items-center gap-2 font-semibold">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Bot className="size-4" aria-hidden />
          </span>
          <span className="hidden sm:inline">Fleet Control</span>
        </Link>

        <nav className="flex items-center gap-1">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
                pathname.startsWith(item.to) && "bg-accent text-accent-foreground",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-2 text-xs text-muted-foreground md:flex">
            <span
              className={cn("size-2 rounded-full", system?.ros_available ? "bg-chart-2" : "bg-muted-foreground")}
              aria-hidden
            />
            ROS {system?.ros_available ? "online" : "offline"}
          </span>

          <Button
            variant="destructive"
            size="sm"
            onClick={() => stopAll.mutate()}
            disabled={stopAll.isPending}
            className="gap-2"
          >
            <OctagonX className="size-4" aria-hidden />
            <span className="hidden sm:inline">E-STOP ALL</span>
          </Button>

          <div className="hidden text-right sm:block">
            <p className="text-sm font-medium leading-none">{user?.username}</p>
            <p className="text-xs uppercase text-muted-foreground">{user?.role}</p>
          </div>

          <Button
            variant="ghost"
            size="icon"
            aria-label="Sign out"
            onClick={async () => {
              await queryClient.cancelQueries();
              queryClient.clear();
              logout();
              navigate({ to: "/login", replace: true });
            }}
          >
            <LogOut className="size-4" />
          </Button>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
