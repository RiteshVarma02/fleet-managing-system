# Fleet Management System: Backend

FastAPI + MongoDB + ROS 2 control plane for a fleet of waypoint-driven robots.
One server process owns the ROS runtime. All robots share one ROS domain and
are namespaced `/{robot}/...`.

```
backend/
  app/
    api/            HTTP/WS layer (deps, error handlers, v1 routers)
    core/           config, logging, security, exceptions
    db/             Motor client, document helpers, repositories
    ros/            rclpy lifecycle, topic registry, capabilities, registration
    schemas/        Pydantic request/response models
    services/       business logic (robots, missions, fleet files, telemetry)
    main.py         app factory + lifespan
  config/fleet_topics.yaml    every topic, type and QoS (the one place)
  requirements.txt  Dockerfile  docker-compose.yml  .env.example
```

## Layering rule

`api -> services -> repositories -> MongoDB`, with `app/ros/*` as the only code
that touches `rclpy`. Routers never hold business logic, services never build
HTTP responses, and only `app/ros/manager.py` owns node and executor lifetimes.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set JWT_SECRET and the bootstrap passwords
docker run -d -p 27017:27017 --name fleet-mongo mongo:7

# The API boots without ROS installed (robot endpoints answer 503):
ROS_ENABLED=false uvicorn app.main:app --reload
```

With ROS 2 Humble sourced, drop `ROS_ENABLED=false`. API docs are at
`http://localhost:8000/docs` (off when `ENVIRONMENT=production`).

## Configuration

Environment driven (`app/core/config.py`, see `.env.example`).

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | Signing key. Required in production. |
| `BOOTSTRAP_{DEVELOPER,ADMIN,OPERATOR}_{USERNAME,PASSWORD}` | Accounts created on first start. Production requires the developer password; admin and operator are created only if their password is set. |
| `MONGO_MODE` / `MONGO_URI` | `local` or `atlas` (`mongodb+srv://...`). |
| `ROS_ENABLED`, `ROS_DOMAIN_ID` | The single shared ROS domain (default 0). |
| `FLEET_TOPICS_FILE` | Path of the topic config (default `config/fleet_topics.yaml`). |
| `WAYPOINT_ARRIVAL_DEBOUNCE_SECONDS` | Ignore an "arrived" message this soon after a goal is sent (default 1.5). |
| `NAV_GOAL_TIMEOUT_SECONDS` | Fail a leg that never arrives. |
| `MAX_TASK_STOPS`, `MAX_TASK_REPEATS` | Mission size limits (50 stops, 1000 repeats). |
| `FLEET_FILES_ACK_TIMEOUT_SECONDS` | How long a push waits for each robot's reply (default 8). |
| `TELEMETRY_FLUSH_INTERVAL_SECONDS`, `TELEMETRY_WS_INTERVAL_SECONDS` | Telemetry write and WebSocket rates. |
| `AUTOSTART_ROBOT_CONTROLLERS` | Reconnect approved robots on boot. |

## Topics and robot types

`config/fleet_topics.yaml` lists, per robot type, a **logical name** (`goal`,
`pose`, `stop_active`, ...) mapped to `{name, type, qos}`. Code only uses the
logical names. `{robot}` in a name is replaced by the robot id.

| Logical name | Topic | Type | Direction |
| --- | --- | --- | --- |
| `goal` | `/{robot}/amr/goal` | `std_msgs/String` (waypoint name) | server to robot |
| `goal_reached` | `/{robot}/amr/final_goal_reached` | `std_msgs/Bool` | robot to server |
| `route_abort` | `/{robot}/amr/route` | `nav_msgs/Path` (empty = halt) | server to robot |
| `pose` | `/{robot}/amcl_pose` | `PoseWithCovarianceStamped` | robot to server |
| `battery` | `/{robot}/battery_state` | `sensor_msgs/BatteryState` | robot to server |
| `stop_active` | `/{robot}/stop_active` | `std_msgs/Bool` (true = button pressed) | robot to server |
| `emergency_stop` | `/{robot}/emergency_stop` | `std_msgs/Bool` | server to robot |
| `cmd_vel` | `/{robot}/cmd_vel` | `geometry_msgs/Twist` | server to robot |
| `file_update` / `file_ack` | `/{robot}/fleet/file_update` / `file_ack` | `std_msgs/String` (JSON) | both |

A robot type is `extends` + `capabilities` + `topics`. `app/ros/robot_factory.py`
builds the controller class from one mixin per capability in
`app/ros/capabilities/` (`waypoint_nav`, `telemetry`, `emergency`, `movement`,
`fleet_files`, plus `docking`, `fork_control`, `arm_control` for other kinds).
To add a robot kind: a YAML entry and, if needed, one capability file.
Developers can view the parsed config and reload it (`GET /system/topics`,
`POST /system/topics/reload`); already-connected robots keep their old topics
until reconnected.

## Missions

A mission is an ordered list of waypoint **names**, a repeat count and a mode:

- `continuous`: stop to stop without waiting.
- `step` ("move on click"): after every arrival except the very last, the task
  enters `awaiting_approval` until the operator presses Continue.

A single waypoint is a one-stop mission. Names are checked against the active
graph (when one is uploaded). `final_goal_reached` carries no goal id, so each
goal gets an epoch and arrivals within the debounce window are ignored. The task
engine reads robot state from memory and writes to Mongo only on transitions.
A server restart resets running missions to `pending`; it never moves a robot.

## Safety

- A physical E-stop (`stop_active` true) or the dashboard E-stop puts the robot
  in a *safety hold*: it is halted, its mission is **paused (not failed)**.
- While held, the controller turns any non-zero velocity into a stop and the
  dock / fork / gripper endpoints answer `409 safety_hold`. Teleop cannot override
  an E-stop. Plain stop is always allowed.
- Releasing the button does not resume. An operator presses Continue, which is
  refused while the hold is active. Approve ("go") is refused too.

## Robot status

One pure function (`services/robot_status.py`) decides the status shown
everywhere. First match wins: `offline`, `stop_active` (red), `e_stopped`,
`awaiting_approval`, `paused`, `error`, `moving`, `idle`.

## Fleet files (graph JSON and map)

One graph and one map for the whole fleet, stored versioned in Mongo (file bytes
in GridFS). Pushing publishes a JSON update on `/{robot}/fleet/file_update`
(base64 + sha256); the robot-side receiver
([`tools/fleet_files`](../tools/fleet_files/README.md)) verifies it, writes
atomically with a `.bak`, and replies on `file_ack`. Rollback = make an older
version active, then push. `app/services/fleet_file_protocol.py` is a copy of the
tools one (a test fails if they differ).

## Roles

`developer` > `admin` > `operator`; each includes the roles below. Unknown or
retired roles (the old `viewer`) have no access, and old viewer accounts are
disabled at startup. Admins can only manage operator accounts; developers manage
everyone; nobody can disable themselves or remove the last developer.
`POST /auth/login` accepts an optional `portal` and refuses accounts below it.

## Onboarding a robot

Either an admin adds it by namespace (`POST /robots`), or the robot announces its
MAC (`/robot/register` topic or `POST /robots/register`) and an admin approves it
with a name (which becomes its namespace) and type. Approved robots reconnect
automatically.

## API (`/api/v1`)

| Group | Endpoints |
| --- | --- |
| system | `GET /health`, `/ready`, `/system/info`; developer: `GET /system/topics`, `POST /system/topics/reload` |
| auth | `POST /auth/login`, `GET /auth/me` |
| users | `GET/POST /users`, `PATCH /users/{id}`, `POST /users/me/password` |
| robots | `GET/POST /robots`, `GET /robots/types`, `POST /robots/connect|disconnect`, `GET /robots/{id}/status`, `DELETE /robots/{id}` |
| teleop | `POST /robots/move|stop` |
| emergency | `POST /robots/emergency-stop|emergency-stop-all|emergency-release` |
| extras | `POST /robots/dock|fork|gripper` (robot types that have them) |
| registration | `POST /robots/register`, `GET /robots/registrations/pending`, `POST /robots/registrations/approve|reject` |
| missions | `POST /tasks/missions`, `POST /tasks/waypoint`, `GET /tasks/robot/{id}/progress`, `POST /tasks/robot/{id}/pause|resume|cancel` |
| tasks | `GET/POST /tasks`, `GET/PATCH /tasks/{id}`, `POST /tasks/{id}/start`, `GET /tasks/{id}/history|progress` |
| queue | `POST /tasks/requests`, `GET /tasks/requests/unassigned`, `POST /tasks/requests/{id}/cancel` |
| fleet files | `GET /fleet-files`, `/fleet-files/status`, `/fleet-files/map/preview`, `POST /fleet-files/graph|map`, `GET /fleet-files/{kind}/download`, `POST /fleet-files/{kind}/versions/{n}/activate`, `POST /fleet-files/{kind}/push` |
| waypoints | `GET /waypoints` (from the active graph) |
| telemetry | `WS /telemetry/ws?token=<jwt>` one fleet frame per interval |

Reads need any signed-in user; mission and robot commands need operator;
fleet-file changes, robot add/remove/approve need admin; topic config needs
developer.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

They cover topic config parsing, the waypoint tracker, status derivation,
mission execution (continuous, move on click, E-stop pause), E-stop over teleop,
fleet-file storage/push with fake ROS, roles and authorization.

## Load characteristics

ROS callbacks write into `services/telemetry_bus.py`, drained by two loops: one
bulk Mongo write and one WebSocket frame per interval. Database load does not
depend on ROS publish rate, and network cost does not depend on operator count.

## Deploy

```bash
export JWT_SECRET=... BOOTSTRAP_DEVELOPER_PASSWORD=... \
       BOOTSTRAP_ADMIN_PASSWORD=... BOOTSTRAP_OPERATOR_PASSWORD=...
docker compose up -d --build
```

- Run **one** uvicorn worker per host: ROS nodes and task state are process-local.
- `network_mode: host` is required for DDS discovery.
- Health: `GET /api/v1/health` (liveness), `GET /api/v1/ready` (Mongo check).
