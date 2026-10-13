# Make task scheduling easy to find and use

## What exists today
The operator Console already has a basic "Schedule" option inside the Pick & drop card: a date/time box plus a "Schedule (pick a time)" button, and a list of queued/scheduled requests with a Cancel button. The backend already holds scheduled work until its time, then hands it to a free robot. Your local findings point at an older copy (they report no task UI), so first make sure your local project is in sync with this one.

The current option is easy to miss: it sits under the Start/Pause/Stop buttons, the button stays greyed out until a time is picked, and it does not say that a scheduled task goes to *any free robot*, not the selected one.

## Changes
1. **"Run now / Schedule" switch** at the top of the Pick & drop card. In Schedule mode, the Start button becomes "Schedule task" and the date/time picker appears.
2. **Quick picks:** "In 1 hour", "Tonight 8 PM", "Tomorrow 9 AM", "Tomorrow 5 PM", plus a custom date/time. Past times are blocked with a clear message.
3. **Robot choice for scheduled tasks:** "Any free robot" (default) or "This robot type only". The scheduler already supports matching by robot type.
4. **"Scheduled tasks" panel** listing time (with a countdown like "in 14h 20m"), pickup to drop, repeats, and Cancel. It also appears on the admin Fleet page so admins can see upcoming work.
5. Times are shown in the user's local time and sent to the server in UTC (as today).

## Out of scope
- Assigning a scheduled task to one specific robot (needs backend changes; can be a follow-up).
- Recurring schedules (for example, every day at 5 PM).

## Technical details
- `src/routes/_app.console.tsx`: add mode toggle, preset helpers, validation that `scheduled_at > now`, and pass `robot_type` from the selected robot when that option is chosen; move the scheduled list into a separate `ScheduledRequests` component in `src/components/fleet/`.
- `src/routes/_app.fleet.tsx`: show the same component read-only for admins (admins can still cancel).
- Reuse `taskRequestsQuery`, `createTaskRequest`, and `cancelTaskRequest` from `src/lib/api/queries.ts`. No backend changes needed.
