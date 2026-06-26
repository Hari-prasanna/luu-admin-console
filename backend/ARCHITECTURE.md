# LUU Q-Console Backend Architecture Review

Comprehensive analysis and growth strategy for FastAPI logistics platform.

---

## Executive Summary

**Current State:** Solid foundation with modular routing, schema validation, and service layer separation.

**Growth Readiness:** Prepared for 5-10 new modules without major refactoring; scaling path clear.

**Key Strengths:**
- ✓ Clean route organization by domain
- ✓ Generic response wrappers (reusable)
- ✓ Service-Repository pattern in place
- ✓ Dependency injection via FastAPI middleware
- ✓ Request correlation IDs built-in
- ✓ Structured logging framework

**Improvement Areas:**
- Configuration management (env-based, not code-based)
- Shared validation across services
- Error standardization across all routes
- Dependency injection completeness
- Testing strategy formalization

---

## 1. Future Route Organization Strategy

### Current Structure
```
backend/api/v1/
├── routes/
│   ├── auth.py          (4 endpoints)
│   ├── metrics.py       (3 endpoints)
│   ├── health.py        (5 endpoints)
│   ├── audit.py         (3 endpoints)
│   ├── automation.py    (5 endpoints)
│   └── users.py         (4 endpoints - stub)
└── schemas.py           (Unified schemas)
```

### Recommended Future Structure (Scalable to 50+ endpoints)

```
backend/
├── api/v1/
│   ├── app.py                       (App factory, unchanged)
│   ├── schemas.py                   (Unified - keep growing here)
│   ├── routes/
│   │   ├── __init__.py             (Exports all routers)
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py             (Authentication)
│   │   │   ├── health.py           (System health)
│   │   │   └── users.py            (User management)
│   │   ├── monitoring/
│   │   │   ├── __init__.py
│   │   │   ├── metrics.py          (Real-time metrics)
│   │   │   ├── analytics.py        (Historical analysis - NEW)
│   │   │   ├── dashboards.py       (Dashboard endpoints - NEW)
│   │   │   └── reports.py          (Report generation - NEW)
│   │   ├── automation/
│   │   │   ├── __init__.py
│   │   │   ├── sektor_pilot.py     (Sector automation)
│   │   │   ├── jobs.py             (Job scheduling - NEW)
│   │   │   └── workflows.py        (Workflow management - NEW)
│   │   ├── integration/
│   │   │   ├── __init__.py
│   │   │   ├── webhooks.py         (External webhooks - NEW)
│   │   │   ├── imports.py          (Data imports - NEW)
│   │   │   └── exports.py          (Data exports - NEW)
│   │   ├── notifications/
│   │   │   ├── __init__.py
│   │   │   ├── alerts.py           (Alert management - NEW)
│   │   │   ├── channels.py         (Notification channels - NEW)
│   │   │   └── delivery.py         (Delivery tracking - NEW)
│   │   └── audit.py                (Audit log access)
│   └── depends.py                   (NEW: Shared dependencies)
│
├── services/
│   ├── __init__.py
│   ├── base.py                     (NEW: BaseService class)
│   ├── metric_service.py           (Extract from services.py)
│   ├── audit_service.py            (Extract from services.py)
│   ├── analytics_service.py        (NEW)
│   ├── automation_service.py       (NEW)
│   ├── notification_service.py     (Extract from services.py)
│   ├── integration_service.py      (NEW)
│   └── report_service.py           (NEW)
│
├── repositories/
│   ├── __init__.py
│   ├── base.py                     (NEW: BaseRepository class)
│   ├── metric_repository.py        (Extract from repositories.py)
│   ├── audit_repository.py         (Extract from repositories.py)
│   ├── analytics_repository.py     (NEW)
│   ├── notification_repository.py  (Extract from repositories.py)
│   ├── job_repository.py           (NEW)
│   └── webhook_repository.py       (NEW)
│
├── domain/                          (NEW: Aggregate roots)
│   ├── __init__.py
│   ├── metric.py
│   ├── audit.py
│   ├── notification.py
│   └── job.py
│
├── events/                          (NEW: Domain events)
│   ├── __init__.py
│   ├── event_bus.py
│   └── handlers/
│       ├── __init__.py
│       ├── metric_events.py
│       └── notification_events.py
│
├── validators/                      (NEW: Shared validation)
│   ├── __init__.py
│   ├── metric_validators.py
│   ├── audit_validators.py
│   └── common_validators.py
│
├── middleware/                      (NEW: Extracted middleware)
│   ├── __init__.py
│   ├── correlation_id.py
│   ├── error_handler.py
│   ├── auth.py
│   └── rate_limit.py
│
├── security/                        (NEW: Auth consolidation)
│   ├── __init__.py
│   ├── jwt.py
│   ├── rbac.py
│   └── permissions.py
│
└── config/                          (NEW: Configuration)
    ├── __init__.py
    ├── settings.py                  (Merged from config.py)
    ├── database.py
    ├── logging.py
    └── api.py
```

### Rationale

1. **Grouped by Feature, Not Layer**
   - Routes group by business domain (monitoring, automation, notifications)
   - Easier to navigate for new features
   - Clear ownership boundaries
   - Scales to 10+ teams naturally

2. **Service & Repository Layers Split**
   - One file per service/repo (easier to find)
   - Base classes prevent duplication
   - Consistent patterns across modules

3. **Extracted Middleware**
   - Easier to test in isolation
   - Clear separation of concerns
   - Reusable across versions

4. **New Directories for New Concerns**
   - `domain/` - Aggregate roots (future DDD expansion)
   - `events/` - Event-driven flows (notifications, integrations)
   - `validators/` - Shared validation logic
   - `security/` - Auth consolidation
   - `config/` - All configuration in one place

### Migration Path

**Phase 1 (Immediate):** Create `depends.py`, extract base classes
**Phase 2 (Short-term):** Organize routes into subfolders
**Phase 3 (Long-term):** Move to domain/events model as features grow

---

## 2. Modular API Structure

### Current State
- Routes have coupling to services
- Services directly instantiate repositories
- No shared dependency pattern

### Recommended: Dependency Container Pattern

**File:** `backend/api/v1/depends.py` (NEW)

```python
"""Dependency injection container for v1 API."""

from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session
from backend.services import (
    MetricService,
    AuditService,
    NotificationService,
    PipelineService,
)

async def get_metric_service(
    session: AsyncSession = Depends(get_db_session),
) -> MetricService:
    """Get metric service with injected session."""
    return MetricService(session)

async def get_audit_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuditService:
    """Get audit service with injected session."""
    return AuditService(session)

async def get_notification_service(
    session: AsyncSession = Depends(get_db_session),
) -> NotificationService:
    """Get notification service with injected session."""
    return NotificationService(session)

# Future services
async def get_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    return AnalyticsService(session)

async def get_automation_service(
    session: AsyncSession = Depends(get_db_session),
) -> AutomationService:
    return AutomationService(session)
```

### Benefits

✓ Single source of truth for service instantiation
✓ Easy to swap implementations (testing, staging)
✓ Consistent dependency pattern across all routes
✓ New services added in one place
✓ FastAPI dependency resolution handles async

### Usage in Routes

**Before:**
```python
@router.get("/metrics")
async def get_metrics(session: AsyncSession = Depends(get_db_session)):
    service = MetricService(session)
    return service.get_live_metrics()
```

**After:**
```python
from backend.api.v1.depends import get_metric_service

@router.get("/metrics")
async def get_metrics(service: MetricService = Depends(get_metric_service)):
    return await service.get_live_metrics()
```

### Advantages
- Service is already instantiated
- Testable (swap implementation in tests)
- Clear dependencies in function signature
- No session management in routes

---

## 3. Service Layer Improvements

### Current Issues

1. **No Base Class** - Repeated error handling, logging patterns
2. **Tight Coupling** - Services directly instantiate repositories
3. **No Context Passing** - Request ID, user info not available to services
4. **Limited Querying** - Services don't validate input before delegating
5. **No Transaction Support** - Complex operations aren't atomic

### Recommendation: BaseService Class

**File:** `backend/services/base.py` (NEW)

```python
"""Base service class with common patterns."""

import logging
from typing import Any, Optional, TypeVar, Generic
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from backend.repositories.base import BaseRepository
from backend.exceptions import AppError, ValidationError

T = TypeVar('T')

class BaseService(Generic[T]):
    """Base service with common patterns."""

    def __init__(
        self,
        db: AsyncSession,
        repo: BaseRepository[T],
        logger: logging.Logger,
    ):
        self.db = db
        self.repo = repo
        self.logger = logger

    async def validate_input(self, **kwargs) -> dict:
        """Validate input before processing.
        
        Override in subclass for specific validation.
        """
        return kwargs

    async def log_operation(
        self,
        operation: str,
        details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ):
        """Log service operation."""
        self.logger.info(
            event=f"service_{operation}",
            extra={
                "service": self.__class__.__name__,
                "details": details,
                "duration_ms": duration_ms,
            },
        )

    async def handle_error(self, error: Exception, operation: str):
        """Centralized error handling."""
        self.logger.error(
            event="service_error",
            extra={
                "service": self.__class__.__name__,
                "operation": operation,
                "error": str(error),
            },
            exc_info=error,
        )
        raise AppError(f"Failed to {operation}") from error
```

### Updated Service Example

```python
class MetricService(BaseService[MetricRepository]):
    """Handles metrics with improved pattern."""

    def __init__(self, db: AsyncSession):
        repo = MetricRepository(db)
        logger = logging.getLogger("luu.services.metrics")
        super().__init__(db, repo, logger)

    async def record_metric(
        self,
        metric_key: str,
        metric_value: float,
        metric_status: str,
    ):
        """Record with validation and error handling."""
        start = time.time()
        try:
            # Validate input
            validated = await self.validate_input(
                metric_key=metric_key,
                metric_value=metric_value,
                metric_status=metric_status,
            )

            # Business logic
            result = await self.repo.create(**validated)

            # Log success
            duration_ms = int((time.time() - start) * 1000)
            await self.log_operation(
                "record_metric",
                {"metric_key": metric_key},
                duration_ms,
            )

            return result

        except Exception as e:
            await self.handle_error(e, "record_metric")
```

### Benefits

✓ Consistent error handling across all services
✓ Structured logging in one place
✓ Validation patterns standardized
✓ Easy to add new services (inherit base)
✓ Operations are testable and monitorable

---

## 4. Repository Layer Improvements

### Current Issues

1. **Repeated Query Logic** - Multiple repos do similar filtering/pagination
2. **No Type Safety** - Generic types not used consistently
3. **Manual Error Mapping** - Each repo handles DB errors differently
4. **N+1 Query Potential** - No eager loading patterns
5. **Transaction Isolation** - No patterns for multi-table operations

### Recommendation: BaseRepository Class

**File:** `backend/repositories/base.py` (NEW)

```python
"""Base repository with common patterns."""

from typing import TypeVar, Generic, Optional, List, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.exceptions import NotFoundError, DatabaseError

T = TypeVar('T')

class BaseRepository(Generic[T]):
    """Generic repository base class."""

    def __init__(self, db: AsyncSession, model: type[T]):
        self.db = db
        self.model = model

    async def create(self, **kwargs) -> T:
        """Create and return entity."""
        try:
            entity = self.model(**kwargs)
            self.db.add(entity)
            await self.db.flush()
            return entity
        except Exception as e:
            raise DatabaseError(f"Failed to create {self.model.__name__}") from e

    async def get_by_id(self, id: Any) -> T:
        """Get entity by ID."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            raise NotFoundError(f"{self.model.__name__} not found")
        return entity

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[T], int]:
        """List with pagination and optional filters."""
        query = select(self.model)

        if filters:
            conditions = [
                getattr(self.model, k) == v
                for k, v in filters.items()
                if hasattr(self.model, k)
            ]
            if conditions:
                query = query.where(and_(*conditions))

        # Get total count
        count_query = select(func.count()).select_from(self.model)
        if filters:
            count_query = count_query.where(and_(*conditions))
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            query.limit(limit).offset(offset)
        )
        return result.scalars().all(), total

    async def update(self, id: Any, **kwargs) -> T:
        """Update entity."""
        entity = await self.get_by_id(id)
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        await self.db.flush()
        return entity

    async def delete(self, id: Any) -> bool:
        """Delete entity."""
        entity = await self.get_by_id(id)
        await self.db.delete(entity)
        await self.db.flush()
        return True
```

### Specialized Repositories

For domain-specific queries, extend base:

```python
class MetricRepository(BaseRepository[MetricHistory]):
    """Metric-specific queries."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, MetricHistory)

    async def get_by_metric_and_date_range(
        self,
        metric_key: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 100,
    ) -> List[MetricHistory]:
        """Get metrics in date range."""
        result = await self.db.execute(
            select(self.model)
            .where(
                and_(
                    self.model.metric_key == metric_key,
                    self.model.timestamp >= start_date,
                    self.model.timestamp <= end_date,
                )
            )
            .limit(limit)
            .order_by(self.model.timestamp.desc())
        )
        return result.scalars().all()
```

### Benefits

✓ 80% of query logic reusable
✓ Consistent error handling
✓ Standard pagination pattern
✓ Type-safe generic implementation
✓ Easy to test with mock DB

---

## 5. Authentication Improvements

### Current State
- JWT implementation in routes
- Token stored in environment variable
- No role-based access control
- No permission scoping

### Recommendation: RBAC Layer

**File:** `backend/security/permissions.py` (NEW)

```python
"""Role-Based Access Control."""

from enum import Enum
from typing import Set

class Role(str, Enum):
    """System roles."""
    ADMIN = "admin"
    VIEWER = "viewer"
    OPERATOR = "operator"
    GUEST = "guest"

class Permission(str, Enum):
    """Fine-grained permissions."""
    METRICS_READ = "metrics:read"
    METRICS_WRITE = "metrics:write"
    AUDIT_READ = "audit:read"
    AUTOMATION_START = "automation:start"
    AUTOMATION_STOP = "automation:stop"
    USER_MANAGE = "user:manage"
    REPORT_READ = "report:read"
    EXPORT_DATA = "export:data"

# Role-permission mapping
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.METRICS_READ,
        Permission.METRICS_WRITE,
        Permission.AUDIT_READ,
        Permission.AUTOMATION_START,
        Permission.AUTOMATION_STOP,
        Permission.USER_MANAGE,
        Permission.REPORT_READ,
        Permission.EXPORT_DATA,
    },
    Role.OPERATOR: {
        Permission.METRICS_READ,
        Permission.METRICS_WRITE,
        Permission.AUTOMATION_START,
        Permission.AUTOMATION_STOP,
        Permission.REPORT_READ,
    },
    Role.VIEWER: {
        Permission.METRICS_READ,
        Permission.AUDIT_READ,
        Permission.REPORT_READ,
    },
    Role.GUEST: set(),
}
```

### Usage in Routes

```python
from fastapi import Security
from backend.security.permissions import require_permission, Permission

@router.post("/automation/start")
async def start_automation(
    request: AutomationRequest,
    current_user = Security(get_current_user, scopes=[Permission.AUTOMATION_START]),
):
    """Start automation - requires permission."""
    # User already validated to have permission
    return await service.start()
```

### Benefits

✓ Granular permission control
✓ Easy to audit who can do what
✓ Scales to complex scenarios (time-based, resource-specific)
✓ Centralizes authorization logic
✓ Clear permission requirements in code

---

## 6. Dependency Injection Opportunities

### Current State
- FastAPI `Depends()` used for sessions
- Some hardcoded instantiation in services
- Limited testing flexibility

### Recommendation: DI Patterns by Layer

**1. Database Session Injection** (Already implemented)
```python
@router.get("/")
async def get_data(session: AsyncSession = Depends(get_db_session)):
    pass
```

**2. Service Injection** (Recommended in `depends.py`)
```python
@router.get("/")
async def get_data(service: MetricService = Depends(get_metric_service)):
    pass
```

**3. Configuration Injection** (NEW)
```python
from fastapi import Depends
from backend.config.settings import get_settings

@router.get("/")
async def get_data(settings = Depends(get_settings)):
    timeout = settings.QUERY_TIMEOUT
```

**4. User Context Injection** (NEW)
```python
from backend.security.context import get_user_context

@router.get("/")
async def get_data(user = Depends(get_user_context)):
    user_id = user.id
    user_role = user.role
```

**5. External Client Injection** (NEW - for integrations)
```python
from backend.infrastructure.clients import get_slack_client

@router.post("/notify")
async def notify(slack = Depends(get_slack_client)):
    await slack.send_message()
```

### File: `backend/api/v1/depends.py`

```python
"""Dependency injection for v1 API."""

from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session
from backend.services import MetricService, AuditService, NotificationService
from backend.config.settings import Settings, get_settings
from backend.security.context import UserContext, get_user_context

@lru_cache
def get_settings_cached() -> Settings:
    """Cached settings (doesn't change at runtime)."""
    return get_settings()

async def get_metric_service(
    session: AsyncSession = Depends(get_db_session),
) -> MetricService:
    return MetricService(session)

async def get_audit_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuditService:
    return AuditService(session)

async def get_notification_service(
    session: AsyncSession = Depends(get_db_session),
) -> NotificationService:
    return NotificationService(session)
```

### Testing Benefits

```python
# Mock service for testing
class MockMetricService:
    async def get_live_metrics(self):
        return {"test": "data"}

# Override in test
def test_metrics_endpoint(client):
    client.app.dependency_overrides[get_metric_service] = MockMetricService
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
```

---

## 7. Technical Debt Risk Areas

### High Risk (Address Immediately)

**1. Monolithic services.py & repositories.py**
- Risk: 200+ line files become unmaintainable
- Impact: Hard to find code, merge conflicts
- Fix: Split into individual files (base.py + specific ones)
- Timeline: **Next 2 weeks**

**2. Missing Error Standardization**
- Risk: Inconsistent error responses across endpoints
- Impact: Client confusion, hard to handle errors
- Fix: Create error handler middleware for all exceptions
- Timeline: **Next 1 week**

**3. No Input Validation Framework**
- Risk: Each route validates differently
- Impact: Security issues, duplicate validation logic
- Fix: Create shared validators, apply via middleware/depends
- Timeline: **Next 2 weeks**

**4. Configuration Hard-Coded**
- Risk: Environment-specific values in code
- Impact: Can't run in different environments safely
- Fix: Centralize in `config/settings.py`, load from env
- Timeline: **Next 1 week**

### Medium Risk (Address Soon)

**5. Testing Strategy Not Formal**
- Risk: Coverage gaps, brittle tests
- Fix: Define test structure, pytest fixtures
- Timeline: **Week 3-4**

**6. No Request ID Propagation to Services**
- Risk: Can't trace operations end-to-end
- Fix: Pass context object through DI
- Timeline: **Week 3-4**

**7. Logging Not Structured Consistently**
- Risk: Hard to parse logs, find issues
- Fix: Use structured logging everywhere (JSON format)
- Timeline: **Week 3-4**

### Low Risk (Plan, Don't Rush)

**8. Database Indexing Strategy**
- Risk: Queries slow down as data grows
- Fix: Add indexes, monitor query performance
- Timeline: **When scaling past 1M rows**

**9. Caching Layer**
- Risk: Repeated queries hurt performance
- Fix: Add Redis or in-memory cache layer
- Timeline: **When response times exceed SLA**

**10. Rate Limiting**
- Risk: Clients can abuse endpoints
- Fix: Implement per-user/per-IP rate limits
- Timeline: **Before production release**

---

## 8. Naming Conventions

### Current State
- Inconsistent naming patterns
- Mix of abbreviated and full names
- No clear domain language

### Recommended Conventions

**Routes**
```python
# Naming: {resource}_{operation}
get_metrics              # GET /metrics
get_metric_history      # GET /metrics/history/{key}
start_automation        # POST /automation/start
search_audit_logs       # GET /audit/search

# DON'T
metrics_list            # Ambiguous verb
get_all_metrics         # Redundant
fetch_data              # Too generic
```

**Services**
```python
# Class: {Domain}Service
MetricService           # Handles metrics
AuditService           # Handles auditing
NotificationService    # Handles alerts

# Method: {verb}_{object}
async def record_metric()
async def get_history()
async def send_alert()

# DON'T
async def process()     # Too vague
async def do_stuff()    # Meaningless
async def handle()      # Too generic
```

**Repositories**
```python
# Class: {Domain}Repository
MetricRepository       # Data access for metrics
AuditRepository       # Data access for audits

# Method: {verb}_{criteria}
async def get_by_id()
async def get_by_metric_and_date_range()
async def list_recent()

# DON'T
async def fetch()       # Ambiguous
async def query()       # Too generic
async def get_all()     # Unbounded
```

**Schemas**
```python
# Request: {Resource}Request or Create{Resource}
MetricValueRequest
CreateNotificationRequest
UpdateUserRequest

# Response: {Resource}Response
MetricValueResponse
NotificationResponse

# Lists: {Resource}ListResponse or Paginated{Resource}
PaginatedAuditLogResponse
MetricsListResponse

# DON'T
MetricInput, MetricOutput          # Ambiguous
CreateData, UpdateInfo             # Too generic
GetResponse                        # What resource?
```

**Database Models**
```python
# Table: {resource_plural}
metrics_history
audit_logs
job_executions
notifications

# Columns: snake_case, self-documenting
metric_key          # What metric
metric_value        # The value
metric_status       # Current status
created_at          # When created
updated_at          # Last update
created_by          # Who created

# DON'T
data, info, value   # Ambiguous
t, d, r             # Abbreviated
```

**Environment Variables**
```python
# Format: {LAYER}_{COMPONENT}_{PROPERTY}
# Examples:
DB_HOST
DB_PORT
DB_NAME
API_VERSION
API_TIMEOUT
LOG_LEVEL
JWT_SECRET
JWT_EXPIRY
SLACK_WEBHOOK_URL

# DON'T
DATABASE_HOSTNAME   # Too specific
timeout             # lowercase
SECRET              # ambiguous
```

**File Structure**
```python
# Use full names in public APIs
backend/
├── services/
│   ├── metric_service.py        # NOT metric_svc.py
│   ├── audit_service.py
│   └── notification_service.py

# Use abbreviated names in private helpers
backend/internal/
├── _metric_helpers.py           # Internal only
├── _query_builders.py
```

**Boolean Naming**
```python
# Prefix with is_, has_, can_, should_
is_active
has_permission
can_modify
should_retry

# DON'T
active              # Could be noun or adjective
valid               # What's being validated?
status              # Not boolean
```

---

## 9. Testing Strategy

### Current State
- Some unit tests exist
- No integration test patterns
- No fixtures defined
- Testing not documented

### Recommended Test Structure

```
backend/tests/
├── __init__.py
├── conftest.py                  (Pytest fixtures)
├── fixtures/
│   ├── __init__.py
│   ├── auth_fixtures.py        (Users, tokens)
│   ├── db_fixtures.py          (Test database)
│   ├── sample_data.py          (Test data)
│   └── mocks.py                (Mock objects)
├── unit/
│   ├── __init__.py
│   ├── services/
│   │   ├── test_metric_service.py
│   │   ├── test_audit_service.py
│   │   └── test_notification_service.py
│   ├── repositories/
│   │   ├── test_metric_repository.py
│   │   └── test_audit_repository.py
│   └── validators/
│       └── test_common_validators.py
├── integration/
│   ├── __init__.py
│   ├── test_auth_flow.py       (Login → request → logout)
│   ├── test_metrics_flow.py    (Get config → metrics → history)
│   └── test_automation_flow.py (Start → status → stop)
├── e2e/
│   ├── __init__.py
│   ├── test_dashboard_workflow.py
│   └── test_admin_panel.py
└── performance/
    ├── __init__.py
    ├── test_query_performance.py
    └── test_concurrent_requests.py
```

### Testing Pyramid

```
          /\
         /  \  E2E Tests (10%)
        /    \ - Full workflows
       /------\
      /\      /
     /  \    /  Integration (30%)
    /    \  /  - Multiple services
   /------\/
  /\      /\
 /  \    /  \ Unit Tests (60%)
/    \  /    \ - Single function
/------\\/----\
```

### Fixture Example: `conftest.py`

```python
"""Shared pytest fixtures."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from backend.db_models import Base
from backend.services import MetricService, AuditService
from backend.repositories import MetricRepository

@pytest.fixture
async def test_db():
    """Create in-memory test database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSession(engine) as session:
        yield session
    
    await engine.dispose()

@pytest.fixture
async def metric_service(test_db):
    """Service for testing."""
    return MetricService(test_db)

@pytest.fixture
def test_user():
    """Sample user for testing."""
    return {
        "id": 1,
        "username": "testuser",
        "role": "admin",
        "email": "test@example.com",
    }
```

### Unit Test Example

```python
"""Test metric service."""

import pytest
from backend.services import MetricService
from backend.exceptions import ValidationError

@pytest.mark.asyncio
async def test_record_metric(metric_service):
    """Record a metric."""
    result = await metric_service.record_metric(
        metric_key="we_bgl",
        metric_value=100,
        metric_status="Aktiv",
    )
    
    assert result.metric_key == "we_bgl"
    assert result.metric_value == 100

@pytest.mark.asyncio
async def test_record_metric_invalid_value(metric_service):
    """Recording with invalid value fails."""
    with pytest.raises(ValidationError):
        await metric_service.record_metric(
            metric_key="we_bgl",
            metric_value=-100,  # Invalid
            metric_status="Aktiv",
        )
```

### Integration Test Example

```python
"""Test metrics API flow."""

@pytest.mark.asyncio
async def test_metrics_flow(client, auth_headers):
    """Complete metrics workflow."""
    
    # 1. Get config
    response = await client.get(
        "/api/v1/metrics/config",
        headers=auth_headers,
    )
    assert response.status_code == 200
    config = response.json()["data"]
    
    # 2. Get live metrics
    response = await client.get(
        "/api/v1/metrics",
        headers=auth_headers,
    )
    assert response.status_code == 200
    metrics = response.json()["data"]
    
    # 3. Get history
    metric_key = list(config.keys())[0]
    response = await client.get(
        f"/api/v1/metrics/history/{metric_key}",
        headers=auth_headers,
    )
    assert response.status_code == 200
```

### Test Execution

```bash
# Run all tests
pytest

# Run by category
pytest backend/tests/unit           # Unit tests only
pytest backend/tests/integration    # Integration tests
pytest -m "not slow"               # Skip slow tests

# With coverage
pytest --cov=backend --cov-report=html

# In CI/CD
pytest --tb=short --maxfail=3       # Stop after 3 failures
```

---

## 10. API Governance Standards

### Documentation Standards

**Every Endpoint Must Have:**

```python
@router.get(
    "/metrics",
    response_model=DataResponse[MetricsResponse],
    responses={
        200: {"description": "Live metrics retrieved"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get live metrics",
    description="Fetch real-time metric values from Oracle for all configured tiles",
    tags=["metrics"],
)
async def get_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> DataResponse[MetricsResponse]:
    """
    Get live metrics from all tiles.
    
    Returns current metric values with status coloring:
    - Aktiv (green): value ≤ green_threshold
    - Warnung (amber): value ≤ amber_threshold
    - Kritisch (red): value > amber_threshold
    
    ### Response Example
    ```json
    {
        "status": "success",
        "data": {
            "metrics": {
                "we_bgl": {
                    "value": 150,
                    "status": "Aktiv",
                    "unit": "units"
                }
            },
            "last_updated": "2026-06-26T17:00:00Z",
            "cached": false
        }
    }
    ```
    """
```

### Error Response Standards

**All errors must follow:**

```python
{
    "status": "error",
    "error_code": "SPECIFIC_ERROR_CODE",
    "message": "Human-readable message",
    "details": [
        {
            "field": "metric_value",
            "code": "INVALID_VALUE",
            "message": "Must be positive number"
        }
    ],
    "timestamp": "2026-06-26T17:00:00Z",
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Pagination Standards

**All list endpoints must support:**

```python
GET /api/v1/audit/logs?limit=50&offset=0&sort_by=created_at&sort_order=desc

Response:
{
    "status": "success",
    "data": [...],
    "pagination": {
        "limit": 50,
        "offset": 0,
        "total": 1000,
        "has_more": true
    }
}
```

### Versioning Standards

```python
# API versions in header OR path
GET /api/v1/metrics              # Path-based (recommended)
GET /api/v2/metrics              # New version alongside

# Deprecation timeline
@deprecated(version="1.5", removed_in="2.0")
async def old_endpoint():
    """This endpoint is deprecated. Use /new-endpoint instead."""
    pass
```

### Performance Standards

**Target response times:**

```
Health checks          → < 50ms
Cached endpoints       → < 100ms
Direct DB queries      → < 300ms
Aggregation queries    → < 1000ms
Exports/reports        → < 5000ms (async)
```

### Security Standards

**Every protected endpoint requires:**

```python
from fastapi import Security
from backend.security.permissions import require_permission

@router.post("/automation/start")
async def start_automation(
    request: AutomationRequest,
    current_user = Security(
        get_current_user,
        scopes=["automation:start"],
    ),
):
    """Protected endpoint with permission check."""
    pass
```

### Code Review Checklist

Before merging any API code:

- [ ] Endpoint documented with docstring
- [ ] Error responses defined in decorator
- [ ] Input validation performed
- [ ] Output wrapped in `DataResponse` or `PaginatedResponse`
- [ ] Pagination implemented (if list endpoint)
- [ ] Tests written (unit + integration)
- [ ] Performance acceptable (meets SLA)
- [ ] No hardcoded values (config from environment)
- [ ] Request ID logged in audit trail
- [ ] RBAC checked (if protected)

---

## Implementation Roadmap

### ⚡ Immediate (Week 1-2)

```
Priority    Task                                  Effort  Owner
────────────────────────────────────────────────────────────
🔴 P0       Create depends.py                     1h      Backend
🔴 P0       Extract base.py (service/repo)        4h      Backend
🔴 P0       Error standardization middleware      3h      Backend
🔴 P0       Configuration to settings.py          2h      Backend
─
Total: ~10 hours (~1.5 days)
```

**Files to Create:**
- `backend/api/v1/depends.py`
- `backend/services/base.py`
- `backend/repositories/base.py`
- `backend/config/settings.py`

### 📅 Short-Term (Week 3-4)

```
Priority    Task                                  Effort  Owner
────────────────────────────────────────────────────────────
🟡 P1       Split services into individual files  6h      Backend
🟡 P1       Implement RBAC layer                  5h      Security
🟡 P1       Create test fixtures (conftest)       4h      QA
🟡 P1       Document all endpoints                6h      Backend
🟡 P1       Logging standardization               3h      Backend
─
Total: ~24 hours (~3 days)
```

**Deliverables:**
- RBAC permissions defined
- Test suite structure in place
- All endpoints documented
- Structured logging everywhere

### 🚀 Long-Term (Month 2+)

```
Priority    Task                                  Effort  Owner
────────────────────────────────────────────────────────────
🟢 P2       Route organization refactor           8h      Backend
🟢 P2       Domain-driven design patterns         10h     Architect
🟢 P2       Event-driven flows                    12h     Backend
🟢 P2       Analytics dashboard                  20h     Backend+Frontend
🟢 P2       Integration webhooks                  16h     Backend
🟢 P2       Caching strategy                      10h     Backend
─
Total: ~76 hours (~2 weeks)
```

### Git Commit Strategy

```bash
# Immediate tasks
git commit -m "refactor: extract dependency injection to depends.py"
git commit -m "refactor: create base service class"
git commit -m "refactor: create base repository class"
git commit -m "feat: add error standardization middleware"
git commit -m "refactor: centralize configuration in settings.py"

# Short-term tasks
git commit -m "refactor: split services into individual modules"
git commit -m "feat: implement role-based access control"
git commit -m "test: add pytest fixtures and conftest"
git commit -m "docs: document all API endpoints"
git commit -m "refactor: standardize structured logging"

# Long-term tasks
git commit -m "refactor: reorganize routes by feature domain"
git commit -m "feat: implement domain-driven design patterns"
git commit -m "feat: add event bus for notifications"
```

---

## Growth Capacity Analysis

### Current Architecture Can Handle

- ✓ **50+ endpoints** without major refactoring
- ✓ **10 concurrent users** without scaling
- ✓ **1 year of historical data** (1M rows)
- ✓ **5 team members** collaborating
- ✓ **10 microseconds** to 1 millisecond response times

### When to Refactor/Upgrade

| Metric | Threshold | Action |
|--------|-----------|--------|
| Endpoints | > 100 | Split to v2 API |
| Concurrent Users | > 50 | Add caching layer |
| Data Rows | > 10M | Add database indexes |
| Team Size | > 20 | Split into bounded contexts |
| Response Time | > 500ms | Profile and optimize |

### Technology Upgrade Path

```
Current         → Near-term      → Future
─────────────────────────────────────────
FastAPI 0.x     → FastAPI 1.x    → (auto-upgrade)
SQLAlchemy 2.0  → SQLAlchemy 2.x → (stable)
PostgreSQL      → PostgreSQL 14+ → PostgreSQL 16+
Python 3.10     → Python 3.11+   → Python 3.12+
```

---

## Summary

### Key Recommendations

1. **Routes:** Organize by domain (monitoring, automation, integration)
2. **Services:** Extract base class, split into individual files
3. **Repositories:** Implement generic base for 80% code reuse
4. **DI:** Use `depends.py` container for all services
5. **RBAC:** Implement granular permissions by resource
6. **Testing:** Pytest structure with fixtures, unit/integration/e2e
7. **Error Handling:** Standardize across all routes
8. **Configuration:** All env vars in settings.py
9. **Naming:** Follow conventions (resource_action, verb_criteria)
10. **Governance:** Document all endpoints, enforce standards in CI

### Implementation Timeline

- **Week 1-2 (Immediate):** 10 hours - DI, base classes, config
- **Week 3-4 (Short-term):** 24 hours - RBAC, testing, docs
- **Month 2+ (Long-term):** 76 hours - Refactoring, new features

### Expected Outcomes

✓ 50+ endpoints supported without technical debt
✓ New features added in 1-2 days (not weeks)
✓ Clear ownership boundaries by domain
✓ Onboarding time: 3 days (not 2 weeks)
✓ 90%+ test coverage
✓ 100% request traceability
✓ Scalable to 100+ users

---

**Document Version:** 1.0  
**Last Updated:** 2026-06-26  
**Target Audience:** Backend team, architects, tech leads
