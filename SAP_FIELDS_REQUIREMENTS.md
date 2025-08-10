# SAP Fields Requirements for Multi-Store Shopify Integration

## Overview
This document outlines all the SAP custom fields required for the multi-store Shopify integration, including variant management and inventory synchronization.

## 1. Item Master Data Fields

### Core Variant Management Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_MainItem` | Text | Main item code that groups variants together. Items with the same main item become variants of one product. | ✅ |
| `U_Color` | Text | Color information for the variant. Used to create color-based variants in Shopify. | ✅ |

### Store-Specific Shopify ID Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_LOCAL_SID` | Text | Shopify product ID for local store | ✅ |
| `U_LOCAL_VARIANT_SID` | Text | Shopify variant ID for local store | ✅ |
| `U_LOCAL_INVENTORY_SID` | Text | Shopify inventory item ID for local store | ✅ |
| `U_INTERNATIONAL_SID` | Text | Shopify product ID for international store | ✅ |
| `U_INTERNATIONAL_VARIANT_SID` | Text | Shopify variant ID for international store | ✅ |
| `U_INTERNATIONAL_INVENTORY_SID` | Text | Shopify inventory item ID for international store | ✅ |

### Sync Status Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_SyncDT` | Date | Date when item was last synced to Shopify | ✅ |
| `U_SyncTime` | Text | Sync status indicator ("SYNCED", "PENDING", "ERROR") | ✅ |

### Additional Product Information Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_Text1` | Text | Vendor/Brand information | ✅ |
| `U_BRND` | Text | Brand name for tagging | ✅ |
| `U_Size` | Text | Size information for variants | Optional |
| `U_Flavor` | Text | Flavor information for variants | Optional |
| `U_Attribute` | Text | Additional attribute information | Optional |

## 2. Gift Card Master Data Fields

### Core Gift Card Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `CardCode` | Text | Unique gift card code (SKU) | ✅ |
| `CardName` | Text | Gift card name/title | ✅ |
| `CardDescription` | Text | Gift card description | ✅ |
| `Price` | Decimal | Gift card price | ✅ |
| `Active` | Text | Active status ("Y"/"N") | ✅ |

### Store-Specific Shopify ID Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_LOCAL_SID` | Text | Shopify product ID for local store | ✅ |
| `U_INTERNATIONAL_SID` | Text | Shopify product ID for international store | ✅ |

### Additional Gift Card Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_Category` | Text | Gift card category | Optional |
| `U_Occasion` | Text | Occasion type | Optional |
| `U_Theme` | Text | Theme information | Optional |
| `U_Value` | Text | Value range | Optional |

## 3. Inventory Management Fields

### Warehouse-Specific Inventory Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_Warehouse01_Qty` | Integer | Available quantity in Warehouse 01 (Local) | ✅ |
| `U_Warehouse02_Qty` | Integer | Available quantity in Warehouse 02 (International) | ✅ |
| `U_LastInventoryUpdate` | DateTime | Last inventory update timestamp | ✅ |

### Inventory Sync Status Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `U_InventorySyncStatus` | Text | Inventory sync status ("SYNCED", "PENDING", "ERROR") | ✅ |
| `U_InventorySyncDT` | DateTime | Last inventory sync timestamp | ✅ |

## 4. SAP Endpoints Required

### Items Endpoints
| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `sml.svc/NEW_ITEMS` | GET | Get new items for sync | ✅ Implemented |
| `Items` | GET/PATCH | Standard SAP items endpoint | ✅ Implemented |
| `sml.svc/INVENTORY_UPDATE` | GET | Get inventory changes | 🔄 To Implement |

### Gift Cards Endpoints
| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `sml.svc/GIFT_CARDS` | GET | Get gift cards for sync | 🔄 To Implement |
| `GiftCards` | GET/PATCH | Standard SAP gift cards endpoint | 🔄 To Implement |

## 5. Variant Logic Implementation

### How Variants Work
1. **Main Item Grouping**: Items with the same `U_MainItem` value are grouped together
2. **Color Variants**: Each item in the group becomes a variant with its `U_Color` value
3. **Product Creation**: One Shopify product is created with multiple variants
4. **ID Mapping**: Each SAP item gets its specific Shopify variant ID stored

### Example Variant Structure
```
SAP Items:
- ItemCode: "SHIRT001", U_MainItem: "SHIRT_MAIN", U_Color: "Red"
- ItemCode: "SHIRT002", U_MainItem: "SHIRT_MAIN", U_Color: "Blue"
- ItemCode: "SHIRT003", U_MainItem: "SHIRT_MAIN", U_Color: "Green"

Shopify Product:
- Title: "Main Shirt"
- Variants:
  - SKU: "SHIRT001", Color: "Red"
  - SKU: "SHIRT002", Color: "Blue"
  - SKU: "SHIRT003", Color: "Green"
```

## 6. Inventory Sync Requirements

### Inventory Update Process
1. **Change Tracking**: Use SAP's change tracking table to identify modified items
2. **Store Mapping**: Map SAP warehouses to Shopify locations
3. **Efficient Updates**: Update only changed inventory quantities
4. **Status Tracking**: Track sync status and timestamps

### Warehouse Mapping
| SAP Warehouse | Shopify Store | Location ID |
|---------------|---------------|-------------|
| ONL | Local Store | `gid://shopify/Location/68605345858` |
| 02 | International Store | `gid://shopify/Location/your_location_id` |

### Required SAP Tables/Views

#### 1. Change Tracking Table: `sml.svc/QTY_CHANGE`
This table tracks inventory changes with timestamps.

**Required Fields:**
- `ItemCode`: SAP item code
- `UpdateDate`: Date when inventory was last updated
- `UpdateTime`: Time when inventory was last updated
- `WarehouseCode`: Warehouse where change occurred
- `Quantity`: New quantity after change

#### 2. Shopify Mapping Table: `U_SHOPIFY_MAPPING_2`
This table maps SAP items to Shopify inventory item IDs.

**Required Fields:**
- `Code`: Shopify inventory item ID
- `U_SAP_Code`: SAP item code
- `U_Shopify_Store`: Store key (e.g., 'local', 'international')
- `U_Shopify_Type`: Type of mapping ('variant_inventory')
- `U_SAP_Type`: SAP entity type ('item')

### Inventory Sync Fields

#### Item Master Data Fields
| Field Name | Type | Description | Required |
|------------|------|-------------|----------|
| `QuantityOnStock` | Number | Current inventory quantity | ✅ |
| `WarehouseCode` | Text | Warehouse code for inventory | ✅ |
| `U_SyncDT` | Date | Date when inventory was last synced | ✅ |
| `U_SyncTime` | Text | Time when inventory was last synced | ✅ |

### Inventory Sync Endpoints
| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `sml.svc/QTY_CHANGE` | GET | Get inventory changes since last sync | 🔄 To Implement |
| `Items` | GET | Get current inventory quantities | ✅ Implemented |
| `U_SHOPIFY_MAPPING_2` | GET | Get Shopify inventory mappings | ✅ Implemented |

## 7. Implementation Priority

### Phase 1: Core Variant Support ✅
- [x] `U_MainItem` field for grouping
- [x] `U_Color` field for variant differentiation
- [x] Store-specific Shopify ID fields
- [x] Basic sync status fields

### Phase 2: Gift Cards 🔄
- [ ] Gift card master data fields
- [ ] Gift card sync endpoints
- [ ] Gift card sync module

### Phase 3: Inventory Management 🔄
- [ ] Warehouse-specific inventory fields
- [ ] Inventory sync endpoints
- [ ] Real-time inventory updates
- [ ] Inventory sync status tracking

## 8. SAP Setup Instructions

### Creating Custom Fields in SAP
1. **Access SAP B1**: Log into SAP Business One
2. **Go to Tools > Custom Fields**: Navigate to custom fields management
3. **Select Item Master Data**: Choose the Items table
4. **Add Required Fields**: Create each field with the specified name and type
5. **Set Field Properties**: Configure field properties (mandatory, default values, etc.)

### Field Configuration Tips
- **Text Fields**: Use appropriate length limits (255 characters for IDs)
- **Date Fields**: Use standard date format
- **Mandatory Fields**: Mark sync status fields as mandatory
- **Default Values**: Set appropriate default values for new items

## 9. Testing Checklist

### Variant Testing
- [ ] Create items with same `U_MainItem` but different `U_Color`
- [ ] Verify products are created with multiple variants
- [ ] Check that each SAP item gets correct Shopify variant ID
- [ ] Test with single items (no variants)

### Multi-Store Testing
- [ ] Test sync to local store only
- [ ] Test sync to both stores
- [ ] Verify store-specific pricing
- [ ] Check store-specific inventory allocation

### Error Handling
- [ ] Test with missing required fields
- [ ] Test with invalid data
- [ ] Verify error logging and reporting
- [ ] Test recovery from sync failures

## 10. Maintenance and Monitoring

### Regular Tasks
- **Monitor Sync Logs**: Check for sync errors and issues
- **Verify Data Integrity**: Ensure SAP and Shopify data consistency
- **Update Exchange Rates**: Keep currency conversion rates current
- **Review Performance**: Monitor sync performance and optimize

### Troubleshooting
- **Missing Fields**: Check if all required SAP fields exist
- **Sync Failures**: Review error logs and SAP endpoint availability
- **Data Mismatches**: Verify field mappings and data formats
- **Performance Issues**: Check API limits and batch sizes 