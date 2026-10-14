import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Bot, Code2, Loader2, ShieldCheck, UserCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Role } from "@/lib/api/types";
import { homeRouteFor, useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/login")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Sign in — Robot Fleet Control" },
      {
        name: "description",
        content: "Operator, admin and developer sign-in for the robot fleet control system.",
      },
      { property: "og:title", content: "Sign in — Robot Fleet Control" },
      {
        property: "og:description",
        content: "Operator, admin and developer sign-in for the robot fleet control system.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LoginPage,
});

const PORTALS: { role: Role; label: string; hint: string; icon: typeof UserCog }[] = [
  {
    role: "operator",
    label: "Operator",
    hint: "Send robots to waypoints and run missions.",
    icon: UserCog,
  },
  {
    role: "admin",
    label: "Admin",
    hint: "Robots, JSON and map files, accounts.",
    icon: ShieldCheck,
  },
  {
    role: "developer",
    label: "Developer",
    hint: "Everything, plus topic configuration.",
    icon: Code2,
  },
];

function LoginPage() {
  const { login, user, ready, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [portal, setPortal] = useState<Role>("operator");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (ready && isAuthenticated) navigate({ to: homeRouteFor(user), replace: true });
  }, [ready, isAuthenticated, user, navigate]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      // The server checks that this account may use the chosen panel.
      const signedIn = await login(username.trim(), password, portal);
      toast.success(`Signed in as ${signedIn.username}`);
      navigate({ to: homeRouteFor(signedIn), replace: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sign-in failed");
    } finally {
      setPending(false);
    }
  }

  const current = PORTALS.find((p) => p.role === portal) ?? PORTALS[0];

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-4 flex size-12 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Bot className="size-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Robot Fleet Control</h1>
        </div>

        <div role="tablist" aria-label="Sign in as" className="mb-4 grid grid-cols-3 gap-2">
          {PORTALS.map(({ role, label, icon: Icon }) => (
            <button
              key={role}
              type="button"
              role="tab"
              aria-selected={portal === role}
              onClick={() => setPortal(role)}
              className={cn(
                "flex flex-col items-center gap-1 rounded-lg border p-3 text-sm transition-colors",
                portal === role
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </button>
          ))}
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-border bg-card p-6"
        >
          <p className="text-xs text-muted-foreground">{current.hint}</p>
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <Button type="submit" className="w-full" disabled={pending}>
            {pending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Sign in as {current.label.toLowerCase()}
          </Button>
        </form>
      </div>
    </main>
  );
}
