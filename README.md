# LUU Admin Console

> **Portfolio note:** This project is derived from production internal tooling I built and shipped at work. Company-identifying names, database hosts, and customer references have been replaced with neutral placeholders. The architecture, patterns, and all implementation code are my own.

Real-time operations dashboard — FastAPI backend polling Oracle, React + Vite frontend, containerised with Docker Compose.

---

## What This Does

LUU Admin Console is a full-stack internal platform with three integrated systems:

**Metrics Dashboard** — A tile-based grid that polls Oracle SQL queries every 5 seconds and colour-codes each KPI by configurable thresholds (green / amber / red). A TV Mode unmounts the header and sidebar for wall-display deployment.

**Sektor Pilot** — An automation engine that orchestrates short-lived Docker workers. Each worker watches a Google Sheets trigger cell, queries Oracle on change, writes results back to Sheets, and auto-exits after 20 minutes of inactivity. Start, pause, and stop are driven from the UI with a live elapsed-time counter.

**Admin Panel** — JWT-authenticated role-based access (admin / operator) with bootstrap credentials, user management, and a full paginated audit log.

**Webhook Alerting** — Stateful change detection that fires a Google Chat webhook only when a tile's status *changes* (e.g. `GREEN → AMBER`), never on every polling cycle.

---

## Architecture

```
Frontend (React + Vite)               Backend (FastAPI + Python 3.11)
  useMetricsPolling (5s)     →        GET  /api/metrics
  useSectorController        →        POST /api/sektor-pilot/start
  Admin / Audit views        →        POST /auth/login · GET /audit/logs
                                               ↓
                                       Oracle connection pool
                                       Google Sheets API client
                                               ↓
                                       Docker socket (spawns worker containers)
```

### Design Decisions

| Decision | Rationale |
|---|---|
| FastAPI + Pydantic | Type-safe contracts and auto-generated OpenAPI docs with zero validation boilerplate |
| Oracle connection pooling | Reuses connections across the 5-second polling cycle rather than reconnecting per request |
| Ephemeral Docker workers | Sektor Pilot spawns short-lived containers from the API — each worker is independently cancellable and leaves no residual state |
| CSS custom properties for theming | All colours are `var(--token)` — no hex in JSX — so dark/light mode switches without touching component code |
| Stateful webhook alerting | `notify.py` tracks the previous status in memory; fires once on transition, not on every successful poll |
| JWT with bootstrap credentials | First-start users created from env vars into `users.json` — no migration step, no separate auth service |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 5, CSS custom properties |
| Backend | Python 3.11, FastAPI, Pydantic v2, uvicorn |
| Database | Oracle (pooled connections via `oracledb`) |
| Automation | Docker SDK, Google Sheets API (service account) |
| Auth | JWT HS256, bcrypt password hashing |
| Alerting | Google Chat incoming webhook |
| Infra | Docker Compose (multi-service, health-checked) |

---

## Quick Start

### 1. Credentials

```bash
cp .env.example oracle.env
# Edit oracle.env with your Oracle connection details
```

| Variable | Required | Description |
|---|---|---|
| `ORA_USER` | Yes | Oracle username |
| `ORA_PASSWORD` | Yes | Oracle password |
| `ORA_HOST` | Yes | Oracle host or IP |
| `ORA_PORT` | No | Default `1521` |
| `ORA_SERVICE` | Yes | Oracle service name |
| `CHAT_WEBHOOK_URL` | No | Google Chat webhook for status-change alerts |

For Sektor Pilot, place your Google Cloud service account JSON at `service_account.json` in the project root (downloaded from Google Cloud Console → IAM → Service Accounts).

### 2. Run

```bash
docker compose up --build -d
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

### 3. Log In

Open the frontend → **Administration → Admin Panel** → sign in with the bootstrap credentials defined in `docker-compose.yml` (`AUTH_BOOTSTRAP_ADMIN_USER` / `AUTH_BOOTSTRAP_ADMIN_PASSWORD`).

Bootstrap runs only once when `backend/auth/users.json` is empty. After first start you can remove those env vars.

---

## Project Layout

```
luu-admin-console/
├── backend/
│   ├── main.py                      # FastAPI entry point
│   ├── config.py                    # Pydantic Settings — reads ORA_* env vars
│   ├── models.py                    # Pydantic schemas (TileConfig, MetricsResponse)
│   ├── exceptions.py                # Typed exception hierarchy (no bare except)
│   ├── api/v1/
│   │   ├── internal_transport.py   # /api/*, /auth/*, /audit/* routes
│   │   └── sektor_pilot.py         # /api/sektor-pilot/* routes
│   ├── infrastructure/
│   │   ├── oracle_pool.py          # Connection pooling with retry logic
│   │   └── google_sheets.py        # Google Sheets read/write client
│   ├── auth/                        # Runtime auth store (users.json, audit_logs.json)
│   ├── internal-transport/
│   │   ├── config.json             # Tile definitions and thresholds
│   │   └── queries/                # SQL files — filename must match tile `query` field
│   └── automation/sektor_pilot/    # Container orchestration engine
│       ├── worker.py               # 3s poll loop, 20-min idle timeout
│       ├── executor.py             # Docker subprocess management
│       ├── repository.py           # Non-blocking Google Sheets audit logging
│       └── sector_config.py        # Sector definitions and spreadsheet IDs
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Root: router, theme toggle, TV mode
│   │   ├── styles.css              # CSS custom properties — all theme tokens
│   │   ├── components/layout/      # Header, Sidebar, SystemFooter, TheaterLayout
│   │   ├── views/                  # InternalTransport, SektorPilot, AdminPanel, …
│   │   ├── hooks/                  # useMetricsPolling, useTheme, useTvMode
│   │   └── config/
│   │       ├── console.config.js   # Deployment config (location name, disabled views)
│   │       └── i18n.config.js      # EN / DE / ES translations
│   └── vite.config.js              # Dev proxy: /api/* → localhost:8000
├── common/
│   └── notify.py                   # Stateful Google Chat webhook
├── docker-compose.yml
├── .env.example                    # Oracle credential template
└── .gitignore
```

---

## API Reference

### Metrics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/config` | Tile definitions from `config.json` |
| GET | `/api/metrics` | Live Oracle values and threshold status per tile |

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Returns Bearer JWT |
| GET | `/auth/me` | Current user info |
| GET | `/auth/users` | List users (admin only) |
| POST | `/auth/users` | Create user (admin only) |

### Audit

| Method | Endpoint | Description |
|---|---|---|
| GET | `/audit/logs` | Paginated audit log (admin only) |
| GET | `/audit/search` | Filter by date, user, or action (admin only) |

### Sektor Pilot

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/sektor-pilot/start` | Launch worker container |
| POST | `/api/sektor-pilot/pause` | Suspend polling |
| POST | `/api/sektor-pilot/stop` | Terminate container |
| GET | `/api/sektor-pilot/status` | All sector states |
| GET | `/api/sektor-pilot/status/{id}` | Single sector state + elapsed time |

---

## Extending

### Add a Metric Tile

1. Write the SQL — must return a single number:
   ```sql
   -- backend/internal-transport/queries/delivery_queue.sql
   SELECT COUNT(*) FROM orders WHERE status = 'PENDING'
   ```
2. Register in `backend/internal-transport/config.json`:
   ```json
   {
     "key": "delivery_queue",
     "label": "Delivery Queue",
     "query": "delivery_queue.sql",
     "unit": "orders",
     "thresholds": { "green_threshold": 50, "amber_threshold": 200 }
   }
   ```
3. Drop an SVG at `frontend/src/assets/icons/delivery_queue.svg` — filename must match `key`.
4. Reload — no code changes needed.

### Add a Monitoring View

1. Create `frontend/src/views/MyView.jsx`.
2. Add an entry to the `MENU` array and a `case` in the router switch in `App.jsx`.
3. Add backend routes to `backend/api/v1/` (new file or extend existing).

---

## Development

```bash
# Full stack (recommended)
docker compose up --build
docker compose logs -f luu-backend-api

# Backend only (requires Oracle reachable)
cd backend
pip install -r requirements.txt
python main.py

# Frontend only (proxies /api/* to localhost:8000)
cd frontend
npm install && npm run dev
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Tile shows ERROR (red) | SQL missing or query failed | Check `backend/internal-transport/logs/butler.log` |
| Backend can't reach Oracle | Wrong credentials or network issue | Verify `ORA_*` in `oracle.env`; test from inside container |
| Worker exits immediately | Missing `service_account.json` | Ensure file is at project root and mounted in compose |
| Timer frozen at 0 | Frontend not reaching `/status/{id}` | Check browser console; verify backend health |
| No icon on tile | SVG not found | Add `frontend/src/assets/icons/<key>.svg` |
| Port already in use | Another process on 5173 or 8000 | `docker compose down`, then check what's on those ports |
| Frontend blank after login | `/api/config` failing | Check DB connectivity and `config.json` validity |
| Webhook not firing | URL missing or no state change | Webhook fires on status *change* only — not every poll |

---

*Derived from production tooling I built at work, published here with identifying details removed.*
