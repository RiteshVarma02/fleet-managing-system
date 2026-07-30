# ROS 2 Swarm Controller — Backend

Production-grade refactor of the original single-file `main.py` into a layered FastAPI service.

```
backend/
  app/
    api/          HTTP layer (deps, error handlers, v1 routers)
    core/         config, logging, security, exceptions
    db/           engine/session, ORM models, repositories
    ros/          rclpy lifecycle: manager, controllers, map & registration
    schemas/      Pydantic request/response models
    services/     business logic (robots, tasks, maps)
    main.py       app factory + lifespan
  requirements.txt  Dockerfile  docker-compose.yml  .env.example
```

## Layering rule
`api -> services -> repositories -> models`. Routers never touch the ORM
directly for business logic, services never build HTTP responses, and only
`app/ros/manager.py` owns `rclpy` state.

## Run locally
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set SECRET_KEY and ADMIN_PASSWORD
ROS_ENABLED=false uvicorn app.main:app --reload   # boots fine without ROS
```
Docs at `http://localhost:8000/docs` (disabled when `ENVIRONMENT=production`).

## Key fixes over the original script
- Global `rclpy` import removed — the API boots on non-ROS hosts (CI, laptops).
- One `rclpy.init`/`shutdown` and one executor thread per node group; nodes are
  destroyed on shutdown instead of leaking.
- DB sessions are request- or scope-bound; no session shared across threads.
- Timezone-aware UTC timestamps everywhere (naive `datetime.now()` removed).
- Occupancy grid conversion vectorised with numpy instead of per-pixel loops.
- Hardcoded credential dict replaced with bcrypt hashes + JWT bearer auth.
- Path traversal blocked on every map filename; upload size/format validated.
- SLAM subprocess runs in its own process group and is signalled as a group.
- Long pick/drop runs happen on worker threads with cancellation, timeouts and
  guaranteed DB status updates in `finally`.
- Robot deletion is a soft delete so task history stays intact.

## Production notes
- Set `AUTO_CREATE_TABLES=false` and manage schema with Alembic.
- Run a single uvicorn worker per host: the ROS nodes and task threads are
  process-local state. Scale horizontally by sharding robots across hosts.
- Health: `GET /api/v1/health` (liveness), `GET /api/v1/ready` (DB check).
