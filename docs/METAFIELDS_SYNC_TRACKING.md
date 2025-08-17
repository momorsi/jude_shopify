# Metafields-Based Sync Tracking

## Overview

This document explains how to use Shopify Metafields for tracking sync status instead of tags. This approach is more efficient, organized, and provides better filtering capabilities.

## Metafield Structure

### Sync Status Metafield
- **Namespace**: `jude_system`
- **Key**: `sap_sync_status`
- **Type**: `single_line_text_field`
- **Values**: 
  - `"synced"` - Product successfully synced to SAP
  - `"failed"` - Product failed to sync (excluded from future attempts)
  - `""` (empty) - Product not yet processed

### External ID Metafield
- **Namespace**: `jude_system`
- **Key**: `external_id`
- **Type**: `single_line_text_field`
- **Value**: SAP item code or external reference

## Advantages Over Tags

1. **Better Performance**: Filtering by metafields is faster than parsing tags
2. **Structured Data**: Key-value pairs are more organized than tag strings
3. **Type Safety**: Metafields have specific data types
4. **Cleaner UI**: Doesn't clutter the product tags section
5. **Efficient Filtering**: Can filter products directly by metafield values

## Usage Examples

### 1. Get Products by Sync Status

```python
from app.sync.items_init import items_init

# Get all products that haven't been processed yet
unprocessed_products = await items_init.get_products_by_sync_status("store1")

# Get all successfully synced products
synced_products = await items_init.get_products_by_sync_status("store1", "synced")

# Get all failed products
failed_products = await items_init.get_products_by_sync_status("store1", "failed")
```

### 2. Set Sync Status

```python
# Mark product as successfully synced
await items_init.set_sync_status("store1", product_id, "synced")

# Mark product as failed
await items_init.set_sync_status("store1", product_id, "failed")

# Set external ID
await items_init.set_external_id("store1", product_id, "SAP_ITEM_001")
```

### 3. Check Current Status

```python
# Get sync status from product data
sync_status = items_init._get_metafield_value(product, "jude_system", "sap_sync_status")
external_id = items_init._get_metafield_value(product, "jude_system", "external_id")

if sync_status == "synced":
    print("Product already synced")
elif sync_status == "failed":
    print("Product failed to sync")
else:
    print("Product not yet processed")
```

## GraphQL Query Examples

### Filter Products by Metafield

```graphql
# Get products with specific sync status
query GetSyncedProducts {
  products(first: 250, query: "status:active AND metafield:jude_system.sap_sync_status=\"synced\"") {
    edges {
      node {
        id
        title
        metafields(first: 10, namespace: "jude_system") {
          edges {
            node {
              key
              value
            }
          }
        }
      }
    }
  }
}

# Get products without sync status (not yet processed)
query GetUnprocessedProducts {
  products(first: 250, query: "status:active AND -metafield:jude_system.sap_sync_status") {
    edges {
      node {
        id
        title
      }
    }
  }
}
```

### Create/Update Metafields

```graphql
# Create new metafield
mutation CreateSyncStatusMetafield {
  metafieldCreate(input: {
    ownerId: "gid://shopify/Product/123456789"
    namespace: "jude_system"
    key: "sap_sync_status"
    value: "synced"
    type: "single_line_text_field"
  }) {
    metafield {
      id
      namespace
      key
      value
    }
    userErrors {
      field
      message
    }
  }
}

# Update existing metafield
mutation UpdateSyncStatusMetafield {
  metafieldUpdate(input: {
    id: "gid://shopify/Metafield/987654321"
    value: "failed"
  }) {
    metafield {
      id
      value
    }
    userErrors {
      field
      message
    }
  }
}
```

## Migration from Tags

If you're migrating from the tag-based system:

1. **Run the initialization process** - It will automatically use metafields
2. **Remove old tags** - Clean up `SYNCED_BY_JUDE_SYSTEM` and `SYNC_FAILED_JUDE_SYSTEM` tags
3. **Update existing code** - Replace tag checks with metafield checks

### Migration Script Example

```python
async def migrate_from_tags_to_metafields(store_key: str):
    """
    Migrate products from tag-based to metafield-based sync tracking
    """
    # Get all products with sync tags
    query = """
    query GetProductsWithSyncTags {
      products(first: 250, query: "status:active AND tag:SYNCED_BY_JUDE_SYSTEM OR tag:SYNC_FAILED_JUDE_SYSTEM") {
        edges {
          node {
            id
            tags
          }
        }
      }
    }
    """
    
    result = await multi_store_shopify_client.execute_query(store_key, query)
    
    for edge in result["data"]["products"]["edges"]:
        product = edge["node"]
        product_id = product["id"]
        tags = product["tags"]
        
        # Determine sync status from tags
        if "SYNCED_BY_JUDE_SYSTEM" in tags:
            await items_init.set_sync_status(store_key, product_id, "synced")
        elif "SYNC_FAILED_JUDE_SYSTEM" in tags:
            await items_init.set_sync_status(store_key, product_id, "failed")
        
        # Remove sync tags
        new_tags = [tag for tag in tags if tag not in ["SYNCED_BY_JUDE_SYSTEM", "SYNC_FAILED_JUDE_SYSTEM"]]
        
        # Update product tags
        mutation = """
        mutation UpdateProductTags($input: ProductInput!) {
          productUpdate(input: $input) {
            product {
              id
              tags
            }
          }
        }
        """
        
        variables = {
            "input": {
                "id": product_id,
                "tags": new_tags
            }
        }
        
        await multi_store_shopify_client.execute_query(store_key, mutation, variables)
```

## Best Practices

1. **Consistent Namespace**: Always use `jude_system` namespace for consistency
2. **Error Handling**: Always check for metafield creation/update errors
3. **Batch Processing**: Process metafields in batches for better performance
4. **Backup**: Keep backup of metafield data before bulk operations
5. **Monitoring**: Log all metafield operations for debugging

## Troubleshooting

### Common Issues

1. **Metafield Not Found**: Check namespace and key spelling
2. **Permission Errors**: Ensure app has metafield read/write permissions
3. **Type Mismatch**: Ensure metafield type matches the value being set
4. **Rate Limits**: Respect Shopify API rate limits for metafield operations

### Debug Queries

```graphql
# Check all metafields for a product
query GetProductMetafields($productId: ID!) {
  product(id: $productId) {
    id
    title
    metafields(first: 50) {
      edges {
        node {
          id
          namespace
          key
          value
          type
        }
      }
    }
  }
}

# Check specific metafield
query GetSpecificMetafield($productId: ID!, $namespace: String!, $key: String!) {
  product(id: $productId) {
    metafield(namespace: $namespace, key: $key) {
      id
      namespace
      key
      value
      type
    }
  }
}
```

## Performance Considerations

1. **Filtering**: Use metafield filters in queries for better performance
2. **Pagination**: Always use pagination for large product catalogs
3. **Caching**: Cache metafield values when possible
4. **Bulk Operations**: Use bulk metafield operations when available

## Integration with Existing Systems

The metafield-based system is fully compatible with:
- Existing SAP mapping tables
- Current sync processes
- Product creation workflows
- Inventory management systems

Simply replace tag-based checks with metafield-based checks in your existing code.
