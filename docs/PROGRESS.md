# V1 progress tracker

Branch: `v1-waypoint-fleet` (never edit `waypointIntegration` or `V0Draft`).
Updated after every working session. Newest status on top.

## In progress
- Phase 6 (hardware only): route_manager restart command for the receiver, real graph x/y format. Done: README rewrite; stop_active confirmed Bool.

## To do
- Phase 2b: auto-push to a robot when it reconnects out of sync (optional).
- V1.1: natural-language waypoint commands.

## Done
- Phase 5 (frontend): Maps page removed; one zoomable/pannable/fullscreen fleet map (robots coloured by status, red for E-stop, waypoints clickable, mission route numbered); status badges; waypoint text box; Plus-button mission builder (repeats, continuous / move on click); single Pause/Continue/Cancel set; E-stop card separate from manual-drive card; admin page (robots, add/approve, JSON + map upload/download/history/send/sync table, accounts); developer page (topics + reload); three-portal login. Typecheck, lint and production build pass; driven end to end in a browser against a mock API.
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
