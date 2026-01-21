# SAP-Shopify Integration Technical Documentation

## Overview

This document provides technical details about the SAP-Shopify integration, focusing on SAP Business One Service Layer operations, integration-specific fields (UDFs), document relationships, and data flows. It covers SAP views, document types, and the technical implementation of each synchronization process.

---

## Table of Contents

1. [SAP Service Layer Architecture](#sap-service-layer-architecture)
2. [SAP Views and Custom Tables](#sap-views-and-custom-tables)
3. [Process 1: New Products Sync (SAP → Shopify)](#process-1-new-products-sync)
4. [Process 2: Sales Orders Sync (Shopify → SAP)](#process-2-sales-orders-sync)
5. [Process 3: Payment Recovery Sync (SAP → Shopify → SAP)](#process-3-payment-recovery-sync)
6. [Process 4: Returns Sync (Shopify → SAP)](#process-4-returns-sync)
7. [Process 5: Inventory Sync (SAP → Shopify)](#process-5-inventory-sync)
8. [Gift Card Processing](#gift-card-processing)
9. [SAP Document Types - Integration Fields](#sap-document-types---integration-fields)

---

## SAP Service Layer Architecture

### Service Layer Endpoints

The integration uses SAP Business One Service Layer (OData v2) for all SAP operations. Base URL: `https://{server}:{port}/b1s/v1/`

**Authentication**: Session-based using SAP Business One user credentials. Sessions maintained via cookies and automatically renewed on expiration.

**OData Query Parameters**: `$filter`, `$select`, `$orderby`, `$top`, `$skip`

---

## SAP Views and Custom Tables

### Custom Views

#### 1. `view.svc/MASHURA_New_ItemsB1SLQuery`

**Purpose**: Retrieves items from SAP pending synchronization to Shopify.

**Endpoint**: `GET view.svc/MASHURA_New_ItemsB1SLQuery`

**Key Integration Fields**:
- `itemcode`: SAP item code (SKU)
- `MainProduct`: Parent product identifier (groups variants)
- `Color`: Variant identifier
- `Shopify_Store`: Target store ('local' or 'international')
- `Status`: 'new' for initial sync, 'existing' for updates
- `Shopify_ProductCode`: Existing Shopify product ID (if previously synced)

**Query**: `$filter=Shopify_Store eq 'local' and Status eq 'new'`

---

#### 2. `sml.svc/QTY_CHANGE`

**Purpose**: Tracks inventory quantity changes with timestamps for incremental sync.

**Endpoint**: `GET sml.svc/QTY_CHANGE`

**Key Fields**:
- `ItemCode`: SAP item code
- `UpdateDate`: Date of change
- `UpdateTime`: Time of change
- `WarehouseCode`: Warehouse where change occurred
- `Quantity`: New quantity after change

**Query**: `$filter=UpdateDate gt datetime'{last_sync_date}'`

---

### Custom Tables

#### `U_SHOPIFY_MAPPING_2`

**Purpose**: Bidirectional mapping between SAP items and Shopify entities.

**Endpoint**: `GET/POST U_SHOPIFY_MAPPING_2`

**Key Fields**:
- `Code`: Shopify entity ID (product/variant/inventory item ID)
- `U_SAP_Code`: SAP item code
- `U_Shopify_Store`: Store identifier ('local' or 'international')
- `U_Shopify_Type`: Entity type ('product', 'variant', 'variant_inventory')
- `U_SAP_Type`: SAP entity type ('item')
- `U_CreateDT`: Creation date

**Usage**: Created during product sync, used for reverse lookups during inventory updates.

---

## Process 1: New Products Sync (SAP → Shopify)

### Data Flow: SAP → Shopify

### SAP Operations

**1. Retrieve New Items**
- Endpoint: `GET view.svc/MASHURA_New_ItemsB1SLQuery`
- Filter by `Shopify_Store` and `Status`

**2. Update Item Master Data (Post-Sync)**
- Endpoint: `PATCH Items('{itemcode}')`
- **Integration UDFs Updated**:
  - `U_LOCAL_SID` / `U_INTERNATIONAL_SID`: Shopify product ID
  - `U_LOCAL_VARIANT_SID` / `U_INTERNATIONAL_VARIANT_SID`: Shopify variant ID
  - `U_LOCAL_INVENTORY_SID` / `U_INTERNATIONAL_INVENTORY_SID`: Shopify inventory item ID
  - `U_SyncDT`: Last sync date
  - `U_SyncTime`: Sync status

**3. Create Mapping Records**
- Endpoint: `POST U_SHOPIFY_MAPPING_2`
- Creates mapping records for product, variant, and inventory item IDs

**Variant Grouping Logic**: Items with same `MainProduct` value are grouped into single Shopify product. `Color` field becomes variant identifier.

---

## Process 2: Sales Orders Sync (Shopify → SAP)

### Data Flow: Shopify → SAP

### Documents Created in SAP

#### 1. Invoice Document (`Invoices`)

**Endpoint**: `POST Invoices`

**Integration-Specific Header Fields**:

**User-Defined Fields (UDFs)**:
- `U_Shopify_Order_ID` (String): Shopify order ID (numeric portion)
- `U_Pay_type` (Integer): Payment status (1=Paid, 2=Local Pending, 3=International Pending)
- `U_OrderType` (String): Order type ("1"=Online)
- `U_DeliveryAddress` (String): Complete shipping address
- `U_BillingAddress` (String): Complete billing address
- `U_POS_Receipt_Number` (String): POS receipt number (for POS orders only)

**Standard Fields Used**:
- `NumAtCard`: Shopify order name (e.g., "#3505")
- `Comments`: "Shopify Order: {name} | Payment: {status} | Fulfillment: {status}"

**Integration-Specific Line Item Fields**:

**Line Item UDFs**:
- `U_GiftCard` (String): Shopify gift card ID (numeric) - populated when line item is a gift card purchase

**Note**: Gift card redemptions are NOT added as expense entries. They are processed as credit card payments in the incoming payment document (see Payment Processing section).

---

#### 2. Business Partner (Customer)

**Endpoint**: `POST BusinessPartners` (if customer doesn't exist)

**Integration-Specific UDFs**:
- `U_ShopifyCustomerID` (String): Shopify customer ID (numeric)
- `U_ShopifyEmail` (String): Customer email

**Customer Matching**: Uses phone number lookup across `Phone1`, `Phone2`, `Cellular` fields.

---

## Process 3: Payment Recovery Sync (SAP → Shopify → SAP)

### Data Flow: SAP → Shopify → SAP

### SAP Operations

**1. Query Invoices**
- Endpoint: `GET Invoices`
- Filter: `$filter=U_Shopify_Order_ID eq '{order_id}'`

**2. Check Payment Existence**
- Endpoint: `GET IncomingPayments`
- Filter by `U_Shopify_Order_ID` or invoice reference

**3. Create Incoming Payment**
- Endpoint: `POST IncomingPayments`

**Integration-Specific Fields**:
- `U_Shopify_Order_ID` (String): Shopify order ID

**Payment Methods**:

**POS Orders**:
- **Cash**: `CashSum`, `CashAccount` (from location `cash` field)
- **Credit Cards**: `PaymentCreditCards` array - gateway mapped to credit account from location `credit` mapping
- **Gift Cards**: `PaymentCreditCards` array - uses gift card credit account from location `credit` mapping
  - `VoucherNum`: Gift card ID
  - `CreditCardNumber`: Gift card last characters

**Online Orders**:
- **Bank Transfer**: `TransferSum`, `TransferAccount` (gateway mapped from location `bank_transfers` mapping)
- **Gift Cards**: `PaymentCreditCards` array - uses gift card credit account from web location `credit` mapping

**Payment Gateway Mapping**:
- Gateways mapped to SAP accounts via location configuration:
  - Credit card gateways (QNB POS, Geidea POS, etc.) → Credit card accounts
  - Bank transfer gateways (Paymob, Stripe, etc.) → Bank transfer accounts
  - Gift card gateway → Gift card credit account

**Payment Invoice Linkage**:
- `PaymentInvoices` array links payment to invoice:
  - `DocEntry`: Invoice DocEntry
  - `SumApplied`: Payment amount

---

## Process 4: Returns Sync (Shopify → SAP)

### Data Flow: Shopify → SAP

### Documents Created in SAP

#### 1. Credit Note (`CreditNotes`)

**Endpoint**: `POST CreditNotes`

**Integration-Specific Fields**:

**UDFs**:
- `U_ShopifyOrderID` (String): Shopify return/order ID

**Original Invoice Lookup**: Uses `U_Shopify_Order_ID` field to find original invoice and copy warehouse/costing codes.

---

#### 2. Scenario 1: Store Credit (Gift Card Return)

**Documents Created**:

**a. Gift Card Invoice (`Invoices`)**
- Endpoint: `POST Invoices`
- **Integration UDFs**:
  - `U_Shopify_Order_ID`: Original Shopify order ID
  - `U_Pay_type`: 1 (PAID)
  - `U_OrderType`: "1"
- **Line Item UDFs**:
  - `U_GiftCard`: Shopify gift card ID

**b. Reconciliation**
- Credit note and gift card invoice reconciled to balance accounts

---

#### 3. Scenario 2: Refund (Outgoing Payment)

**Document Created**:

**Outgoing Payment (`VendorPayments`)**
- Endpoint: `POST VendorPayments`

**Payment Method Determination**:
- Refund gateway extracted from Shopify refund transaction
- Gateway mapped to SAP payment account:
  - Credit card gateways → Credit card accounts
  - Bank transfer gateways → Bank transfer accounts
  - Cash gateways → Cash accounts

**Payment Invoice Linkage**:
- `PaymentInvoices` array:
  - `DocEntry`: Credit note DocEntry
  - `InvoiceType`: "it_CredItnote"
  - `SumApplied`: Refund amount (equals credit note total or partial refund amount)

**Partial Refunds**: `SumApplied` equals actual refunded amount from Shopify transaction, not original payment amount.

---

## Process 5: Inventory Sync (SAP → Shopify)

### Data Flow: SAP → Shopify

### SAP Operations

**1. Get Inventory Changes**
- Endpoint: `GET sml.svc/QTY_CHANGE`
- Filter: `$filter=UpdateDate gt datetime'{last_sync_date}'`

**2. Get Current Quantities**
- Endpoint: `GET Items('{itemcode}')`
- Select: `QuantityOnStock`, `WarehouseCode`

**3. Get Shopify Mappings**
- Endpoint: `GET U_SHOPIFY_MAPPING_2`
- Filter: `$filter=U_SAP_Code eq '{itemcode}' and U_Shopify_Store eq '{store_key}' and U_Shopify_Type eq 'variant_inventory'`

---

## Gift Card Processing

### Gift Card Purchase Flow

**Detection**: Gift card purchases identified by SKU matching configured gift card item code.

**SAP Invoice Line Item**:
- Added as regular invoice line item
- `ItemCode`: Gift card SKU
- `U_GiftCard`: Shopify gift card ID (numeric)

**Note**: Gift card entries are NOT created in SAP `GiftCards` entity. Gift card IDs stored in invoice line items only.

---

### Gift Card Redemption Flow

**Current Implementation**: Gift card redemptions are processed as **credit card payments** in incoming payment documents, NOT as invoice expense entries.

**Processing**:
- Gift card transactions detected in Shopify order transactions (gateway = "gift_card")
- Gift card information extracted: ID, amount, last characters
- Added to `PaymentCreditCards` array in incoming payment:
  - `CreditCard`: Gift card credit account (from location `credit` mapping, key "Gift Card")
  - `CreditCardNumber`: Gift card last characters
  - `VoucherNum`: Gift card ID
  - `CreditSum`: Gift card redemption amount
  - `CreditCur`: Currency code

**Payment Amount Calculation**:
- For POS orders: Gift card amounts included in `PaymentCreditCards` array
- For online orders: Gateway payment amount = Order total - Store credit - Gift card amounts; Gift card amounts processed separately as credit card payments

**No Expense Entries**: Gift card redemptions are NOT added to `DocumentAdditionalExpenses` array in invoices.

---

### Gift Card Return Processing

#### Scenario 1: Return to Gift Card (Store Credit)

**Process**:
1. Credit note created for returned items
2. Gift card created in Shopify (if not exists)
3. Gift card invoice created in SAP:
   - Single line item with gift card SKU
   - `U_GiftCard`: Gift card ID
   - `U_Pay_type`: 1 (PAID)
   - `U_Shopify_Order_ID`: Original order ID
4. Credit note and gift card invoice reconciled

#### Scenario 2: Return with Refund

**Process**:
1. Credit note created for returned items
2. Outgoing payment created:
   - Refund gateway extracted from Shopify refund transaction
   - Payment method mapped to SAP account based on refund gateway
   - `SumApplied` equals refund amount (credit note total or partial refund)

---

## SAP Document Types - Integration Fields

### Invoices (`Invoices`)

**Integration-Specific Header UDFs**:
- `U_Shopify_Order_ID`: Shopify order ID (numeric)
- `U_Pay_type`: Payment status (1=Paid, 2=Local Pending, 3=International Pending)
- `U_OrderType`: Order type ("1"=Online)
- `U_DeliveryAddress`: Shipping address
- `U_BillingAddress`: Billing address
- `U_POS_Receipt_Number`: POS receipt number

**Integration-Specific Line Item UDFs**:
- `U_GiftCard`: Gift card ID (for gift card purchases)

**Standard Fields Used for Integration**:
- `NumAtCard`: Shopify order name
- `Comments`: Order details summary

**Operations**:
- `POST Invoices`: Create invoice
- `GET Invoices?$filter=U_Shopify_Order_ID eq '{order_id}'`: Find by Shopify order ID

---

### Credit Notes (`CreditNotes`)

**Integration-Specific UDFs**:
- `U_ShopifyOrderID`: Shopify return/order ID

**Operations**:
- `POST CreditNotes`: Create credit note
- `GET CreditNotes?$filter=U_ShopifyOrderID eq '{return_id}'`: Find by return ID

---

### Incoming Payments (`IncomingPayments`)

**Integration-Specific UDFs**:
- `U_Shopify_Order_ID`: Shopify order ID

**Payment Methods**:
- `CashSum`, `CashAccount`: Cash payments
- `TransferSum`, `TransferAccount`: Bank transfer payments
- `PaymentCreditCards`: Credit card and gift card payments

**PaymentCreditCards Array Fields**:
- `CreditCard`: Account code (from location credit mapping)
- `CreditCardNumber`: Card number or gift card last characters
- `VoucherNum`: Payment gateway identifier or gift card ID
- `CreditSum`: Payment amount

**Operations**:
- `POST IncomingPayments`: Create payment
- `GET IncomingPayments?$filter=U_Shopify_Order_ID eq '{order_id}'`: Find by order ID

---

### Outgoing Payments (`VendorPayments`)

**Payment Methods**: Same structure as IncomingPayments

**PaymentInvoice Linkage**:
- `DocEntry`: Credit note DocEntry
- `InvoiceType`: "it_CredItnote"
- `SumApplied`: Refund amount

**Operations**:
- `POST VendorPayments`: Create outgoing payment

---

### Business Partners (`BusinessPartners`)

**Integration-Specific UDFs**:
- `U_ShopifyCustomerID`: Shopify customer ID (numeric)
- `U_ShopifyEmail`: Customer email

**Operations**:
- `GET BusinessPartners?$filter=Phone1 eq '{phone}' or Phone2 eq '{phone}' or Cellular eq '{phone}'`: Search by phone
- `POST BusinessPartners`: Create customer

---

### Items (`Items`)

**Integration-Specific UDFs**:

**Variant Grouping**:
- `U_MainItem`: Parent product identifier
- `U_Color`: Variant identifier

**Shopify Product IDs** (Store-Specific):
- `U_LOCAL_SID`: Shopify product ID (local store)
- `U_LOCAL_VARIANT_SID`: Shopify variant ID (local store)
- `U_LOCAL_INVENTORY_SID`: Shopify inventory item ID (local store)
- `U_INTERNATIONAL_SID`: Shopify product ID (international store)
- `U_INTERNATIONAL_VARIANT_SID`: Shopify variant ID (international store)
- `U_INTERNATIONAL_INVENTORY_SID`: Shopify inventory item ID (international store)

**Sync Status**:
- `U_SyncDT`: Last sync date
- `U_SyncTime`: Sync status

**Operations**:
- `GET Items('{itemcode}')`: Retrieve item
- `PATCH Items('{itemcode}')`: Update UDFs

---

## Payment Processing Details

### Payment Gateway to Account Mapping

**Location Configuration Structure**:

Each location has payment account mappings:

**Credit Accounts** (`credit` object):
- Maps payment gateways to credit card account IDs
- Format: `{"Gateway Name": credit_card_id}`
- Example: `{"QNB POS": 2, "Geidea POS": 1, "Gift Card": 6}`
- Credit card ID maps to GL account via `credit_cards` configuration

**Bank Transfer Accounts** (`bank_transfers` object):
- Maps payment gateways to bank account codes
- Format: `{"Gateway Name": "account_code"}`
- Example: `{"Paymob": "10801247"}`

**Cash Accounts** (`cash` field):
- Single cash account per location
- Format: `"cash": "10801239"`

**Account Resolution**:
- Location determined from order `retailLocation` (POS) or `sourceName` (online)
- Payment gateway mapped to account within location configuration
- Account codes must exist in SAP GL master data

---

### Gift Card Payment Processing

**Gift Card Redemptions as Credit Card Payments**:

Gift card redemptions are processed as credit card payments in `PaymentCreditCards` array:

**PaymentCreditCards Entry**:
- `CreditCard`: Gift card credit account (from location `credit` mapping, key "Gift Card")
- `CreditCardNumber`: Gift card last characters (e.g., "f978")
- `VoucherNum`: Gift card ID (numeric)
- `CreditSum`: Gift card redemption amount
- `CreditCur`: Currency code
- `CreditType`: "cr_Regular"
- `PaymentMethodCode`: 1

**Multiple Gift Cards**: Each gift card creates separate entry in `PaymentCreditCards` array.

**Payment Amount**: Gift card amounts included in payment total calculation.

---

## Configuration and Customization

### Location Mapping Structure

**Location Configuration** (`location_warehouse_mapping`):

**Basic Information**:
- `type`: "store" or "online"
- `warehouse`: SAP warehouse code
- `location_cc`, `department_cc`, `activity_cc`: Costing codes
- `group_code`: Customer group code
- `sales_employee`: Sales person code

**Document Series**:
- `series.invoices`: Invoice series
- `series.credit_notes`: Credit note series
- `series.incoming_payments`: Incoming payment series
- `series.outgoing_payments`: Outgoing payment series

**Payment Accounts**:
- `credit`: Object mapping gateways to credit card IDs
- `bank_transfers`: Object mapping gateways to bank accounts
- `cash`: Cash account code

---

## Error Handling and Idempotency

### Idempotency Mechanisms

**Order Tags**:
- Format: `sap_invoice_{doc_entry}`, `sap_payment_{doc_entry}`, `sap_return_cn_{doc_entry}`
- Tags checked before document creation
- Prevents duplicate processing

**Document Existence Checks**:
- Invoices: `GET Invoices?$filter=U_Shopify_Order_ID eq '{order_id}'`
- Payments: `GET IncomingPayments?$filter=U_Shopify_Order_ID eq '{order_id}'`
- Credit Notes: `GET CreditNotes?$filter=U_ShopifyOrderID eq '{return_id}'`

**Error Tagging**: Failed operations tagged in Shopify with `sap_payment_failed`, `sap_invoice_failed` for tracking and recovery.

---

## Conclusion

This technical documentation focuses on integration-specific fields, SAP Service Layer operations, and document relationships for the SAP-Shopify integration. It covers UDFs, custom views, payment processing, and gift card handling without exposing standard SAP fields or implementation-specific code.

For business-focused documentation, refer to `SAP_SHOPIFY_INTEGRATION_DOCUMENTATION.md`.
