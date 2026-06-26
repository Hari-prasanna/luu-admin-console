# LUU Q-Console API - Complete Route Reference

**API Version:** v1  
**Base URL:** `http://localhost:8000`  
**Last Updated:** 2026-06-26

---

## Versioning Strategy

All API endpoints use the `/api/v1/` prefix for consistent versioning.

**Benefits:**
- ✓ Clear API version in every request
- ✓ Easy to introduce `/api/v2/` alongside v1
- ✓ Backward compatibility maintained
- ✓ Scalable to multiple API versions

**Pattern:** `GET /api/v1/{resource}/{action}`

---

## 📋 Complete Route Map

### Root Health Check (Load Balancer)
```
GET  /health
Response: {"status": "ok"}
Purpose: Liveness probe for load balancers (no auth required)
```

---

## 🔐 Authentication Routes (`/api/v1/auth/*`)

### 1. Login
```
POST /api/v1/auth/login
Content-Type: application/json

Request:
{
  "username": "admin",
  "password": "admin123"
}

Response (200):
{
  "status": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 86400,
    "user": {
      "id": 1,
      "username": "admin",
      "role": "admin"
    }
  },
  "timestamp": "2026-06-26T17:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}

Tests:
✓ Status code is 200
✓ Response contains access_token
✓ Token type is bearer
✓ Token stored in environment
✓ Response time < 1000ms

Errors:
401 - Invalid credentials
422 - Missing required fields
```

### 2. Get Current User
```
GET /api/v1/auth/me
Authorization: Bearer {jwt_token}

Response (200):
{
  "status": "success",
  "data": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "created_at": "2026-06-26T17:00:00Z"
  },
  "timestamp": "2026-06-26T17:00:00Z",
  "request_id": "..."
}

Tests:
✓ Status code is 200
✓ Response contains user data
✓ Role is valid
✓ Created_at is ISO format

Errors:
401 - No/invalid token
```

### 3. Logout
```
POST /api/v1/auth/logout
Authorization: Bearer {jwt_token}

Response (200):
{
  "status": "success",
  "message": "Logged out successfully",
  "timestamp": "2026-06-26T17:00:00Z",
  "request_id": "..."
}

Note: Client-side operation. Token removed from environment.
```

---

## 📊 Metrics Routes (`/api/v1/metrics/*`)

### 1. Get Live Metrics
```
GET /api/v1/metrics

Response (200):
{
  "status": "success",
  "data": {
    "metrics": {
      "we_bgl": {
        "key": "we_bgl",
        "value": 150,
        "status": "Aktiv",
        "unit": "units",
        "timestamp": "2026-06-26T17:00:00Z"
      },
      "...": {}
    },
    "last_updated": "2026-06-26T17:00:00Z",
    "cached": false,
    "cache_age_seconds": 0
  },
  "timestamp": "...",
  "request_id": "..."
}

Status Values:
- Aktiv (green): value ≤ green_threshold
- Warnung (amber): value ≤ amber_threshold
- Kritisch (red): value > amber_threshold
- ERROR: Query failed

Tests:
✓ Status code is 200
✓ Metrics have required fields
✓ Status values are valid
✓ Response time < 200ms

Performance:
- First call: 150-300ms (cache miss)
- Subsequent: 50-100ms (cached)
```

### 2. Get Metrics Configuration
```
GET /api/v1/metrics/config

Response (200):
{
  "status": "success",
  "data": {
    "we_bgl": {
      "key": "we_bgl",
      "label": "Wareneingang (BGL)",
      "query": "we_bgl.sql",
      "unit": "units",
      "thresholds": {
        "green_threshold": 100,
        "amber_threshold": 300
      }
    },
    "...": {}
  },
  "timestamp": "...",
  "request_id": "..."
}

Tests:
✓ Status code is 200
✓ All tiles have required fields
✓ Thresholds are numeric
```

### 3. Get Metric History
```
GET /api/v1/metrics/history/{metric_key}?days=7&limit=50&offset=0

Parameters:
- metric_key (path): Metric identifier
- days (query): Number of days to retrieve (1-90, default: 7)
- limit (query): Records per page (1-1000, default: 100)
- offset (query): Pagination offset (default: 0)

Response (200):
{
  "status": "success",
  "data": [
    {
      "timestamp": "2026-06-26T16:00:00Z",
      "value": 150,
      "status": "Aktiv"
    },
    {...}
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1000,
    "has_more": true
  },
  "timestamp": "...",
  "request_id": "..."
}

Examples:
GET /api/v1/metrics/history/we_bgl              (7 days, 100 records)
GET /api/v1/metrics/history/we_bgl?days=30      (30 days)
GET /api/v1/metrics/history/we_bgl?days=1&limit=24 (Today, hourly)

Tests:
✓ Status code is 200
✓ Pagination metadata present
✓ Data sorted by timestamp
✓ Has_more flag accurate

Errors:
400 - Invalid metric_key
400 - Days out of range
422 - Invalid parameters
```

---

## 🏥 Health Routes (`/api/v1/health/*`)

### 1. Basic Health Check
```
GET /api/v1/health

Response (200):
{
  "status": "success",
  "data": {
    "status": "ok"
  },
  "timestamp": "...",
  "request_id": "..."
}

Tests:
✓ Status code is 200
✓ Status is "ok"
✓ Response time < 50ms

Use: Server liveness checks
```

### 2. Deep Health Check
```
GET /api/v1/health/deep

Response (200):
{
  "status": "success",
  "data": {
    "status": "healthy",
    "timestamp": "2026-06-26T17:00:00Z",
    "response_time_ms": 120,
    "checks": {
      "oracle": {
        "status": "ok",
        "response_time_ms": 45,
        "details": {"connected": true}
      },
      "postgres": {
        "status": "ok",
        "response_time_ms": 30,
        "details": {"connected": true, "tables": 8}
      },
      "automation": {
        "status": "ok",
        "response_time_ms": 15,
        "details": {"workers": 0, "last_heartbeat": "2026-06-26T16:55:00Z"}
      }
    }
  }
}

Status Values:
- healthy: All checks passed
- degraded: Some checks slow/warning
- unhealthy: Critical checks failed

Tests:
✓ Status code is 200
✓ All checks present
✓ Status is valid
✓ Response time < 500ms

Use: Comprehensive system diagnostics
```

### 3. Oracle Health
```
GET /api/v1/health/oracle

Response (200):
{
  "status": "success",
  "data": {
    "checks": {
      "oracle": {
        "status": "ok",
        "response_time_ms": 45,
        "details": {
          "connected": true,
          "consecutive_failures": 0
        }
      }
    }
  }
}

Tests:
✓ Status code is 200
✓ Oracle connection status
```

### 4. PostgreSQL Health
```
GET /api/v1/health/postgres

Response (200):
{
  "status": "success",
  "data": {
    "checks": {
      "postgres": {
        "status": "ok",
        "response_time_ms": 30,
        "details": {
          "connected": true,
          "tables": 8,
          "row_counts": {
            "audit_logs": 1234,
            "metric_history": 5678
          }
        }
      }
    }
  }
}

Tests:
✓ Status code is 200
✓ DB connectivity confirmed
✓ Row counts present
```

### 5. Automation Health
```
GET /api/v1/health/automation

Response (200):
{
  "status": "success",
  "data": {
    "checks": {
      "automation": {
        "status": "ok",
        "response_time_ms": 15,
        "details": {
          "workers": 1,
          "worker_states": {
            "bsf_halle1": "running"
          },
          "last_heartbeat": "2026-06-26T16:59:00Z"
        }
      }
    }
  }
}

Tests:
✓ Status code is 200
✓ Worker count present
✓ Last heartbeat recent
```

---

## 📋 Audit Routes (`/api/v1/audit/*`)

### 1. Get Audit Logs
```
GET /api/v1/audit/logs?limit=50&offset=0&event_type=&actor=

Authorization: Bearer {jwt_token}

Parameters:
- limit (query): Records per page (1-1000, default: 50)
- offset (query): Pagination offset (default: 0)
- event_type (query): Filter by event type (optional)
- actor (query): Filter by actor/user (optional)

Response (200):
{
  "status": "success",
  "data": [
    {
      "id": 1,
      "timestamp": "2026-06-26T17:00:00Z",
      "event_type": "LOGIN",
      "actor": "admin",
      "operation_status": "success",
      "detail_message": "User logged in",
      "request_id": "550e8400-...",
      "ip_address": "127.0.0.1"
    },
    {...}
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1000,
    "has_more": true
  }
}

Event Types:
- LOGIN, LOGOUT
- START_WORKER, PAUSE_WORKER, STOP_WORKER
- METRIC_RECORDED, METRIC_QUERIED
- EXPORT_DATA, IMPORT_DATA

Tests:
✓ Status code is 200
✓ Pagination metadata present
✓ All fields present
✓ Timestamps valid
```

### 2. Search Audit Logs (Advanced)
```
GET /api/v1/audit/search?event_type=START_WORKER&actor=admin&status=success

Authorization: Bearer {jwt_token}

Parameters:
- event_type (query): Filter by event
- actor (query): Filter by user
- status (query): Filter by status (success, failure, etc.)
- start_date (query): ISO date (2026-06-20)
- end_date (query): ISO date (2026-06-26)
- limit (query): Records per page
- offset (query): Pagination offset

Response (200): Paginated audit log entries

Examples:
GET /api/v1/audit/search?event_type=START_WORKER
GET /api/v1/audit/search?actor=admin&status=success
GET /api/v1/audit/search?start_date=2026-06-20&end_date=2026-06-26

Tests:
✓ Status code is 200
✓ Filters applied correctly
✓ No duplicates in results
```

### 3. Trace Request by ID
```
GET /api/v1/audit/trace/{request_id}

Authorization: Bearer {jwt_token}

Parameters:
- request_id (path): UUID of the request to trace

Response (200):
{
  "status": "success",
  "data": [
    {
      "id": 1,
      "timestamp": "2026-06-26T17:00:00Z",
      "event_type": "AUTH_CHECK",
      "actor": "system",
      "operation_status": "success",
      "request_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    {
      "id": 2,
      "timestamp": "2026-06-26T17:00:00.1Z",
      "event_type": "METRICS_FETCHED",
      "actor": "admin",
      "operation_status": "success",
      "request_id": "550e8400-e29b-41d4-a716-446655440000"
    }
  ],
  "pagination": {
    "limit": X,
    "offset": 0,
    "total": 2,
    "has_more": false
  }
}

Purpose: Follow complete request flow across all systems

Tests:
✓ Status code is 200
✓ All events for request present
✓ Chronological order
✓ Same request_id
```

---

## 🤖 Automation Routes (`/api/v1/automation/*`)

### 1. Start Worker
```
POST /api/v1/automation/start

Authorization: Bearer {jwt_token}
Content-Type: application/json

Request:
{
  "sector_id": "bsf_halle1",
  "user": "admin"
}

Response (200):
{
  "status": "success",
  "data": {
    "sector_id": "bsf_halle1",
    "status": "started",
    "message": "Worker started for sector bsf_halle1",
    "started_at": "2026-06-26T17:00:00Z",
    "worker_id": "worker-123"
  },
  "timestamp": "...",
  "request_id": "..."
}

Valid Sectors:
- bsf_halle1
- bsf_bestand
- akl_bestand

Tests:
✓ Status code is 200
✓ Status is "started"
✓ Worker ID present
✓ Timestamp recent

Errors:
400 - Invalid sector_id
409 - Worker already running
401 - Unauthorized
```

### 2. Pause Worker
```
POST /api/v1/automation/pause

Authorization: Bearer {jwt_token}
Content-Type: application/json

Request:
{
  "sector_id": "bsf_halle1",
  "user": "admin"
}

Response (200):
{
  "status": "success",
  "data": {
    "sector_id": "bsf_halle1",
    "status": "paused",
    "message": "Worker paused for sector bsf_halle1"
  }
}

Tests:
✓ Status code is 200
✓ Status is "paused"
```

### 3. Stop Worker
```
POST /api/v1/automation/stop

Authorization: Bearer {jwt_token}
Content-Type: application/json

Request:
{
  "sector_id": "bsf_halle1",
  "user": "admin"
}

Response (200):
{
  "status": "success",
  "data": {
    "sector_id": "bsf_halle1",
    "status": "stopped",
    "message": "Worker stopped for sector bsf_halle1"
  }
}

Tests:
✓ Status code is 200
✓ Status is "stopped"
```

### 4. Get All Workers Status
```
GET /api/v1/automation/status

Authorization: Bearer {jwt_token}

Response (200):
{
  "status": "success",
  "data": {
    "workers": [
      {
        "sector_id": "bsf_halle1",
        "status": "running",
        "started_at": "2026-06-26T16:00:00Z",
        "elapsed_seconds": 3600
      },
      {
        "sector_id": "bsf_bestand",
        "status": "stopped",
        "started_at": null,
        "elapsed_seconds": 0
      }
    ],
    "summary": {
      "total": 3,
      "running": 1,
      "paused": 0,
      "stopped": 2
    }
  }
}

Tests:
✓ Status code is 200
✓ Workers array present
✓ Summary counts match
```

### 5. Get Worker Status
```
GET /api/v1/automation/status/{sector_id}

Authorization: Bearer {jwt_token}

Parameters:
- sector_id (path): Sector identifier

Response (200):
{
  "status": "success",
  "data": {
    "sector_id": "bsf_halle1",
    "status": "running",
    "started_at": "2026-06-26T16:00:00Z",
    "elapsed_seconds": 3600,
    "last_heartbeat": "2026-06-26T16:59:50Z"
  }
}

Status Values:
- running: Worker active
- paused: Worker suspended
- stopped: Worker terminated

Tests:
✓ Status code is 200
✓ Status is valid value
✓ Elapsed time increases
```

---

## 👥 Users Routes (`/api/v1/users/*`)

### 1. List Users
```
GET /api/v1/users?limit=50&offset=0

Authorization: Bearer {jwt_token} (admin required)

Parameters:
- limit (query): Records per page
- offset (query): Pagination offset

Response (200):
{
  "status": "success",
  "data": [
    {
      "id": 1,
      "username": "admin",
      "role": "admin",
      "created_at": "2026-06-26T17:00:00Z"
    }
  ],
  "pagination": {...}
}
```

### 2. Create User
```
POST /api/v1/users

Authorization: Bearer {jwt_token} (admin required)
Content-Type: application/json

Request:
{
  "username": "newuser",
  "password": "secure123",
  "role": "viewer"
}

Response (201):
{
  "status": "success",
  "data": {
    "id": 2,
    "username": "newuser",
    "role": "viewer",
    "created_at": "2026-06-26T17:00:00Z"
  }
}

Errors:
409 - User already exists
422 - Invalid data
```

### 3. Get User
```
GET /api/v1/users/{user_id}

Authorization: Bearer {jwt_token}

Response (200): User details
```

### 4. Delete User
```
DELETE /api/v1/users/{user_id}

Authorization: Bearer {jwt_token} (admin required)

Response (200): Success message
```

---

## 🔑 Authentication

### Bearer Token Usage

All protected endpoints require a Bearer token:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Token Lifecycle

1. **Obtain:** `POST /api/v1/auth/login`
2. **Use:** Include in `Authorization` header
3. **Expiry:** 24 hours (86400 seconds)
4. **Refresh:** Call login again to get new token

### Error Responses

```
401 Unauthorized:
{
  "status": "error",
  "error_code": "UNAUTHORIZED",
  "message": "Invalid or missing authentication",
  "request_id": "..."
}

403 Forbidden:
{
  "status": "error",
  "error_code": "FORBIDDEN",
  "message": "You do not have permission to perform this action",
  "request_id": "..."
}
```

---

## 📊 Standard Response Format

### Success Response
```json
{
  "status": "success",
  "data": {...},
  "timestamp": "2026-06-26T17:00:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Paginated Response
```json
{
  "status": "success",
  "data": [...],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1000,
    "has_more": true
  },
  "timestamp": "...",
  "request_id": "..."
}
```

### Error Response
```json
{
  "status": "error",
  "error_code": "VALIDATION_ERROR",
  "message": "Request validation failed",
  "details": [
    {
      "field": "email",
      "code": "INVALID_FORMAT",
      "message": "Invalid email format"
    }
  ],
  "timestamp": "...",
  "request_id": "..."
}
```

---

## 🎯 HTTP Status Codes

| Code | Meaning | Use Case |
|------|---------|----------|
| 200 | OK | Successful GET, PUT, DELETE |
| 201 | Created | Successful POST |
| 204 | No Content | Successful DELETE (no body) |
| 400 | Bad Request | Invalid parameters |
| 401 | Unauthorized | Missing/invalid token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource already exists |
| 422 | Unprocessable Entity | Validation failed |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Backend error |

---

## 🧪 Testing

### Manual Testing (Postman)
- Use provided Postman collection
- Environment: `LUU Q-Console Environment`
- Token auto-stores after login

### Integration Tests
```bash
pytest backend/tests/integration/
```

### Performance Tests
```bash
# Expected response times
Health checks     → < 50ms
Cached endpoints  → < 100ms
DB queries        → < 300ms
```

---

## 📈 API Evolution

### Current Version
- `/api/v1/*` - Current stable API

### Future Versions
- `/api/v2/*` - New features (non-breaking changes to v1)
- `/api/v3/*` - Major refactoring (breaking changes)

### Deprecation Policy
- Endpoints marked `@deprecated` 1 version before removal
- 6-month notice before breaking changes
- Old versions supported for 12 months minimum

---

## 🔍 Rate Limiting

- Default: 100 requests/minute per IP
- Protected endpoints: 1000 requests/minute per user
- Rate limit exceeded: `HTTP 429`

---

## 📞 Support & Issues

For API issues:
1. Check this documentation
2. Review Postman collection
3. Check backend logs: `docker compose logs -f luu-backend-api`
4. Open GitHub issue with error details

---

**Version:** 1.0  
**Last Updated:** 2026-06-26  
**Maintainer:** Backend Team
