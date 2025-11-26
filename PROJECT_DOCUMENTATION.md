# Shopify-SAP Integration System
## Professional Documentation

---

### Overview

The Shopify-SAP Integration System is a comprehensive solution that synchronizes data between multiple Shopify stores and SAP Business One. It provides automated, bidirectional data flow with support for multiple stores, intelligent customer management, and complete order processing capabilities.

### Key Features

- **Multi-Store Support**: Handles local and international stores with separate configurations
- **Master Data Synchronization**: Products, inventory, prices, and item changes
- **Sales Module**: Complete order processing, payments, returns, and customer management
- **Gift Card Management**: Handles gift card purchases and redemptions
- **Automated Scheduling**: Configurable intervals for each sync type
- **Error Handling**: Comprehensive retry logic and detailed logging
- **Location-Based Configuration**: Warehouse, costing codes, and payment accounts per location

---

## Configuration File Documentation

The system is configured entirely through the `configurations.json` file. This section provides detailed documentation for each configuration field.

### Root Level Settings

#### `test_mode`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Enables test mode for the entire system. When set to `true`, the system operates in test mode without affecting production data.

---

### SAP Configuration (`sap`)

#### `server`
- **Type**: String (URL)
- **Example**: `"https://10.0.0.100:50000/b1s/v1"`
- **Description**: The SAP Business One API server URL. Must include protocol (https/http), IP address or hostname, port number, and API path.

#### `company`
- **Type**: String
- **Example**: `"JudeBenHalim_New"`
- **Description**: The SAP company database name where operations will be performed.

#### `user`
- **Type**: String
- **Description**: SAP user account name for API authentication.

#### `password`
- **Type**: String
- **Description**: Password for the SAP user account.

#### `language`
- **Type**: String
- **Default**: `"en_US"`
- **Description**: SAP language code for API responses.

#### `timeout`
- **Type**: Integer (seconds)
- **Default**: `30`
- **Description**: API request timeout in seconds.

#### `custom_giftcard`
- **Type**: String
- **Example**: `"SR-0000083"`
- **Description**: SAP item code for gift card products.

---

### Shopify Configuration (`shopify`)

#### `stores`
- **Type**: Object
- **Description**: Configuration for each Shopify store. Each store key (e.g., "local", "international") contains store-specific settings.

##### Store Object Fields

**`name`**
- **Type**: String
- **Description**: Display name for the store.

**`shop_url`**
- **Type**: String
- **Example**: `"eg-judebenhalim.myshopify.com"`
- **Description**: Shopify store domain (without https://).

**`access_token`**
- **Type**: String
- **Description**: Shopify Admin API access token with required permissions.

**`api_version`**
- **Type**: String
- **Example**: `"2025-07"`
- **Description**: Shopify API version to use.

**`timeout`**
- **Type**: Integer (seconds)
- **Default**: `45`
- **Description**: Request timeout for Shopify API calls.

**`currency`**
- **Type**: String
- **Examples**: `"EGP"`, `"USD"`
- **Description**: Currency code for the store.

**`price_list`**
- **Type**: Integer
- **Description**: SAP price list number to use for this store.

**`enabled`**
- **Type**: Boolean
- **Description**: Enable or disable this store in sync operations.

#### `location_warehouse_mapping`
- **Type**: Object
- **Description**: Maps Shopify locations to SAP warehouses, costing codes, and payment accounts. Critical for proper order processing.

##### Location Mapping Structure

Each location can be:
- `"web"` - For online orders
- Location ID (numeric string) - For physical store locations

##### Location Configuration Fields

**`type`**
- **Type**: String
- **Values**: `"online"` or `"store"`
- **Description**: Determines if location is online or physical store.

**`warehouse`**
- **Type**: String
- **Example**: `"SW"`, `"5A"`, `"Arkan"`
- **Description**: SAP warehouse code for inventory allocation.

**`location_cc`**
- **Type**: String
- **Example**: `"ONL"`, `"SRM"`, `"WAT"`
- **Description**: SAP location costing code for cost allocation.

**`department_cc`**
- **Type**: String
- **Example**: `"SAL"`
- **Description**: SAP department costing code.

**`activity_cc`**
- **Type**: String
- **Example**: `"OnlineS"`, `"General"`
- **Description**: SAP activity costing code.

**`bin_location`**
- **Type**: Integer
- **Description**: SAP bin location number (typically for online locations).

**`group_code`**
- **Type**: Integer
- **Description**: SAP customer group code for customer creation.

**`sales_employee`**
- **Type**: Integer
- **Description**: SAP sales employee code assigned to orders from this location.

**`series`**
- **Type**: Object
- **Description**: Document series numbers for this location.
  - `invoices`: Invoice series number
  - `credit_notes`: Credit note series number
  - `incoming_payments`: Payment series number

**`bank_transfers`**
- **Type**: Object
- **Description**: Maps payment gateways to SAP account codes.
  - For online locations: Nested by store key, then gateway name
  - For store locations: Direct gateway name mapping
  - Example: `{"Paymob": "10801247", "Tuyingo": "10801245"}`

**`credit`**
- **Type**: Object
- **Description**: Maps credit card payment gateways to SAP credit account codes (store locations only).
  - Example: `{"Geidea POS": 1, "QNB POS": 2}`

**`cash`**
- **Type**: String
- **Description**: SAP cash account code for cash payments (store locations only).

#### `freight_master_data`
- **Type**: Object
- **Description**: Maps courier names to SAP expense codes.
  - Example: `{"Tuyingo": 6, "Loadbugs": 5, "DHL": 1}`

#### `freight_config`
- **Type**: Object
- **Description**: Shipping fee to expense configuration.
  - For local store: Maps shipping fee amounts to revenue/cost expenses
  - For international store: DHL configuration
  - Example: `{"100": {"revenue": {"ExpenseCode": 6, "LineTotal": 100}, "cost": {"ExpenseCode": 4, "LineTotal": 60}}}`

---

### Sync Configuration (`sync`)

Controls which synchronization processes run and their intervals.

#### `new_items`
- **Description**: Sync new products from SAP to Shopify.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of items to process per batch

#### `inventory`
- **Description**: Sync inventory levels from SAP to Shopify.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of items to process per batch
  - `locations`: Array of Shopify location IDs to sync

#### `item_changes`
- **Description**: Sync item changes from SAP to Shopify.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of items to process per batch

#### `price_changes`
- **Description**: Sync price changes from SAP to Shopify.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of items to process per batch

#### `freight_prices`
- **Description**: Daily sync of freight prices from SAP to configuration.
  - `enabled`: Enable/disable this sync
  - `run_time`: Daily run time in HH:MM format (e.g., "06:00")
  - `timezone`: Timezone for scheduling (e.g., "UTC", "Africa/Cairo")

#### `color_metaobjects`
- **Description**: Daily sync of color metaobjects from Shopify.
  - `enabled`: Enable/disable this sync
  - `run_time`: Daily run time in HH:MM format
  - `timezone`: Timezone for scheduling

#### `sales`
- **Description**: Sales module synchronization settings.

##### `orders`
- **Description**: Sync orders from Shopify to SAP (creates invoices and payments).
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of orders to process per batch
  - `from_date`: Start date for order filtering (YYYY-MM-DD format)
  - `channel`: Order channel filter (e.g., "web")

##### `payment_recovery`
- **Description**: Recover missing payments for orders.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of orders to process per batch
  - `from_date`: Start date for order filtering
  - `channel`: Order channel filter

##### `returns`
- **Description**: Sync returns/refunds from Shopify to SAP.
  - `enabled`: Enable/disable this sync
  - `interval_minutes`: How often to run (in minutes)
  - `batch_size`: Number of returns to process per batch
  - `from_date`: Start date for return filtering
  - `channel`: Order channel filter

---

### Logging Configuration (`logging`)

#### `level`
- **Type**: String
- **Values**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **Default**: `"INFO"`
- **Description**: Logging verbosity level.

#### `file`
- **Type**: String (file path)
- **Default**: `"logs/sync.log"`
- **Description**: Path to the log file.

#### `max_size_mb`
- **Type**: Integer
- **Default**: `10`
- **Description**: Maximum log file size in MB before rotation.

#### `backup_count`
- **Type**: Integer
- **Default**: `5`
- **Description**: Number of backup log files to keep.

---

### Retry Configuration (`retry`)

#### `max_attempts`
- **Type**: Integer
- **Default**: `3`
- **Description**: Maximum number of retry attempts for failed operations.

#### `delay_seconds`
- **Type**: Integer
- **Default**: `5`
- **Description**: Delay in seconds between retry attempts.

---

## Usage Instructions

### Running the System

#### Single Run Mode
Execute all enabled syncs once:
```bash
python main.py
```

Or run a specific sync:
```bash
python -m app.main --sync sales_orders
```

#### Continuous Mode
Run syncs continuously with configured intervals:
```bash
python continuous_main.py
```

### Available Sync Types

- `new_items` - Sync new products
- `stock` - Sync inventory levels
- `item_changes` - Sync item modifications
- `price_changes` - Sync price updates
- `sales_orders` - Sync orders to SAP
- `payment_recovery` - Recover missing payments
- `returns` - Sync returns/refunds
- `freight_prices` - Sync freight prices (daily)
- `color_metaobjects` - Sync color mappings (daily)
- `all` - Run all enabled syncs

---

## Important Notes

1. **Configuration File**: The `configurations.json` file must be placed in the same directory as the executable or in the current working directory.

2. **SAP Custom Fields**: Ensure all required custom fields exist in SAP (e.g., `U_Shopify_Order_ID`, `U_GiftCard`).

3. **Logs**: Check `logs/sync.log` for detailed operation logs.

4. **API Logging**: All SAP API calls are automatically logged to the `U_API_LOG` table in SAP.

5. **Order Tags**: The system adds tags to Shopify orders to track sync status (e.g., `sap_invoice_synced`, `sap_payment_synced`).

---

## Support

For issues or questions:
1. Review logs in `logs/sync.log`
2. Check SAP `U_API_LOG` table for API call details
3. Verify configuration settings in `configurations.json`
4. Ensure all required SAP custom fields are configured

---

**Document Version**: 1.0  
**Last Updated**: 2025

---

*This documentation covers the main configuration options. For specific implementation details, refer to the code comments and technical documentation in the `docs/` directory.*

