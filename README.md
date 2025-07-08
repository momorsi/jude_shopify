# SAP-Shopify Integration

A comprehensive integration solution for synchronizing master data between SAP Business One and multiple Shopify stores.

## Features

### Multi-Store Support
- **Local Store**: SAR currency, Warehouse 01, Price List 1
- **International Store**: USD currency, Warehouse 02, Price List 2
- Store-specific pricing and inventory management
- Automatic currency conversion (SAR to USD)

### Master Data Synchronization

#### Items with Variants
- **Parent Items**: Items with `U_ParentItem` field are grouped as product variants
- **Color Variants**: Items with `U_Color` field create color-based variants
- **Unique SKUs**: Each variant maintains its unique SAP ItemCode as SKU
- **Shopify IDs**: Updates SAP with store-specific Shopify product and variant IDs

#### Gift Cards
- **Create/Update**: Automatically creates new gift cards or updates existing ones
- **Multi-Store**: Syncs to all enabled Shopify stores
- **Store-Specific Pricing**: Different prices for local and international stores
- **High Inventory**: Gift cards have high inventory (999) for continuous availability

### Technical Features
- **GraphQL API**: Uses Shopify's GraphQL API for efficient data operations
- **Session Management**: Automatic SAP session handling with retry logic
- **Error Handling**: Comprehensive error handling and logging
- **Batch Processing**: Configurable batch sizes for large data sets
- **Unicode Support**: Full support for Arabic and international characters

## Configuration

### SAP Settings
```json
{
  "sap": {
    "server": "https://your-sap-server:50000/b1s/v1",
    "company": "YOUR_COMPANY",
    "user": "YOUR_USER",
    "password": "YOUR_PASSWORD",
    "language": "en_US",
    "timeout": 30
  }
}
```

### Shopify Multi-Store Settings
```json
{
  "shopify": {
    "stores": {
      "local": {
        "name": "Local Store",
        "shop_url": "your-local-store.myshopify.com",
        "access_token": "your_local_access_token",
        "api_version": "2024-01",
        "location_id": "gid://shopify/Location/your_location_id",
        "currency": "SAR",
        "price_list": 1,
        "warehouse_code": "01",
        "enabled": true
      },
      "international": {
        "name": "International Store",
        "shop_url": "your-international-store.myshopify.com",
        "access_token": "your_international_access_token",
        "api_version": "2024-01",
        "location_id": "gid://shopify/Location/your_location_id",
        "currency": "USD",
        "price_list": 2,
        "warehouse_code": "02",
        "enabled": true
      }
    }
  }
}
```

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd jude_shopify
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure settings**
   - Update `configurations.json` with your SAP and Shopify credentials
   - Ensure SAP custom fields exist for Shopify IDs

4. **Test connections**
   ```bash
   python test_multi_store_setup.py
   ```

## Usage

### Sync New Items (with Variants)
```bash
python run_sync.py new-items-multi
```

**What it does:**
- Groups items by `U_ParentItem` field to create product variants
- Uses `U_Color` field for color-based variants
- Creates products with variants in all enabled stores
- Updates SAP with Shopify product and variant IDs

### Sync Gift Cards
```bash
python run_sync.py gift-cards
```

**What it does:**
- Creates new gift cards or updates existing ones
- Syncs to all enabled Shopify stores
- Applies store-specific pricing
- Updates SAP with Shopify IDs

### Run All Sync Operations
```bash
python run_sync.py all
```

## SAP Custom Fields Required

### For Items
- `U_ParentItem`: Parent item code for grouping variants
- `U_Color`: Color information for variants
- `U_LOCAL_SID`: Shopify product ID for local store
- `U_LOCAL_VARIANT_SID`: Shopify variant ID for local store
- `U_INTERNATIONAL_SID`: Shopify product ID for international store
- `U_INTERNATIONAL_VARIANT_SID`: Shopify variant ID for international store

### For Gift Cards
- `U_LOCAL_SID`: Shopify product ID for local store
- `U_INTERNATIONAL_SID`: Shopify product ID for international store

## SAP Endpoints

### Items
- `sml.svc/NEW_ITEMS`: Get new items for sync
- `Items`: Standard SAP items endpoint

### Gift Cards
- `sml.svc/GIFT_CARDS`: Get gift cards for sync (to be implemented)

## Logging

All operations are logged to `logs/sync.log` with:
- API calls and responses
- Sync events and statistics
- Error details and stack traces

## Error Handling

- **SAP Connection**: Automatic session renewal and retry logic
- **Shopify API**: Rate limiting and error recovery
- **Data Validation**: Comprehensive validation before sync
- **Partial Failures**: Continues processing even if some items fail

## Development

### Project Structure
```
jude_shopify/
├── app/
│   ├── core/
│   │   └── config.py          # Configuration management
│   ├── services/
│   │   ├── sap/
│   │   │   └── client.py      # SAP API client
│   │   └── shopify/
│   │       └── multi_store_client.py  # Multi-store Shopify client
│   ├── sync/
│   │   ├── new_items_multi_store.py   # Items sync with variants
│   │   └── gift_cards.py      # Gift cards sync
│   └── utils/
│       └── logging.py         # Logging utilities
├── configurations.json        # Configuration file
├── run_sync.py               # CLI interface
└── test_multi_store_setup.py # Setup testing
```

### Adding New Stores
1. Add store configuration to `configurations.json`
2. Set `enabled: true` for the new store
3. Configure store-specific settings (currency, price list, warehouse)
4. The sync will automatically include the new store

### Extending Functionality
- **New Master Data**: Create new sync modules following the existing pattern
- **Additional Variants**: Extend the variant logic in `new_items_multi_store.py`
- **Custom Pricing**: Modify `_get_store_price()` methods for custom pricing logic

## Troubleshooting

### Common Issues
1. **SAP Connection Failed**: Check credentials and server URL
2. **Shopify API Errors**: Verify access tokens and API version
3. **Missing Custom Fields**: Ensure SAP custom fields exist
4. **Unicode Errors**: Check logging configuration for UTF-8 support

### Debug Mode
Enable debug logging in `configurations.json`:
```json
{
  "logging": {
    "level": "DEBUG"
  }
}
```

## Support

For issues and questions:
1. Check the logs in `logs/sync.log`
2. Verify configuration settings
3. Test individual components using the test script
4. Review error messages for specific guidance 