# Taalmel Sync — frontend

React 19 + TypeScript + Vite + Tailwind CSS, with Lucide icons.

## Run it

The API must be running first.

```bash
# terminal 1 — API
cd ../backend-py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010

# terminal 2 — frontend
cd frontend
npm install --include=dev
npm run dev          # http://127.0.0.1:5173
```

Vite proxies `/api` to `http://127.0.0.1:8010`, so the browser talks to a single
origin and no CORS preflight is needed in development. The API also allows the dev
origin directly (`TAALMEL_CORS_ORIGINS`), so either path works.

> **Install note:** if `npm install` skips dev dependencies (vite, TypeScript), the
> shell has `NODE_ENV=production` set. Use `npm install --include=dev`.

## Screens

| Route | Purpose |
|---|---|
| `/` | Landing page — hero, headline word reveal, three-panel strip |
| `/signin`, `/signup` | Phone + password auth (phone is the login identifier) |
| `/app` | Today: open cases first, then today's medicines |
| `/app/medicines` | The record; upload a prescription, confirm what was read, record evidence |
| `/app/cases` | Open cases, each stating what actually disagreed |
| `/app/cases/:id` | What / why / source / next step, record the reason, resolve |
| `/app/export` | Preview the doctor export and issue a 2-hour link / QR |
| `/app/wellness` | Patient timeline, symptom connector, lab upload, refill order |
| `/app/safety` | Interaction check — "not covered" never means "safe" |
| `/doctor/:token` | Public, read-only view for the doctor. No login |
| `/doctor/dashboard` | Optional doctor account: redeem a link token and keep a patient list |

## Completed since the first UI pass

- Language selector for English, Hindi, Tamil, Telugu, Bengali, and Marathi interface strings.
- Large-text and high-contrast toggles, persisted on the device.
- Browser Web Speech API voice reports, with an audio-file fallback.
- QR image rendering from the server-issued link.
- Offline evidence outbox with idempotent replay.

## Design decisions worth knowing

- **The doctor view is public by design.** It is reached by a signed, short-lived
  token scoped to one patient, and sits deliberately outside the authenticated shell.
- **Tokens live in `sessionStorage`, not `localStorage`.** This app holds family
  medical records; a token that survives every tab and browser restart is more
  exposure than the convenience is worth.
- **Nothing medical is generated in the UI.** Where an explanation would go, the
  doctor's own instruction is shown verbatim, or the honest "not checked" state.
- **The landing page uses a layered gradient instead of a photograph.** It is faster,
  and an evidence card says more about this product than stock imagery would.
- **`prefers-reduced-motion` is respected** — all entrance animations collapse.
- **Empty states are explicit**, because "no medicines" and "nothing needs attention"
  mean different things and a caregiver must be able to tell them apart.

## Verify it

```bash
npm run build              # type-check + production build
node scripts/check-ui.mjs  # drives real Chromium; fails on any console error
node scripts/seed-ui.mjs   # seeds a household via the API, captures populated screens
```

`check-ui.mjs` writes screenshots to `screens/`. It waits for the staged entrance
animations (up to 1.1s) before capturing — otherwise panels are caught at opacity 0.

## Known gaps

- Clinical symptom guidance is not provided; the symptom connector records the patient's
  severity and routes to care. Content needs professional review before any guidance ships.
- Offline mode queues evidence writes; reads still require connectivity.
- The caregiver currently sees one patient at a time. The API supports several.
- Prescription upload is a file picker, not a camera capture.
- `scripts/sample-rx.png` is a synthetic prescription used only for seeding screenshots.
