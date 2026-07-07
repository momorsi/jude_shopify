# Admin UI & Operations Dashboard — Design Spec
**Date:** 2026-05-08  
**Project:** Jude Ben Halim — Shopify ↔ SAP B1 Integration  
**Status:** Approved

---

## Overview

A web-based admin UI served from the same Windows machine that runs the sync service. The business team accesses it from the office network. It provides: a live operations dashboard, a structured sync event log, manual sync controls, selective stock resync, mapping validation, configuration editing, and email notifications.

---

## Architecture

### Single Process — FastAPI wraps the sync engine

FastAPI is the main entry point, replacing `continuous_main.py`. All sync loops run as `asyncio` background tasks within the FastAPI app. One Windows service manages everything.

```
Windows Service → FastAPI app (port 8000)
  ├─ HTTP server (HTMX + Bootstrap frontend)
  ├─ orders_sync loop        (asyncio background task)
  ├─ inventory_sync loop     (asyncio background task)
  ├─ returns_sync loop       (asyncio background task)
  ├─ price_changes loop      (asyncio background task)
  └─ ... other sync tasks
  
Shared state:
  ├─ sync_events.db          (SQLite — structured event log)
  ├─ configurations.json     (runtime config, edited via UI)
  └─ SAP MSSQL via ODBC      (SAP B1 analytics + Shopify_Mapping2)
```

### Data sources

| Source | Used for |
|--------|----------|
| SAP Service Layer (HTTP) | All SAP writes (invoices, payments, credit notes, item creation) |
| SAP MSSQL via ODBC | Reads for analytics, stock levels, `Shopify_Mapping2` validation |
| SQLite `sync_events.db` | Sync run history, per-item event log, system state (locks, global pause) |
| `configurations.json` | Runtime config — edited via UI, reloaded without restart |

### Authentication

Single shared password via HTTP Basic Auth middleware. No per-user accounts. Password stored in `.env` as `UI_PASSWORD` (bcrypt hashed at startup).

### Store scoping

A global store selector in the top bar (Local EGP / International USD) scopes all dashboard data, logs, manual triggers, and mapping checks to the selected store. Selection persists in a session cookie.

---

## SQLite Schema (`sync_events.db`)

### `sync_runs`
One row per sync execution.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| sync_type | TEXT | `orders`, `stock`, `returns`, `price_changes`, `new_items`, `payment_recovery`, `returns_followup`, `gift_card_expiry` |
| store_key | TEXT | `local` or `international` |
| started_at | DATETIME | Run start timestamp |
| finished_at | DATETIME | Run end timestamp (NULL if running) |
| status | TEXT | `running`, `success`, `partial`, `failed` |
| total_processed | INTEGER | Total entities attempted |
| total_success | INTEGER | Successfully synced |
| total_errors | INTEGER | Failed |
| triggered_by | TEXT | `scheduler` or `manual` |

### `sync_events`
One row per entity processed within a run.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| run_id | INTEGER FK | References `sync_runs.id` |
| entity_type | TEXT | `order`, `sku`, `return`, `item`, `price` |
| entity_id | TEXT | Shopify order ID / SAP item code / etc. |
| entity_name | TEXT | Human-readable (order #4521, JB-BLK-S) |
| status | TEXT | `success` or `error` |
| sap_document | TEXT | SAP doc number created (e.g. `INV-82-00441`) |
| error_message | TEXT | Full error text if failed |
| created_at | DATETIME | Event timestamp |

### `system_state`
Key-value store for global runtime state.

| Key | Values | Description |
|-----|--------|-------------|
| `integration_paused` | `true` / `false` | Global stop/start switch |
| `sync_{type}_lock` | `running` / `idle` | Per-sync run lock (prevents overlap) |
| `sync_{type}_started_at` | ISO datetime | When current run started |

---

## Per-Sync Run Lock

Each sync type has a lock entry in `system_state`. Rules enforced in both the scheduler and the API:

1. Before starting any run (scheduled or manual): check `sync_{type}_lock`. If `running`, skip.
2. On run start: set lock to `running`, record `started_at`.
3. On run end (success or failure): set lock to `idle`, clear `started_at`.
4. On app startup: reset all stale locks (any lock with `started_at` older than 2 hours is considered stale and reset to `idle`).
5. UI: "Run Now" button is disabled + shows 🔒 tooltip when lock is `running`.

---

## Global Stop/Start

Stored as `integration_paused = true/false` in `system_state`.

- When `true`: all scheduled sync loops check this flag at the top of each iteration and sleep without running.
- Manual "Run Now" triggers also check this flag and return a `503 Integration is paused` error.
- The Stop All / Start button in the top bar toggles this value via `POST /api/system/pause` and `POST /api/system/resume`.
- State survives app restart (persisted in SQLite).

---

## Pages

### Dashboard (`/`)
- KPI cards: orders synced today, failed orders, stock updates today, mapping issues from last check
- Sync status table: all sync types, last run time, processed/errors, next scheduled run, Run Now button (locked if running), Enable/Disable toggle for disabled syncs
- Recent failures panel: last 10 failures with entity name, error summary, and context-aware action button
- Today's summary: aggregated counts from `sync_events` for the current day

### Logs (`/logs`)
- Filter bar: sync type, status (success/partial/failed), date range
- Collapsible run rows: expand to see per-item events (entity name, status, SAP document, error message)
- Pagination: load more items within a run on demand
- All data scoped to selected store

### Run Sync (`/sync`)
Three sections on one page:

**1. Manual Sync Triggers**  
Card per sync type with Run Now button (locked state when running, disabled state when sync is turned off in config).

**2. Selective Stock Resync**  
Text area for pasting SAP item codes (one per line). On submit: fetches current stock from SAP via ODBC for each code, pushes to Shopify for the selected store. Live progress output via Server-Sent Events (SSE) — one line per item as it completes.

**3. Mapping Health Check** (also accessible via `/mapping`)  
Reads `Shopify_Mapping2` via ODBC for the selected store. For each row: verifies the mapped Shopify product/variant exists via Shopify GraphQL and the SKU matches.  
Issues are classified as:
- **Not found in Shopify** — variant ID in mapping table doesn't exist → manual fix required
- **SKU mismatch** — variant exists but SKU doesn't match → auto-fixable by re-querying Shopify by SKU
- **OK** — mapping is valid

"Fix All Auto-fixable" updates the `Shopify_Mapping2` rows where the variant can be found by SKU match. These updates are written via SAP Service Layer PATCH (not direct ODBC writes) to avoid bypassing SAP's business logic layer.

### Config (`/config`)
Sections (all collapsible):
- **General**: test mode toggle, retry attempts, retry delay
- **SAP B1**: Service Layer URL, company, credentials (masked), ODBC/MSSQL connection fields
- **Shopify Stores**: per-store URL, credentials (masked), enabled toggle, currency, price list
- **Sync Schedule**: per-sync enable/disable toggle, interval (minutes), batch size, from date; disabled syncs grey out their fields

On save: writes changes back to `configurations.json`. The FastAPI app watches the file and reloads `ConfigSettings` without a restart. A "Test SAP Connection" button validates the Service Layer login in real time.

### Notifications (`/notifications`)
- **SMTP Settings**: host, port, username, password, TLS toggle, "Send test email" button
- **Recipients**: add/remove email addresses; each gets a role label (Admin/Staff)
- **Alert Rules**: per sync type — enable/disable alerts, minimum error threshold before alert fires

Email format: plain-text summary with sync type, store, error count, and the top 5 failed entities with their error messages.

---

## Retry Logic (per entity type)

Retry is not a generic re-run. Each entity type has specific retry semantics:

| Sync type | Failure marker | Retry action |
|-----------|---------------|-------------|
| Orders | Shopify tag `sap_invoice_failed` added on failure | Remove tag via Shopify GraphQL → eligible for next cycle |
| Returns | Shopify tag `sap_return_failed` added on failure | Remove tag via Shopify GraphQL → eligible for next cycle |
| New Items | SAP item has no `U_LOCAL_SID` / `U_LOCAL_VARIANT_SID` | Re-run item creation for that specific SAP item code |
| Stock | No persistent failure state | Force-push current ODBC stock value for that SKU via selective resync |
| Price Changes | No persistent failure state | Re-run price change sync; or use selective resync if per-item targeting needed |

The "Recent Failures" panel on the dashboard shows the correct action button per entity type. Tag-based retries call `POST /api/retry/order/{shopify_order_id}` which removes the failure tag via Shopify API.

---

## Structured Logging (new items sync)

Replace plain `logger.info()` calls in sync modules with writes to `sync_events`. Each item processed emits one event row with outcome, SAP document created or error text. This gives the business a per-item audit trail visible in the Logs page — replacing the current opaque rotating text file.

The existing `logs/sync.log` is kept for debugging but is no longer the primary business log.

---

## ODBC Integration

Used for reads only. All writes (including `Shopify_Mapping2` auto-fixes) continue through SAP Service Layer.

Key queries:
- Stock levels: `OITW` (item warehouse) filtered by warehouse codes from config
- `Shopify_Mapping2`: full table read for mapping validation
- Analytics: `OINV` (invoices), `ORIN` (credit notes) for dashboard summary stats

Connection configured via `.env` file (populated by the operator). Variables: `ODBC_HOST`, `ODBC_PORT`, `ODBC_DATABASE`, `ODBC_USERNAME`, `ODBC_PASSWORD`. Driver hardcoded to `ODBC Driver 17 for SQL Server`. Managed via `pyodbc`. Connection pooled and reused across requests.

SAP user-defined tables use the `@` prefix in MSSQL — e.g. `[@U_SHOPIFY_MAPPING_2]`. The mapping health check queries `WHERE U_Shopify_Type = 'variant' AND U_Shopify_Store = '{store_key}'`, using `Code` as the Shopify variant ID and `U_SAP_Code` as the SAP item code (SKU).

---

## Implementation Phases

| Phase | Scope |
|-------|-------|
| 1 | Backend foundation: SQLite event log schema, per-sync lock, global pause flag, FastAPI app replacing `continuous_main.py`, ODBC connection module, structured event writes in all sync modules, HTTP Basic Auth middleware |
| 2 | Dashboard + Logs pages: KPI cards (from SQLite), sync status table, recent failures, log viewer with collapsible runs and per-item detail, store-scoped queries |
| 3 | Manual controls: Run Now endpoint with lock enforcement, selective stock resync with SSE progress, mapping health check against `Shopify_Mapping2`, tag-based retry endpoints for orders/returns |
| 4 | Config editor: form UI for all `configurations.json` sections, file write on save, live reload without restart, connection test endpoint |
| 5 | Email notifications: SMTP config, recipient management, alert rules, per-sync-run email dispatch after error threshold exceeded |

Each phase is independently deliverable and leaves the system in a working state.
