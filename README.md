# Fleet Management System (V1)

Web control plane for a fleet of waypoint-driven ROS 2 robots. A FastAPI +
MongoDB backend owns the ROS runtime; a React dashboard gives operators, admins
and developers their own panel.

- Backend details and API list: [`backend/README.md`](backend/README.md)
- Pushing the graph JSON / map to robots from a terminal: [`tools/fleet_files/README.md`](tools/fleet_files/README.md)
- Why things are built this way: [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md)
- What is done and what is next: [`docs/PROGRESS.md`](docs/PROGRESS.md)

## How it works

- **One ROS domain, no Nav2.** The server and every robot share one domain.
  Robots are namespaced `/{robot}/...`; the robot id *is* its ROS namespace.
- **Waypoints only.** To send a robot somewhere the server publishes the
  waypoint **name** on `/{robot}/amr/goal` and waits for
  `/{robot}/amr/final_goal_reached`, the same interface as `mission_commander.py`.
  `route_manager` and `traffic_manager_node` must be running.
- **Topics are never hard-coded.** Every topic name, message type and QoS lives
  in [`backend/config/fleet_topics.yaml`](backend/config/fleet_topics.yaml).
- **One graph and one map for the whole fleet.** Upload them on the website;
  every robot gets a copy.

## Roles

Each role includes everything the roles below it can do.

| Role | Lands on | Can do |
| --- | --- | --- |
| Operator | Operate | See the map and robot status, send a robot to a waypoint, build and run missions, Pause / Continue / Cancel, E-stop, manual drive |
| Admin | Admin | Everything above, plus add / approve / connect / remove robots, upload and send the JSON graph and map, manage operator accounts |
| Developer | Developer | Everything, plus view and reload the topic configuration, manage all accounts |

The login page has a tab per role. The server refuses a login on a panel the
account's role is too low for (an operator cannot use the Admin tab).

## Using it

**Go to a waypoint.** Pick a robot, type the waypoint name (or click it on the
map), press Send.

**Missions.** Press *Add stop* for each waypoint in order (or click waypoints on
the map), set *Repeat* (for example 1 → 2 → 5 → 7 → 8 repeated 50 times), then
choose a mode:

- *Move continuously*: the robot goes stop to stop without waiting.
- *Move on click*: the robot stops at every stop and waits for you to press
  **Continue**. Starting the mission is the click for the first move.

**Controls.** One set per robot: **Pause**, **Continue**, **Cancel mission**.

**Emergency stop.**

- A pressed physical button publishes `true` on `/{robot}/stop_active`
  (`std_msgs/Bool`). The robot shows **red**, stops, and its mission is paused
  (not failed).
- *E-STOP* on the dashboard is the software equivalent.
- While any E-stop is on, **nothing can move the robot**, manual drive included.
- After release the robot stays stopped until an operator presses Continue.
- Manual drive and E-stop are separate controls.

**Status** shown on the map and cards: Offline, Idle, Moving, Paused, Waiting for
click, E-STOP (button), E-STOP (software), Error.

**Files (Admin → JSON & map files).** Upload a new graph JSON or map (`.yaml` +
image), download any version, make an older version active again, then *Send to
all robots*. The table shows which robots are up to date. Robots need
[`fleet_file_receiver.py`](tools/fleet_files/README.md) running.

## Run it

```bash
# 1. backend (needs MongoDB; see backend/README.md)
cd backend && cp .env.example .env     # set JWT_SECRET and the three bootstrap passwords
docker compose up -d --build

# 2. frontend
cp .env.example .env                   # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm install
npm run dev
```

The first start creates three accounts from `backend/.env`:
`BOOTSTRAP_DEVELOPER_*`, `BOOTSTRAP_ADMIN_*`, `BOOTSTRAP_OPERATOR_*`. Change the
passwords after signing in. In production the developer password is required.

First-time setup in the UI: sign in as developer or admin, add your robots
(*Admin → Add robot*, using each robot's ROS namespace), upload the graph JSON
and the map, press *Send to all robots*.

## Adding a new kind of robot

Add an entry to `backend/config/fleet_topics.yaml` under `robot_types` (it can
`extends: waypoint_amr` and add topics and capabilities). If it needs new
behaviour, add one file in `backend/app/ros/capabilities/`. The robot-type
picker and the controls shown for each robot follow from that; no frontend
change is needed for the existing capabilities.

## Frontend layout

```
src/
  lib/api/        client (bearer token, envelope, file download), queries, one
                  shared telemetry WebSocket, types mirroring the backend
  lib/auth.tsx    session, role helpers, landing page per role
  lib/robot-status.ts   one table: label and colour of every status
  components/fleet/
    FleetMap          zoom / pan / fullscreen map, robots, waypoints, route pins
    WaypointSendBox   "go to waypoint" text box
    MissionBuilder    Plus-button stops, repeats, continuous / move on click
    MissionControls   the single Pause / Continue / Cancel set
    EstopCard         E-stop (separate from driving)
    TeleopCard        manual drive (disabled during an E-stop)
    FleetFilesPanel   JSON + map upload / download / history / send / sync
    AdminPanels       add robot, approvals, accounts
  routes/         login, _app layout, console (Operate), fleet (Admin), dev
```

One WebSocket per browser tab carries live robot data; HTTP polling slows down
while it is up and resumes if it drops.

## Testing

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest
cd tools/fleet_files && python -m pytest
npm run typecheck && npm run lint
```
