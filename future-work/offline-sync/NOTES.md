# Offline-First Sync — Future Work

Not implemented. Relevant for low-connectivity areas where a caregiver or
patient may need to log an availability check or self-report without a
live connection.

Sketch, if picked up later:
- Client queues events locally (same event shape as `src/events/eventTypes.js`).
- On reconnect, POST queued events to `/api/evidence/...` in `occurred_at`
  order, using the client-recorded timestamp (the event store already
  separates `occurred_at` from `recorded_at` for exactly this reason —
  see `src/db/schema.sql`).
- Conflict/trigger evaluation (`triggerEngine.js`) re-runs naturally once
  events land, no special-casing needed server-side.
