# Sales Module Documentation

## Overview

The Sales Module is a comprehensive solution for managing sales-related synchronization between Shopify and SAP. It handles two main processes:

1. **Gift Cards Sync** (SAP → Shopify): Syncs gift card products from SAP to Shopify stores
2. **Orders Sync** (Shopify → SAP): Syncs orders from Shopify to SAP with customer management and invoice creation

## Features

### Gift Cards Sync
- **Multi-store Support**: Syncs gift cards to all enabled Shopify stores
- **Price Management**: Handles store-specific pricing and currency conversion
- **Inventory Management**: Sets high inventory levels for gift cards
- **SEO Optimization**: Automatically generates SEO titles and descriptions
- **Tag Management**: Creates tags based on SAP custom fields

### Orders Sync
- **Customer Management**: Automatically creates customers in SAP if they don't exist
- **Phone Number Matching**: Uses phone numbers to identify existing customers
- **Invoice Creation**: Creates SAP invoices from Shopify orders
- **Gift Card Redemption**: Handles gift card discount applications
- **Freight Calculation**: Calculates shipping costs
- **Meta Field Updates**: Updates Shopify orders with sync status and SAP invoice numbers

## Configuration

### Enable Sales Module

Update your `configurations.json` to enable the sales module:

```json
{
    "sync": {
        "sales": {
            "gift_cards": {
                "enabled": true,
                "interval_minutes": 30,
                "batch_size": 50
            },
            "orders": {
                "enabled": true,
                "interval_minutes": 5,
                "batch_size": 20
            }
        }
    }
}
```

### Configuration Options

#### Gift Cards Sync
- `enabled`: Enable/disable gift cards sync
- `interval_minutes`: How often to run the sync (default: 30 minutes)
- `batch_size`: Number of gift cards to process per batch (default: 50)

#### Orders Sync
- `enabled`: Enable/disable orders sync
- `interval_minutes`: How often to run the sync (default: 5 minutes)
- `batch_size`: Number of orders to process per batch (default: 20)

## Usage

### Command Line Interface

#### Run Specific Sales Syncs

```bash
# Run gift cards sync only
python -m app.main --sync sales_gift_cards

# Run orders sync only
python -m app.main --sync sales_orders

# Run all syncs (including sales)
python -m app.main --sync all
```

#### Continuous Mode

```bash
# Run all enabled syncs continuously
python -m app.main --continuous
```

### Programmatic Usage

```python
from app.sync.sales import GiftCardsSalesSync, OrdersSalesSync

# Initialize sync classes
gift_cards_sync = GiftCardsSalesSync()
orders_sync = OrdersSalesSync()

# Run syncs
gift_cards_result = await gift_cards_sync.sync_gift_cards()
orders_result = await orders_sync.sync_orders()
```

## SAP Requirements

### Gift Cards Sync

SAP Items table should have the following custom fields:
- `U_IsGiftCard`: Set to 'Y' for gift card items
- `U_GiftCardDescription`: Description for the gift card
- `U_Category`: Gift card category
- `U_Occasion`: Occasion type
- `U_Theme`: Theme type
- `U_Value`: Value type
- `U_Design`: Design type

### Orders Sync

SAP should have:
- Business Partners table for customer management
- Invoices table for order processing
- Custom fields for Shopify mapping:
  - `U_ShopifyCustomerID`: Links to Shopify customer
  - `U_ShopifyEmail`: Customer email
  - `U_ShopifyOrderID`: Links to Shopify order
  - `U_ShopifyOrderNumber`: Order number
  - `U_ShopifyCreatedAt`: Order creation date
  - `U_ShopifyCurrency`: Order currency
  - `U_ShopifyTotal`: Order total
  - `U_ShopifySubtotal`: Order subtotal
  - `U_ShopifyTax`: Tax amount
  - `U_ShopifyShipping`: Shipping amount
  - `U_FreightAmount`: Freight amount

## Shopify Requirements

### Gift Cards Sync

Shopify stores should have:
- Proper location IDs configured
- Price lists configured for multi-store pricing
- API access with product creation permissions

### Orders Sync

Shopify stores should have:
- Orders with customer information
- Phone numbers in customer data
- Proper shipping and billing addresses
- Gift card discount applications (if applicable)

## Customer Management

The Sales Module includes intelligent customer management:

### Customer Lookup
- Searches SAP by phone number (cleaned and normalized)
- Checks multiple phone fields (Phone1, Phone2, Cellular)
- Handles international phone number formats

### Customer Creation
- Automatically creates new customers in SAP
- Generates unique CardCode based on name
- Maps Shopify customer data to SAP format
- Includes address information

### Customer Mapping
- Updates SAP customers with Shopify IDs
- Maintains bidirectional relationship
- Tracks sync status and timestamps

## Gift Card Redemption Handling

The Orders Sync handles gift card redemptions by:

1. **Identifying Redemptions**: Detects discount applications that are gift card redemptions
2. **Creating Redemption Lines**: Adds special line items for gift card redemptions
3. **Negative Pricing**: Applies negative amounts to reflect the discount
4. **Tracking**: Marks redemption lines for reporting and reconciliation

## Freight Calculation

Freight calculation is handled automatically:

1. **Shipping Address Analysis**: Uses shipping address to determine freight costs
2. **Shipping Price Extraction**: Gets shipping cost from Shopify order
3. **Custom Logic**: Allows for custom freight calculation rules
4. **SAP Integration**: Passes freight amount to SAP invoice

## Meta Field Updates

After successful order processing, Shopify orders are updated with:

1. **Sync Status**: Adds "synced" tag to processed orders
2. **SAP Invoice Number**: Adds SAP invoice number as a tag
3. **Error Handling**: Continues processing even if meta update fails

## Error Handling

The Sales Module includes comprehensive error handling:

### Gift Cards Sync
- Continues processing if individual gift cards fail
- Logs detailed error information
- Maintains sync statistics
- Handles API rate limits

### Orders Sync
- Continues processing if individual orders fail
- Handles customer creation failures gracefully
- Manages SAP invoice creation errors
- Provides detailed error reporting

## Logging

All operations are logged with:
- Sync start/completion events
- Processing statistics
- Error details
- Performance metrics

Logs are stored in the configured log file with appropriate log levels.

## Monitoring

Monitor the Sales Module through:

1. **Log Files**: Check sync logs for errors and statistics
2. **Shopify Tags**: Look for "synced" tags on orders
3. **SAP Records**: Verify customer and invoice creation
4. **API Logs**: Monitor API call success/failure rates

## Troubleshooting

### Common Issues

1. **Customer Not Found**: Check phone number format and SAP customer data
2. **Gift Card Sync Fails**: Verify SAP custom fields are properly configured
3. **Order Processing Errors**: Check Shopify order data completeness
4. **API Rate Limits**: Adjust batch sizes and intervals

### Debug Mode

Enable debug logging in `configurations.json`:

```json
{
    "logging": {
        "level": "DEBUG"
    }
}
```

## Performance Considerations

1. **Batch Sizes**: Adjust based on API rate limits and system performance
2. **Sync Intervals**: Balance between real-time updates and system load
3. **Multi-store Processing**: Consider store-specific performance characteristics
4. **Database Optimization**: Ensure SAP and Shopify APIs are optimized

## Future Enhancements

Potential improvements for the Sales Module:

1. **Webhook Support**: Real-time order processing via webhooks
2. **Advanced Freight Rules**: Configurable freight calculation logic
3. **Gift Card Balance Tracking**: Real-time gift card balance updates
4. **Customer Segmentation**: Advanced customer categorization
5. **Reporting Dashboard**: Web-based monitoring interface
6. **Retry Mechanisms**: Enhanced error recovery and retry logic 