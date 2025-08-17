# Items Initialization Module

## Overview

The Items Initialization Module (`items_init.py`) is designed to handle the mapping of existing Shopify products to SAP and update necessary fields. This is a crucial step before moving the sync solution to production.

## Purpose

1. **Map existing Shopify products to SAP**: Create records in the `Shopify_Mapping` table for all active products
2. **Update SAP item fields**: Update `ForeignName`, `U_ParentCommercialName`, and `U_ShopifyColor` fields
3. **Introduce sync tracking**: Add tags to distinguish between products synced by our system vs existing ones

## Key Features

### Sync Tag System
- **Success Tag**: `SYNCED_BY_JUDE_SYSTEM`
- **Failure Tag**: `SYNC_FAILED_JUDE_SYSTEM`
- **Purpose**: Distinguish between products created by our sync system vs existing products
- **Behavior**: 
  - Products with success tag are skipped during initialization (already mapped)
  - Products with failure tag are excluded from future requests (failed to sync)
  - Products without either tag need manual mapping in SAP
  - New products created by our system automatically get the success tag
  - Products that fail to sync get the failure tag to prevent retry attempts

### Product Processing Logic

#### Single Products (No Variants)
- **ForeignName**: Product title
- **U_ParentCommercialName**: Empty (not applicable)
- **U_ShopifyColor**: Empty (not applicable)

#### Multi-Variant Products
- **ForeignName**: Main product title
- **U_ParentCommercialName**: Main product title
- **U_ShopifyColor**: Variant title/color name

## Usage

### Running the Initialization

```python
# Import the module
from app.sync.items_init import items_init

# Run initialization for all stores
await items_init.initialize_all_stores()

# Or run for a specific store
store_key = "store1"
store_config = config_settings.get_enabled_stores()[store_key]
await items_init.initialize_store(store_key, store_config)
```

### Testing

```bash
# Test the module without making SAP changes
python test_items_init.py

# Run the full initialization
python -m app.sync.items_init
```

## Configuration

### Required SAP Tables

#### Shopify_Mapping Table (`U_SHOPIFY_MAPPING_2`)
Uses the existing SAP mapping table structure with the following fields:
- `Code`: Shopify ID (product or variant)
- `Name`: Shopify ID (product or variant)  
- `U_Shopify_Type`: Type of Shopify entity ("product", "variant", "variant_inventory")
- `U_SAP_Code`: SAP item code or product name
- `U_Shopify_Store`: Store identifier
- `U_SAP_Type`: Type of SAP entity ("item")
- `U_CreateDT`: Creation date

#### Items Table Updates
The module updates the following fields on existing items:
- `ForeignName`: Product title
- `U_ParentCommercialName`: Main product name (for variants)
- `U_ShopifyColor`: Color/variant name (for variants)

### SAP API Endpoints

#### Create Mapping Record
```
POST https://10.0.0.100:50000/b1s/v1/U_SHOPIFY_MAPPING_2
```

#### Update Item Fields
```
PATCH https://10.0.0.100:50000/b1s/v1/Items('SKU Code')
{
    "ForeignName": "Product Title",
    "U_ParentCommercialName": "Main Product Name",
    "U_ShopifyColor": "Color Name"
}
```

## Process Flow

1. **Get All Active Products**: Retrieve all active products from each Shopify store
2. **Check Sync Status**: Verify if product has success or failure tags
3. **Process Products**: 
   - Skip products already synced by our system
   - Skip products that previously failed to sync
   - Create mapping records for existing products
   - Update SAP item fields
   - Mark products as successfully synced
4. **Error Handling**: 
   - Mark failed products with failure tag
   - Log errors and continue processing other products
5. **Batch Processing**: Process products in batches of 100 for performance

## Error Handling

### Common Issues

1. **Missing SKU**: Products without SKU are skipped with warning and marked as failed
2. **SAP Connection**: Automatic retry with exponential backoff
3. **API Limits**: Respects Shopify API rate limits
4. **Invalid Data**: Logs errors, marks products as failed, and continues processing
5. **Failed Products**: Products that fail to sync are tagged and excluded from future requests

### Logging

All operations are logged to:
- Application logs (`logs/sync.log`)
- SAP API logger (`sl_add_log`)
- Console output for monitoring

## Integration with Existing Sync Modules

### New Items Sync
- Automatically adds `SYNCED_BY_JUDE_SYSTEM` tag to new products
- Uses the same tag system for consistency

### Other Sync Modules
- Can check sync status using the tag system
- Maintains mapping consistency across all modules

## Production Deployment

### Pre-deployment Checklist

1. **Backup SAP Data**: Ensure backup of Items and Shopify_Mapping tables
2. **Test Mode**: Run in test mode first to verify functionality
3. **Store Configuration**: Verify all store configurations are correct
4. **API Permissions**: Ensure SAP and Shopify API permissions are sufficient

### Deployment Steps

1. **Run Initialization**: Execute `items_init.py` for all stores
2. **Verify Results**: Check logs and SAP tables for successful mappings
3. **Enable Sync Modules**: Start the 4 approved sync processes
4. **Monitor**: Watch for any errors or issues

### Rollback Plan

1. **Remove Tags**: Remove `SYNCED_BY_JUDE_SYSTEM` and `SYNC_FAILED_JUDE_SYSTEM` tags from products
2. **Clear Mappings**: Delete records from `U_SHOPIFY_MAPPING_2` table
3. **Revert Fields**: Restore original values for updated item fields

## Monitoring and Maintenance

### Regular Checks

1. **Mapping Consistency**: Verify all active products are mapped
2. **Tag Integrity**: Ensure sync tags are properly applied
3. **Field Updates**: Monitor SAP item field updates
4. **Error Rates**: Track and address any recurring errors

### Performance Optimization

1. **Batch Size**: Adjust `batch_size` based on system performance
2. **Concurrency**: Consider running stores in parallel if needed
3. **Caching**: Implement caching for frequently accessed data
4. **Rate Limiting**: Respect API rate limits to avoid throttling

## Troubleshooting

### Common Problems

1. **Authentication Errors**: Check SAP credentials and session management
2. **API Timeouts**: Increase timeout values in configuration
3. **Missing Products**: Verify Shopify store configuration and permissions
4. **Mapping Failures**: Check SAP table structure and field names

### Debug Mode

Enable debug logging by setting log level to DEBUG in configuration:
```json
{
    "logging": {
        "level": "DEBUG"
    }
}
```

## Future Enhancements

1. **Incremental Updates**: Only process new/changed products
2. **Bulk Operations**: Optimize for large product catalogs
3. **Real-time Sync**: Implement real-time product monitoring
4. **Advanced Filtering**: Add filters for specific product types or categories
