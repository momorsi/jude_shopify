# Inventory Sync System

## Overview

The inventory sync system provides efficient synchronization of inventory quantities from SAP to Shopify using a change-based tracking approach. This system supports multi-store inventory management and provides comprehensive logging and error handling.

## Architecture

### Change-Based Sync (Recommended)

Instead of checking current vs last synced quantity for every item, the system uses SAP's change tracking to identify only items that have actually changed since the last sync.

**Benefits:**
- **Efficient**: Only processes items that have actually changed
- **Fast**: Reduces API calls and processing time
- **Reliable**: Uses SAP's built-in change tracking
- **Scalable**: Performance doesn't degrade with large item catalogs

### Multi-Store Support

The system supports multiple Shopify stores with different warehouse configurations:
- Each store can have its own warehouse code
- Inventory quantities are mapped by warehouse
- Store-specific inventory updates

## Configuration

### Store Configuration

Each store in `configurations.json` should include:

```json
{
    "local": {
        "name": "Local Store",
        "shop_url": "your-store.myshopify.com",
        "access_token": "your_access_token",
        "api_version": "2024-01",
        "location_id": "gid://shopify/Location/your_location_id",
        "warehouse_code": "ONL",
        "enabled": true
    }
}
```

**Key Fields:**
- `warehouse_code`: SAP warehouse code for this store
- `location_id`: Shopify location ID for inventory updates
- `enabled`: Whether this store should be synced

### Sync Configuration

```json
{
    "inventory": {
        "enabled": true,
        "interval_minutes": 15,
        "batch_size": 50
    }
}
```

## Usage

### Running Inventory Sync

#### 1. Change-Based Sync (Recommended)

```bash
python run_inventory_sync.py
```

This runs the efficient change-based sync that only processes items with inventory changes.

#### 2. Full Inventory Sync

```bash
python run_full_inventory_sync.py
```

This syncs all inventory quantities (used for initial setup or when change tracking is not available).

#### 3. Programmatic Usage

```python
from app.sync.inventory import inventory_sync

# Change-based sync
result = await inventory_sync.sync_inventory_changes()

# Full sync
result = await inventory_sync.sync_all_inventory()
```

## SAP Requirements

### Required Tables/Views

1. **Change Tracking Table**: `sml.svc/QTY_CHANGE`
   - Tracks inventory changes with timestamps
   - Contains ItemCode, UpdateDate, UpdateTime fields

2. **Shopify Mapping Table**: `U_SHOPIFY_MAPPING_2`
   - Maps SAP items to Shopify inventory item IDs
   - Contains U_SAP_Code, Code, U_Shopify_Store, U_Shopify_Type fields

3. **Items Table**: Standard SAP Items table
   - Contains ItemCode, QuantityOnStock, WarehouseCode fields

### SAP Custom Fields

Each SAP item should have:
- `U_SyncDT`: Date when last synced
- `U_SyncTime`: Time when last synced
- Store-specific Shopify ID fields (e.g., `U_LOCAL_SID`, `U_INTERNATIONAL_SID`)

## Shopify Requirements

### Inventory Management

- Products must have `inventoryManagement` set to "SHOPIFY"
- Inventory quantities are managed through Shopify's inventory API
- Each store has its own location for inventory tracking

### API Permissions

The Shopify access token needs:
- `read_products` - to read product information
- `write_products` - to update inventory levels
- `read_inventory` - to read current inventory
- `write_inventory` - to update inventory levels

## Process Flow

### Change-Based Sync Process

1. **Get Changes**: Query SAP change tracking table for items modified since last sync
2. **Get Mappings**: Retrieve Shopify inventory item IDs for changed items
3. **Get Current Quantities**: Fetch current inventory quantities from SAP
4. **Update Shopify**: Update inventory levels in each store
5. **Log Results**: Log all operations to SAP API log table

### Full Sync Process

1. **Get All Mappings**: Retrieve all Shopify inventory mappings
2. **Get Current Quantities**: Fetch current inventory for all mapped items
3. **Update Shopify**: Update inventory levels in each store
4. **Log Results**: Log all operations to SAP API log table

## Error Handling

### Retry Logic

- Automatic retry for transient errors
- Exponential backoff for rate limiting
- Maximum 3 retry attempts

### Error Logging

All errors are logged to:
- Application logs (`logs/sync.log`)
- SAP API log table (`U_API_LOG`)

### Error Recovery

- Failed items are logged but don't stop the sync
- Partial failures are reported in the result
- System continues processing other items

## Monitoring

### Log Files

- **Application Logs**: `logs/sync.log`
- **SAP API Logs**: `U_API_LOG` table in SAP

### Key Metrics

- Items processed
- Successful updates
- Error count
- Processing time

### Health Checks

Monitor these indicators:
- Sync frequency (should match configured interval)
- Error rate (should be low)
- Processing time (should be reasonable)

## Troubleshooting

### Common Issues

1. **No Changes Found**
   - Check if SAP change tracking is working
   - Verify last sync time is correct
   - Check SAP change tracking table

2. **Mapping Errors**
   - Verify Shopify mappings exist in SAP
   - Check mapping table structure
   - Ensure items have been synced to Shopify first

3. **API Errors**
   - Check Shopify API permissions
   - Verify access tokens are valid
   - Check rate limiting

4. **Quantity Mismatches**
   - Verify warehouse codes match
   - Check SAP inventory quantities
   - Ensure correct location IDs

### Debug Mode

Enable debug logging in `configurations.json`:

```json
{
    "logging": {
        "level": "DEBUG"
    }
}
```

## Performance Optimization

### Batch Processing

- Process items in batches to avoid overwhelming APIs
- Configurable batch size in configuration
- Automatic delays between batches

### Change Tracking

- Only process items that have actually changed
- Reduces processing time significantly
- Scales well with large catalogs

### Multi-Store Efficiency

- Parallel processing for multiple stores
- Shared SAP connections
- Optimized API calls

## Security

### Access Control

- Secure storage of API tokens
- HTTPS for all API communications
- Session management for SAP connections

### Data Protection

- No sensitive data in logs
- Secure credential storage
- Audit trail for all operations

## Future Enhancements

### Planned Features

1. **Real-time Sync**: Webhook-based real-time inventory updates
2. **Bidirectional Sync**: Sync inventory changes from Shopify back to SAP
3. **Advanced Filtering**: More sophisticated change detection
4. **Performance Monitoring**: Real-time performance metrics
5. **Automated Recovery**: Automatic error recovery and retry

### Integration Points

- Order management system
- Warehouse management system
- Analytics and reporting
- Alerting and notifications 