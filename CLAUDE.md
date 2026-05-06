# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

SAP Business One ↔ Shopify bidirectional integration. It syncs master data (items, prices, inventory) from SAP to Shopify, and sales data (orders, returns, payment recovery) from Shopify back to SAP. Supports multiple Shopify stores (local EGP store + international USD store) mapped to SAP warehouses and cost centers.

## Running the Sync

```bash
# Install dependencies
pip install -r requirements.txt

# Run all enabled syncs once
python main.py

# Continuous mode (runs each sync on its own interval from config)
python continuous_main.py

# Run a specific sync type via the CLI
python app/main.py --sync <type> --verbose
# Available types: new_items, stock, item_changes, price_changes, freight_prices,
#                  color_metaobjects, sales_orders, payment_recovery, returns, all

# Build Windows executable
python build_exe.py
```

Syncs are individually toggled via `configurations.json` — set `enabled: true/false` under `sync.*`. No sync runs if its flag is `false`, even in continuous mode.

## Architecture

### Configuration (`app/core/config.py`)
Single source of truth. Loads `configurations.json` from CWD or project root. `config_settings` is a singleton `ConfigSettings` instance used everywhere. Location-to-warehouse mapping is a nested JSON structure inside `configurations.json` under `shopify.location_warehouse_mapping`; each Shopify location ID maps to a SAP warehouse code, cost center codes, series numbers, and payment account codes.

### SAP Client (`app/services/sap/client.py`)
HTTP client for SAP B1 Service Layer. Manages `B1SESSION` cookie automatically — sessions expire after 30 minutes and are renewed transparently. All requests go through `_make_request()` which handles retry (via `tenacity`) and automatic re-login. All SAP API calls are logged to SAP's `U_API_LOG` table via `app/services/sap/api_logger.py`.

### Shopify Client (`app/services/shopify/multi_store_client.py`)
Multi-store GraphQL client using the `gql` library. OAuth client credentials grant (client_id + client_secret → access token). Tokens expire every 24 hours; `ShopifyTokenManager` refreshes them 1 hour before expiry. Each store has its own token. Uses `multi_store_shopify_client` singleton for all Shopify GraphQL queries.

### Sync Modules (`app/sync/`)
Each sync module is a class with an async `sync_*()` method that returns `{"msg": "success"|"failure", "processed": N, "successful": N, "errors": N}`. The `ShopifySAPSync` class in `app/main.py` wires them all together.

| Module | Direction | Description |
|--------|-----------|-------------|
| `new_items_multi_store.py` | SAP → Shopify | Creates products/variants using `U_ParentItem` and `U_Color` SAP fields |
| `inventory.py` | SAP → Shopify | Stock quantity updates via `sml.svc` view |
| `item_changes.py` | SAP → Shopify | Updates existing product data |
| `price_changes.py` | SAP → Shopify | Price list updates |
| `freight_sync.py` | SAP → config | Updates freight pricing in `configurations.json` |
| `sales/orders_sync.py` | Shopify → SAP | Creates SAP invoices + incoming payments from Shopify orders |
| `sales/payment_recovery.py` | SAP → Shopify | Finds SAP invoices missing Shopify payment, links them |
| `sales/returns_sync_v4.py` | Shopify → SAP | Creates SAP credit notes from Shopify refunds (v4 is the active version; v1/v2/v3 are obsolete) |
| `sales/customers.py` | Shopify → SAP | Customer create/lookup used by orders sync |
| `sales/gift_card_expiry_sync.py` | Shopify → Shopify | Deactivates expired gift cards |

### Order Location Mapping (`order_location_mapper.py`)
Root-level module (not inside `app/`). Parses POS order `source_identifier` (format: `locationId-register-receipt`) to determine which SAP warehouse, cost center series, and payment accounts to use. The `series`, `bank_transfers`, `credit`, and `cash` keys in `configurations.json` locations are consumed here.

## Key Conventions

- **Async everywhere**: all sync methods are `async`; run with `asyncio.run()`.
- **Shopify API**: GraphQL only (no REST except for OAuth token exchange and a few utility scripts).
- **SAP custom fields**: Items use `U_ParentItem`, `U_Color`, `U_LOCAL_SID`, `U_LOCAL_VARIANT_SID`, `U_INTERNATIONAL_SID`, `U_INTERNATIONAL_VARIANT_SID` to track Shopify IDs.
- **SAP endpoints**: Custom views like `sml.svc/NEW_ITEMS`, `sml.svc/PRICE_CHANGES` are used to fetch data; standard SAP endpoints (`Items`, `Invoices`, etc.) for writes.
- **`test_mode`**: When `true` in `configurations.json`, syncs run in dry-run mode without writing to SAP/Shopify.
- **Logging**: `app/utils/logging.py` exports `logger` (file + console). All API interactions also land in SAP's `U_API_LOG` table via `sap_api_logger`.
- **SSL**: Custom SSL context setup in `app/utils/ssl_cert.py`; SAP server uses a self-signed cert (`verify=False` in SAP client).
