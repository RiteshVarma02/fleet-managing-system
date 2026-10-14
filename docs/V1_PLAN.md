# FMS V1 — Waypoint Fleet: Implementation Plan

Branch: `v1-waypoint-fleet` (created from `waypointIntegration` @ `9ce3c9d`)
Baseline: V0 = `taskModification` / `V0Draft` @ `05d568b`

> Note on the baseline: `waypointIntegration` sits 5 commits behind `taskModification`.
> Those 5 commits only add domain-bridge YAMLs (`kumki`, `riteshlap`, `something`, `ubot`),
> clear `robot_config_file.txt` and bump `@lovable.dev/vite-tanstack-config` 2.23.1 → 2.25.3.
> V1 deletes domain bridges entirely, so nothing functional is lost. The package bump can be
> cherry-picked in Phase 0 if wanted.

---

## 1. What V1 is

V0 is a multi-domain Nav2 fleet manager: every robot has its own `ROS_DOMAIN_ID`, a
`domain_bridge` process per robot moves topics, Nav2 goals go through
`robot_action_forwarder.py`, and missions are fixed pickup → drop pairs built from
manually created locations.

V1 is a **single-domain, waypoint-graph fleet manager**:

| Area | V0 | V1 |
| --- | --- | --- |
| Transport | one domain per robot + `domain_bridge` | one shared domain, no bridge |
| Topic names | robot `/odom` remapped to server `/{id}/odom` | `/{robotName}/{topic}` everywhere, no remap |
| Navigation | Nav2 `NavigateToPose` via action forwarder | waypoint route_manager (`amr/goal`, `amr/final_goal_reached`, `amr/route`) |
| Destinations | `locations` collection, typed in by hand | waypoints from each robot's graph JSON (`{"waypoints":[{id,name,…}]}`) |
| Missions | pickup → drop × repeats | ordered list of N waypoints × repeats, continuous or step-approval |
| Robot files | none | per-robot graph JSON + map upload/download |
| Roles | admin / operator / viewer | admin / developer / operator |
| Map | separate Maps page | zoomable, expandable map embedded in operator + admin panels |
| Safety | software e-stop only | + physical stop button state from `/{robotName}/stop_active` |

---

## 2. Robot-side contract (from `mission_commander.py`)

V1 drives robots through the same interface `mission_commander.py` already uses, so the
robot stack (route_manager, motion_controller, traffic_manager_node) needs no changes.

| Logical | Topic | Type | Dir | Purpose |
| --- | --- | --- | --- | --- |
| `goal` | `/{robot}/amr/goal` | `std_msgs/String` (waypoint **name**) | server → robot | dispatch one leg |
| `final_goal_reached` | `/{robot}/amr/final_goal_reached` | `std_msgs/Bool` | robot → server | true arrival (traffic-filtered) |
| `route` | `/{robot}/amr/route` | `nav_msgs/Path` (empty = abort) | server → robot | abort / halt in place |
| `amcl_pose` | `/{robot}/amcl_pose` | `PoseWithCovarianceStamped` (TRANSIENT_LOCAL) | robot → server | pose + liveness |
| `stop_active` | `/{robot}/stop_active` | `std_msgs/Bool` *(to confirm)* | robot → server | physical stop button pressed |
| `battery_state` | `/{robot}/battery_state` | `BatteryState` | robot → server | battery (if published) |
| `cmd_vel` | `/{robot}/cmd_vel` | `Twist` | server → robot | teleop joystick |
| `emergency_stop` | `/{robot}/emergency_stop` | `Bool` | server → robot | software e-stop |
| `task` / `task_status` | `/{robot}/fleet/task`, `/{robot}/fleet/task_status` | `String` JSON | both | **not used by the server** (see §7 Q2) |

Rules carried over from `mission_commander.py`:

* Always wait on `amr/final_goal_reached`, never raw `amr/goal_reached`, because it fires at traffic waits too.
* `traffic_manager_node` must be running or every dispatch hangs. The server surfaces
  "no arrival within N s" as a warning instead of waiting silently.
* Validate every waypoint against the robot's graph before publishing. An unknown name fails
  silently in route_manager.

`robot_id` **is** the ROS namespace (`robotName`). Registration keeps slugifying the display
name, and admins can override it so it matches the namespace the robot actually runs with.

---

## 3. The 8 changes → workstreams

| # | Request | Workstream | Phase |
| --- | --- | --- | --- |
| 7 | Single domain, no Nav2, `/{robot}/{topic}` | WS-A ROS core rewrite | 1 |
| 6 | `stop_active` → show robot red | WS-A + WS-E | 1, 5 |
| 4 | Robot status (online / idle / offline …) | WS-B status model | 1, 5 |
| 3 | JSON + map upload/download per robot | WS-C robot files | 2 |
| 1 | Waypoint text box | WS-D missions | 3 |
| 2 | Plus-button multi-waypoint mission, repeats, continuous / on-click | WS-D missions | 3 |
| 5 | Admin / developer / operator logins | WS-F roles | 4 |
| 8 | Remove Maps page, zoomable map in panels | WS-E frontend | 5 |

---

## 4. Phased plan

### Phase 0 — Branch hygiene (½ day)

* Untrack the committed `__pycache__/*.pyc` (≈60 files), add `__pycache__/` and `*.pyc` to `.gitignore`.
* Optional: cherry-pick the `@lovable.dev/vite-tanstack-config` 2.25.3 bump from V0.
* Tag the baseline: `git tag v0 05d568b`.

### Phase 1 — Backend ROS core: single domain + waypoints (WS-A, WS-B)

**Remove**
* `app/ros/domain_bridge.py`, `data/bridges/*`, `tests/test_domain_bridge.py`, `tests/test_domain_validation.py`.
* `deploy/robot_action_forwarder.py`, `developmentLogs/client_side_code/robot_action_forwarder.py`.
* `app/ros/capabilities/navigation.py` (Nav2 goal/cancel/initial-pose) and the `/robots/goal*`, `/robots/initial-pose` endpoints.
* SLAM / cartographer flow (`/maps/slam/*`, `/maps/save-from-robot`, `/maps/from-robot`) and the server `/map` publisher + map-share (`/robots/{id}/map-share`, `map_share_enabled`).
* Config: all `domain_bridge_*`, `slam_launch_command`, per-robot `ros_domain_id`. `GET /robots/bridges` and `GET /robots/domains/next` go away, and the domain field disappears from the approval form.

**Change**
* `topics_registry.py`: one `server == robot` name, `"/{robot_id}/amr/goal"` etc. Drop the `direction` / `robot` fields, which only existed for the bridge. Collapse robot types to `waypoint_amr` (keep `forklift_bot` / `arm_bot` only if those robots exist, see Q7).
* `manager.start_controller(robot_id, robot_type)`: no bridge, just node + executor.

**Add**
* `capabilities/waypoint_nav.py` (replaces `navigation.py`):
  * `send_waypoint(name) -> (ok, detail)`: publish String on `amr/goal`, bump `epoch`, set state `sending → active`.
  * `_on_final_goal_reached(Bool)`: on `True`, mark the current epoch `succeeded`.
  * `abort()`: publish empty `Path` (frame `map`) on `amr/route`, state `cancelled`.
  * `pause()` / `resume()`: abort, then re-send the same waypoint (same pattern V0 used for Nav2).
  * **Stale-arrival guard:** `final_goal_reached` carries no goal id. Ignore a `True` that arrives
    < `arrival_debounce_ms` after a send, unless the pose is already within `arrival_radius_m` of
    the target (needs waypoint x/y from the graph). This is the V1 equivalent of V0's epoch check.
* `capabilities/safety.py`: subscribe `stop_active`. When it is active: cancel any running leg (pause the task, don't
  fail it), set `stop_active=True` in telemetry. Released → stays paused until the operator resumes (see Q4).
* `telemetry` capability: subscribe `amcl_pose` (RELIABLE + TRANSIENT_LOCAL QoS, as in
  `mission_commander.py`) → `position`, and use it as the liveness heartbeat.

**Status model (WS-B)**: computed server-side in one place (`robot_service.derive_status`)
and sent in every WebSocket frame:

| Status | Rule (first match wins) | UI colour |
| --- | --- | --- |
| `offline` | controller not running, or no `amcl_pose` / any topic for > `telemetry_stale_after_seconds` | grey |
| `stop_active` | last `stop_active` = true | **red** |
| `e_stopped` | software e-stop engaged | red outline |
| `error` | last leg failed / timed out | orange |
| `awaiting_approval` | step-mode mission waiting for operator click | amber, pulsing |
| `paused` | mission paused | amber |
| `moving` | leg in progress | blue |
| `idle` | online, no mission | green |

`RobotStatus` enum is extended accordingly. `idle_robot_ids()` uses `idle` only.

**Tests**: registry resolves `/{robot}/amr/goal`, the status-derivation table, and the stale-arrival guard.

### Phase 2 — Robot files: graph JSON + map (WS-C)

Server is the source of truth, with versioned copies per robot.

* Mongo `robot_files` collection: `{robot_id, kind: "graph"|"map", version, filename, sha256, size, uploaded_by, uploaded_at, active}`.
  Blobs in GridFS (map PGM can be ~1 MB; fine, but don't inline it in documents).
* Map = `map.yaml` + `map.pgm` (or `.png`) uploaded together. Validate the YAML keys
  (`image`, `resolution`, `origin`) and reuse the existing grid↔image conversion + its tests.
* Graph JSON validation: `waypoints[]` with unique `id` (int) and unique `name`. Keep extra
  fields (x/y/edges) as-is. Reject on error with line-level messages.
* Endpoints (`/api/v1/robots/{id}/files/…`):
  * `GET  …/graph`, `GET …/map` → download active version (file attachment)
  * `POST …/graph`, `POST …/map` → upload new version (multipart), becomes active
  * `GET  …/history`, `POST …/{kind}/{version}/activate` → rollback
  * `POST …/sync` → push the active files to the robot (see Q3)
* **Waypoints come from the active graph.** `GET /robots/{id}/waypoints` replaces the global
  `locations` collection for missions. `locations` endpoints and repo are removed after the
  frontend switches.
* Delivery to the robot is an open decision (Q3). The recommendation is a small robot-side `fleet_agent.py` that
  receives files on `/{robot}/fleet/file_update` (String JSON: kind, version, sha256, base64
  payload), writes them to the configured paths, restarts route_manager, and acks on
  `/{robot}/fleet/file_ack`. Download from the robot = agent publishes its current files on request.

### Phase 3 — Missions: single waypoint + multi-stop sequences (WS-D)

**Data model** (`tasks`):
```
{
  task_type: "waypoint_mission",
  robot_id, created_by,
  stops: [ {waypoint_id, name}, ... ],     # ordered, ≥1, duplicates allowed (1→2→5→2)
  repeats: 1..1000,                        # e.g. 50
  mode: "continuous" | "step",
  cursor: {cycle, stop_index},             # persisted on each arrival
  status: pending|running|paused|awaiting_approval|completed|failed|cancelled
}
```
`from_location_id` / `to_location_id` are dropped. A "pickup → drop" mission is just
`stops=[A,B]`.

**Engine** (`task_service.TaskEngine._run`):
* Loop `for cycle in range(repeats): for stop in stops: drive_to(stop)`, the same structure as V0 but with N legs.
* `mode == "step"`: after each arrival (except the very last), set `awaiting_approval`, publish
  progress, and wait on a per-task `asyncio.Event`. `POST /tasks/{id}/approve` releases it.
  Pause / cancel still work while waiting.
* Persist `cursor` on every arrival so a server restart can resume or report exactly where it stopped
  (V0 just requeued).
* Progress payload: `{cycle, repeats, stop_index, stops_total, current_stop, next_stop, mode, status}`.

**Single waypoint (item 1)**: `POST /robots/{id}/waypoint {target}`. `target` = id or name,
resolved against the robot's graph (same `resolve_waypoint` logic as `mission_commander.py`).
Internally this is a 1-stop, 1-repeat continuous mission, so it gets status, abort and history for free.

**Endpoints**: `POST /tasks/missions` (create + start), `POST /tasks/{id}/approve|pause|resume|cancel`,
`GET /tasks/{id}/progress`. Register static routes **before** `/{task_id}` routes (the V0 audit
bug H1).

**Scheduler / unassigned requests**: keep the queue, but a request now carries `stops` + `mode`.
It only assigns robots whose active graph contains every stop.

### Phase 4 — Roles: admin / developer / operator (WS-F)

| Capability | Admin | Developer | Operator |
| --- | :-: | :-: | :-: |
| Login, see fleet + status + map | ✓ | ✓ | ✓ |
| Send waypoint, run / approve / pause / cancel missions | ✓ | ✓ | ✓ |
| Software e-stop (single + all) | ✓ | ✓ | ✓ |
| Teleop joystick | ✓ | ✓ | ✗ *(Q5)* |
| Upload / download / rollback robot graph JSON + map, push to robot | ✓ | ✓ | ✗ |
| Live topic / debug view (raw status, last messages, file sync log) | ✓ | ✓ | ✗ |
| Approve / reject / delete robots | ✓ | ✗ | ✗ |
| Manage users and roles | ✓ | ✗ | ✗ |

* `Role` enum: `admin`, `developer`, `operator`. Migrate existing `viewer` users → `operator`
  (or deactivate them) with a one-off startup migration.
* Dependencies: `require_admin`, `require_developer` (admin|developer), `require_operator` (all three).
  Fix the V0 audit gaps M1/M2 while doing this (map and location writes accepted any user).
* Bootstrap env: `BOOTSTRAP_DEVELOPER_PASSWORD` alongside the admin/operator ones.
* Frontend: one login page. The role decides the landing panel: `/admin`, `/developer`, `/operator`.
  Route guards per role, and the sidebar is built from the role.

### Phase 5 — Frontend (WS-E)

**Remove**: `routes/_app.maps.tsx`, Maps nav item, map-share UI, SLAM UI, bridge panel,
domain field in approval, Nav2 goal-click, locations CRUD.

**New shared components**
* `FleetMapView`: replaces `FleetMap.tsx`.
  * Pan + wheel/pinch zoom (`react-zoom-pan-pinch`, or a small transform hook), zoom-in/out/fit
    buttons, **expand to fullscreen** (dialog / Fullscreen API).
  * Layers: map image, waypoint graph (nodes labelled by name, edges if present), robots
    (heading arrow, colour = status, **solid red + pulse when `stop_active`**), active mission path
    with the current and next stop highlighted.
  * Click a waypoint → "Send <robot> here" / "Add to mission".
  * Coordinate transform from map YAML (`resolution`, `origin`, bottom-up row flip).
* `RobotStatusBadge` + `FleetStatusBoard`: one card per robot (status, battery, current stop,
  mission progress, last-seen). A red banner across the panel when any robot has `stop_active`.
* `WaypointSendBox` (item 1): text input with autocomplete over the selected robot's
  waypoints (id or name), Enter to send, inline validation ("'WP_99' not in kumki's graph").
* `MissionBuilder` (item 2): ordered stop list with **+ Add stop**, drag to reorder, remove,
  duplicate. Repeats input (1–1000). Mode toggle **Move continuously / Move on click**. Preview
  like `1 → 2 → 5 → 7 → 8 × 50`. Start / Pause / Resume / Cancel, plus a big **Approve next →**
  button that appears only in `awaiting_approval`.
* `RobotFilesPanel` (item 3): per robot, active graph + map version, Download, Upload (with
  validation errors shown), history + rollback, "Push to robot" with sync status.

**Panels**
* **Operator** `/operator`: status board, map (zoomable), robot selector, waypoint box, mission builder, mission progress, e-stop.
* **Admin** `/admin`: everything Operator has, plus robot approval/deletion, users and roles, robot files.
* **Developer** `/developer`: robot files, teleop, debug/topic view, map.

### Phase 6 — Robot-side + integration + docs

* `fleet_agent.py` (if Q3 = agent): file receive/apply/ack, optional registration announce.
* Robots stop running `mission_commander.py` while under fleet control, because two dispatchers on one
  `amr/goal` would conflict. Keep it for manual CLI testing only.
* End-to-end checklist on hardware: offline → online detection, single waypoint, 5-stop × 50
  continuous, step mode approve, pause/resume mid-leg, physical stop button → red + task paused,
  file upload → push → robot restarts on new graph, every role's access.
* Rewrite `backend/README.md` and the root README for V1, and archive the V0 domain-bridge docs.

---

## 5. Suggested commit / PR sequence

1. `chore: untrack pycache, tag v0`
2. `feat(ros)!: single domain, remove domain_bridge + Nav2 + SLAM`
3. `feat(ros): waypoint_nav capability (amr/goal, final_goal_reached, route abort)`
4. `feat(ros): stop_active safety + amcl_pose liveness; status derivation`
5. `feat(files): per-robot graph JSON + map storage, upload/download/rollback`
6. `feat(tasks)!: multi-stop missions, repeats, continuous/step, approve endpoint`
7. `feat(auth)!: admin/developer/operator roles + migration`
8. `feat(ui): FleetMapView (zoom/pan/fullscreen), status board, remove Maps page`
9. `feat(ui): waypoint send box + mission builder`
10. `feat(ui): role panels + robot files panel`
11. `feat(robot): fleet_agent.py` (if chosen)
12. `docs: V1 README`

Each step keeps `pytest` + `tsc --noEmit` green.

---

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| `final_goal_reached` has no goal id → stale `True` ends the wrong leg | debounce + arrival-radius check (Phase 1) |
| `traffic_manager_node` down → dispatches hang forever | per-leg "no movement / no arrival" watchdog, surfaced as `error` with a clear message |
| Two dispatchers (`mission_commander.py` + server) on one robot | document it; optionally detect foreign `amr/goal` publishers via `count_publishers` |
| Unknown waypoint name silently ignored by route_manager | strict validation against the active graph before publish |
| One shared domain = all robots' traffic on one DDS graph | fine at this fleet size; only subscribe to the topics the server uses (no `scan`, no `tf`) |
| Graph/map out of sync between server and robot | sha256 in ack; show "robot running v3, server active v4" |

---

## 7. Open questions (need answers before the phase they block)

1. **Waypoint text box (item 1):** plain id/name entry, or free-text commands ("go to dock A
   then charging") through the S.P.A.R.K. model in `send_task_updated.py`? The NL route adds TensorFlow
   to the server and a model/vocab deployment. Recommendation: plain entry in V1, NL as V1.1.
2. **Dispatch path:** the server publishes `amr/goal` directly (recommended: needed for N stops,
   repeats and step approval), or the server sends JSON to a robot-side `mission_commander` via
   `fleet/task` (only supports pickup→drop today)?
3. **Getting files onto the robot:** (a) robot-side `fleet_agent.py` over ROS topics
   (recommended), (b) robot pulls via HTTP from the server, or (c) the website only stores and serves
   files and someone copies them manually. Which paths and which restart command on the robot?
4. **`stop_active`:** message type (`std_msgs/Bool`?), latched or periodic? When the button is
   released, should the mission auto-resume or wait for the operator?
5. **Developer vs operator:** is teleop operator-allowed? Should developers see the user list?
6. **Maps:** does every robot have its own map, or do all robots share one floor map? This decides
   whether the panel shows one combined map or the selected robot's map.
7. **Robot types:** keep forklift/arm capabilities, or are all V1 robots plain waypoint AMRs?
8. **Battery:** do the robots publish `battery_state`? If not, hide it.
