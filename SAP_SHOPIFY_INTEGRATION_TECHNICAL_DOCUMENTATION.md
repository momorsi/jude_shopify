# SAP-Shopify Integration Technical Documentation

## Overview

This document provides technical details about the SAP-Shopify integration, including SAP views, document types, API endpoints, and data flows for each synchronization process.

---

## Table of Contents

1. [SAP Views and Tables](#sap-views-and-tables)
2. [Process 1: New Products Sync (SAP → Shopify)](#process-1-new-products-sync)
3. [Process 2: Sales Orders Sync (Shopify → SAP)](#process-2-sales-orders-sync)
4. [Process 3: Payment Recovery Sync (SAP → Shopify → SAP)](#process-3-payment-recovery-sync)
5. [Process 4: Returns Sync (Shopify → SAP)](#process-4-returns-sync)
6. [Process 5: Inventory Sync (SAP → Shopify)](#process-5-inventory-sync)
7. [Gift Card Processing](#gift-card-processing)
8. [SAP Document Types Reference](#sap-document-types-reference)

---

## SAP Views and Tables

### Custom Views

#### 1. `view.svc/MASHURA_New_ItemsB1SLQuery`
**Purpose**: Retrieves new items from SAP that need to be synchronized to Shopify.

**Endpoint**: `GET view.svc/MASHURA_New_ItemsB1SLQuery`

**Query Parameters**:
- `$filter`: Filter by `Shopify_Store` (e.g., `Shopify_Store eq 'local'`)

**Key Fields**:
- `itemcode`: SAP item code
- `ItemName`: Product name
- `MainProduct`: Parent product identifier (groups variants)
- `Color`: Variant identifier
- `Shopify_Store`: Target Shopify store
- `Status`: Item status (new/existing)
- `Shopify_ProductCode`: Existing Shopify product ID (if Status='existing')

**Usage**: Called during new products sync to fetch items pending synchronization.

---

#### 2. `sml.svc/QTY_CHANGE`
**Purpose**: Tracks inventory quantity changes with timestamps.

**Endpoint**: `GET sml.svc/QTY_CHANGE`

**Query Parameters**:
- `$filter`: Filter by date/time ranges
- `$orderby`: Sort order

**Key Fields**:
- `ItemCode`: SAP item code
- `UpdateDate`: Date when inventory changed
- `UpdateTime`: Time when inventory changed
- `WarehouseCode`: Warehouse where change occurred
- `Quantity`: New quantity after change

**Usage**: Used during inventory sync to identify items with stock changes.

---

### Custom Tables

#### 1. `U_SHOPIFY_MAPPING_2`
**Purpose**: Maps SAP items to Shopify product/variant/inventory IDs.

**Endpoint**: `GET/POST U_SHOPIFY_MAPPING_2`

**Key Fields**:
- `Code`: Shopify ID (product/variant/inventory item ID)
- `Name`: Shopify ID (duplicate of Code)
- `U_SAP_Code`: SAP item code
- `U_Shopify_Store`: Store identifier ('local', 'international')
- `U_Shopify_Type`: Type of mapping ('product', 'variant', 'variant_inventory')
- `U_SAP_Type`: SAP entity type ('item')
- `U_CreateDT`: Creation date

**Usage**: 
- Created when products are synced to Shopify
- Used to retrieve Shopify IDs for inventory updates
- Maintains bidirectional mapping between systems

---

## Process 1: New Products Sync

### Data Flow
**Direction**: SAP → Shopify

### SAP Operations

#### 1. Retrieve New Items
**Endpoint**: `GET view.svc/MASHURA_New_ItemsB1SLQuery`
**Filter**: `$filter=Shopify_Store eq '{store_key}'`

**Response Structure**:
```json
{
  "value": [
    {
      "itemcode": "ITEM001",
      "ItemName": "Product Name",
      "MainProduct": "MAIN001",
      "Color": "Red",
      "Shopify_Store": "local",
      "Status": "new",
      "FrgnName": "Description",
      "U_Text1": "Vendor",
      "U_BRND": "Brand"
    }
  ]
}
```

#### 2. Update Item Fields (After Sync)
**Endpoint**: `PATCH Items('{itemcode}')`

**Fields Updated**:
- `U_LOCAL_SID` / `U_INTERNATIONAL_SID`: Shopify product ID
- `U_LOCAL_VARIANT_SID` / `U_INTERNATIONAL_VARIANT_SID`: Shopify variant ID
- `U_LOCAL_INVENTORY_SID` / `U_INTERNATIONAL_INVENTORY_SID`: Shopify inventory item ID
- `U_SyncDT`: Sync date
- `U_SyncTime`: Sync status

#### 3. Create Mapping Records
**Endpoint**: `POST U_SHOPIFY_MAPPING_2`

**Data Structure**:
```json
{
  "Code": "{shopify_variant_id}",
  "Name": "{shopify_variant_id}",
  "U_SAP_Code": "{itemcode}",
  "U_Shopify_Store": "{store_key}",
  "U_Shopify_Type": "variant",
  "U_SAP_Type": "item",
  "U_CreateDT": "2024-01-01"
}
```

### Shopify Operations

#### 1. Create Product
**GraphQL Mutation**: `productCreate`

**Product Structure**:
- Single product: One product with one variant
- Variant product: One product with multiple variants (grouped by `MainProduct`)

#### 2. Create Variants
Variants are created as part of the product creation when `MainProduct` field groups multiple items.

### Variant Grouping Logic

Items are grouped into products using:
- **Primary Key**: `(MainProduct, Shopify_Store)`
- **Variant Identifier**: `Color` field

**Example**:
- Item 1: `itemcode=SHIRT001`, `MainProduct=SHIRT_MAIN`, `Color=Red`
- Item 2: `itemcode=SHIRT002`, `MainProduct=SHIRT_MAIN`, `Color=Blue`

Result: One Shopify product "SHIRT_MAIN" with two variants (Red, Blue)

---

## Process 2: Sales Orders Sync

### Data Flow
**Direction**: Shopify → SAP

### Documents Created in SAP

#### 1. Invoice Document
**Document Type**: `Invoices`
**Endpoint**: `POST Invoices`

**Document Structure**:
```json
{
  "DocDate": "2024-01-01",
  "CardCode": "{customer_code}",
  "NumAtCard": "{order_number}",
  "Series": "{series_code}",
  "Comments": "Shopify Order: {order_name} | Payment: {status} | Fulfillment: {status}",
  "SalesPersonCode": {sales_person_id},
  "DocumentLines": [
    {
      "ItemCode": "{sku}",
      "Quantity": {quantity},
      "Price": {unit_price},
      "WarehouseCode": "{warehouse}",
      "COGSCostingCode": "{location_cc}",
      "COGSCostingCode2": "{department_cc}",
      "COGSCostingCode3": "{activity_cc}",
      "U_GiftCard": "{gift_card_id}"  // If gift card purchase
    }
  ],
  "DocumentAdditionalExpenses": [
    {
      "ExpenseCode": {expense_code},
      "LineTotal": {amount},
      "DistributionRule": "{location_cc}",
      "DistributionRule2": "{department_cc}",
      "DistributionRule3": "{activity_cc}",
      "U_GiftCard": "{gift_card_id}"  // If gift card redemption
    }
  ],
  "U_Pay_type": {1|2|3},  // 1=Paid, 2=Local Pending, 3=International Pending
  "U_Shopify_Order_ID": "{shopify_order_id}",
  "U_OrderType": "{order_type}",  // "1"=Online
  "U_DeliveryAddress": "{shipping_address}",
  "U_BillingAddress": "{billing_address}",
  "U_POS_Receipt_Number": "{receipt_number}",  // For POS orders
  "ImportFileNum": "{order_number}",
  "DocCurrency": "{currency}"
}
```

**User-Defined Fields (UDFs)**:
- `U_Shopify_Order_ID`: Shopify order ID
- `U_Pay_type`: Payment type indicator
- `U_OrderType`: Order type
- `U_DeliveryAddress`: Shipping address
- `U_BillingAddress`: Billing address
- `U_POS_Receipt_Number`: POS receipt number

#### 2. Business Partner (Customer)
**Document Type**: `BusinessPartners`
**Endpoint**: `POST BusinessPartners` (if customer doesn't exist)

**Customer Matching**: Uses phone number lookup across `Phone1`, `Phone2`, `Cellular` fields.

**UDFs**:
- `U_ShopifyCustomerID`: Shopify customer ID
- `U_ShopifyEmail`: Customer email

#### 3. Gift Cards (for Gift Card Purchases)
**Document Type**: `GiftCards`
**Endpoint**: `POST GiftCards`

**Note**: Gift card entries are created in SAP's `GiftCards` entity when gift cards are purchased. The gift card ID is stored in invoice line items using the `U_GiftCard` field.

---

## Process 3: Payment Recovery Sync

### Data Flow
**Direction**: SAP → Shopify → SAP

### SAP Operations

#### 1. Query Invoices
**Endpoint**: `GET Invoices`
**Filter**: `$filter=U_Shopify_Order_ID eq '{order_id}'`

#### 2. Query Payments
**Endpoint**: `GET IncomingPayments`
**Filter**: Filter by invoice reference

#### 3. Create/Update Payment
**Endpoint**: `POST IncomingPayments`

**Payment Structure**:
```json
{
  "CardCode": "{customer_code}",
  "DocDate": "{payment_date}",
  "PaymentInvoices": [
    {
      "DocEntry": {invoice_doc_entry},
      "InvoiceType": "it_Invoice",
      "SumApplied": {amount}
    }
  ],
  "TransferAccount": "{account_code}",
  "CashAccount": "{cash_account}",
  "CashSum": {cash_amount},
  "TransferSum": {transfer_amount}
}
```

### Shopify Operations

#### 1. Update Order Tags
**GraphQL Mutation**: `tagsUpdate`

Tags added:
- `sap_payment_{payment_doc_entry}`
- `sap_payment_synced`

---

## Process 4: Returns Sync

### Data Flow
**Direction**: Shopify → SAP

### Documents Created in SAP

#### 1. Credit Note
**Document Type**: `CreditNotes`
**Endpoint**: `POST CreditNotes`

**Document Structure**:
```json
{
  "CardCode": "{customer_code}",
  "DocDate": "{return_date}",
  "Comments": "Return for Shopify Order {order_name}",
  "Series": "{series_code}",
  "SalesPersonCode": {sales_person_id},
  "U_ShopifyOrderID": "{shopify_order_id}",
  "DocumentLines": [
    {
      "ItemCode": "{sku}",
      "Quantity": -{returned_quantity},
      "Price": {unit_price},
      "WarehouseCode": "{warehouse}",
      "COGSCostingCode": "{location_cc}",
      "COGSCostingCode2": "{department_cc}",
      "COGSCostingCode3": "{activity_cc}"
    }
  ]
}
```

**UDFs**:
- `U_ShopifyOrderID`: Links credit note to Shopify return/order

#### 2. Scenario 1: Store Credit (Gift Card)

When a return results in store credit (no money refunded), the system creates:

**a. Gift Card Invoice**
**Document Type**: `Invoices`
**Endpoint**: `POST Invoices`

**Structure**:
```json
{
  "DocDate": "{credit_note_date}",
  "CardCode": "{customer_code}",
  "Series": "{series_code}",
  "Comments": "Gift Card Invoice for Return - Order {order_name}",
  "SalesPersonCode": {sales_person_id},
  "DocumentLines": [
    {
      "ItemCode": "{gift_card_sku}",
      "Quantity": 1,
      "Price": {credit_note_total},
      "U_GiftCard": "{gift_card_id}"
    }
  ],
  "U_Pay_type": 1,  // PAID
  "U_Shopify_Order_ID": "{shopify_order_id}",
  "U_OrderType": "1",
  "ImportFileNum": "{order_number}",
  "DocCurrency": "{currency}"
}
```

**b. Reconciliation**
**Endpoint**: `POST Invoices({invoice_doc_entry})/Close` (if needed)
**Endpoint**: `POST CreditNotes({credit_note_doc_entry})/Close` (if needed)

The credit note and gift card invoice are reconciled to balance the accounts.

#### 3. Scenario 2: Refund (Outgoing Payment)

When a return results in a money refund, the system creates:

**Outgoing Payment**
**Document Type**: `VendorPayments` (Outgoing Payments)
**Endpoint**: `POST VendorPayments`

**Structure**:
```json
{
  "CardCode": "{customer_code}",
  "DocDate": "{payment_date}",
  "PaymentInvoices": [
    {
      "DocEntry": {credit_note_doc_entry},
      "InvoiceType": "it_CredItnote",
      "SumApplied": {credit_note_total}
    }
  ],
  "TransferAccount": "{original_payment_account}",
  "CashAccount": "{original_payment_cash_account}",
  "TransferSum": {refund_amount},
  "CashSum": {cash_refund_amount},
  "Series": "{original_payment_series}"
}
```

### Return Processing Logic

**Scenario Determination**:
- **Scenario 1 (Store Credit)**: Return disposition indicates store credit or gift card
- **Scenario 2 (Refund)**: Return disposition indicates refund to original payment method

**Original Invoice Lookup**:
- Uses `U_Shopify_Order_ID` field to find original invoice
- Retrieves invoice line items to match returned items
- Copies warehouse and costing codes from original invoice

**Credit Note Line Items**:
- Quantities are negative (representing returns)
- Warehouse and costing codes copied from original invoice lines
- Bin locations preserved if configured

---

## Process 5: Inventory Sync

### Data Flow
**Direction**: SAP → Shopify

### SAP Operations

#### 1. Get Inventory Changes
**Endpoint**: `GET sml.svc/QTY_CHANGE`
**Filter**: `$filter=UpdateDate gt datetime'{last_sync_date}'`

#### 2. Get Current Quantities
**Endpoint**: `GET Items('{itemcode}')`
**Select**: `QuantityOnStock`, `WarehouseCode`

#### 3. Get Shopify Mappings
**Endpoint**: `GET U_SHOPIFY_MAPPING_2`
**Filter**: `$filter=U_SAP_Code eq '{itemcode}' and U_Shopify_Store eq '{store_key}' and U_Shopify_Type eq 'variant_inventory'`

### Shopify Operations

#### 1. Update Inventory Levels
**GraphQL Mutation**: `inventorySetOnHandQuantities`

**Structure**:
```json
{
  "inventoryItemId": "{inventory_item_id}",
  "locationId": "{location_id}",
  "quantities": [
    {
      "quantity": {quantity},
      "availableQuantity": {quantity}
    }
  ]
}
```

---

## Gift Card Processing

### Gift Card Purchase Flow

#### 1. Detection
Gift card purchases are detected in Shopify orders by:
- SKU pattern matching
- Product type identification

#### 2. Query Shopify Gift Cards API
**GraphQL Query**: `getGiftCards`
**Filter**: `created_at:>={order_date}T00:00:00Z status:enabled`

**Response Structure**:
```json
{
  "giftCards": {
    "edges": [
      {
        "node": {
          "id": "gid://shopify/GiftCard/{id}",
          "order": {
            "id": "gid://shopify/Order/{order_id}"
          },
          "initialValue": {
            "amount": "{amount}",
            "currencyCode": "{currency}"
          },
          "createdAt": "{timestamp}",
          "expiresOn": "{expiry_date}",
          "customer": {
            "id": "{customer_id}",
            "email": "{email}"
          }
        }
      }
    ]
  }
}
```

#### 3. Create Gift Card Entry in SAP
**Endpoint**: `POST GiftCards`

**Structure**:
```json
{
  "CardCode": "{gift_card_id}",
  "CardName": "{gift_card_name}",
  "CardDescription": "{description}",
  "Price": {amount},
  "Active": "Y",
  "U_LOCAL_SID": "{shopify_product_id}",  // If applicable
  "U_INTERNATIONAL_SID": "{shopify_product_id}"  // If applicable
}
```

**Note**: In the current implementation, gift card entries are NOT created in the SAP `GiftCards` entity. Instead, gift card IDs are stored in invoice line items using the `U_GiftCard` field.

#### 4. Add to Invoice Line Item
Gift card purchases are added as regular invoice line items with:
- `ItemCode`: Gift card SKU
- `Quantity`: Number of gift cards
- `Price`: Gift card amount
- `U_GiftCard`: Shopify gift card ID (numeric portion)

### Gift Card Redemption Flow

#### 1. Detection
Gift card redemptions are detected in Shopify orders by:
- Transaction type: `gateway = "gift_card"`
- Discount applications

#### 2. Create Expense Entry
Gift card redemptions are added as expense entries in the invoice:

**Expense Structure**:
```json
{
  "ExpenseCode": 2,  // Gift card expense code (or 3 for redemptions)
  "LineTotal": -{redemption_amount},  // Negative amount
  "Remarks": "Gift Card: {last_characters}",
  "U_GiftCard": "{gift_card_id}",
  "DistributionRule": "{location_cc}",
  "DistributionRule2": "{department_cc}",
  "DistributionRule3": "{activity_cc}"
}
```

**Key Points**:
- Amount is **negative** (reduces invoice total)
- `U_GiftCard` field contains the gift card ID
- Expense code varies by configuration (typically 2 or 3)

### Gift Card Return Processing

#### Scenario 1: Return to Gift Card (Store Credit)

When a return is processed and the customer receives store credit:

1. **Create Credit Note** for returned items
2. **Create Gift Card** in Shopify (if not already exists)
3. **Create Gift Card Invoice** in SAP:
   - Single line item with gift card SKU
   - Amount equals credit note total
   - `U_GiftCard` field contains gift card ID
4. **Reconcile** credit note with gift card invoice

**Gift Card Invoice Structure**:
```json
{
  "DocDate": "{credit_note_date}",
  "CardCode": "{customer_code}",
  "DocumentLines": [
    {
      "ItemCode": "{gift_card_sku}",
      "Quantity": 1,
      "Price": {credit_note_total},
      "U_GiftCard": "{gift_card_id}"
    }
  ],
  "U_Pay_type": 1,  // PAID
  "U_Shopify_Order_ID": "{order_id}"
}
```

#### Scenario 2: Return with Refund

When a return results in a money refund:
1. **Create Credit Note** for returned items
2. **Create Outgoing Payment** (VendorPayment) to refund customer
3. **No gift card** is created

---

## SAP Document Types Reference

### Invoices (`Invoices`)
**Purpose**: Sales invoices for Shopify orders

**Key Fields**:
- `DocEntry`: Internal document entry number
- `DocNum`: Document number
- `DocDate`: Document date
- `CardCode`: Customer code
- `DocTotal`: Total amount
- `DocumentLines`: Line items array
- `DocumentAdditionalExpenses`: Expense entries array

**UDFs**:
- `U_Shopify_Order_ID`: Shopify order ID
- `U_Pay_type`: Payment type (1=Paid, 2=Local Pending, 3=International Pending)
- `U_OrderType`: Order type
- `U_DeliveryAddress`: Shipping address
- `U_BillingAddress`: Billing address
- `U_POS_Receipt_Number`: POS receipt number

**Line Item UDFs**:
- `U_GiftCard`: Gift card ID (for gift card purchases)

**Expense UDFs**:
- `U_GiftCard`: Gift card ID (for gift card redemptions)

---

### Credit Notes (`CreditNotes`)
**Purpose**: Returns and refunds

**Key Fields**:
- `DocEntry`: Internal document entry number
- `DocNum`: Document number
- `DocDate`: Document date
- `CardCode`: Customer code
- `DocTotal`: Total credit amount (negative)
- `DocumentLines`: Returned items array

**UDFs**:
- `U_ShopifyOrderID`: Shopify order/return ID

**Operations**:
- `POST CreditNotes`: Create credit note
- `GET CreditNotes({doc_entry})`: Retrieve credit note
- `POST CreditNotes({doc_entry})/Close`: Close credit note

---

### Incoming Payments (`IncomingPayments`)
**Purpose**: Customer payments received

**Key Fields**:
- `DocEntry`: Internal document entry number
- `CardCode`: Customer code
- `DocDate`: Payment date
- `PaymentInvoices`: Array of invoices being paid
- `TransferAccount`: Bank account for transfers
- `CashAccount`: Cash account
- `TransferSum`: Transfer amount
- `CashSum`: Cash amount

**PaymentInvoices Structure**:
```json
{
  "DocEntry": {invoice_doc_entry},
  "InvoiceType": "it_Invoice",
  "SumApplied": {amount}
}
```

**Operations**:
- `POST IncomingPayments`: Create payment
- `GET IncomingPayments({doc_entry})`: Retrieve payment

---

### Outgoing Payments (`VendorPayments`)
**Purpose**: Refunds to customers

**Key Fields**:
- `DocEntry`: Internal document entry number
- `CardCode`: Customer code
- `DocDate`: Payment date
- `PaymentInvoices`: Array of credit notes being refunded
- `TransferAccount`: Bank account for transfers
- `CashAccount`: Cash account
- `TransferSum`: Transfer refund amount
- `CashSum`: Cash refund amount

**PaymentInvoices Structure**:
```json
{
  "DocEntry": {credit_note_doc_entry},
  "InvoiceType": "it_CredItnote",
  "SumApplied": {refund_amount}
}
```

**Operations**:
- `POST VendorPayments`: Create outgoing payment

---

### Gift Cards (`GiftCards`)
**Purpose**: Gift card master data

**Key Fields**:
- `CardCode`: Gift card ID (Shopify gift card ID)
- `CardName`: Gift card name
- `CardDescription`: Description
- `Price`: Gift card value
- `Active`: Active status ("Y"/"N")

**UDFs**:
- `U_LOCAL_SID`: Shopify product ID (local store)
- `U_INTERNATIONAL_SID`: Shopify product ID (international store)

**Note**: In the current implementation, gift card entries are typically NOT created in this entity. Gift card IDs are stored in invoice line items using the `U_GiftCard` field instead.

**Operations**:
- `POST GiftCards`: Create gift card entry
- `GET GiftCards('{id}')`: Check if gift card exists

---

### Business Partners (`BusinessPartners`)
**Purpose**: Customer master data

**Key Fields**:
- `CardCode`: Customer code
- `CardName`: Customer name
- `Phone1`, `Phone2`, `Cellular`: Phone numbers (used for matching)
- `EmailAddress`: Email address

**UDFs**:
- `U_ShopifyCustomerID`: Shopify customer ID
- `U_ShopifyEmail`: Customer email

**Operations**:
- `GET BusinessPartners`: Search customers (by phone number)
- `POST BusinessPartners`: Create new customer

---

### Items (`Items`)
**Purpose**: Product master data

**Key Fields**:
- `ItemCode`: Item code (SKU)
- `ItemName`: Product name
- `QuantityOnStock`: Current inventory quantity
- `WarehouseCode`: Warehouse code

**UDFs**:
- `U_MainItem`: Parent product identifier
- `U_Color`: Variant identifier
- `U_LOCAL_SID`: Shopify product ID (local store)
- `U_LOCAL_VARIANT_SID`: Shopify variant ID (local store)
- `U_LOCAL_INVENTORY_SID`: Shopify inventory item ID (local store)
- `U_INTERNATIONAL_SID`: Shopify product ID (international store)
- `U_INTERNATIONAL_VARIANT_SID`: Shopify variant ID (international store)
- `U_INTERNATIONAL_INVENTORY_SID`: Shopify inventory item ID (international store)
- `U_SyncDT`: Last sync date
- `U_SyncTime`: Sync status
- `U_Text1`: Vendor/Brand
- `U_BRND`: Brand name
- `U_ParentCommercialName`: Parent product name (for variants)
- `U_ShopifyColor`: Shopify color/variant name
- `U_SalesChannel`: Sales channel indicator

**Operations**:
- `GET Items('{itemcode}')`: Retrieve item
- `PATCH Items('{itemcode}')`: Update item fields

---

## API Endpoints Summary

### SAP Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `view.svc/MASHURA_New_ItemsB1SLQuery` | GET | Get new items for sync |
| `sml.svc/QTY_CHANGE` | GET | Get inventory changes |
| `U_SHOPIFY_MAPPING_2` | GET/POST | Shopify mapping table |
| `Items` | GET/PATCH | Item master data |
| `Invoices` | GET/POST | Sales invoices |
| `CreditNotes` | GET/POST | Credit notes (returns) |
| `IncomingPayments` | GET/POST | Customer payments |
| `VendorPayments` | POST | Outgoing payments (refunds) |
| `BusinessPartners` | GET/POST | Customer master data |
| `GiftCards` | GET/POST | Gift card master data |

### Shopify GraphQL Queries/Mutations

| Operation | Type | Purpose |
|-----------|------|---------|
| `productCreate` | Mutation | Create product |
| `productUpdate` | Mutation | Update product |
| `inventorySetOnHandQuantities` | Mutation | Update inventory |
| `tagsUpdate` | Mutation | Update order tags |
| `getGiftCards` | Query | Query gift cards |
| `getOrders` | Query | Get orders |
| `getReturn` | Query | Get return details |

---

## Data Flow Diagrams

### Order Processing Flow

```
Shopify Order
    ↓
Detect Gift Card Purchases
    ↓
Query Shopify Gift Cards API
    ↓
Create/Update Customer in SAP
    ↓
Create Invoice in SAP
    ├─ Regular Line Items
    ├─ Gift Card Line Items (with U_GiftCard)
    └─ Gift Card Redemption Expenses (negative, with U_GiftCard)
    ↓
Create Payment in SAP (if paid)
    ↓
Update Shopify Order Tags
```

### Return Processing Flow

```
Shopify Return
    ↓
Get Original Invoice from SAP
    ↓
Create Credit Note in SAP
    ↓
Determine Scenario
    ├─ Scenario 1: Store Credit
    │   ├─ Create Gift Card in Shopify
    │   ├─ Create Gift Card Invoice in SAP
    │   └─ Reconcile Credit Note with Invoice
    │
    └─ Scenario 2: Refund
        └─ Create Outgoing Payment in SAP
    ↓
Update Shopify Order Tags
```

---

## Error Handling and Retry Logic

### SAP API Retries
- Automatic retry on session expiration (401 errors)
- Exponential backoff for transient failures
- Maximum 3 retry attempts

### Idempotency
- Order tags prevent duplicate processing
- Document entry checks before creation
- Gift card ID tracking prevents duplicates

### Error Logging
- All API calls logged to `U_API_LOG` table
- Detailed error messages in application logs
- Failed operations tagged in Shopify for review

---

## Configuration and Customization

### Location Mapping
Each Shopify location maps to SAP:
- Warehouse code
- Costing codes (Location, Department, Activity)
- Sales person code
- Document series (Invoices, Credit Notes, Payments)

### Expense Codes
- Gift card redemption: Code 2 or 3 (configurable)
- Freight revenue: Code 6 (or configured)
- Freight cost: Configurable

### Document Series
- Invoices: Location-specific series
- Credit Notes: Location-specific series
- Payments: Location-specific series

---

## Conclusion

This technical documentation provides a comprehensive reference for understanding the SAP-Shopify integration at a technical level. It covers all SAP views, document types, API endpoints, and data flows for each synchronization process.

For business-focused documentation, refer to `SAP_SHOPIFY_INTEGRATION_DOCUMENTATION.md`.
