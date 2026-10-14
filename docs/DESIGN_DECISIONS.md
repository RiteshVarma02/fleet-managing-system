# Design decisions (and why)

Each entry: decision, reason, what it costs. Add new ones at the bottom.

## D1. Work only on `v1-waypoint-fleet`
`waypointIntegration` is the V1 base and `V0Draft` is the V0 backup; both stay untouched so we can always diff or fall back. (User rule.)

## D2. One ROS domain, namespaced topics `/{robot}/...`
Removes the domain bridges and per-robot domain IDs. A robot is identified by its ROS namespace (`robot_id`), validated as `^[A-Za-z][A-Za-z0-9_]*$` because it becomes part of topic names.
Cost: all robots share one DDS network, so the fleet PC and robots must be on the same network segment.

## D3. No Nav2: waypoints through route_manager
Server publishes the waypoint NAME to `/{robot}/amr/goal` and waits for `amr/final_goal_reached`, the same interface as `mission_commander.py`. The raw `amr/goal_reached` is not used because route_manager already filters it.
Cost: needs `traffic_manager_node` running or goals hang (timeout fails the leg with a hint).

## D4. Config-driven topics in one YAML
`backend/config/fleet_topics.yaml` is the only place a topic name, type or QoS appears. Code asks for logical names (`goal`, `pose`...). Reason: user requirement "changeable in a single place". Reload without restart for new connections.

## D5. Robot types by inheritance + capability mixins
A robot type is `extends` + capability list + topics. Controllers are assembled from one mixin per capability. Reason: future robots (forklift, arm) are a YAML entry plus at most one new capability file, not a new controller.

## D6. Stale arrival guard (epoch + debounce)
`final_goal_reached` has no goal id. Each goal gets an epoch and arrivals within `waypoint_arrival_debounce_seconds` (1.5s) of sending are ignored. Reason: a late "arrived" from the previous leg must not complete the next one.
Cost: a goal truly reached in <1.5s is delayed to the window end (negligible).

## D7. E-stop pauses, never fails; operator must press Continue
Physical `stop_active` and software E-stop halt the robot and pause the mission. Release does not auto-resume. Reason: safety; user asked for operator confirmation after the button is released.

## D8. One pure `derive_status` function
offline > stop_active > e_stopped > awaiting_approval > paused > error > moving > idle. Used by WebSocket, REST, Mongo flush and scheduler so the UI and dispatcher never disagree.

## D9. One fleet graph and one fleet map, versioned
Every robot gets a copy of the same files. Stored once, versioned (history + rollback), pushed to selected robots. Reason: user: "only ONE map for the whole fleet".

## D10. Fleet file bytes in GridFS, metadata in Mongo
A map image can exceed the 16 MB document limit. GridFS keeps blobs out of documents; the `fleet_files` doc holds version, hashes, who/when/note.

## D11. Push over ROS topics, acked with sha256
Robots need no inbound port or SSH: they subscribe `/{robot}/fleet/file_update` and reply on `file_ack`. Receiver writes atomically with a `.bak`. The same protocol file is used by the CLI script and the backend.
Cost: the protocol file is vendored into `backend/app/services/` (Docker build context is `backend/`); a test fails if the two copies differ.

## D12. Server pushes, robots do not pull
Simple, auditable (who pushed what, per-robot result). Offline robots show "out of sync" and can be re-pushed.

## D13. File changes are admin-only; reading is for every signed-in user
Pushing a wrong graph to every robot is the most dangerous action in the system, so upload, rollback and push need admin (developer inherits). Operators only see the waypoint list and map. Revisit in Phase 4 when roles are final.

## D14. Rollback = activate an older version, then push
Activating never touches robots by itself. Reason: it separates "which file is the truth" from "send it", so a rollback can be reviewed before it reaches the fleet.

## D15. Sync state is per (robot, kind), derived from version numbers
`in_sync | out_of_sync | failed | never | no_file`, computed by one pure function from the active version and the robot's last acked version. A late ack (arrives after the push call timed out) is picked up on the next status read.

## D16. The dashboard map is the active fleet map file
The old `/maps` module (separate map uploads, SLAM, activate) is deleted. `GET /fleet-files/map/preview` returns the active map as PNG plus resolution/origin. Reason: one map, one source of truth; the Maps page is removed anyway.

## D17. Waypoint coordinates are read tolerantly from the graph
Only `id` and `name` are guaranteed by route_manager's graph, so `x`/`y` (also `pose.x`, `position.x`) are optional. Waypoints without coordinates still work for sending; they just cannot be drawn on the map.
