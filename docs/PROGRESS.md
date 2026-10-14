# V1 progress tracker

Branch: `v1-waypoint-fleet` (never edit `waypointIntegration` or `V0Draft`).
Updated after every working session. Newest status on top.

## In progress
- Phase 5: frontend rewrite (next; large).

## To do
- Phase 2b: auto-push to a robot when it reconnects out of sync (optional).
- Phase 5 scope: remove Maps page, fleet map with zoom/fullscreen, status board, Plus-button mission builder + Approve button, waypoint text box, JSON/map file panel, three role panels and login pages.
- Phase 6: README rewrite, hardware checks (stop_active type, route_manager restart command, real graph x/y format).
- V1.1: natural-language waypoint commands.

## Done
- Safety/controls pass: E-stop beats teleop in the controller, single per-robot control route (pause/resume/cancel), teleop kept separate from E-stop. 128 backend tests.
- Phase 4 (backend): roles developer > admin > operator (`viewer` retired), `require_developer`, optional `portal` on login, admins can only manage operators, last-developer lockout guard, topics endpoints developer-only, seeding of the three accounts (`BOOTSTRAP_DEVELOPER_PASSWORD` required in production). 126 backend tests.
- Phase 3 (backend): missions = ordered `stops[]` x `repeats`, `mode` continuous | step (move on click), `awaiting_approval` state, `POST /tasks/{id}/approve`, `POST /tasks/missions`, `POST /tasks/waypoint` (text box), `GET /tasks/robot/{id}/progress`; pick/drop and `locations` removed; waypoint names validated against the active graph. 110 backend tests.
- Phase 2 (backend): versioned fleet graph + map in Mongo/GridFS, `/fleet-files` upload/download/rollback/push/status, `/waypoints`, `fleet_files` ROS capability (publish + ack), legacy `/maps` module and `locations`-independent map removed, Dockerfile no longer installs Nav2/SLAM. 88 backend tests.
- Phase 0/1: single ROS domain, no Nav2, config-driven topics (`backend/config/fleet_topics.yaml`), waypoint navigation, E-stop semantics, derived robot status, battery. (commits b7973b2..b3b0008)
- Fleet push tooling: `tools/fleet_files/` (push script, robot receiver, protocol, tests).
- V1 plan (`docs/V1_PLAN.md`).

## Known gaps / open questions
- Frontend still calls removed V0 endpoints until Phase 5.
- `stop_active` assumed `std_msgs/Bool` (edit YAML if not).
- Real `amr_path.json` shape unknown beyond `waypoints[].id/name`; x/y read tolerantly for map overlay.
