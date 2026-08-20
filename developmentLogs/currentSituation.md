Audit complete. Here is the full report.
Complete System Audit Report
Verified backend↔frontend contracts across all 57 REST endpoints + 1 WebSocket, all schemas, services, and repos, plus runtime route-resolution tests and the live frontend call graph.
🔴 HIGH — functional breakage (3)
H1. POST /tasks/pickdrop/start is unreachable — shadowed by the generic route
- tasks.py:114 declares POST /tasks/{task_id}/start before POST /tasks/pickdrop/start (tasks.py:143).
- Runtime test confirms /tasks/pickdrop/start resolves to /tasks/{task_id}/start with task_id="pickdrop" → hits start_task → 404 Task pickdrop not found.
- Every "Start mission" from the console (_app.console.tsx:175) fails. Same class of issue: GET /tasks/requests would be swallowed by GET /tasks/{task_id} (harmless today — frontend only POSTs it).
- Fix: declare all static task paths (/pickdrop/start, /pickdrop/stop, /pickdrop/{robot_id}/status, /requests, /requests/unassigned) before the /{task_id}* dynamic routes (or move them to a separate router).
H2. Map-share toggle always 404s from the UI
- queries.ts:199 uses double quotes ("/robots/${robotId}/map-share"), so the literal path /robots/${robotId}/map-share is sent, never interpolated.
- Every toggle of "Send map to robots" on the Maps page fails. Body shape is correct.
- Fix: change to a backtick template literal  `/robots/${robotId}/map-share` .
H3. map_share_enabled is silently dropped on every reconnect
- ros_manager.start_controller (manager.py:173) calls domain_bridge_manager.ensure(robot_id, robot_type, ros_domain_id) with no share_map → defaults to False.
- Any reconnect — POST /robots/connect (robot_service.py:51), registration approval (registration_service.py:39), or app-restart autostart — rebuilds the bridge without the DOWN /map topic and overwrites the offline-configured YAML. The feature only survives within one live session.
- Fix: add share_map: bool = False to start_controller, pass it to ensure, and have connect/registration/autostart pass bool(robot.get("map_share_enabled")).
🟠 MEDIUM — authorization (2)
M1. All map write endpoints accept any authenticated user (incl. viewer)
- maps.py: load(:45), activate(:58), from-robot(:79), slam/start(:86), slam/stop(:91), save-from-robot(:105), save(:114), and DELETE /maps/{name} all use get_current_user, not require_operator. A read-only viewer can upload/activate/delete maps and start SLAM — contradicts the roles table and PRD 4.1.
- Fix: switch the 8 write endpoints to require_operator.
M2. Location write endpoints same issue
- locations.py:33,50 (POST/DELETE) use get_current_user. A viewer can create/delete waypoints.
- Fix: require_operator on both.
🟡 LOW — cleanup / typing (7)
- L1. task_service.py:134-135: dead code controller = robot_service.live_snapshot(robot_id) and None; del controller — remove.
- L2. types.ts:164-165 TaskProgress.status/message never emitted by backend (task_service.py:117-123); console card (_app.console.tsx:310) shows empty at cycle start. Align type or rendering.
- L3. queries.ts:188 slamStart typed {running:boolean} but backend returns {pid, map_name, robot_id} — unused, still wrong.
- L4. types.ts:94 TelemetrySample.updated_at vs backend at — dead field.
- L5. types.ts:5-8 User missing id/active/last_login_at — informational.
- L6. Socket never carries velocity/dock_state/fork_height/arm_state/emergency_active (HTTP poll only) — no impact, useful to know for poll tuning.
- L7. MapShareCommand.robot_id body field is redundant vs path param and silently ignored if mismatched — minor.
✅ Verified correct
All other 50+ routes match method+path+fields; envelope unwrapping correct (raw only for login); WS URL (/api/v1/telemetry/ws) + ?token= auth match principal_from_websocket; upload form fields; route ordering in robots/maps routers; map_share_enabled/map_available/active/image/metadata/name all emitted correctly; all 24 tests + tsgo --noEmit pass.
Proposed rectification plan
1. H1: reorder tasks router (static-before-dynamic) + add regression test asserting /tasks/pickdrop/start resolves to start_pickdrop.
2. H2: fix queries.ts:199 backticks.
3. H3: thread share_map through start_controller + 3 call sites; extend test_domain_bridge to cover connect path.
4. M1/M2: switch maps write + locations write to require_operator; add auth tests.
5. L1–L7: cleanup pass (dead code, type corrections).
6. Re-run: pytest, tsgo --noEmit, npx tsc --noEmit, route-resolution script, eslint on touched files.