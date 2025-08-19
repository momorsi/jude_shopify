"""
Payment Recovery Module
Queries SAP for open invoices with U_Pay_type=2, checks Shopify order status, and creates payments for PAID orders
"""

import asyncio
from typing import Dict, Any, List, Optional
from decimal import Decimal
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from datetime import datetime


class PaymentRecoverySync:
    """
    Handles payment recovery for open invoices that were initially pending payment
    """
    
    def __init__(self):
        self.batch_size = 50  # Number of invoices to process at once
    
    async def get_open_invoices_from_sap(self) -> Dict[str, Any]:
        """
        Get open invoices from SAP where U_Pay_type = 2
        """
        try:
            # Query to get open invoices with U_Pay_type = 2 using OData
            # First try with just DocumentStatus to test the field name
            endpoint = "Invoices"
            params = {
                "$select": "DocEntry,CardCode,DocTotal,U_Shopify_Order_ID",
                "$filter": "DocumentStatus eq 'bost_Open' and U_Pay_type eq '2' and U_Shopify_Order_ID ne null"
            }
            result = await sap_client._make_request(
                method='GET',
                endpoint=endpoint,
                params=params
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to get open invoices from SAP: {result.get('error')}")
                return result
            
            invoices = result["data"]["value"] if "value" in result["data"] else result["data"]
            logger.info(f"Retrieved {len(invoices)} open invoices with U_Pay_type=2 from SAP")
            
            return {"msg": "success", "data": invoices}
            
        except Exception as e:
            logger.error(f"Error getting open invoices from SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def get_shopify_order_status(self, order_id: str, store_key: str) -> Dict[str, Any]:
        """
        Get order status from Shopify by order ID
        """
        try:
            # Query to get order status
            query = """
            query getOrder($id: ID!) {
                order(id: $id) {
                    id
                    name
                    displayFinancialStatus
                    displayFulfillmentStatus
                    totalPriceSet {
                        shopMoney {
                            amount
                            currencyCode
                        }
                    }
                    transactions(first: 10) {
                        id
                        kind
                        status
                        gateway
                        amountSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        processedAt
                    }
                }
            }
            """
            
            # Add retry logic for GraphQL queries
            max_retries = 3
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    result = await multi_store_shopify_client.execute_query(
                        store_key,
                        query,
                        {"id": f"gid://shopify/Order/{order_id}"}
                    )
                    
                    if result["msg"] == "success":
                        break
                    else:
                        logger.warning(f"GraphQL attempt {attempt + 1}/{max_retries} failed: {result.get('error', 'Unknown error')}")
                        
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            
                except Exception as e:
                    logger.error(f"GraphQL attempt {attempt + 1}/{max_retries} exception: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        result = {"msg": "failure", "error": f"All {max_retries} attempts failed: {str(e)}"}
            
            if result["msg"] == "failure":
                return result
            
            order_data = result["data"]["order"]
            if not order_data:
                return {"msg": "failure", "error": f"Order {order_id} not found in Shopify"}
            
            return {
                "msg": "success",
                "data": {
                    "order_id": order_id,
                    "order_name": order_data["name"],
                    "financial_status": order_data["displayFinancialStatus"],
                    "fulfillment_status": order_data["displayFulfillmentStatus"],
                    "total_amount": float(order_data["totalPriceSet"]["shopMoney"]["amount"]),
                    "currency": order_data["totalPriceSet"]["shopMoney"]["currencyCode"],
                    "transactions": order_data["transactions"]
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting order status from Shopify: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    def prepare_payment_data(self, sap_invoice: Dict[str, Any], shopify_order: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Prepare incoming payment data for SAP
        """
        try:
            # Get payment information from transactions
            payment_info = self._extract_payment_info_from_transactions(shopify_order["transactions"])
            
            # Get order channel information (we'll need to determine this from the order)
            # For now, assume it's an online payment since U_Pay_type=2 typically means pending online payment
            payment_type = "PaidOnline"
            
            # Initialize payment data
            payment_data = {
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "CardCode": sap_invoice["CardCode"],
                "DocType": "rCustomer",
                "Series": 15,  # Series for incoming payments
                "TransferSum": sap_invoice["DocTotal"],  # Use the invoice total from SAP
                "TransferAccount": ""
            }
            
            # Set payment method based on type
            if payment_type == "PaidOnline":
                # Online store payments - use Paymob account
                transfer_account = config_settings.get_bank_transfer_account(store_key, "Paymob")
                payment_data["TransferAccount"] = transfer_account
                logger.info(f"Online store payment - using Paymob account: {transfer_account}")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": sap_invoice["DocEntry"],
                "SumApplied": sap_invoice["DocTotal"],  # Use the invoice total from SAP
                "InvoiceType": "it_Invoice"
            }
            
            # Add invoice to payment data
            payment_data["PaymentInvoices"] = [inv_obj]
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing payment data: {str(e)}")
            raise
    
    def _extract_payment_info_from_transactions(self, transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract payment information from Shopify order transactions
        """
        payment_info = {
            "gateway": "Unknown",
            "card_type": "Unknown", 
            "last_4": "Unknown",
            "payment_id": "Unknown",
            "amount": 0.0,
            "status": "Unknown",
            "processed_at": "Unknown"
        }
        
        try:
            for transaction in transactions:
                # Look for successful payment transactions
                if (transaction.get("kind") == "SALE" and 
                    transaction.get("status") == "SUCCESS"):
                    
                    payment_info["gateway"] = transaction.get("gateway", "Unknown")
                    payment_info["amount"] = float(transaction.get("amountSet", {}).get("shopMoney", {}).get("amount", 0))
                    payment_info["status"] = transaction.get("status", "Unknown")
                    payment_info["processed_at"] = transaction.get("processedAt", "Unknown")
                    payment_info["payment_id"] = transaction.get("id", "Unknown")
                    
                    # Use gateway as card type if payment details not available
                    payment_info["card_type"] = transaction.get("gateway", "Unknown")
                    
                    # Use the first successful payment transaction
                    break
                    
        except Exception as e:
            logger.error(f"Error extracting payment info: {str(e)}")
        
        return payment_info
    
    async def create_incoming_payment_in_sap(self, payment_data: Dict[str, Any], order_id: str = "") -> Dict[str, Any]:
        """
        Create incoming payment in SAP
        """
        try:
            result = await sap_client._make_request(
                method='POST',
                endpoint='IncomingPayments',
                data=payment_data,
                order_id=order_id
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create incoming payment in SAP: {result.get('error')}")
                return result
            
            created_payment = result["data"]
            payment_number = created_payment.get('DocEntry', '')
            
            logger.info(f"Created incoming payment in SAP: {payment_number}")
            
            return {
                "msg": "success",
                "sap_payment_number": payment_number,
                "sap_doc_entry": created_payment.get('DocEntry', ''),
                "sap_doc_num": created_payment.get('DocNum', '')
            }
            
        except Exception as e:
            logger.error(f"Error creating incoming payment in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def process_invoice_payment_recovery(self, sap_invoice: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Process payment recovery for a single invoice
        """
        try:
            order_id = sap_invoice["U_Shopify_Order_ID"]
            doc_entry = sap_invoice["DocEntry"]
            
            logger.info(f"Processing payment recovery for invoice DocEntry: {doc_entry} - Shopify Order: {order_id}")
            
            # Get order status from Shopify
            order_result = await self.get_shopify_order_status(order_id, store_key)
            if order_result["msg"] == "failure":
                logger.warning(f"Failed to get order status for {order_id}: {order_result.get('error')}")
                return {"msg": "failure", "error": f"Failed to get order status: {order_result.get('error')}"}
            
            shopify_order = order_result["data"]
            financial_status = shopify_order["financial_status"]
            
            logger.info(f"Order {order_id} status: {financial_status}")
            
            # Check if order is now PAID
            if financial_status == "PAID":
                logger.info(f"Order {order_id} is now PAID - creating incoming payment")
                
                # Prepare payment data
                payment_data = self.prepare_payment_data(sap_invoice, shopify_order, store_key)
                
                # Create incoming payment in SAP
                payment_result = await self.create_incoming_payment_in_sap(payment_data, order_id)
                
                if payment_result["msg"] == "success":
                    logger.info(f"✅ Successfully created payment for invoice DocEntry: {doc_entry} - Payment: {payment_result['sap_payment_number']}")
                    return {
                        "msg": "success",
                        "invoice_doc_entry": doc_entry,
                        "order_id": order_id,
                        "order_name": shopify_order["order_name"],
                        "payment_number": payment_result["sap_payment_number"],
                        "amount": shopify_order["total_amount"]
                    }
                else:
                    logger.error(f"❌ Failed to create payment for invoice DocEntry: {doc_entry}: {payment_result.get('error')}")
                    return {"msg": "failure", "error": f"Payment creation failed: {payment_result.get('error')}"}
            
            else:
                logger.info(f"Order {order_id} is still not PAID (status: {financial_status}) - skipping payment creation")
                return {
                    "msg": "skipped",
                    "invoice_doc_entry": doc_entry,
                    "order_id": order_id,
                    "reason": f"Order not PAID (status: {financial_status})"
                }
            
        except Exception as e:
            logger.error(f"Error processing payment recovery for invoice DocEntry: {sap_invoice.get('DocEntry', 'Unknown')}: {str(e)}")
            return {"msg": "failure", "error": str(e)}
    
    async def sync_payment_recovery(self) -> Dict[str, Any]:
        """
        Main payment recovery sync process
        """
        logger.info("Starting payment recovery sync...")
        
        try:
            # Get open invoices from SAP
            invoices_result = await self.get_open_invoices_from_sap()
            if invoices_result["msg"] == "failure":
                logger.error(f"Failed to get open invoices: {invoices_result.get('error')}")
                return invoices_result
            
            invoices = invoices_result["data"]
            if not invoices:
                logger.info("No open invoices with U_Pay_type=2 found")
                return {"msg": "success", "processed": 0, "success": 0, "skipped": 0, "errors": 0}
            
            logger.info(f"Found {len(invoices)} open invoices to process")
            
            total_processed = 0
            total_success = 0
            total_skipped = 0
            total_errors = 0
            
            # Get enabled stores to determine which store to query
            enabled_stores = config_settings.get_enabled_stores()
            if not enabled_stores:
                logger.warning("No enabled stores found")
                return {"msg": "failure", "error": "No enabled stores found"}
            
            # For now, we'll use the first enabled store
            # In the future, you might want to determine the store based on the invoice data
            store_key = list(enabled_stores.keys())[0]
            logger.info(f"Using store: {store_key}")
            
            # Process each invoice
            for sap_invoice in invoices:
                try:
                    result = await self.process_invoice_payment_recovery(sap_invoice, store_key)
                    
                    if result["msg"] == "success":
                        total_success += 1
                        logger.info(f"✅ Payment recovery successful for invoice DocEntry: {result['invoice_doc_entry']} -> Order: {result['order_name']} -> Payment: {result['payment_number']}")
                    
                    elif result["msg"] == "skipped":
                        total_skipped += 1
                        logger.info(f"⏭️ Skipped invoice DocEntry: {result['invoice_doc_entry']} - {result['reason']}")
                    
                    else:
                        total_errors += 1
                        logger.error(f"❌ Payment recovery failed for invoice DocEntry: {sap_invoice.get('DocEntry', 'Unknown')}: {result.get('error')}")
                    
                    total_processed += 1
                    
                except Exception as e:
                    total_errors += 1
                    logger.error(f"Error processing invoice DocEntry: {sap_invoice.get('DocEntry', 'Unknown')}: {str(e)}")
                    continue
            
            # Log sync event
            log_sync_event(
                sync_type="payment_recovery",
                items_processed=total_processed,
                success_count=total_success,
                error_count=total_errors
            )
            
            logger.info(f"Payment recovery sync completed. Processed: {total_processed}, Success: {total_success}, Skipped: {total_skipped}, Errors: {total_errors}")
            
            return {
                "msg": "success",
                "processed": total_processed,
                "success": total_success,
                "skipped": total_skipped,
                "errors": total_errors
            }
            
        except Exception as e:
            logger.error(f"Error in payment recovery sync: {str(e)}")
            return {"msg": "failure", "error": str(e)}
