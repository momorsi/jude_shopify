# Phase 1: Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `continuous_main.py` with a FastAPI app that runs all sync loops as asyncio background tasks, adds a SQLite event log, per-sync locking, a global pause flag, ODBC connectivity, and HTTP Basic Auth — leaving the system fully functional and ready for the Phase 2 UI.

**Architecture:** FastAPI lifespan launches one asyncio task per enabled sync type (mirroring the current `run_continuous_syncs` loop). A SQLite database (`sync_events.db`) tracks every run and per-entity event. A `contextvars.ContextVar` carries the active `run_id` into sync modules without touching their signatures. All credentials (UI password, ODBC details) come from `.env`.

**Tech Stack:** FastAPI, Uvicorn, aiosqlite, pyodbc, passlib[bcrypt], python-dotenv, python-multipart, itsdangerous, jinja2

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `.env.example` | Template for operator to populate |
| Create | `app/db/__init__.py` | Package marker |
| Create | `app/db/database.py` | SQLite init, schema creation, `get_db()` async context manager |
| Create | `app/db/models.py` | SQLite query helpers: `start_run`, `finish_run`, `emit_event`, `get_state`, `set_state` |
| Create | `app/db/lock.py` | `acquire_lock`, `release_lock`, `reset_stale_locks`, `is_paused` using system_state table |
| Create | `app/services/odbc/__init__.py` | Package marker |
| Create | `app/services/odbc/client.py` | `ODBCClient` — connection pool, `execute_query`, `get_stock_levels`, `get_mapping_rows` |
| Create | `app/web/__init__.py` | Package marker |
| Create | `app/web/auth.py` | `verify_password`, `BasicAuthMiddleware` (starlette middleware) |
| Create | `app/web/app.py` | FastAPI app factory with lifespan (sync background tasks), placeholder routes |
| Create | `web_main.py` | Entry point — `uvicorn.run(app, host="0.0.0.0", port=8000)` |
| Modify | `requirements.txt` | Add: pyodbc, passlib[bcrypt], aiosqlite, itsdangerous, jinja2, python-multipart |
| Modify | `app/main.py` | Wrap `_run_sync_with_interval` with lock-check + `start_run`/`finish_run`; check global pause flag; accept `triggered_by` param |
| Modify | `app/sync/sales/orders_sync.py` | Call `emit_event()` for each processed order |
| Modify | `app/sync/sales/returns_sync_v4.py` | Call `emit_event()` for each processed return |
| Modify | `app/sync/inventory.py` | Call `emit_event()` for each processed SKU |
| Modify | `app/sync/price_changes.py` | Call `emit_event()` for each processed price |
| Modify | `app/sync/new_items_multi_store.py` | Call `emit_event()` for each processed item |
| Modify | `app/sync/sales/payment_recovery.py` | Call `emit_event()` for each processed payment |

---

## Task 1: Add dependencies to requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add missing packages**

Open `requirements.txt` and append:

```
pyodbc>=4.0.39
passlib[bcrypt]>=1.7.4
aiosqlite>=0.19.0
itsdangerous>=2.1.2
jinja2>=3.1.2
python-multipart>=0.0.6
```

- [ ] **Step 2: Install**

```
pip install pyodbc passlib[bcrypt] aiosqlite itsdangibles jinja2 python-multipart
```

Expected: packages install without errors. If `pyodbc` fails on Windows, install "ODBC Driver 17 for SQL Server" from Microsoft first.

- [ ] **Step 3: Commit**

```
git add requirements.txt
git commit -m "chore: add admin UI dependencies (aiosqlite, pyodbc, passlib, jinja2)"
```

---

## Task 2: Create `.env.example`

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Write the template**

```
# Admin UI password (plain text here; hashed at startup)
UI_PASSWORD=changeme

# SAP MSSQL / ODBC connection
ODBC_HOST=10.0.0.100
ODBC_PORT=1433
ODBC_DATABASE=SBODemoUS
ODBC_USERNAME=sa
ODBC_PASSWORD=
```

- [ ] **Step 2: Verify `.gitignore` excludes `.env`**

Check that `.gitignore` contains a line matching `.env`. If not, add it.

- [ ] **Step 3: Commit**

```
git add .env.example
git commit -m "chore: add .env.example with UI and ODBC config placeholders"
```

---

## Task 3: SQLite database module

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/database.py`

- [ ] **Step 1: Write `app/db/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Write `app/db/database.py`**

```python
import aiosqlite
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

DB_PATH = Path("sync_events.db")

_CREATE_SYNC_RUNS = """
CREATE TABLE IF NOT EXISTS sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type     TEXT    NOT NULL,
    store_key     TEXT    NOT NULL DEFAULT '',
    started_at    DATETIME NOT NULL DEFAULT (datetime('now')),
    finished_at   DATETIME,
    status        TEXT    NOT NULL DEFAULT 'running',
    total_processed INTEGER NOT NULL DEFAULT 0,
    total_success   INTEGER NOT NULL DEFAULT 0,
    total_errors    INTEGER NOT NULL DEFAULT 0,
    triggered_by  TEXT    NOT NULL DEFAULT 'scheduler'
)
"""

_CREATE_SYNC_EVENTS = """
CREATE TABLE IF NOT EXISTS sync_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES sync_runs(id),
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL DEFAULT '',
    entity_name   TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL,
    sap_document  TEXT    NOT NULL DEFAULT '',
    error_message TEXT    NOT NULL DEFAULT '',
    created_at    DATETIME NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_SYSTEM_STATE = """
CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT (datetime('now'))
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_runs_type_store  ON sync_runs(sync_type, store_key)",
    "CREATE INDEX IF NOT EXISTS idx_runs_started     ON sync_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_run_id    ON sync_events(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_status    ON sync_events(status)",
]

async def init_db() -> None:
    """Create tables and indexes if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_SYNC_RUNS)
        await db.execute(_CREATE_SYNC_EVENTS)
        await db.execute(_CREATE_SYSTEM_STATE)
        for idx in _INDEXES:
            await db.execute(idx)
        await db.commit()

@asynccontextmanager
async def get_db():
    """Async context manager returning an open aiosqlite connection."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
```

- [ ] **Step 3: Verify the module imports cleanly**

```
python -c "from app.db.database import init_db; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```
git add app/db/__init__.py app/db/database.py
git commit -m "feat: add SQLite database module with schema for sync_runs, sync_events, system_state"
```

---

## Task 4: SQLite model helpers

**Files:**
- Create: `app/db/models.py`

- [ ] **Step 1: Write `app/db/models.py`**

```python
from datetime import datetime
from typing import Optional
from app.db.database import get_db


async def start_run(sync_type: str, store_key: str = "", triggered_by: str = "scheduler") -> int:
    """Insert a new sync_run row and return its id."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO sync_runs (sync_type, store_key, status, triggered_by)
            VALUES (?, ?, 'running', ?)
            """,
            (sync_type, store_key, triggered_by),
        )
        await db.commit()
        return cursor.lastrowid


async def finish_run(
    run_id: int,
    status: str,
    total_processed: int,
    total_success: int,
    total_errors: int,
) -> None:
    """Mark a sync_run as finished with final counters."""
    async with get_db() as db:
        await db.execute(
            """
            UPDATE sync_runs
            SET finished_at = datetime('now'),
                status = ?,
                total_processed = ?,
                total_success = ?,
                total_errors = ?
            WHERE id = ?
            """,
            (status, total_processed, total_success, total_errors, run_id),
        )
        await db.commit()


async def emit_event(
    run_id: int,
    entity_type: str,
    entity_id: str,
    entity_name: str,
    status: str,
    sap_document: str = "",
    error_message: str = "",
) -> None:
    """Insert one row into sync_events."""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO sync_events
                (run_id, entity_type, entity_id, entity_name, status, sap_document, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, entity_type, entity_id, entity_name, status, sap_document, error_message),
        )
        await db.commit()


async def get_state(key: str) -> Optional[str]:
    """Read a value from system_state. Returns None if key is absent."""
    async with get_db() as db:
        async with db.execute("SELECT value FROM system_state WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None


async def set_state(key: str, value: str) -> None:
    """Upsert a key in system_state."""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value),
        )
        await db.commit()
```

- [ ] **Step 2: Quick smoke test**

```python
# run once interactively or as a quick script
import asyncio
from app.db.database import init_db
from app.db.models import start_run, finish_run, emit_event, get_state, set_state

async def test():
    await init_db()
    run_id = await start_run("orders", "local", "manual")
    await emit_event(run_id, "order", "12345", "Order #12345", "success", "INV-82-00441")
    await finish_run(run_id, "success", 1, 1, 0)
    await set_state("integration_paused", "false")
    val = await get_state("integration_paused")
    assert val == "false", f"Expected 'false', got {val!r}"
    print("all assertions passed")

asyncio.run(test())
```

Expected: `all assertions passed`

- [ ] **Step 3: Commit**

```
git add app/db/models.py
git commit -m "feat: add sync_runs and sync_events model helpers (start_run, finish_run, emit_event, get/set_state)"
```

---

## Task 5: Per-sync lock module

**Files:**
- Create: `app/db/lock.py`

- [ ] **Step 1: Write `app/db/lock.py`**

```python
from datetime import datetime, timedelta
from app.db.models import get_state, set_state
from app.utils.logging import logger

STALE_AFTER_HOURS = 2

SYNC_TYPES = [
    "orders", "stock", "returns", "price_changes", "new_items",
    "payment_recovery", "returns_followup", "gift_card_expiry",
    "item_changes", "freight_prices", "color_metaobjects",
]


async def reset_stale_locks() -> None:
    """Called on app startup. Resets any lock whose started_at is >2 hours old."""
    now = datetime.utcnow()
    for sync_type in SYNC_TYPES:
        lock_val = await get_state(f"sync_{sync_type}_lock")
        if lock_val == "running":
            started_str = await get_state(f"sync_{sync_type}_started_at")
            if started_str:
                try:
                    started = datetime.fromisoformat(started_str)
                    if (now - started) > timedelta(hours=STALE_AFTER_HOURS):
                        logger.warning(f"Resetting stale lock for {sync_type} (started {started_str})")
                        await set_state(f"sync_{sync_type}_lock", "idle")
                        await set_state(f"sync_{sync_type}_started_at", "")
                except ValueError:
                    await set_state(f"sync_{sync_type}_lock", "idle")


async def acquire_lock(sync_type: str) -> bool:
    """
    Attempt to acquire the run lock for sync_type.
    Returns True if acquired, False if already running.
    """
    current = await get_state(f"sync_{sync_type}_lock")
    if current == "running":
        return False
    await set_state(f"sync_{sync_type}_lock", "running")
    await set_state(f"sync_{sync_type}_started_at", datetime.utcnow().isoformat())
    return True


async def release_lock(sync_type: str) -> None:
    """Release the run lock for sync_type."""
    await set_state(f"sync_{sync_type}_lock", "idle")
    await set_state(f"sync_{sync_type}_started_at", "")


async def is_paused() -> bool:
    """Return True if the integration_paused flag is set to 'true'."""
    val = await get_state("integration_paused")
    return val == "true"
```

- [ ] **Step 2: Verify it imports**

```
python -c "from app.db.lock import acquire_lock, release_lock, reset_stale_locks, is_paused; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add app/db/lock.py
git commit -m "feat: add per-sync lock module with stale-lock reset and global pause check"
```

---

## Task 6: ODBC client module

**Files:**
- Create: `app/services/odbc/__init__.py`
- Create: `app/services/odbc/client.py`

- [ ] **Step 1: Write `app/services/odbc/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Write `app/services/odbc/client.py`**

```python
import os
import pyodbc
from typing import List, Dict, Any, Optional
from app.utils.logging import logger

_DRIVER = "ODBC Driver 17 for SQL Server"


def _build_connection_string() -> str:
    host = os.getenv("ODBC_HOST", "")
    port = os.getenv("ODBC_PORT", "1433")
    database = os.getenv("ODBC_DATABASE", "")
    username = os.getenv("ODBC_USERNAME", "")
    password = os.getenv("ODBC_PASSWORD", "")
    return (
        f"DRIVER={{{_DRIVER}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )


class ODBCClient:
    """
    Synchronous pyodbc wrapper. All heavy queries should be run in a
    thread pool executor so they don't block the asyncio event loop.
    """

    def __init__(self):
        self._conn: Optional[pyodbc.Connection] = None

    def connect(self) -> None:
        """Open (or re-open) the MSSQL connection."""
        conn_str = _build_connection_string()
        self._conn = pyodbc.connect(conn_str, autocommit=True)
        logger.info("ODBC connection established")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_connected(self) -> pyodbc.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    def execute_query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT and return rows as list-of-dicts."""
        conn = self._ensure_connected()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_stock_levels(self, warehouse_codes: List[str], item_codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetch on-hand quantity from OITW for given warehouses.
        Optionally filter by a list of item codes.
        """
        placeholders = ",".join("?" * len(warehouse_codes))
        sql = f"""
            SELECT w.ItemCode, w.WhsCode, w.OnHand
            FROM OITW w
            WHERE w.WhsCode IN ({placeholders})
        """
        params: list = list(warehouse_codes)
        if item_codes:
            item_ph = ",".join("?" * len(item_codes))
            sql += f" AND w.ItemCode IN ({item_ph})"
            params.extend(item_codes)
        return self.execute_query(sql, tuple(params))

    def get_mapping_rows(self, store_key: str) -> List[Dict[str, Any]]:
        """
        Return all variant rows from [@U_SHOPIFY_MAPPING_2] for the given store.
        Columns: Code, U_SAP_Code, U_Shopify_Type, U_Shopify_Store, U_SAP_Type
        """
        sql = """
            SELECT Code, U_SAP_Code, U_Shopify_Type, U_Shopify_Store, U_SAP_Type
            FROM [@U_SHOPIFY_MAPPING_2]
            WHERE U_Shopify_Type = 'variant'
              AND U_Shopify_Store = ?
        """
        return self.execute_query(sql, (store_key,))

    def test_connection(self) -> bool:
        """Return True if a simple query succeeds."""
        try:
            self.execute_query("SELECT 1 AS ok")
            return True
        except Exception as e:
            logger.error(f"ODBC connection test failed: {e}")
            return False


odbc_client = ODBCClient()
```

- [ ] **Step 3: Verify it imports (ODBC credentials not needed for import check)**

```
python -c "from app.services.odbc.client import odbc_client; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```
git add app/services/odbc/__init__.py app/services/odbc/client.py
git commit -m "feat: add ODBC client module for SAP MSSQL reads (stock levels, mapping table)"
```

---

## Task 7: HTTP Basic Auth middleware

**Files:**
- Create: `app/web/__init__.py`
- Create: `app/web/auth.py`

- [ ] **Step 1: Write `app/web/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Write `app/web/auth.py`**

```python
import os
import base64
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_hashed_password: str = ""


def _get_hashed_password() -> str:
    """Hash UI_PASSWORD from env on first call, cache result."""
    global _hashed_password
    if not _hashed_password:
        plain = os.getenv("UI_PASSWORD", "changeme")
        _hashed_password = _pwd_context.hash(plain)
    return _hashed_password


def verify_password(plain: str) -> bool:
    return _pwd_context.verify(plain, _get_hashed_password())


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Require HTTP Basic Auth for all routes."""

    REALM = "Jude Sync Admin"

    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                if verify_password(password):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{self.REALM}"'},
        )
```

- [ ] **Step 3: Verify it imports**

```
python -c "from app.web.auth import BasicAuthMiddleware, verify_password; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```
git add app/web/__init__.py app/web/auth.py
git commit -m "feat: add HTTP Basic Auth middleware (password from UI_PASSWORD env var)"
```

---

## Task 8: FastAPI app with lifespan sync tasks

**Files:**
- Create: `app/web/app.py`

- [ ] **Step 1: Write `app/web/app.py`**

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db.database import init_db
from app.db.lock import reset_stale_locks
from app.web.auth import BasicAuthMiddleware
from app.main import ShopifySAPSync
from app.core.config import config_settings
from app.utils.logging import logger
from app.utils.ssl_cert import init_ssl


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_ssl()
    await init_db()
    await reset_stale_locks()
    logger.info("sync_events.db initialised; stale locks reset")

    sync_controller = ShopifySAPSync()
    app.state.sync_controller = sync_controller

    tasks = []

    def schedule(sync_type: str, interval_minutes: int):
        t = asyncio.create_task(
            _run_sync_loop(sync_controller, sync_type, interval_minutes)
        )
        tasks.append(t)

    if config_settings.new_items_enabled:
        schedule("new_items", config_settings.new_items_interval)
    if config_settings.inventory_enabled:
        schedule("stock", config_settings.inventory_interval)
    if config_settings.item_changes_enabled:
        schedule("item_changes", config_settings.item_changes_interval)
    if config_settings.price_changes_enabled:
        schedule("price_changes", config_settings.price_changes_interval)
    if config_settings.sales_orders_enabled:
        schedule("sales_orders", config_settings.sales_orders_interval)
    if config_settings.payment_recovery_enabled:
        schedule("payment_recovery", config_settings.payment_recovery_interval)
    if config_settings.returns_enabled:
        schedule("returns", config_settings.returns_interval)
    if config_settings.returns_followup_enabled:
        schedule("returns_followup", config_settings.returns_followup_interval)
    if config_settings.gift_card_expiry_enabled:
        schedule("gift_card_expiry", config_settings.gift_card_expiry_interval)

    logger.info(f"Started {len(tasks)} sync background task(s)")
    yield

    # Shutdown
    sync_controller.running = False
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("All sync tasks stopped")


async def _run_sync_loop(controller: ShopifySAPSync, sync_type: str, interval_minutes: int):
    """Background loop: check pause/lock, run sync, sleep, repeat."""
    from app.db.lock import acquire_lock, release_lock, is_paused
    from app.db.models import start_run, finish_run
    import contextvars

    run_id_var: contextvars.ContextVar[int] = contextvars.ContextVar("run_id", default=0)

    while controller.running:
        paused = await is_paused()
        if paused:
            logger.info(f"[{sync_type}] Integration paused — skipping run")
            await asyncio.sleep(60)
            continue

        acquired = await acquire_lock(sync_type)
        if not acquired:
            logger.info(f"[{sync_type}] Lock held — skipping scheduled run")
            await asyncio.sleep(60)
            continue

        run_id = await start_run(sync_type, triggered_by="scheduler")
        run_id_var.set(run_id)
        # Make run_id available to sync modules via a module-level ContextVar
        from app.db import _run_id_ctx
        token = _run_id_ctx.set(run_id)

        processed = success = errors = 0
        final_status = "success"
        try:
            logger.info(f"[{sync_type}] Starting scheduled run (run_id={run_id})")
            result = await controller.run_specific_sync(sync_type)
            processed = result.get("processed", 0)
            success = result.get("successful", result.get("success", 0))
            errors = result.get("errors", 0)
            if result.get("msg") != "success":
                final_status = "failed"
            elif errors > 0:
                final_status = "partial"
        except Exception as e:
            logger.error(f"[{sync_type}] Unhandled exception: {e}")
            final_status = "failed"
            errors = 1
        finally:
            _run_id_ctx.reset(token)
            await finish_run(run_id, final_status, processed, success, errors)
            await release_lock(sync_type)

        logger.info(
            f"[{sync_type}] Run {run_id} finished — status={final_status}, "
            f"processed={processed}, success={success}, errors={errors}"
        )
        await asyncio.sleep(interval_minutes * 60)


def create_app() -> FastAPI:
    app = FastAPI(title="Jude Sync Admin", lifespan=lifespan)
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
```

- [ ] **Step 2: Add `_run_id_ctx` to `app/db/__init__.py`**

The lifespan loop references `app.db._run_id_ctx`. Add it:

```python
import contextvars

_run_id_ctx: contextvars.ContextVar[int] = contextvars.ContextVar("run_id", default=0)
```

- [ ] **Step 3: Verify app imports**

```
python -c "from app.web.app import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```
git add app/db/__init__.py app/web/app.py
git commit -m "feat: FastAPI app with lifespan sync loops, lock enforcement, global pause check"
```

---

## Task 9: `web_main.py` entry point

**Files:**
- Create: `web_main.py`

- [ ] **Step 1: Write `web_main.py`**

```python
#!/usr/bin/env python3
import os
from dotenv import load_dotenv

load_dotenv()

import uvicorn
from app.web.app import app  # noqa: F401 — import triggers lifespan registration

if __name__ == "__main__":
    uvicorn.run(
        "app.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
```

- [ ] **Step 2: Start the app and verify it responds**

```
python web_main.py
```

In another terminal:
```
curl -u :changeme http://localhost:8000/health
```

Expected response: `{"status":"ok"}`

Expected logs: `sync_events.db initialised; stale locks reset`, then `Started N sync background task(s)`

- [ ] **Step 3: Commit**

```
git add web_main.py
git commit -m "feat: add web_main.py entry point (replaces continuous_main.py)"
```

---

## Task 10: Wrap `_run_sync_with_interval` in `app/main.py` with run tracking

The `_run_sync_loop` in `app/web/app.py` already handles locking and `start_run`/`finish_run` for scheduled runs. For **manual triggers** (added in Phase 3), `run_specific_sync` needs the same wrapping. In this phase, we add a helper that Phase 3 can call.

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Read current `run_specific_sync` method (lines 210-283)**

Confirm the method signature: `async def run_specific_sync(self, sync_type: str) -> Dict[str, Any]`

- [ ] **Step 2: Add `run_tracked_sync` method after `run_specific_sync`**

Add this method to the `ShopifySAPSync` class, right after `run_specific_sync`:

```python
async def run_tracked_sync(self, sync_type: str, triggered_by: str = "manual") -> Dict[str, Any]:
    """
    Run a sync with full lock enforcement, pause check, and SQLite event logging.
    Returns the sync result dict, augmented with run_id.
    Used by the manual Run Now API endpoint (Phase 3).
    """
    from app.db.lock import acquire_lock, release_lock, is_paused
    from app.db.models import start_run, finish_run
    from app.db import _run_id_ctx

    if await is_paused():
        return {"msg": "failure", "error": "Integration is paused", "code": 503}

    acquired = await acquire_lock(sync_type)
    if not acquired:
        return {"msg": "failure", "error": f"{sync_type} is already running", "code": 409}

    run_id = await start_run(sync_type, triggered_by=triggered_by)
    token = _run_id_ctx.set(run_id)

    processed = success = errors = 0
    final_status = "success"
    try:
        result = await self.run_specific_sync(sync_type)
        processed = result.get("processed", 0)
        success = result.get("successful", result.get("success", 0))
        errors = result.get("errors", 0)
        if result.get("msg") != "success":
            final_status = "failed"
        elif errors > 0:
            final_status = "partial"
        result["run_id"] = run_id
        return result
    except Exception as e:
        final_status = "failed"
        errors = 1
        return {"msg": "failure", "error": str(e), "run_id": run_id}
    finally:
        _run_id_ctx.reset(token)
        await finish_run(run_id, final_status, processed, success, errors)
        await release_lock(sync_type)
```

- [ ] **Step 3: Verify app still starts cleanly**

```
python -c "from app.main import ShopifySAPSync; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```
git add app/main.py
git commit -m "feat: add run_tracked_sync() to ShopifySAPSync for manual triggers with lock + event log"
```

---

## Task 11: Emit events in `orders_sync.py`

**Files:**
- Modify: `app/sync/sales/orders_sync.py`

The orders sync processes one order at a time. We need to emit a `sync_events` row for each order at the point where success/failure is determined.

- [ ] **Step 1: Find the success/failure points**

The confirmed tag patterns are at approximately:
- Success tag `sap_invoice_synced` — around line 2510 and 2826
- Failure tag `sap_invoice_failed` — around line 2861

Search for these locations:
```
grep -n "sap_invoice_synced\|sap_invoice_failed" app/sync/sales/orders_sync.py | head -20
```

- [ ] **Step 2: Add import at the top of `orders_sync.py`**

After the existing imports, add:

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event**

At each location where `sap_invoice_synced` tag is added (success path), add after the tag call:

```python
await emit_event(
    run_id=_run_id_ctx.get(),
    entity_type="order",
    entity_id=str(order_id),
    entity_name=f"Order #{order_name}",
    status="success",
    sap_document=str(invoice_doc_entry or ""),
)
```

Replace `order_id`, `order_name`, `invoice_doc_entry` with the actual variable names at those locations.

- [ ] **Step 4: Emit error event**

At the location where `sap_invoice_failed` tag is added (failure path), add after the tag call:

```python
await emit_event(
    run_id=_run_id_ctx.get(),
    entity_type="order",
    entity_id=str(order_id),
    entity_name=f"Order #{order_name}",
    status="error",
    error_message=str(error_msg),
)
```

Replace `order_id`, `order_name`, `error_msg` with the actual variable names at those locations.

- [ ] **Step 5: Guard — skip emit if run_id is 0**

If `_run_id_ctx.get()` returns 0 (sync ran outside FastAPI, e.g. CLI), emit is a no-op. Wrap any `emit_event` call:

```python
if _run_id_ctx.get() != 0:
    await emit_event(...)
```

- [ ] **Step 6: Test that orders sync still runs without errors**

```
python -c "
import asyncio
from app.db.database import init_db
from app.db import _run_id_ctx
from app.sync.sales.orders_sync import OrdersSalesSync
async def t():
    await init_db()
    _run_id_ctx.set(0)  # simulate no-tracking context
    print('import ok')
asyncio.run(t())
"
```

Expected: `import ok`

- [ ] **Step 7: Commit**

```
git add app/sync/sales/orders_sync.py
git commit -m "feat: emit sync_events rows for each order success/failure in orders_sync"
```

---

## Task 12: Emit events in `returns_sync_v4.py`

**Files:**
- Modify: `app/sync/sales/returns_sync_v4.py`

Tags confirmed: success = `sap_return_synced` (lines ~463/524), failure = `sap_return_failed` (lines ~499/532/537).

- [ ] **Step 1: Find the tag locations**

```
grep -n "sap_return_synced\|sap_return_failed" app/sync/sales/returns_sync_v4.py | head -20
```

- [ ] **Step 2: Add imports**

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event** at each `sap_return_synced` location:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="return",
        entity_id=str(return_id),
        entity_name=f"Return for Order #{order_name}",
        status="success",
        sap_document=str(credit_note_doc or ""),
    )
```

Replace variable names with actuals at each location.

- [ ] **Step 4: Emit error event** at each `sap_return_failed` location:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="return",
        entity_id=str(return_id),
        entity_name=f"Return for Order #{order_name}",
        status="error",
        error_message=str(error_msg),
    )
```

- [ ] **Step 5: Verify import**

```
python -c "from app.sync.sales.returns_sync_v4 import ReturnsSyncV4; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```
git add app/sync/sales/returns_sync_v4.py
git commit -m "feat: emit sync_events rows for each return success/failure in returns_sync_v4"
```

---

## Task 13: Emit events in `inventory.py`

**Files:**
- Modify: `app/sync/inventory.py`

- [ ] **Step 1: Find where individual SKU results are logged**

```
grep -n "logger\.\(info\|error\|warning\)" app/sync/inventory.py | head -30
```

Identify the loop body where per-SKU success/error is determined.

- [ ] **Step 2: Add imports**

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event** for each SKU pushed to Shopify successfully:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="sku",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="success",
    )
```

- [ ] **Step 4: Emit error event** for each SKU that failed:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="sku",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="error",
        error_message=str(error_msg),
    )
```

- [ ] **Step 5: Verify import**

```
python -c "from app.sync.inventory import sync_stock_change_view; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```
git add app/sync/inventory.py
git commit -m "feat: emit sync_events rows per SKU in inventory sync"
```

---

## Task 14: Emit events in `price_changes.py`

**Files:**
- Modify: `app/sync/price_changes.py`

- [ ] **Step 1: Find per-item success/error points**

```
grep -n "logger\.\(info\|error\|warning\)" app/sync/price_changes.py | head -30
```

- [ ] **Step 2: Add imports**

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event** per price item updated:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="price",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="success",
    )
```

- [ ] **Step 4: Emit error event** per item that failed:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="price",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="error",
        error_message=str(error_msg),
    )
```

- [ ] **Step 5: Verify import**

```
python -c "from app.sync.price_changes import price_changes_sync; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```
git add app/sync/price_changes.py
git commit -m "feat: emit sync_events rows per price item in price_changes sync"
```

---

## Task 15: Emit events in `new_items_multi_store.py`

**Files:**
- Modify: `app/sync/new_items_multi_store.py`

- [ ] **Step 1: Find per-item success/error points**

```
grep -n "logger\.\(info\|error\|warning\)" app/sync/new_items_multi_store.py | head -40
```

Look for the loop where each SAP item is processed and either created in Shopify or fails.

- [ ] **Step 2: Add imports**

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event** per new item created:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="item",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="success",
        sap_document=str(shopify_product_id or ""),
    )
```

- [ ] **Step 4: Emit error event** per item that failed:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="item",
        entity_id=str(item_code),
        entity_name=str(item_code),
        status="error",
        error_message=str(error_msg),
    )
```

- [ ] **Step 5: Verify import**

```
python -c "from app.sync.new_items_multi_store import MultiStoreNewItemsSync; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```
git add app/sync/new_items_multi_store.py
git commit -m "feat: emit sync_events rows per item in new_items_multi_store sync"
```

---

## Task 16: Emit events in `payment_recovery.py`

**Files:**
- Modify: `app/sync/sales/payment_recovery.py`

- [ ] **Step 1: Find per-payment success/error points**

```
grep -n "logger\.\(info\|error\|warning\)" app/sync/sales/payment_recovery.py | head -30
```

- [ ] **Step 2: Add imports**

```python
from app.db import _run_id_ctx
from app.db.models import emit_event
```

- [ ] **Step 3: Emit success event** per recovered payment:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="order",
        entity_id=str(invoice_id),
        entity_name=f"Invoice {invoice_id}",
        status="success",
        sap_document=str(invoice_id),
    )
```

- [ ] **Step 4: Emit error event** per failed recovery:

```python
if _run_id_ctx.get() != 0:
    await emit_event(
        run_id=_run_id_ctx.get(),
        entity_type="order",
        entity_id=str(invoice_id),
        entity_name=f"Invoice {invoice_id}",
        status="error",
        error_message=str(error_msg),
    )
```

- [ ] **Step 5: Verify import**

```
python -c "from app.sync.sales.payment_recovery import PaymentRecoverySync; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```
git add app/sync/sales/payment_recovery.py
git commit -m "feat: emit sync_events rows per payment in payment_recovery sync"
```

---

## Task 17: End-to-end smoke test

- [ ] **Step 1: Start `web_main.py` with `.env` populated**

```
python web_main.py
```

Confirm in logs:
- `sync_events.db initialised`
- `stale locks reset`
- `Started N sync background task(s)`

- [ ] **Step 2: Verify health endpoint requires auth**

```
curl http://localhost:8000/health
```
Expected: `401 Unauthorized`

```
curl -u :changeme http://localhost:8000/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: Let one sync cycle run, then verify database has rows**

```python
import asyncio, aiosqlite

async def check():
    async with aiosqlite.connect("sync_events.db") as db:
        async with db.execute("SELECT COUNT(*) FROM sync_runs") as cur:
            print("sync_runs:", (await cur.fetchone())[0])
        async with db.execute("SELECT COUNT(*) FROM system_state") as cur:
            print("system_state rows:", (await cur.fetchone())[0])

asyncio.run(check())
```

Expected: `sync_runs: 1` (or more), `system_state rows: 2` (or more)

- [ ] **Step 4: Commit**

```
git add -A
git commit -m "test: Phase 1 smoke test — FastAPI app starts, auth works, SQLite log populated"
```

---

## Phase 1 Complete Checklist

- [ ] `requirements.txt` has all 6 new packages
- [ ] `.env.example` exists; `.env` excluded from git
- [ ] `sync_events.db` schema creates on startup (3 tables, indexes)
- [ ] `start_run` / `finish_run` / `emit_event` / `get_state` / `set_state` work
- [ ] Per-sync lock prevents overlapping runs
- [ ] Stale locks reset on startup (2-hour threshold)
- [ ] Global `integration_paused` flag checked before each run
- [ ] `_run_id_ctx` ContextVar threads run_id into sync modules
- [ ] ODBC client imports; connects when `.env` is populated
- [ ] HTTP Basic Auth rejects unauthenticated requests
- [ ] `web_main.py` starts Uvicorn on port 8000
- [ ] All 6 sync modules emit `sync_events` rows (guarded by `run_id != 0`)
- [ ] `run_tracked_sync()` exists on `ShopifySAPSync` for Phase 3 manual triggers
- [ ] `continuous_main.py` still works (not deleted — kept as fallback)
