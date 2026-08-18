# Fleet Management System

Web control plane for a heterogeneous ROS 2 robot fleet: a FastAPI + MongoDB
backend that owns the ROS runtime and per-robot domain bridges, and a React
dashboard for administrators and operators.

- Backend documentation and API reference: [`backend/README.md`](backend/README.md)

## Roles

| Role | Landing page | Can do |
| --- | --- | --- |
| Administrator | `/fleet` | Monitor every robot on the map, approve/reject robot registrations (name + robot type), watch domain-bridge health, remove robots, connect/disconnect, jump into any console |
| Operator | `/console` | Pick one robot, teleoperate it with the joystick, send Nav2 goals, dock/undock, fork/gripper commands, dispatch and cancel pick & drop missions, while still seeing the whole fleet on the map |

## Run it

```bash
# 1. backend (see backend/README.md for the full setup)
cd backend && cp .env.example .env
docker compose up -d --build

# 2. frontend
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000/api/v1
bun install
bun run dev
```

Sign in with the bootstrap credentials from `backend/.env`
(`BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_OPERATOR_USERNAME`) and change the
passwords afterwards.

## Frontend architecture

```
src/
  lib/api/client.ts      fetch wrapper: bearer token, envelope unwrap, GET de-dup
  lib/api/queries.ts     TanStack Query options + the whole polling budget
  lib/api/telemetry.ts   one shared WebSocket, merged into the query caches
  lib/api/types.ts       mirrors backend/app/schemas/*
  lib/auth.tsx           JWT session, role routing, 401 handling
  components/fleet/      FleetMap (canvas occupancy grid), Joystick,
                         RobotCard, CapabilityPanel
  routes/                login, _app layout (E-stop + health), fleet, console
```

### Keeping backend load low

- **One WebSocket per tab.** `/telemetry/ws` delivers a single fleet-wide frame
  per interval; samples are merged into the existing `robots` and
  `robots/:id/status` caches, so components keep using the same hooks.
- **Polling backs off when the socket is up:** fleet list 3s → 30s, per-robot
  telemetry 1s → off. If the socket drops, polling resumes automatically, so the
  UI degrades instead of freezing.
- **Static data is fetched once:** robot types are cached for the session, the
  occupancy grid for 10 minutes, locations for 5.
- **Identical in-flight GETs are de-duplicated** in the client, so several
  widgets reading the same resource cost one request.
- **Teleop is throttled** in the joystick component and mission progress is read
  from the task engine's in-memory state, never from a database scan.
- **Capability-driven UI:** each robot reports its capabilities, so fork and
  gripper controls only appear for robots that have them — adding a robot type
  server-side needs no frontend change.
