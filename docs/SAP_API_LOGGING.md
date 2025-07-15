# SAP API Logging System

This document describes the SAP API logging system that has been implemented to provide similar functionality to the reference project's `log_crud.py` file.

## Overview

The SAP API logging system allows you to log API calls and sync events directly to SAP tables, similar to how it was done in the reference project. This provides a centralized way to track all API interactions and sync operations.

## Features

- **Dual Logging**: Logs to both file system and SAP tables
- **Backward Compatibility**: Provides functions with the same signature as the reference project
- **Async Support**: Fully async implementation for better performance
- **Error Handling**: Graceful fallback if SAP logging fails
- **Flexible Parameters**: Support for all the same parameters as the reference project

## Components

### 1. SAPAPILogger Class (`app/services/sap/api_logger.py`)

The main logging class that handles communication with SAP tables.

```python
from app.services.sap.api_logger import SAPAPILogger

logger = SAPAPILogger()
await logger.log_api_call(
    server="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "Test Product"},
    response_data={"product": {"id": 12345}},
    status="success",
    reference="PROD_12345",
    action="create_product",
    value="Product created successfully"
)
```

### 2. Convenience Functions

Functions that match the reference project's signature:

```python
from app.services.sap.api_logger import sl_add_log, sl_add_sync

# Log API call (equivalent to reference project's sl_add_log)
await sl_add_log(
    server="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "Test Product"},
    response_data={"product": {"id": 12345}},
    status="success",
    reference="PROD_12345",
    action="create_product",
    value="Product created successfully"
)

# Log sync event (equivalent to reference project's sl_add_sync)
await sl_add_sync(
    sync_code=1,
    sync_date="2024-01-15",
    sync_time="1430"
)
```

### 3. Integrated Logging

The existing `log_api_call` function in `app/utils/logging.py` has been enhanced to automatically log to both file and SAP table:

```python
from app.utils.logging import log_api_call

# This now logs to both file and SAP table automatically
await log_api_call(
    service="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "Test Product"},
    response_data={"product": {"id": 12345}},
    status="success"
)
```

## SAP Table Structure

The system expects the following SAP tables to exist:

### U_API_LOG Table
- `U_Server`: Server name (e.g., 'shopify', 'sap')
- `U_EndPoint`: API endpoint
- `U_Request`: JSON string of request data
- `U_Response`: JSON string of response data
- `U_Status`: Status ('success', 'failure', 'error')
- `U_Reference`: Reference information
- `U_LogDate`: Log date (YYYY-MM-DD format)
- `U_LogTime`: Log time (HHMM format)
- `U_Action`: Action being performed
- `U_Value`: Additional value information

### U_SYNC_LOG Table
- `U_SyncDate`: Sync date (YYYY-MM-DD format)
- `U_SyncTime`: Sync time (HHMM format)

## Usage Examples

### Basic API Logging

```python
from app.services.sap.api_logger import sl_add_log

# Simple API call logging
await sl_add_log(
    server="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "New Product"},
    response_data={"product": {"id": 12345}},
    status="success"
)
```

### Detailed API Logging

```python
from app.services.sap.api_logger import sl_add_log

# Detailed logging with all parameters
await sl_add_log(
    server="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "New Product", "body_html": "Product description"},
    response_data={"product": {"id": 12345, "title": "New Product"}},
    status="success",
    reference="PROD_12345",
    action="create_product",
    value="Product created successfully"
)
```

### Error Logging

```python
from app.services.sap.api_logger import sl_add_log

# Log API errors
await sl_add_log(
    server="shopify",
    endpoint="/admin/api/2024-01/products.json",
    request_data={"title": "Invalid Product"},
    response_data={"errors": "Validation failed"},
    status="failure",
    reference="PROD_12345",
    action="create_product",
    value="Validation failed"
)
```

### Sync Event Logging

```python
from app.services.sap.api_logger import sl_add_sync

# Log sync events
await sl_add_sync(
    sync_code=1,  # Sync type identifier
    sync_date="2024-01-15",
    sync_time="1430"  # 2:30 PM
)
```

## Integration with Existing Code

The SAP client has been updated to automatically use the new logging system. All API calls made through the SAP client will now be logged to both file and SAP table.

## Error Handling

The system includes robust error handling:

1. **SAP Connection Failures**: If SAP is unavailable, logging continues to file
2. **JSON Serialization Errors**: Handles non-serializable data gracefully
3. **Network Timeouts**: Includes timeout handling for SAP requests
4. **Fallback Logging**: Always logs to file even if SAP logging fails

## Configuration

The logging system uses the existing SAP configuration from `configurations2.json`:

```json
{
  "sap": {
    "server": "https://your-sap-server.com",
    "company": "your-company",
    "user": "your-user",
    "password": "your-password"
  }
}
```

## Migration from Reference Project

If you're migrating from the reference project, you can replace calls to the old `sl_add_log` and `sl_add_sync` functions with the new ones:

### Before (Reference Project)
```python
from crud.log_crud import sl_add_log, sl_add_sync

await sl_add_log(server, endpoint, req, resp, status, ref, dt, ti, action, value)
await sl_add_sync(code, dt, ti)
```

### After (New System)
```python
from app.services.sap.api_logger import sl_add_log, sl_add_sync

await sl_add_log(server, endpoint, req, resp, status, ref, action, value)
await sl_add_sync(code, dt, ti)
```

The main differences are:
- Date and time are now automatically generated
- All functions are async
- Better error handling and logging
- Integration with the existing logging system

## Testing

You can test the logging system using the example file:

```bash
python -m app.examples.api_logging_example
```

This will run various examples and demonstrate the different ways to use the logging system. 