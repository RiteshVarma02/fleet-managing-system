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
  routes/                login, _app layout (E-stop + health), fleet, console,
                         maps (upload/activate, build from a robot, map sharing)
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

## Facility maps

The Maps page (`/maps`) is the single place to manage the fleet's facility map:

- **Upload & activate** — upload a PNG/PGM/JPG that becomes the active fleet
  map, published on the server domain's `/map`.
- **Build from a robot** — pick a robot, *Start SLAM*, watch its grid grow live
  (polled every 2s), then *Save map* (`.pgm`+`.yaml`+`.png` written straight
  from the captured grid — no `map_saver_cli`) and *Activate* it fleet-wide.
- **Use a robot's map** — on the console, promote a robot's own map to the
  fleet map without saving it first.
- **Send the map to robots** — toggle *map sharing* per robot: the server's
  `/map` is bridged down to the robot's domain (`map_share_enabled`) so its
  Nav2 can consume the static map.

## Testing

- **Backend:** `cd backend && python -m pytest` — grid↔image round-trip,
  ROS-domain assignment and domain-bridge config (with/without map-share).
  Test dependencies live in `backend/requirements-dev.txt`.
- **Frontend:** `npm run typecheck` (`tsgo --noEmit`) and `npm run lint`.
