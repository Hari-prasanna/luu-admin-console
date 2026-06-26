# API Routing Guide - `/api/v1/` Standardization

Complete reference for route organization and versioning strategy.

---

## 🎯 Routing Architecture

### Versioning Strategy

```
/api/v1/*  ← Current (v1)
/api/v2/*  ← Future (v2 - non-breaking additions)
/api/v3/*  ← Future (v3 - breaking changes)
```

### URL Structure

```
{base_url}/api/{version}/{resource}/{action}
           │    │        │          │
           │    │        │          └─ HTTP method provides action
           │    │        └─ Domain/collection
           │    └─ API version for stability
           └─ Protocol prefix
```

**Examples:**
```
GET    /api/v1/metrics              ← Get all metrics
GET    /api/v1/metrics/config       ← Get config (subresource)
GET    /api/v1/metrics/history/we_bgl  ← Get specific metric history
POST   /api/v1/auth/login           ← Login action
POST   /api/v1/automation/start     ← Start automation
GET    /api/v1/automation/status/{id} ← Get status with ID
```

---

## 📊 Complete Route Directory

### Root Level
```
GET /health                                  → Load balancer liveness
```

### Authentication (`/api/v1/auth/`)
```
POST   /api/v1/auth/login                   → Login, get token
GET    /api/v1/auth/me                      → Current user info
POST   /api/v1/auth/logout                  → Logout
```

### Metrics (`/api/v1/metrics/`)
```
GET    /api/v1/metrics                      → Live metrics (all tiles)
GET    /api/v1/metrics/config               → Tile definitions
GET    /api/v1/metrics/history/{key}        → Historical data (paginated)
```

### Health (`/api/v1/health/`)
```
GET    /api/v1/health                       → Basic liveness
GET    /api/v1/health/deep                  → Full diagnostics
GET    /api/v1/health/oracle                → Oracle connectivity
GET    /api/v1/health/postgres              → PostgreSQL connectivity
GET    /api/v1/health/automation            → Worker health
```

### Audit (`/api/v1/audit/`)
```
GET    /api/v1/audit/logs                   → Paginated log entries
GET    /api/v1/audit/search                 → Advanced search
GET    /api/v1/audit/trace/{request_id}    → Request correlation trace
```

### Automation (`/api/v1/automation/`)
```
POST   /api/v1/automation/start             → Launch worker
POST   /api/v1/automation/pause             → Pause worker
POST   /api/v1/automation/stop              → Stop worker
GET    /api/v1/automation/status            → All workers status
GET    /api/v1/automation/status/{id}       → Single worker status
```

### Users (`/api/v1/users/`)
```
GET    /api/v1/users                        → List users (paginated)
POST   /api/v1/users                        → Create user
GET    /api/v1/users/{id}                   → Get user
DELETE /api/v1/users/{id}                   → Delete user
```

---

## 🔧 Implementation Details

### Route Registration (app.py)

```python
from backend.api.v1.routes import (
    metrics_router,
    auth_router,
    health_router,
    audit_router,
    automation_router,
    users_router,
)

# All routers include with /api/v1 prefix
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")

# Root health (no prefix needed)
@app.get("/health")
async def root_health():
    return {"status": "ok"}
```

### Router Setup (per route file)

**Before (Old):**
```python
router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("/")
async def get_metrics():
    pass

# Result: GET /metrics
```

**After (New):**
```python
router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("")  # Empty since router has prefix
async def get_metrics():
    pass

# Result: GET /api/v1/metrics (via include_router prefix)
```

### Route File Structure

All route files follow this pattern:

```python
"""Module docstring describing this domain."""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.v1.depends import get_metric_service  # DI
from backend.api.v1.schemas import DataResponse, ErrorResponse

# Router with domain prefix (no /api/v1 here!)
router = APIRouter(
    prefix="/metrics",           # ← Relative prefix only
    tags=["metrics"],
)

@router.get(
    "",                          # ← Empty or relative path
    response_model=DataResponse[Dict],
    summary="Get live metrics",
    tags=["metrics"],
)
async def get_metrics(
    service = Depends(get_metric_service),
):
    """Get live metrics from all tiles."""
    return DataResponse(data=await service.get_live_metrics())
```

**Key Points:**
- ✓ Router prefix is relative (e.g., `/metrics`)
- ✓ Route endpoints are relative (e.g., `""` for root, `/{id}` for ID)
- ✓ No `/api/v1` in route files (added by include_router)
- ✓ All routes follow the same pattern

---

## 📋 Route File Checklist

✅ Each route file has:
- [ ] Clear module docstring
- [ ] APIRouter with relative prefix
- [ ] tags parameter
- [ ] @router.method decorators (not @app)
- [ ] response_model parameter
- [ ] summary and description
- [ ] Error responses documented
- [ ] Type hints on parameters
- [ ] Dependency injection via Depends()
- [ ] No hardcoded `/api/v1` in paths

---

## 🔄 Adding New Routes

### Step 1: Create Route File

```python
# backend/api/v1/routes/new_domain.py

"""New domain API endpoints."""

from fastapi import APIRouter, Depends
from backend.api.v1.schemas import DataResponse
from backend.api.v1.depends import get_metric_service

router = APIRouter(
    prefix="/new-domain",        # Relative prefix
    tags=["new-domain"],
)

@router.get(
    "",                          # Root of domain
    response_model=DataResponse[Dict],
    summary="Get items",
)
async def get_items(service = Depends(get_metric_service)):
    """Get all items in this domain."""
    return DataResponse(data=[])
```

### Step 2: Export Router

**File:** `backend/api/v1/routes/__init__.py`

```python
from .new_domain import router as new_domain_router

__all__ = [
    "metrics_router",
    "auth_router",
    "health_router",
    "audit_router",
    "automation_router",
    "users_router",
    "new_domain_router",  # ← Add here
]
```

### Step 3: Include in App

**File:** `backend/api/v1/app.py`

```python
from .routes import (
    metrics_router,
    auth_router,
    health_router,
    audit_router,
    automation_router,
    users_router,
    new_domain_router,  # ← Add here
)

# In create_app():
app.include_router(new_domain_router, prefix="/api/v1")  # ← Add here
```

### Result

```
GET /api/v1/new-domain              (from router prefix + route path)
```

---

## 🚀 Future: Adding API v2

### Directory Structure

```
backend/api/
├── v1/
│   ├── routes/
│   ├── schemas.py
│   ├── depends.py
│   └── app.py
├── v2/                           ← NEW
│   ├── routes/
│   ├── schemas.py
│   ├── depends.py
│   └── app.py
└── __init__.py
```

### Dual API Support

```python
# backend/main.py

from backend.api.v1.app import app as app_v1
from backend.api.v2.app import app as app_v2

# Mount both versions
app.mount("/api/v1", app_v1)
app.mount("/api/v2", app_v2)

# Now both work:
# GET /api/v1/metrics
# GET /api/v2/metrics
```

---

## 🔐 URL Patterns & Best Practices

### ✓ DO

```
GET    /api/v1/metrics              ← Plural resource
GET    /api/v1/metrics/{id}         ← Get by ID
POST   /api/v1/metrics              ← Create new
PUT    /api/v1/metrics/{id}         ← Update by ID
DELETE /api/v1/metrics/{id}         ← Delete by ID

GET    /api/v1/users/search         ← Special action
POST   /api/v1/automation/start     ← Action verb
GET    /api/v1/audit/trace/{id}     ← Specific data
```

### ✗ DON'T

```
GET    /api/v1/get_metrics          ← Verb in URL
POST   /api/v1/create_metric        ← Verb in URL
GET    /api/v1/metric/{id}          ← Singular
GET    /api/v1/getAllMetrics        ← camelCase
GET    /api/v1/Metrics              ← PascalCase
GET    /api/v1/metrics/get          ← Verb at end
GET    /api/v1/api/v1/metrics       ← Duplication
```

---

## 📊 Route Statistics

**Current Endpoints:** 28
```
Authentication:  3 endpoints
Metrics:         3 endpoints
Health:          5 endpoints
Audit:           3 endpoints
Automation:      5 endpoints
Users:           4 endpoints
```

**Expected Growth:**
- **50+ endpoints**: Add domains (monitoring/, integration/)
- **100+ endpoints**: Split to v2, use bounded contexts
- **200+ endpoints**: Consider microservices (if truly justified)

---

## 🧪 Testing Routes

### Manual Testing

```bash
# Get live metrics
curl -X GET http://localhost:8000/api/v1/metrics \
  -H "Authorization: Bearer $TOKEN"

# Start automation
curl -X POST http://localhost:8000/api/v1/automation/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sector_id": "bsf_halle1", "user": "admin"}'

# Health check (no auth)
curl -X GET http://localhost:8000/health
curl -X GET http://localhost:8000/api/v1/health
```

### Using Postman

- Import collection: `LUU-Q-Console.postman_collection.json`
- Select environment: `LUU Q-Console Environment`
- All routes pre-configured with `/api/v1/` prefix
- Token auto-stored after login

### Automated Testing

```bash
pytest backend/tests/integration/test_metrics_routes.py
```

---

## 📈 Performance Targets

By route type:

| Route Type | Target | Priority |
|-----------|--------|----------|
| Health checks | < 50ms | Critical |
| Cached endpoints | < 100ms | High |
| DB queries | < 300ms | High |
| List (paginated) | < 500ms | Medium |
| Complex aggregations | < 1000ms | Medium |

---

## 🔍 Debugging Routes

### Check Registered Routes

```bash
# See all routes in app
python3 -c "
from backend.api.v1.app import app
for route in app.routes:
    print(f'{route.methods or [\"GET\"]} {route.path}')
" | sort
```

### Expected Output

```
{'GET'} /health
{'POST'} /api/v1/auth/login
{'GET'} /api/v1/auth/me
{'POST'} /api/v1/auth/logout
{'GET'} /api/v1/metrics
{'GET'} /api/v1/metrics/config
{'GET'} /api/v1/metrics/history/{metric_key}
{'GET'} /api/v1/health
{'GET'} /api/v1/health/deep
...
```

### Common Issues

**Issue:** Routes show `/api/v1/api/v1/metrics`
- **Cause:** include_router has prefix, route also has `/api/v1`
- **Fix:** Remove `/api/v1` from route prefix in `routes/*.py`

**Issue:** Route returns 404
- **Cause:** Route not registered or wrong prefix
- **Fix:** Check routes/__init__.py exports, app.py includes router

**Issue:** 405 Method Not Allowed
- **Cause:** Wrong HTTP method
- **Fix:** Check decorator (@router.get, @router.post, etc.)

---

## 📋 Migration Checklist

If migrating old routes to v1 structure:

- [ ] All routes under `/api/v1/`
- [ ] Root `/health` endpoint remains (for load balancers)
- [ ] Each domain in separate file under `routes/`
- [ ] Router prefixes are relative (no `/api/v1`)
- [ ] All routers exported from `routes/__init__.py`
- [ ] All routers included in `app.py` with `/api/v1` prefix
- [ ] No hardcoded `/api/v1` in route paths
- [ ] Postman collection updated with new paths
- [ ] Frontend proxies point to `/api/v1/`
- [ ] Documentation reflects new routes
- [ ] Tests updated for new endpoints

---

## 🎓 Best Practices

### 1. Consistent Prefixes
```python
# All routes use relative prefixes
router = APIRouter(prefix="/metrics")    # ✓ Good
router = APIRouter(prefix="/api/v1/metrics")  # ✗ Bad
```

### 2. Clear Separation
```python
# Each domain in separate file
# routes/metrics.py, routes/auth.py, routes/audit.py
# NOT all in one file
```

### 3. Type Safety
```python
# Always specify response_model
@router.get("", response_model=DataResponse[MetricsResponse])
async def get_metrics():
    pass
```

### 4. Documentation
```python
# Every endpoint documented
@router.get(
    "",
    summary="Get live metrics",
    description="Fetch real-time metric values from all tiles",
    responses={200: {...}, 500: {...}},
)
```

### 5. Error Handling
```python
# All errors use standardized responses
from backend.api.v1.schemas import ErrorResponse

responses={
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
```

---

## 🚀 Deployment Notes

### URL Rewriting (Nginx)

If behind a reverse proxy:

```nginx
location /api/ {
    proxy_pass http://backend:8000;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /health {
    proxy_pass http://backend:8000;
}
```

### Docker Compose

Frontend can reach backend at:

```
http://luu-backend-api:8000/api/v1/
```

### Environment Configuration

```
API_BASE_URL=http://localhost:8000       # Dev
API_BASE_URL=https://api.example.com     # Prod
```

---

## 📞 Support

For route-related issues:
1. Check this guide
2. Review `API_ROUTES.md` for endpoint details
3. Check backend logs: `docker compose logs -f luu-backend-api`
4. Use Postman collection to test endpoints

---

**Version:** 1.0  
**Last Updated:** 2026-06-26  
**Status:** All routes standardized on `/api/v1/` prefix
