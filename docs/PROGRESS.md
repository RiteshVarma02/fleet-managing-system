# V1 progress tracker

Branch: `v1-waypoint-fleet` (never edit `waypointIntegration` or `V0Draft`).
Updated after every working session. Newest status on top.

## In progress
- Phase 3: multi-stop missions (Plus button), repeats, continuous / move-on-click, approve endpoint, single-waypoint send.

## To do
- Phase 2b: auto-push to a robot when it reconnects out of sync (optional).
- Phase 4: roles developer > admin > operator, separate logins, developer-only topic panel.
- Phase 5: frontend rewrite (remove Maps page, fleet map with zoom/fullscreen, status board, mission builder, file panel, role-based panels).
- Phase 6: README rewrite, hardware checks (stop_active type, route_manager restart command, real graph x/y format).
- V1.1: natural-language waypoint commands.

## Done
- Phase 2 (backend): versioned fleet graph + map in Mongo/GridFS, `/fleet-files` upload/download/rollback/push/status, `/waypoints`, `fleet_files` ROS capability (publish + ack), legacy `/maps` module and `locations`-independent map removed, Dockerfile no longer installs Nav2/SLAM. 88 backend tests.
- Phase 0/1: single ROS domain, no Nav2, config-driven topics (`backend/config/fleet_topics.yaml`), waypoint navigation, E-stop semantics, derived robot status, battery. (commits b7973b2..b3b0008)
- Fleet push tooling: `tools/fleet_files/` (push script, robot receiver, protocol, tests).
- V1 plan (`docs/V1_PLAN.md`).

## Known gaps / open questions
- Frontend still calls removed V0 endpoints until Phase 5.
- `stop_active` assumed `std_msgs/Bool` (edit YAML if not).
- Real `amr_path.json` shape unknown beyond `waypoints[].id/name`; x/y read tolerantly for map overlay.
