# Fix: task cycle stops after reaching PICKUP

## Root cause (confirmed in code)

The forwarder is not the problem. The crash is on the server, in the task engine.

`tasks_repo.append_history(db, task_id, status, message)` does `status.value`, so it expects a `TaskStatus` enum. The task engine passes a plain string instead:

- `task_service.py:331` in `_drive_to`: `append_history(db, task_id, TaskStatus.running.value, ...)`
- `task_service.py:270` in `_run` (end of each cycle): same mistake

What happens:
1. `_drive_to` publishes the goal to PICKUP (line 307), so the robot starts moving.
2. Line 331 then raises `AttributeError: 'str' object has no attribute 'value'`.
3. `_run` catches it as a generic exception, marks the task `failed` with "Unexpected error: ...", and never sends the DROP leg.
4. The robot finishes the PICKUP goal it already had and stays there.

## Related bugs found in the same path

- **`poll` used before it is defined** (`task_service.py:321`): the "epoch is 0" fallback calls `asyncio.sleep(poll)` before `poll` is set on line 334. It would crash with `UnboundLocalError` if that branch ever ran.
- **`active_task_id` is never cleared** (`_finish`, line 368): `robots_repo.upsert` drops any field whose value is `None`, so `active_task_id=None` is ignored. The robot stays marked busy, which can block the pending-request scheduler from reassigning it.
- **Fragile repo type**: `append_history` and `set_status` only accept the enum. Any future call that passes a string fails the same way.

## Fix steps

1. **`tasks_repo.py`**: make `append_history` (and `set_status`) accept both `TaskStatus` and `str`. Normalize with `TaskStatus(status).value`, which also rejects invalid values.
2. **`task_service.py`**:
   - Lines 270 and 331: pass `TaskStatus.running` (the enum), not `.value`.
   - Move `poll = max(0.2, settings.nav_poll_interval_seconds)` above the epoch fallback.
   - In `_finish`, clear `active_task_id` with a direct `$set: {active_task_id: None}` (a new `robots_repo.clear_active_task` helper), because `upsert` ignores `None`.
   - Include the exception type in the "Unexpected error" message (for example `AttributeError: ...`) so future failures are easier to trace.
3. **Audit sweep**: search `task_service.py`, `robot_service.py` and the endpoints for other `.value` values passed to repos that expect enums, and fix them the same way.
4. **Regression tests** (`backend/tests/test_task_cycle.py`):
   - Use a fake navigation controller that reports `succeeded` for each goal with the correct epoch.
   - Assert that a pick-drop task with `repeats=2` sends 4 goals in order (pickup, drop, pickup, drop), ends as `completed` with `completed_repeats == 2`, and clears `active_task_id`.
   - Assert that `append_history` accepts both an enum and a string.
5. **Verify**: run `pytest`, then do a live run. The expected history is "Navigating to PICKUP", then "Navigating to DROP", then "Cycle 1/N done", ending in completed.

## Nothing needed on the robot side

`deploy/robot_action_forwarder.py` already publishes the `SUCCEEDED` status correctly. The task was dying before that status could be used, so the robot does not need to be redeployed.
