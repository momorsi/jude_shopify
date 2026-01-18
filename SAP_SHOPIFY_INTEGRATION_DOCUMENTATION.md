# SAP-Shopify Integration Documentation

## Overview

This document provides a comprehensive overview of the integration between SAP Business One and Shopify. The integration enables seamless data synchronization between your ERP system (SAP) and your e-commerce platform (Shopify), ensuring that product information, inventory levels, orders, and customer data remain consistent across both systems.

The integration operates through five automated processes that continuously keep both systems synchronized, eliminating the need for manual data entry and reducing errors.

---

## Module 1: Understanding the Integration Architecture

### What is This Integration?

The SAP-Shopify integration is a bridge that connects your backend business management system (SAP) with your online storefront (Shopify). It ensures that:

- Products created in SAP automatically appear in your Shopify stores
- Inventory levels in SAP are reflected in Shopify in real-time
- Orders placed on Shopify are automatically created as invoices in SAP
- Customer information flows seamlessly between both systems
- Returns and refunds are properly tracked in both systems

### How It Works

The integration runs continuously in the background, checking for new or updated information at regular intervals. When changes are detected, the system automatically updates the corresponding records in the other system. This happens without any manual intervention, ensuring your data is always current.

### The Five Main Processes

The integration consists of five core processes, each handling a specific aspect of data synchronization:

1. **New Products Process** - Retrieves new products from SAP and creates them in Shopify
2. **Sales Orders Process** - Retrieves orders from Shopify and creates invoices in SAP
3. **Payment Recovery Process** - Retrieves payment information from SAP, updates Shopify, and syncs back to SAP
4. **Returns Process** - Retrieves return requests from Shopify and creates credit notes in SAP
5. **Inventory Process** - Retrieves inventory changes from SAP and updates stock levels in Shopify

Each process can be enabled or disabled independently, allowing you to control which aspects of the integration are active.

---

## Module 2: New Products Process (SAP → Shopify)

### Purpose

This process automatically creates products in your Shopify stores when new items are added to SAP. It ensures that your online catalog stays up-to-date with your product master data.

### How It Works

When new products are added to SAP and marked for synchronization, this process:

1. Retrieves the new product information from SAP
2. Groups related items together (if they belong to the same parent product)
3. Creates the product in the appropriate Shopify store(s)
4. Updates SAP with the Shopify product IDs for future reference

### Understanding Product Variants

Many products have multiple variants (for example, a shirt available in different colors or sizes). The system groups these variants together automatically.

**How Variants Are Identified:**

Items in SAP that belong to the same parent product are identified using two key fields:

- **MainProduct Field**: This field contains a common identifier that groups all variants of the same product together. For example, if you have a shirt in red, blue, and green, all three items would have the same value in the MainProduct field.

- **Color Field**: This field identifies the specific variant (e.g., "Red", "Blue", "Green"). Items with the same MainProduct value but different Color values become variants of the same product in Shopify.

**Example:**

If you have three items in SAP:
- Item Code: SHIRT001, MainProduct: SHIRT_MAIN, Color: Red
- Item Code: SHIRT002, MainProduct: SHIRT_MAIN, Color: Blue  
- Item Code: SHIRT003, MainProduct: SHIRT_MAIN, Color: Green

The system will create one product in Shopify called "SHIRT_MAIN" with three variants (Red, Blue, Green).

### Single Products vs. Variant Products

- **Single Products**: Items without a MainProduct value are created as standalone products in Shopify
- **Variant Products**: Items sharing the same MainProduct value are grouped together as one product with multiple variants

### Important SAP Fields for New Products

To ensure products sync correctly, the following fields must be populated in SAP:

**Required Fields:**
- **ItemCode**: Unique identifier for the item
- **ItemName**: Product name/title
- **MainProduct**: Groups variants together (leave empty for single products)
- **Color**: Variant identifier (required if MainProduct is used)
- **Shopify_Store**: Indicates which Shopify store(s) the product should appear in

**Additional Fields (for better product information):**
- **FrgnName**: Product description
- **U_Text1**: Vendor/Brand information
- **U_BRND**: Brand name
- **Barcode**: Product barcode

### What Happens After Sync

Once a product is successfully created in Shopify, SAP is updated with:
- The Shopify product ID (stored in store-specific fields)
- The Shopify variant ID (for variant products)
- The sync date and status

This allows the system to track which products have been synchronized and prevents duplicate creation.

---

## Module 3: Sales Orders Process (Shopify → SAP)

### Purpose

This process automatically creates invoices in SAP when orders are placed on your Shopify stores. It ensures that all sales transactions are properly recorded in your accounting system.

### How It Works

When a customer places an order on Shopify:

1. The system retrieves the order details from Shopify
2. Checks if the customer exists in SAP (creates them if needed)
3. Creates an invoice in SAP with all order line items
4. Handles special cases like gift cards and discounts
5. Updates the Shopify order to indicate it has been processed

### Important Requirements for Orders to Process Successfully

For an order to be successfully created in SAP, several pieces of information must be available:

**Customer Information:**
- Customer name (first and last name)
- Email address
- Phone number (used to match existing customers in SAP)
- Billing address
- Shipping address

**Order Details:**
- Order number
- Order date
- Payment status (paid, pending, etc.)
- Fulfillment status (fulfilled, unfulfilled, etc.)
- All line items with quantities and prices
- Shipping costs
- Tax amounts
- Discounts applied

**Product Information:**
- Each product in the order must have a valid SKU that matches an item in SAP
- Products must be properly mapped between Shopify and SAP

### Customer Matching

The system uses phone numbers to identify existing customers in SAP. If a customer with the same phone number exists, the order is linked to that customer. If no match is found, a new customer record is automatically created in SAP.

### Gift Card Handling

If an order includes gift card purchases or redemptions:
- Gift card purchases are recorded as separate line items
- Gift card redemptions are recorded as expense entries
- All gift card transactions are properly tracked for reconciliation

### SAP User-Defined Fields (UDFs) Used for Orders

To maintain the connection between Shopify orders and SAP invoices, the following custom fields are used in SAP:

**Invoice Header Fields:**
- **U_Shopify_Order_ID**: Stores the Shopify order ID for reference
- **U_Pay_type**: Indicates payment type (1 = Paid, 2 = Local Store Pending, 3 = International Store Pending)
- **U_OrderType**: Indicates the type of order (1 = Online, etc.)
- **U_DeliveryAddress**: Complete shipping address from Shopify
- **U_BillingAddress**: Complete billing address from Shopify
- **U_POS_Receipt_Number**: Receipt number for point-of-sale orders (if applicable)

These fields allow you to:
- Track which Shopify order corresponds to which SAP invoice
- Filter and report on Shopify orders within SAP
- Maintain a complete audit trail

### Order Processing Flow

1. **Order Detection**: System checks Shopify for new orders that haven't been processed
2. **Customer Management**: Customer is located or created in SAP
3. **Invoice Creation**: Invoice is created with all line items, addresses, and payment information
4. **Special Handling**: Gift cards, discounts, and shipping costs are processed
5. **Confirmation**: Shopify order is tagged to indicate successful processing

### What Happens If Processing Fails?

If an order cannot be processed (for example, missing customer information or invalid product SKU), the system:
- Logs the error for review
- Continues processing other orders
- Allows manual intervention to resolve the issue
- Retries failed orders on the next sync cycle

---

## Module 4: Payment Recovery Process (SAP → Shopify → SAP)

### Purpose

This process handles payment recovery scenarios where payment information needs to be synchronized between SAP and Shopify, ensuring that payment statuses are consistent across both systems.

### How It Works

This is a bidirectional process that:

1. Retrieves payment information from SAP that needs to be updated in Shopify
2. Updates the corresponding Shopify order with payment status
3. Syncs the updated information back to SAP

This ensures that payment statuses remain synchronized, which is particularly important for orders that were initially created with pending payment status.

### When This Process Is Used

- When payment is received for an order that was initially marked as pending
- When payment information is updated in SAP and needs to be reflected in Shopify
- When reconciling payment discrepancies between systems

---

## Module 5: Returns Process (Shopify → SAP)

### Purpose

This process automatically creates credit notes in SAP when customers request returns or refunds through Shopify, ensuring that returns are properly recorded in your accounting system.

### How It Works

When a return is processed in Shopify:

1. The system retrieves the return details from Shopify
2. Locates the original invoice in SAP using the Shopify order ID
3. Creates a credit note in SAP for the returned items
4. Updates the Shopify return to indicate it has been processed

### Important Requirements for Returns

For a return to be processed successfully:

- The original order must have been successfully created in SAP (with a valid invoice)
- The Shopify order ID must be stored in the SAP invoice (using the U_Shopify_Order_ID field)
- Return line items must match the original order items
- Return quantities cannot exceed the original order quantities

### SAP User-Defined Fields Used for Returns

**Credit Note Fields:**
- **U_ShopifyOrderID**: Links the credit note back to the Shopify return/order

This field ensures that returns can be traced back to their original orders and Shopify return requests.

---

## Module 6: Inventory Process (SAP → Shopify)

### Purpose

This process automatically updates stock levels in Shopify when inventory changes occur in SAP, ensuring that your online store always displays accurate product availability.

### How It Works

When inventory quantities change in SAP:

1. The system detects the inventory change
2. Identifies which Shopify store(s) need to be updated
3. Updates the stock levels in Shopify
4. Records the sync status in SAP

### Inventory Tracking

The system tracks inventory changes efficiently by only updating items that have actually changed, rather than checking every product every time. This ensures fast synchronization even with large product catalogs.

### Multi-Store Inventory

If you operate multiple Shopify stores, each store maintains its own inventory levels. The system updates each store independently based on warehouse assignments in SAP.

---

## Module 7: SAP User-Defined Fields (UDFs) Reference

### Overview

User-Defined Fields (UDFs) are custom fields added to SAP to store information specific to the Shopify integration. These fields are essential for maintaining the connection between SAP and Shopify records.

### Product-Related UDFs

**Variant Grouping Fields:**
- **U_MainItem**: Groups product variants together (items with the same value become variants)
- **U_Color**: Identifies the specific variant (color, size, etc.)

**Store-Specific Shopify IDs:**
- **U_LOCAL_SID**: Shopify product ID for local store
- **U_LOCAL_VARIANT_SID**: Shopify variant ID for local store
- **U_LOCAL_INVENTORY_SID**: Shopify inventory item ID for local store
- **U_INTERNATIONAL_SID**: Shopify product ID for international store
- **U_INTERNATIONAL_VARIANT_SID**: Shopify variant ID for international store
- **U_INTERNATIONAL_INVENTORY_SID**: Shopify inventory item ID for international store

**Sync Status Fields:**
- **U_SyncDT**: Date when the item was last synchronized
- **U_SyncTime**: Sync status indicator (SYNCED, PENDING, ERROR)

**Product Information Fields:**
- **U_Text1**: Vendor/Brand information
- **U_BRND**: Brand name
- **U_ParentCommercialName**: Parent product name (for variants)
- **U_ShopifyColor**: Shopify color/variant name
- **U_SalesChannel**: Sales channel indicator

### Order-Related UDFs

**Invoice Header Fields:**
- **U_Shopify_Order_ID**: Shopify order ID reference
- **U_Pay_type**: Payment type indicator
- **U_OrderType**: Order type (online, POS, etc.)
- **U_DeliveryAddress**: Shipping address
- **U_BillingAddress**: Billing address
- **U_POS_Receipt_Number**: Point-of-sale receipt number

**Customer Fields:**
- **U_ShopifyCustomerID**: Shopify customer ID reference
- **U_ShopifyEmail**: Customer email address

**Line Item Fields:**
- **U_GiftCard**: Gift card ID (for gift card line items)

### Return-Related UDFs

**Credit Note Fields:**
- **U_ShopifyOrderID**: Links credit note to Shopify return/order

### Why These Fields Are Important

These UDFs serve several critical purposes:

1. **Data Linking**: They maintain the connection between SAP and Shopify records
2. **Tracking**: They allow you to identify which records have been synchronized
3. **Reporting**: They enable filtering and reporting on Shopify-related transactions in SAP
4. **Troubleshooting**: They help identify and resolve synchronization issues
5. **Audit Trail**: They provide a complete history of synchronization activities

---

## Module 8: Best Practices and Recommendations

### Data Quality

**For Products:**
- Ensure all required fields are populated before marking items for sync
- Use consistent naming conventions for MainProduct values
- Keep product descriptions clear and complete
- Maintain accurate barcode information

**For Orders:**
- Ensure customer phone numbers are accurate and consistent
- Verify that all products have valid SKUs that match SAP
- Keep shipping and billing addresses complete
- Review failed orders regularly and resolve issues promptly

### Monitoring

- Regularly review sync logs to identify any issues
- Monitor failed syncs and address root causes
- Verify that inventory levels match between systems
- Check that orders are being processed in a timely manner

### Maintenance

- Keep SAP and Shopify systems updated
- Review and update product mappings as needed
- Ensure UDFs are properly maintained
- Archive or remove obsolete records to maintain system performance

### Troubleshooting Common Issues

**Products Not Syncing:**
- Verify that required fields (MainProduct, Color, Shopify_Store) are populated
- Check sync status fields for error indicators
- Ensure products are marked for the correct Shopify store

**Orders Not Processing:**
- Verify customer information is complete
- Check that product SKUs match between systems
- Review error logs for specific failure reasons
- Ensure payment and fulfillment statuses are valid

**Inventory Not Updating:**
- Verify warehouse assignments in SAP
- Check that inventory mapping exists for the items
- Ensure sync status fields are being updated

---

## Module 9: System Requirements and Setup

### SAP Requirements

**Required Tables:**
- Items master data table
- Business Partners (customers) table
- Invoices table
- Credit Notes table
- Shopify Mapping table (U_SHOPIFY_MAPPING_2)

**Required UDFs:**
- All UDFs listed in Module 7 must be created in SAP
- UDFs must be configured with appropriate data types and lengths

**API Access:**
- SAP API must be accessible from the integration server
- Appropriate user credentials with necessary permissions
- API endpoints must be configured correctly

### Shopify Requirements

**Store Configuration:**
- Shopify stores must be properly configured
- API access tokens with necessary permissions
- Store locations must be set up for inventory tracking

**Product Setup:**
- Products must have inventory management enabled
- SKUs must match SAP item codes
- Product variants must be properly configured

### Integration Server

**System Requirements:**
- Continuous internet connectivity
- Access to both SAP and Shopify APIs
- Sufficient system resources for processing
- Secure storage for credentials and configuration

---

## Module 10: Summary and Key Takeaways

### What This Integration Does

The SAP-Shopify integration automates the synchronization of critical business data between your ERP system and your e-commerce platform. It eliminates manual data entry, reduces errors, and ensures consistency across both systems.

### The Five Processes

1. **New Products**: Automatically creates products in Shopify from SAP
2. **Sales Orders**: Automatically creates invoices in SAP from Shopify orders
3. **Payment Recovery**: Synchronizes payment information between systems
4. **Returns**: Automatically creates credit notes in SAP from Shopify returns
5. **Inventory**: Automatically updates stock levels in Shopify from SAP

### Key Concepts

**Product Variants:**
- Items with the same MainProduct value are grouped as variants
- The Color field identifies specific variants
- Single products don't require MainProduct values

**Order Processing:**
- Requires complete customer and order information
- Uses phone numbers to match customers
- Handles gift cards and discounts automatically
- Creates invoices with all necessary details

**UDFs:**
- Essential for maintaining connections between systems
- Store Shopify IDs, sync status, and reference information
- Enable tracking, reporting, and troubleshooting

### Success Factors

For the integration to work effectively:

1. **Data Quality**: Ensure all required fields are populated accurately
2. **Consistency**: Use consistent naming and coding conventions
3. **Monitoring**: Regularly review sync status and resolve issues promptly
4. **Maintenance**: Keep systems updated and mappings current

### Getting Help

If you encounter issues or have questions:

1. Review the sync logs for error messages
2. Check that all required fields are populated
3. Verify that UDFs are properly configured
4. Contact your system administrator for technical support

---

## Conclusion

This integration provides a robust, automated solution for keeping your SAP and Shopify systems synchronized. By following the guidelines in this documentation and ensuring data quality, you can maintain accurate, up-to-date information across both platforms with minimal manual intervention.

The system is designed to run continuously in the background, processing changes as they occur and keeping both systems aligned. Regular monitoring and maintenance will ensure optimal performance and reliability.
