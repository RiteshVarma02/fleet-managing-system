import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Bot, Loader2, ShieldCheck, UserCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { homeRouteFor, useAuth } from "@/lib/auth";

export const Route = createFileRoute("/login")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Sign in — Robot Fleet Control" },
      { name: "description", content: "Operator and administrator sign-in for the autonomous robot fleet control system." },
      { property: "og:title", content: "Sign in — Robot Fleet Control" },
      { property: "og:description", content: "Operator and administrator sign-in for the autonomous robot fleet control system." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { login, user, ready, isAuthenticated } = useAuth();
  const navigate = useNavigate();
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
      const signedIn = await login(username.trim(), password);
      toast.success(`Signed in as ${signedIn.username}`);
      navigate({ to: homeRouteFor(signedIn), replace: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sign-in failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="mb-4 flex size-12 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Bot className="size-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Robot Fleet Control</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to monitor and operate the fleet</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-border bg-card p-6">
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
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
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          <Button type="submit" className="w-full" disabled={pending}>
            {pending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Sign in
          </Button>
        </form>

        <div className="mt-6 grid grid-cols-2 gap-3 text-xs text-muted-foreground">
          <div className="rounded-lg border border-border p-3">
            <ShieldCheck className="mb-1 size-4 text-primary" aria-hidden />
            <p className="font-medium text-foreground">Administrator</p>
            <p>Full fleet monitoring, approvals and robot lifecycle.</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <UserCog className="mb-1 size-4 text-primary" aria-hidden />
            <p className="font-medium text-foreground">Operator</p>
            <p>Drive a single robot and dispatch pick &amp; drop tasks.</p>
          </div>
        </div>
      </div>
    </main>
  );
}
