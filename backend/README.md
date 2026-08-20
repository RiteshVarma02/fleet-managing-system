# Fleet Management System — Backend

FastAPI + MongoDB + ROS 2 control plane for a heterogeneous robot fleet.
One server process owns the ROS runtime, one `domain_bridge` process per robot
carries topics across `ROS_DOMAIN_ID` boundaries, and a robot-side action
forwarder handles Nav2 (actions cannot cross a domain bridge).

```
backend/
  app/
    api/            HTTP/WS layer (deps, error handlers, v1 routers)
    core/           config, logging, security, exceptions
    db/             Motor client, document helpers, repositories
    ros/            rclpy lifecycle, capabilities, domain bridge, registration
    schemas/        Pydantic request/response models
    services/       business logic (robots, tasks, maps, telemetry, registration)
    main.py         app factory + lifespan
  deploy/
    robot_action_forwarder.py   runs ON the robot: bridges Nav2 actions <-> topics
  requirements.txt  Dockerfile  docker-compose.yml  .env.example
```

## Layering rule

`api -> services -> repositories -> MongoDB`, with `app/ros/*` as the only code
that touches `rclpy`. Routers never query collections for business logic,
services never build HTTP responses, and only `app/ros/manager.py` owns node,
executor and bridge lifetimes.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set JWT_SECRET and the bootstrap passwords

# MongoDB (local)
docker run -d -p 27017:27017 --name fleet-mongo mongo:7

# The API boots fine without ROS installed:
ROS_ENABLED=false uvicorn app.main:app --reload
```

With ROS 2 Humble sourced, drop `ROS_ENABLED=false` and the runtime, the
registration listener and the per-robot bridges start automatically.
Docs at `http://localhost:8000/docs` (disabled when `ENVIRONMENT=production`).

## Configuration

Everything is environment driven (`app/core/config.py`, see `.env.example`).
The settings that matter most in production:

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | Signing key. Required in production; startup fails without it. |
| `MONGO_MODE` / `MONGO_URI` | `local` or `atlas` (`mongodb+srv://…`). |
| `ROS_ENABLED`, `ROS_DOMAIN_ID` | Server-side ROS graph. Domain `0` by default. |
| `DOMAIN_BRIDGE_ENABLED` | Spawn one `domain_bridge` per approved robot. |
| `DOMAIN_BRIDGE_DEFAULT_ROBOT_DOMAIN` | First domain id handed to a new robot. |
| `TELEMETRY_FLUSH_INTERVAL_SECONDS` | Bulk-write interval for the telemetry buffer. |
| `TELEMETRY_WS_INTERVAL_SECONDS` | WebSocket frame interval for the fleet. |
| `AUTOSTART_ROBOT_CONTROLLERS` | Reconnect approved robots on boot. |

## Robot types and capabilities

`app/ros/topics_registry.py` is the single declarative source of truth. Each
robot type lists its logical topics (message type, robot-side name, server-side
name, bridge direction) and the capabilities it implies:

| Type | Capabilities |
| --- | --- |
| `differential_drive` | movement, navigation, telemetry, emergency, docking |
| `forklift_bot` | + fork_control |
| `arm_bot` | + arm_control |

`app/ros/robot_factory.py` composes a controller class per type from the mixins
in `app/ros/capabilities/`, and `app/ros/domain_bridge.py` generates the bridge
YAML from the same registry. Adding a robot type is a registry entry plus (if
needed) one capability module — no endpoint or frontend change required, since
`GET /robots/types` and the per-robot `capabilities` field drive the UI.

## Domain bridge and the action forwarder

Every robot runs on its own `ROS_DOMAIN_ID`, assigned at approval time. For each
approved robot the server writes `data/bridges/<robot_id>.yaml` and supervises
one `domain_bridge` process (backoff + restart cap, status via
`GET /robots/bridges`). Topics move in the direction the registry declares:
telemetry up to the server domain, commands down to the robot domain.

Nav2 uses **actions**, which a domain bridge cannot carry. Run
`deploy/robot_action_forwarder.py` on each robot: it subscribes to the bridged
`goal_request` topic, drives the local `navigate_to_pose` action client, and
publishes progress back on `navigation_status`.

```bash
# on the robot (its own domain id)
ROS_DOMAIN_ID=2 python3 robot_action_forwarder.py --robot-id robot_1
```

## Zero-touch onboarding

1. The robot announces itself by MAC address (`/robot/register` topic, or
   `POST /api/v1/robots/register`).
2. A known, approved MAC is reconnected immediately: bridge + controller start
   and the reply carries the robot's assigned identity.
3. An unknown MAC becomes a pending registration. An admin approves it with a
   name, robot type and (optionally) a domain id — then the bridge and
   controller start and the robot is live.

## Maps and map sharing

The server owns the fleet map (`nav_msgs/OccupancyGrid` on `/map` on the server
domain) plus a set of named maps under `maps/`. All flows are on the **Maps**
page in the dashboard:

- **Upload & activate** — `POST /maps/load` turns an uploaded PNG/PGM/JPG into
  an OccupancyGrid and makes it the active map; `GET /maps/current` serves the
  current grid as a base64 image, `GET /maps` lists the saved maps (with the
  `active` flag).
- **Build from a robot** — `POST /maps/slam/start` runs cartographer on a
  robot; `GET /robots/{id}/map` returns its growing grid (polled every 2s in
  the UI); `POST /maps/save-from-robot` writes `.pgm`/`.yaml`/`.png` straight
  from the captured grid (no `map_saver_cli` involved); `POST /maps/activate`
  then promotes it fleet-wide. `POST /maps/from-robot` does save-and-activate
  in one step from the console.
- **Map sharing** — `POST /robots/{id}/map-share` toggles
  `map_share_enabled` on the robot document and regenerates its bridge YAML
  with an extra DOWN `/map` topic (server `/map` → robot `/map`), restarting
  the bridge when the robot is connected so its Nav2 picks up the fleet map.
  The YAML key `/map` is deliberately distinct from the robot's own UP `/map`
  entry (key `map`) so the two never collide in the bridge config.

The same registry (`topics_registry.py`) drives the normal bridge config; the
map-share entry is the only special case, added by `build_bridge_config(…,
share_map=True)`.

## Tests

Unit tests cover the pieces that are easy to get subtly wrong and are needed
across every map milestone:

- Grid ↔ image round-trip (`tests/test_map_conversion.py`) — cell-class mapping
  (free/occupied/unknown), metadata (resolution/origin) and the bottom-up row
  flip must round-trip exactly.
- Domain-bridge config (`tests/test_domain_bridge.py`) — UP/DOWN topic
  direction and remap shape, and the with/without map-share variants
  (`/map` DOWN topic appears only when sharing; no key collision).
- ROS-domain assignment (`tests/test_domain_validation.py`) — `next_domain_id`
  skips used/soft-deleted domains and the server's own reserved domain, plus
  the Pydantic range checks on `ros_domain_id`.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest          # honours pytest.ini (disables ROS pytest plugins)
```

## Load characteristics

The hot path never touches MongoDB. ROS callbacks write into
`services/telemetry_bus.py`, which is drained by exactly two loops: one bulk
Mongo write and one WebSocket frame per interval. Consequently:

- Database write volume is independent of ROS publish rate.
- Network cost is independent of the number of connected operators (`O(1)`
  serialisation, one frame fanned out to all subscribers).
- `GET /robots`, `/robots/{id}/status` and task progress are served from
  in-memory state, so the UI can render live values with almost no query load.
- One asyncio task per *running task* (not per robot), cancellable, with Mongo
  writes only on state transitions.

## API surface (`/api/v1`)

| Group | Endpoints |
| --- | --- |
| system | `GET /health`, `GET /ready`, `GET /system/info` |
| auth | `POST /auth/login`, `GET /auth/me` |
| users | `GET/POST /users`, `PATCH /users/{id}`, `POST /users/me/password` (admin except the last) |
| robots | `GET /robots`, `GET /robots/types`, `GET /robots/bridges`, `GET /robots/domains/next`, `POST /robots/connect|disconnect`, `GET /robots/{id}/status`, `GET /robots/{id}/map`, `POST /robots/{id}/map-share`, `DELETE /robots/{id}` |
| teleop | `POST /robots/move|stop|emergency-stop|emergency-stop-all` |
| capabilities | `POST /robots/goal`, `/robots/goal/cancel`, `/robots/initial-pose`, `/robots/dock`, `/robots/fork`, `/robots/gripper` |
| registration | `POST /robots/register`, `GET /robots/registrations/pending`, `POST /robots/registrations/approve|reject` |
| locations | `GET/POST /locations`, `DELETE /locations/{id}` |
| tasks | `GET/POST /tasks`, `GET /tasks/{id}`, `PATCH /tasks/{id}`, `GET /tasks/{id}/history`, `POST /tasks/{id}/start|cancel`, `GET /tasks/{id}/progress` |
| pick & drop | `POST /tasks/pickdrop/start|stop`, `GET /tasks/pickdrop/{robot_id}/status` |
| requests | `POST /tasks/requests`, `GET /tasks/requests/unassigned` (auto-assigned to idle robots) |
| maps | `GET /maps`, `GET /maps/current`, `GET /maps/slam/status`, `POST /maps/load|activate|from-robot|save-from-robot|save|slam/start|slam/stop`, `DELETE /maps/{name}` |
| telemetry | `WS /telemetry/ws?token=<jwt>` — one fleet frame per interval |

Roles: `admin` can manage users, approve robots and delete them; `operator` can
command robots and dispatch tasks; both can read.

## Deploy

```bash
export JWT_SECRET=... BOOTSTRAP_ADMIN_PASSWORD=... BOOTSTRAP_OPERATOR_PASSWORD=...
docker compose up -d --build
```

Notes:

- Run **one** uvicorn worker per host: ROS nodes, bridge processes and task
  state are process-local. Scale by sharding robots across hosts.
- `network_mode: host` is required — DDS discovery and `domain_bridge` need it.
- Health: `GET /api/v1/health` (liveness), `GET /api/v1/ready` (Mongo check).
- Change the bootstrap admin/operator passwords after the first login
  (`POST /users/me/password`).
