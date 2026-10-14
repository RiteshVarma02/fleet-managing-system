import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api/client";
import {
  pendingRegistrationsQuery,
  queryKeys,
  robotTypesQuery,
  usersQuery,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function TypeSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data: types = [] } = useQuery(robotTypesQuery());
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8" aria-label="Robot type">
        <SelectValue placeholder="Robot type" />
      </SelectTrigger>
      <SelectContent>
        {types.map((t) => (
          <SelectItem key={t.name} value={t.name}>
            {t.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Add a robot by its ROS namespace, the same name used in its topics. */
export function AddRobotCard() {
  const queryClient = useQueryClient();
  const [robotId, setRobotId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const valid = /^[A-Za-z][A-Za-z0-9_]*$/.test(robotId);

  const add = useMutation({
    mutationFn: () =>
      api.post("/robots", {
        robot_id: robotId,
        name: name || undefined,
        robot_type: type || undefined,
        connect: true,
      }),
    onSuccess: () => {
      toast.success(`Robot ${robotId} added`);
      setRobotId("");
      setName("");
      queryClient.invalidateQueries({ queryKey: queryKeys.robots });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Card title="Add robot">
      <div className="space-y-2">
        <Input
          value={robotId}
          onChange={(e) => setRobotId(e.target.value)}
          placeholder="ROS namespace, e.g. robot1"
          className="h-8"
          aria-label="Robot id"
        />
        {robotId && !valid && (
          <p className="text-xs text-destructive">
            Start with a letter; use letters, digits and _ only.
          </p>
        )}
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Display name (optional)"
          className="h-8"
          aria-label="Display name"
        />
        <TypeSelect value={type} onChange={setType} />
        <Button size="sm" disabled={!valid || add.isPending} onClick={() => add.mutate()}>
          <Plus className="mr-1 size-4" aria-hidden /> Add
        </Button>
        <p className="text-xs text-muted-foreground">
          Topics become /{robotId || "robot1"}/amr/goal and so on (see Developer → Topics).
        </p>
      </div>
    </Card>
  );
}

/** Robots that announced themselves and wait for approval. */
export function PendingCard() {
  const queryClient = useQueryClient();
  const { data: pending = [] } = useQuery(pendingRegistrationsQuery());
  const [names, setNames] = useState<Record<string, string>>({});
  const [types, setTypes] = useState<Record<string, string>>({});

  const done = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.pendingRegistrations });
    queryClient.invalidateQueries({ queryKey: queryKeys.robots });
  };
  const approve = useMutation({
    mutationFn: (mac: string) =>
      api.post("/robots/registrations/approve", {
        mac_address: mac,
        custom_name: (names[mac] ?? "").trim(),
        robot_type: types[mac] || undefined,
      }),
    onSuccess: () => {
      toast.success("Robot approved");
      done();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const reject = useMutation({
    mutationFn: (mac: string) => api.post("/robots/registrations/reject", { mac_address: mac }),
    onSuccess: done,
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Card title={`Waiting for approval (${pending.length})`}>
      {pending.length === 0 && <p className="text-sm text-muted-foreground">Nothing waiting.</p>}
      <ul className="space-y-3">
        {pending.map((r) => (
          <li key={r.mac_address} className="rounded-md border border-border p-3">
            <p className="font-mono text-xs">{r.mac_address}</p>
            <p className="mb-2 text-xs text-muted-foreground">
              {r.hostname ?? "unknown host"} · {r.ip_address ?? "no ip"}
            </p>
            <div className="space-y-2">
              <Input
                placeholder="Robot name (becomes its namespace)"
                value={names[r.mac_address] ?? ""}
                onChange={(e) => setNames((p) => ({ ...p, [r.mac_address]: e.target.value }))}
                className="h-8"
                aria-label={`Name for ${r.mac_address}`}
              />
              <div className="flex gap-2">
                <div className="flex-1">
                  <TypeSelect
                    value={types[r.mac_address] ?? ""}
                    onChange={(v) => setTypes((p) => ({ ...p, [r.mac_address]: v }))}
                  />
                </div>
                <Button
                  size="sm"
                  aria-label="Approve"
                  disabled={!(names[r.mac_address] ?? "").trim() || approve.isPending}
                  onClick={() => approve.mutate(r.mac_address)}
                >
                  <CheckCircle2 className="size-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="Reject"
                  onClick={() => reject.mutate(r.mac_address)}
                >
                  <CircleSlash className="size-4" />
                </Button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Admins manage operators; developers manage everyone. The server enforces it. */
export function UsersCard() {
  const { user, isDeveloper } = useAuth();
  const queryClient = useQueryClient();
  const { data: users = [] } = useQuery(usersQuery());
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");
  const roles = isDeveloper ? ["operator", "admin", "developer"] : ["operator"];
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.users });

  const create = useMutation({
    mutationFn: () => api.post("/users", { username, password, role }),
    onSuccess: () => {
      toast.success(`Account ${username} created`);
      setUsername("");
      setPassword("");
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const toggle = useMutation({
    mutationFn: (u: { id: string; active: boolean }) =>
      api.patch(`/users/${u.id}`, { active: u.active }),
    onSuccess: refresh,
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Card title="Accounts">
      <ul className="mb-4 space-y-2 text-sm">
        {users.map((u) => (
          <li key={u.id ?? u.username} className="flex items-center justify-between gap-2">
            <span className="truncate">
              {u.username}{" "}
              <Badge variant="outline" className="ml-1 uppercase">
                {u.role}
              </Badge>
              {!u.active && <span className="ml-1 text-xs text-muted-foreground">(disabled)</span>}
            </span>
            {u.id && u.username !== user?.username && (isDeveloper || u.role === "operator") && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => toggle.mutate({ id: u.id as string, active: !u.active })}
              >
                {u.active ? "Disable" : "Enable"}
              </Button>
            )}
          </li>
        ))}
      </ul>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="New username"
          className="h-8"
          aria-label="New username"
        />
        <Input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          placeholder="Password (8+ characters)"
          className="h-8"
          aria-label="New password"
        />
        <Select value={role} onValueChange={setRole}>
          <SelectTrigger className="h-8" aria-label="Role">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r} value={r} className="capitalize">
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="submit"
          size="sm"
          disabled={username.length < 3 || password.length < 8 || create.isPending}
        >
          Create account
        </Button>
      </form>
    </Card>
  );
}
