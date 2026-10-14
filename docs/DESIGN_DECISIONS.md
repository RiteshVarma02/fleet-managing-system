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

## D18. One mission model for everything: `stops[]` x `repeats` x `mode`
The text box is just a one-stop mission (`task_type: waypoint`). Pause, resume, cancel, E-stop handling, history and progress therefore work identically for a single waypoint and for 1->2->5->7->8 x 50. No second code path to keep safe.

## D19. "Move on click" = approval after every arrival except the final one
Starting the mission is the approval for the first leg. After each arrival the task enters `awaiting_approval` (robot stands still) until `POST /tasks/{id}/approve`; this includes the hop from the last stop of a cycle back to the first of the next. The final stop of the final cycle finishes without waiting. Approve is refused during an E-stop; pause is refused while waiting (nothing is moving).

## D20. Waypoint names are validated against the active graph, only when one exists
A typo would otherwise ride a robot into a 5-minute goal timeout. With no graph uploaded yet (first bring-up) names are accepted as typed so the system is usable before the first upload. Names are re-validated at start because the graph may have changed since the mission was created.

## D21. A restart never moves a robot by itself
Running/paused/awaiting missions found at startup are reset to `pending`. The last reached stop is stored (`cursor`) for audit/UI but is not used to resume automatically: the robot may have been moved by hand while the server was down.

## D22. Mission endpoints live under `/tasks`, not `/robots/{id}`
`POST /tasks/waypoint` and `POST /tasks/missions` take `robot_id` in the body. One router owns every mission rule (validation, busy check, safety hold), and static paths are declared before `/{task_id}` routes. This deviates from the plan's `/robots/{id}/waypoint` wording on purpose.

## D23. `locations` collection and pick/drop are deleted
Waypoints now come from the graph JSON (single source of truth shared with route_manager). Keeping a second, hand-edited location list would drift from the real graph.

## D24. Three roles by rank; higher roles include lower ones
developer(3) > admin(2) > operator(1); unknown or retired roles rank 0 and get nothing. One integer comparison backs `require_operator / require_admin / require_developer`, so a new role is one table entry. The developer (the project owner) therefore has every permission by construction.

## D25. "Separate logins" = one account store, per-role login pages, role enforced by the server
The login page sends `portal` (operator | admin | developer); the server refuses if the account's rank is lower. A higher role may use a lower page and always receives its true role. The UI then shows the panel for the real role. Reason: separate passwords per role without three user tables; the server, not the browser, decides access.

## D26. Admins cannot create or edit admin/developer accounts
Otherwise any admin could mint a developer and escape the hierarchy. Also: nobody can change their own role or disable themselves, and the last active developer cannot be demoted or disabled (no lock-out).

## D27. Retired `viewer` accounts are disabled, not promoted
Mapping viewer -> operator would silently grant command rights. They are switched off at startup with a warning; an admin re-creates them with an explicit role.

## D28. Topic config is developer-only (view and reload)
It exposes the internal ROS layout and changes how every robot is addressed; it is an engineering tool, not an operations one.

## D29. No built-in default passwords in production
Production needs `BOOTSTRAP_DEVELOPER_PASSWORD`; admin and operator are seeded only when their password is provided. Development falls back to throwaway defaults with a warning.

## D30. E-stop is absolute and enforced inside the controller
`move()` replaces any non-zero velocity with a stop while a physical or software E-stop is active, whoever asks (teleop, scripts). The REST endpoints (`/move`, `/dock`, `/fork`, `/gripper`) also answer 409 `safety_hold` so the operator sees why. Plain `stop` is always allowed. Reason: the guarantee must not depend on the UI behaving.

## D31. Teleop and E-stop are separate controls
Teleop = `/robots/move` and `/robots/stop` (a velocity zero). E-stop = `/robots/emergency-stop` and `emergency-release` (the safety hold that also pauses the mission). Pressing "stop" in teleop never engages the E-stop and vice versa; only the E-stop blocks teleop.

## D32. One set of mission controls, addressed by robot
`POST /tasks/robot/{robot_id}/{pause|resume|cancel}`. `resume` also means "go" for a mission waiting for approval (move on click), so the operator has one Continue button for both cases. The old per-task pause/resume/cancel/approve routes were removed.

## D33. One map component for every page, with markers that do not scale
The map scales with CSS transform; markers are counter-scaled so a robot stays the same size at any zoom. Zoom = wheel, buttons or double-click; pan = drag; fullscreen = Fullscreen API on the map element itself so overlays stay. Reason: operators need to read small waypoint labels without the robots turning into blobs.

## D34. Status colour has one source of truth (`lib/robot-status.ts`)
Badge, map dot and card border all read the same table. A pressed physical E-stop or a software E-stop is always solid red and pulsing, whatever else is going on. Waiting-for-click is amber and pulsing so a stalled move-on-click mission is noticed.

## D35. The map click is a shortcut into the same two inputs
Clicking a waypoint on the map fills the text box and appends a mission stop. There is no separate "map mode". Mission stops show as numbered pins on the map so the route is visible before it starts.

## D36. UI mirrors the safety rules instead of being the only enforcement
Send/Start/Continue are disabled with a visible reason during an E-stop, when offline, or when the robot already has a mission; the joystick is disabled during an E-stop. The server still refuses all of these (D7, D30), so the UI can never be the only guard.

## D37. Login page picks the panel; the server checks it
Three tabs (Operator / Admin / Developer) send `portal`. After login each role lands on its home (operator: Operate; admin: Admin; developer: Developer). Nav items appear by role, but route access is enforced by the API, not by hiding links.
