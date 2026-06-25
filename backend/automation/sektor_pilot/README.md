# Sektor Pilot: Automation Workspace Backend

**Sektor Pilot** is the backend automation engine for the LUU Q-Console that orchestrates three independent audit pipelines, each synchronizing Google Sheets inventory triggers with Oracle database queries.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI Server (port 8000) — /api/sektor-pilot                  │
├──────────────────────────────────────────────────────────────────┤
│  Routes:                                                          │
│  • POST /start    → Launch sector worker in Docker container     │
│  • POST /pause    → Suspend polling (keep container alive)       │
│  • POST /stop     → Terminate and remove container               │
│  • GET  /status   → Query real-time container states             │
└──────────────────────────────────────────────────────────────────┘
         │
         └─→ ContainerManager (Docker SDK)
              • Manages container lifecycle
              • Tracks state per sector
              • Invokes `docker run`, `docker stop`, `docker rm`
         │
         ├─→ AuditLedger (Google Sheets)
         │   • Logs all user actions to audit sheet
         │   • Records: timestamp, user, action, sector, status
         │
         └─→ Worker (async polling loop — runs inside container)
             • Reads trigger cell from Google Sheets
             • Queries ZAL_BESTAND from Oracle
             • Writes results to sektor sheet
             • Implements 20-minute idle timeout
             • Responds to pause signals
```

## Three Sector Instances

All three sectors share the same worker codebase but use isolated configurations:

| Sector ID | Name | Trigger Cell | Description |
|-----------|------|--------------|-------------|
| `bsf_halle1` | Sektor Audit - Halle 1 BSF | A2 | Warehouse hall 1 BSF inventory |
| `bsf_bestand` | Sektor Audit - BSF Bestand | A3 | BSF inventory stock master |
| `akl_bestand` | Sektor Audit - AKL Bestand | A4 | Automated Small Parts Storage |

Configuration mapping is defined in `sector_config.py`.

## Module Structure

```
backend/automation/sektor_pilot/
├── __init__.py                # Module entry point, exports router
├── routes.py                  # FastAPI route handlers (5 endpoints)
├── container_manager.py       # Docker lifecycle management
├── sector_config.py           # Sector instance definitions
├── audit_ledger.py           # Google Sheets audit logging
├── worker.py                 # Async polling loop (runs in container)
├── sheets_client.py          # Google Sheets API client
├── db_client.py              # Oracle database client
├── config.json               # Worker configuration template
├── logs/                     # Auto-created; worker.log
├── state/                    # Auto-created; sector*.state.json
└── queries/                  # SQL query files (zal_bestand.sql)
```

## FastAPI Endpoints

All endpoints are under `/api/sektor-pilot` prefix.

### 1. Start Worker
```
POST /api/sektor-pilot/start
Content-Type: application/json

{
  "sector_id": "bsf_halle1",
  "user": "Hari Prasanna",
  "oracle_env_path": "oracle.env"
}
```

**Response (201 Created):**
```json
{
  "success": true,
  "state": "RUNNING",
  "message": "Container sektor-pilot-bsf_halle1 started",
  "sector_id": "bsf_halle1"
}
```

**Behavior:**
- Validates sector_id exists in configuration
- Removes any stopped container with the same name
- Launches `docker run -d --name sektor-pilot-[sector_id] --env-file oracle.env [image]`
- Saves container state to `state/bsf_halle1.state.json`
- Logs action to Google Sheets audit sheet

### 2. Pause Worker
```
POST /api/sektor-pilot/pause
Content-Type: application/json

{
  "sector_id": "bsf_halle1",
  "user": "Hari Prasanna"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "state": "PAUSED",
  "message": "Container sektor-pilot-bsf_halle1 paused",
  "sector_id": "bsf_halle1"
}
```

**Behavior:**
- Executes `docker exec sektor-pilot-[sector_id] touch /app/.pause`
- Worker detects `.pause` file and stops polling
- Container remains running with memory intact
- Useful for temporary suspension without losing state

### 3. Stop Worker
```
POST /api/sektor-pilot/stop
Content-Type: application/json

{
  "sector_id": "bsf_halle1",
  "user": "Hari Prasanna"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "state": "STOPPED",
  "message": "Container sektor-pilot-bsf_halle1 stopped",
  "sector_id": "bsf_halle1"
}
```

**Behavior:**
- Gracefully stops container: `docker stop -t 15 sektor-pilot-[sector_id]`
- Removes stopped container: `docker rm sektor-pilot-[sector_id]`
- Clears state file
- Logs action to audit sheet

### 4. Get Status (Single Sector)
```
GET /api/sektor-pilot/status/bsf_halle1
```

**Response (200 OK):**
```json
{
  "sector_id": "bsf_halle1",
  "container_name": "sektor-pilot-bsf_halle1",
  "state": "RUNNING",
  "container_id": "abc123def456",
  "started_at": 1719239400.123,
  "paused_at": null
}
```

**States:**
- `RUNNING` — Container is active and polling
- `PAUSED` — Container paused (`.pause` file present)
- `IDLE` — Container exists but not running
- `STOPPED` — Container terminated
- `ERROR` — Failed to determine state

### 5. Get Status (All Sectors)
```
GET /api/sektor-pilot/status
```

**Response (200 OK):**
```json
[
  {
    "sector_id": "bsf_halle1",
    "container_name": "sektor-pilot-bsf_halle1",
    "state": "RUNNING",
    "container_id": "abc123def456",
    "started_at": 1719239400.123,
    "paused_at": null
  },
  {
    "sector_id": "bsf_bestand",
    "container_name": "sektor-pilot-bsf_bestand",
    "state": "STOPPED",
    "container_id": null,
    "started_at": null,
    "paused_at": null
  },
  {
    "sector_id": "akl_bestand",
    "container_name": "sektor-pilot-akl_bestand",
    "state": "RUNNING",
    "container_id": "def789ghi012",
    "started_at": 1719239350.456,
    "paused_at": null
  }
]
```

### 6. List Available Sectors
```
GET /api/sektor-pilot/sectors
```

**Response (200 OK):**
```json
[
  {
    "sector_id": "bsf_halle1",
    "name": "Sektor Audit - Halle 1 BSF",
    "description": "BSF storage hall 1 inventory monitoring"
  },
  {
    "sector_id": "bsf_bestand",
    "name": "Sektor Audit - BSF Bestand",
    "description": "BSF inventory stock master monitoring"
  },
  {
    "sector_id": "akl_bestand",
    "name": "Sektor Audit - AKL Bestand",
    "description": "Automated Small Parts Storage inventory monitoring"
  }
]
```

## Worker Polling Loop (Inside Container)

The `worker.py` runs **inside** each Docker container and implements:

### 1. Trigger Detection (3-second poll)
- Reads trigger cell (e.g., `Inventur!A2`)
- If cell value changes → new LHM ID detected

### 2. Data Fetch & Write
- Queries Oracle `ZAL_BESTAND` table for the LHM
- Maps columns: MainLhm → A, ARTNR → D, Qualität → F, ANZ → G, Sortierziel ID → L, SortKriterium → M
- Writes to `sektor` sheet
- Clears trigger cell (or skips if protected)

### 3. Idle Timeout (20 minutes)
- Tracks `last_active_timestamp` each time a valid LHM is processed
- If no new LHM for 1200 seconds (20 min), logs message and exits:
  ```
  Idle timeout threshold met (1234.5 seconds elapsed). Shutting down worker process container.
  ```
- Container stays alive (Docker container doesn't auto-remove), but process has exited
- Can be restarted via POST /start

### 4. Pause Signal
- Worker checks for `.pause` file inside container
- If exists, suspends polling without exiting
- Resumes when file is deleted
- Useful for temporary maintenance without container restart

## Google Sheets Audit Logging

Every user action and system event is logged to the audit sheet with:

| Column | Value | Example |
|--------|-------|---------|
| Timestamp | ISO 8601 | `2026-06-24T19:15:00.123456` |
| User/Role | Actor identifier | `Hari Prasanna` or `system` |
| Action | Operation type | `START_DOCKER`, `PAUSE_DOCKER`, `STOP_DOCKER`, `IDLE_SHUTDOWN` |
| Sector | Sector ID | `bsf_halle1` |
| Status | Result | `SUCCESS` or `FAILURE` |
| Message | Details | `Worker started successfully` |

**Example entries:**
```
2026-06-24T19:15:00, Hari Prasanna, START_DOCKER, bsf_halle1, SUCCESS, Worker started successfully
2026-06-24T19:16:30, system, IDLE_SHUTDOWN, bsf_bestand, SUCCESS, Worker shut down due to 20-minute idle timeout
2026-06-24T19:18:00, Hari Prasanna, PAUSE_DOCKER, akl_bestand, SUCCESS, Worker paused successfully
```

## State Persistence

Container state is saved to JSON files in `state/` directory:

**File:** `state/bsf_halle1.state.json`
```json
{
  "sector_id": "bsf_halle1",
  "container_id": "abc123def456",
  "state": "RUNNING",
  "started_at": 1719239400.123,
  "paused_at": null
}
```

State is:
- **Created** when container starts
- **Updated** when paused/resumed
- **Cleared** when container stops
- **Loaded** on API calls to ensure consistency with Docker reality

## Error Handling & Recovery

### Container fails to start
- Returns HTTP 500 with error message
- State saved as `ERROR`
- User can retry via POST /start

### Docker daemon unavailable
- Container manager catches subprocess timeout
- Returns error: "Docker command timed out"
- HTTP 500 response

### Pause/Stop on non-running container
- Returns HTTP 200 with informative message
- State updated to reflect reality

### Audit logging failures
- Doesn't block API response
- Error logged to console
- Action completes but audit entry missing

## Configuration

### Worker Configuration (config.json)
```json
{
  "poll_interval_seconds": 3,
  "idle_timeout_seconds": 1200,
  "google_sheets": {
    "spreadsheet_id": "1Db0VNaphDZsWqp3K8Zs8LBHWPAjvgWerHti-VeNsF7w",
    "test_sheet_name": "Inventur",
    "trigger_cell": "A2",
    "sektor_sheet_name": "sektor"
  }
}
```

### Sector Configuration (sector_config.py)
Edit `SECTOR_INSTANCES` dict to add or modify sectors. Each sector defines:
- `name` — Display name
- `description` — Human-readable description
- `spreadsheet_id` — Google Sheets document ID
- `test_sheet_name` — Sheet name for trigger cell
- `trigger_cell` — Cell reference (A2, A3, etc.)
- `sektor_sheet_name` — Output sheet name
- `audit_sheet_name` — Audit log sheet name

## Environment Variables

### For FastAPI Backend:
- `GOOGLE_SHEETS_CREDENTIALS_JSON` — Path to service account JSON (or inline JSON)
- `GOOGLE_SHEETS_CREDENTIALS` — Inline service account JSON string (fallback)

### For Worker Container:
- `ORA_USER`, `ORA_PASSWORD`, `ORA_HOST`, `ORA_PORT`, `ORA_SERVICE` — Oracle connection
- `GOOGLE_SHEETS_CREDENTIALS_JSON` — Google Sheets service account
- `SECTOR_ID` — Set automatically by container manager

## Development & Testing

### Local Development (without Docker)
```bash
cd backend/internal-transport
pip install -r requirements.txt  # Ensure all dependencies installed
python3 -c "from automation.sektor_pilot.routes import router; print('Router imports successfully')"
```

### API Testing
```bash
# Start FastAPI server
uvicorn internal-transport.api:app --host 0.0.0.0 --port 8000 --reload

# In another terminal
curl -X POST http://localhost:8000/api/sektor-pilot/start \
  -H "Content-Type: application/json" \
  -d '{
    "sector_id": "bsf_halle1",
    "user": "test_user",
    "oracle_env_path": "oracle.env"
  }'

# Check status
curl http://localhost:8000/api/sektor-pilot/status

# Stop worker
curl -X POST http://localhost:8000/api/sektor-pilot/stop \
  -H "Content-Type: application/json" \
  -d '{"sector_id": "bsf_halle1", "user": "test_user"}'
```

### Viewing Worker Logs (Inside Container)
```bash
docker exec sektor-pilot-bsf_halle1 tail -f /app/logs/worker.log
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `POST /start` returns 500 | Check Docker daemon running: `docker ps` |
| Container exits immediately | Check `docker logs sektor-pilot-[sector_id]` for startup errors |
| Google Sheets auth fails | Verify `GOOGLE_SHEETS_CREDENTIALS_JSON` path/content |
| Worker never processes trigger | Check trigger cell reference matches config; verify Oracle connection |
| Audit logging fails silently | Check Google Sheets service account has write permission |
| Pause has no effect | Verify `.pause` file created: `docker exec [container] ls -la /app/.pause` |

## Related Documentation

- **Worker loop:** See `worker.py` for polling, idle timeout, and trigger processing logic
- **Container manager:** See `container_manager.py` for Docker SDK integration
- **Audit ledger:** See `audit_ledger.py` for Google Sheets logging
- **Sector configuration:** See `sector_config.py` to add or modify sectors
