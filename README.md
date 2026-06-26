# LUU Admin Console

> **Portfolio note:** Derived from production internal tooling I built and shipped at work. Company-identifying names, database hosts, and customer references have been replaced with neutral placeholders. The architecture, patterns, and implementation are entirely my own.
>
> Also referenced in: [neatify-bot](https://github.com/hariprasannaravichandran-ops/neatify-bot)

Real-time operations dashboard — FastAPI + PostgreSQL backend, React + Vite frontend, containerised with Docker Compose.

---

## What This Does

**Metrics Dashboard** — Tile grid polling Oracle SQL queries every 5 seconds, colour-coded by configurable thresholds. TV Mode for wall-display deployment.

**Sektor Pilot** — Automation engine orchestrating ephemeral Docker workers. Each worker watches a Google Sheets trigger cell, queries Oracle on change, writes results back, and auto-exits after 20 minutes idle. Start / pause / stop from the UI with a live elapsed-time counter.

**Admin Panel** — JWT RBAC (admin / operator) with bootstrap credentials, panel-level grants, SCD2 user access history, paginated audit log, and request-level tracing via `X-Request-ID`.

**Observability** — Structured JSON logging, deep health endpoint (Oracle, PostgreSQL, background threads, workers), and stateful Google Chat alerting that fires only on metric state *change*, not on every poll.

---

## Architecture

```
Frontend (React 18, Vite)          Backend (FastAPI, Python 3.11)
  useMetricsPolling (5s)   →       GET  /api/v1/metrics
  useSectorController      →       POST /api/v1/automation/start
  Admin / Audit views      →       POST /api/v1/auth/login · GET /api/v1/audit/logs
                                            ↓
                                   Oracle  — live metrics queries
                                   PostgreSQL — history, users, audit, feedback
                                   Google Sheets — worker triggers + audit
                                            ↓
                                   Docker socket — spawns ephemeral worker containers
```

### Design Decisions

| Decision | Rationale |
|---|---|
| Oracle + PostgreSQL split | Oracle owns live operational data; PostgreSQL stores history and users — no polling pressure on Oracle |
| Ephemeral Docker workers | Each Sektor Pilot job is its own container — individually cancellable, leaves no residual state |
| Request correlation | `X-Request-ID` injected by middleware — every log line for a request is queryable by ID |
| CSS custom properties | All colours via `var(--token)` — 5 dark + 5 light palettes switchable without touching JSX |
| Stateful webhook | `notify.py` tracks previous status in memory; fires once on transition, not on every poll |
| JWT + bootstrap | First-start users from env vars into `users.json` — no migration step required |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 5, CSS custom properties (multi-palette theming) |
| Backend | Python 3.11, FastAPI, Pydantic v2, uvicorn |
| Databases | Oracle (`oracledb` pooled) · PostgreSQL 16 (`asyncpg` + SQLAlchemy async) |
| Automation | Docker SDK, Google Sheets API (service account) |
| Auth | JWT HS256, bcrypt, panel-level grants, SCD2 access history |
| Observability | Structured JSON logging, `X-Request-ID` correlation, `/api/v1/health/deep` |
| Testing | Postman collection — 28 endpoints, 85 test cases |
| Infra | Docker Compose — 3 services (postgres, backend, frontend), health-checked dependency chain |

---

## Quick Start

### 1. Credentials

```bash
cp .env.example .env
cp oracle.env.example oracle.env
# Place service_account.json at project root for Sektor Pilot
```

**`.env`** — auth and database:

| Variable | Description |
|---|---|
| `AUTH_SECRET` | JWT signing key (`openssl rand -hex 32`) |
| `AUTH_BOOTSTRAP_ADMIN_USER` / `_PASSWORD` | Admin account (first start only) |
| `AUTH_BOOTSTRAP_USER` / `_PASSWORD` | Operator account (first start only) |
| `POSTGRES_PASSWORD` | PostgreSQL password |

**`oracle.env`** — Oracle connection: `ORA_USER`, `ORA_PASSWORD`, `ORA_HOST`, `ORA_PORT`, `ORA_SERVICE`, `CHAT_WEBHOOK_URL`

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

Frontend → **Administration → Admin Panel** → bootstrap credentials from `.env`.

---

## Project Layout

```
luu-admin-console/
├── backend/
│   ├── main.py                      # FastAPI entry point
│   ├── config.py                    # Pydantic Settings (env vars)
│   ├── database.py                  # PostgreSQL async engine + session factory
│   ├── db_models.py                 # SQLAlchemy ORM (metrics, users, audit, feedback)
│   ├── logging_config.py            # Structured JSON logging
│   ├── health_check.py              # Health probes (Oracle, PG, threads, workers)
│   ├── repositories.py / services.py
│   ├── api/v1/
│   │   ├── routes/                  # auth · audit · feedback · health · metrics · users
│   │   └── sektor_pilot.py         # /api/v1/automation/* routes
│   ├── infrastructure/
│   │   ├── oracle_pool.py          # Pooled Oracle connections with retry
│   │   └── google_sheets.py        # Google Sheets client
│   ├── internal-transport/
│   │   ├── config.json             # Tile definitions and thresholds
│   │   └── queries/                # SQL files — filename must match tile key
│   ├── automation/sektor_pilot/    # Container orchestration engine
│   └── tests/                      # pytest suite (auth, config, oracle pool)
├── frontend/src/
│   ├── App.jsx                     # Root: router, theme, TV mode
│   ├── styles.css                  # All CSS tokens (5 dark + 5 light palettes)
│   ├── components/layout/          # Header, Sidebar, SystemFooter, TheaterLayout
│   ├── views/                      # InternalTransport, SektorPilot, AdminPanel, …
│   ├── hooks/                      # useMetricsPolling, useTheme, useTvMode
│   └── config/
│       ├── console.config.js       # Deployment config (location name, disabled views)
│       └── i18n.config.js          # EN / DE / ES translations
├── common/notify.py                # Stateful Google Chat webhook
├── postman/                        # Collection (28 endpoints, 85 tests)
├── docker-compose.yml              # postgres + backend + frontend
├── .env.example                    # Auth + Postgres credential template
└── oracle.env.example              # Oracle credential template
```

---

## API Reference

All endpoints under `/api/v1/`. Full reference: [`backend/API_ROUTES.md`](backend/API_ROUTES.md).

| Group | Endpoints |
|---|---|
| **Metrics** | `GET /metrics` · `GET /metrics/config` · `GET /metrics/history/{key}` |
| **Health** | `GET /health` (root) · `GET /health/deep` · `GET /health/oracle` · `GET /health/postgres` |
| **Auth** | `POST /auth/login` · `GET /auth/me` · `POST /auth/logout` |
| **Users** | `GET /users` · `POST /users` · `PUT /users/{id}` · `DELETE /users/{id}` |
| **Audit** | `GET /audit/logs` · `GET /audit/search` · `GET /audit/trace/{request_id}` |
| **Automation** | `POST /automation/start` · `POST /automation/pause` · `POST /automation/stop` · `GET /automation/status/{id}` |
| **Feedback** | `POST /feedback` · `GET /feedback` (admin) |

---

## Extending

### Add a Metric Tile

1. `backend/internal-transport/queries/<key>.sql` — must return a single number
2. Register in `backend/internal-transport/config.json`:
   ```json
   { "key": "my_kpi", "label": "My KPI", "query": "my_kpi.sql", "unit": "count",
     "thresholds": { "green_threshold": 50, "amber_threshold": 200 } }
   ```
3. Add `frontend/src/assets/icons/my_kpi.svg`

### Add a Monitoring View

1. `frontend/src/views/MyView.jsx`
2. Entry in `MENU` array + `case` in router in `App.jsx`
3. Routes in `backend/api/v1/routes/` or a new file

---

## Development

```bash
# Full stack
docker compose up --build
docker compose logs -f luu-backend-api

# Backend only (requires Oracle + Postgres reachable)
cd backend && pip install -r requirements.txt && python main.py

# Frontend only (proxies /api/* to localhost:8000)
cd frontend && npm install && npm run dev
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tile shows ERROR | Check `backend/internal-transport/logs/butler.log` |
| `/health/deep` degraded | Oracle pool may need first request to initialise — check other indicators |
| Worker exits immediately | `docker logs sektor-pilot-<sector_id>` — likely missing `service_account.json` |
| No icon on tile | Add `frontend/src/assets/icons/<key>.svg` |
| Port in use | `docker compose down` |

---

*Derived from production tooling I built at work, published here with identifying details removed.*
