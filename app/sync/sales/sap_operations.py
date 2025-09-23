"""
Shared SAP operations for invoice and payment creation
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from app.services.sap.client import SAPClient
from app.core.config import config_settings

logger = logging.getLogger(__name__)

class SAPOperations:
    """Shared SAP operations for creating invoices and payments"""
    
    def __init__(self, sap_client: SAPClient):
        self.sap_client = sap_client
    
    async def create_invoice_in_sap(self, invoice_data: Dict[str, Any], order_id: str = "") -> Dict[str, Any]:
        """
        Create invoice in SAP
        """
        try:
            result = await self.sap_client._make_request(
                method='POST',
                endpoint='Invoices',
                data=invoice_data,
                order_id=order_id
            )
            
            if result["msg"] == "failure":
                logger.error(f"Failed to create invoice in SAP: {result.get('error')}")
                return result
            
            created_invoice = result["data"]
            invoice_number = created_invoice.get('DocEntry', '')
            
            logger.info(f"Created invoice in SAP: {invoice_number}")
            
            return {
                "msg": "success",
                "sap_invoice_number": invoice_number,
                "sap_doc_entry": created_invoice.get('DocEntry', ''),
                "sap_doc_num": created_invoice.get('DocNum', ''),
                "sap_trans_num": created_invoice.get('TransNum', ''),
                "sap_doc_total": created_invoice.get('DocTotal', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Error creating invoice in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    async def create_incoming_payment_in_sap(self, payment_data: Dict[str, Any], order_id: str = "") -> Dict[str, Any]:
        """
        Create incoming payment in SAP
        """
        try:
            result = await self.sap_client._make_request(
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
                "sap_doc_num": created_payment.get('DocNum', ''),
                "sap_doc_total": created_payment.get('DocTotal', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Error creating incoming payment in SAP: {str(e)}")
            return {"msg": "failure", "error": str(e)}

    def prepare_invoice_data(self, order_data: Dict[str, Any], customer_card_code: str, 
                           store_key: str, location_analysis: Dict[str, Any], 
                           line_items: List[Dict[str, Any]], 
                           financial_status: str = "PAID", 
                           fulfillment_status: str = "FULFILLED",
                           order_type: str = "1",
                           doc_date: str = None,
                           comments: str = None,
                           custom_fields: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Prepare invoice data with all required fields including series, costing codes, etc.
        """
        try:
            if doc_date is None:
                doc_date = datetime.now().strftime("%Y-%m-%d")
            
            if comments is None:
                comments = f"Shopify Order: {order_data.get('name', '')} | Payment: {financial_status} | Fulfillment: {fulfillment_status}"
            
            # Get series for invoices
            series = config_settings.get_series_for_location(
                store_key, 
                location_analysis.get('location_mapping', {}), 
                'invoices'
            )
            
            # Get currency for store
            currency = config_settings.get_currency_for_store(store_key)
            
            # Prepare base invoice data
            invoice_data = {
                "DocDate": doc_date,
                "CardCode": customer_card_code,
                "NumAtCard": order_data.get('name', '').replace("#", ""),
                "Series": series,
                "Comments": comments,
                "SalesPersonCode": 28,
                "DocumentLines": line_items,
                "U_Pay_type": 1 if financial_status in ["PAID", "PARTIALLY_REFUNDED"] else 2 if store_key == "local" else 3,
                "U_Shopify_Order_ID": order_data.get('id', '').split("/")[-1] if "/" in order_data.get('id', '') else order_data.get('id', ''),
                "U_OrderType": order_type,
                "ImportFileNum": order_data.get('name', '').replace("#", ""),
                "DocCurrency": currency
            }
            
            # Add delivery and billing addresses if available
            if 'shippingAddress' in order_data:
                delivery_address = self._generate_address_string(order_data['shippingAddress'])
                invoice_data["U_DeliveryAddress"] = delivery_address
            
            if 'billingAddress' in order_data:
                billing_address = self._generate_address_string(order_data['billingAddress'])
                invoice_data["U_BillingAddress"] = billing_address
            
            # Add POS receipt number if this is a POS order
            if location_analysis.get('is_pos_order') and location_analysis.get('extracted_receipt_number'):
                invoice_data["U_POS_Receipt_Number"] = location_analysis['extracted_receipt_number']
                logger.info(f"Added POS receipt number to invoice: {location_analysis['extracted_receipt_number']}")
            
            # Add freight expenses if any
            if 'freight_expenses' in order_data:
                invoice_data["DocumentAdditionalExpenses"] = order_data['freight_expenses']
            
            # Add gift card expenses if any
            if 'gift_card_expenses' in order_data:
                if "DocumentAdditionalExpenses" not in invoice_data:
                    invoice_data["DocumentAdditionalExpenses"] = []
                invoice_data["DocumentAdditionalExpenses"].extend(order_data['gift_card_expenses'])
            
            # Add custom fields if provided
            if custom_fields:
                invoice_data.update(custom_fields)
            
            return invoice_data
            
        except Exception as e:
            logger.error(f"Error preparing invoice data: {str(e)}")
            raise

    def prepare_payment_data(self, order_data: Dict[str, Any], customer_card_code: str, 
                           store_key: str, location_analysis: Dict[str, Any], 
                           invoice_doc_entry: str, payment_amount: float,
                           payment_type: str = "PaidOnline",
                           gateway: str = "Paymob",
                           courier_name: str = None,
                           custom_fields: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Prepare payment data with all required fields including series, transfer accounts, etc.
        """
        try:
            # Debug logging
            
            # Get series for incoming payments
            series = config_settings.get_series_for_location(
                store_key, 
                location_analysis.get('location_mapping', {}), 
                'incoming_payments'
            )
            
            # Get order ID number
            order_id_number = order_data.get('id', '').split("/")[-1] if "/" in order_data.get('id', '') else order_data.get('id', '')
            
            # Initialize payment data with the correct structure
            payment_data = {
                "DocDate": datetime.now().strftime("%Y-%m-%d"),
                "CardCode": customer_card_code,
                "DocType": "rCustomer",
                "Series": series,
                "U_Shopify_Order_ID": order_id_number
            }
            
            # Get location type
            location_type = config_settings.get_location_type(location_analysis.get('location_mapping', {}))
            
            # Handle different payment types based on gateway (copying logic from orders_sync)
            location_mapping = location_analysis.get('location_mapping', {})
            
            
            if gateway.lower() == "cash":
                # Cash transactions - use cash account from custom_fields (original payment details)
                cash_account = custom_fields.get("CashAccount") if custom_fields else None
                if cash_account:
                    payment_data["CashSum"] = payment_amount
                    payment_data["CashAccount"] = cash_account
                    logger.info(f"💰 CASH TRANSACTION: {payment_amount} EGP - Account: {cash_account}")
                else:
                    # Fallback to location configuration
                    cash_account = config_settings.get_cash_account_for_location(location_mapping)
                    if cash_account:
                        payment_data["CashSum"] = payment_amount
                        payment_data["CashAccount"] = cash_account
                        logger.info(f"💰 CASH TRANSACTION (fallback): {payment_amount} EGP - Account: {cash_account}")
                    else:
                        logger.warning(f"No cash account configured for location")
                    
            elif gateway in config_settings.get_credits_for_location(store_key, location_mapping):
                # Handle credit card transactions - use original payment details
                original_credit_cards = custom_fields.get("PaymentCreditCards") if custom_fields else None
                if original_credit_cards:
                    # Use original credit card details but update the amount
                    for card in original_credit_cards:
                        card['CreditSum'] = payment_amount
                    payment_data["PaymentCreditCards"] = original_credit_cards
                    logger.info(f"💳 CREDIT CARD TRANSACTION (original): {gateway} - {payment_amount} EGP")
                else:
                    # Fallback to creating new credit card details
                    cred_obj = {}
                    cred_obj['CreditCard'] = 1
                    
                    # Get credit account from configuration
                    credit_account = config_settings.get_credit_account_for_location(store_key, location_mapping, gateway)
                    if credit_account:
                        cred_obj['CreditAcct'] = credit_account
                    else:
                        logger.warning(f"No credit account found for gateway: {gateway}")
                        return payment_data
                    
                    cred_obj['CreditCardNumber'] = "1234"
                    
                    # Calculate next month date
                    next_month = datetime.now().replace(day=28) + timedelta(days=4)
                    res = next_month - timedelta(days=next_month.day)
                    cred_obj['CardValidUntil'] = str(res.date())
                    
                    cred_obj['VoucherNum'] = gateway
                    cred_obj['PaymentMethodCode'] = 1
                    cred_obj['CreditSum'] = payment_amount
                    cred_obj['CreditCur'] = "EGP"
                    cred_obj['CreditType'] = "cr_Regular"
                    cred_obj['SplitPayments'] = "tNO"
                    
                    payment_data["PaymentCreditCards"] = [cred_obj]
                    logger.info(f"💳 CREDIT CARD TRANSACTION (fallback): {gateway} - {payment_amount} EGP - Account: {credit_account}")
                
            else:
                # Bank transfer transactions - use original payment details
                transfer_account = custom_fields.get("TransferAccount") if custom_fields else None
                if transfer_account:
                    payment_data["TransferSum"] = payment_amount
                    payment_data["TransferAccount"] = transfer_account
                    logger.info(f"🏦 BANK TRANSFER TRANSACTION (original): {gateway} - {payment_amount} EGP - Account: {transfer_account}")
                else:
                    # Fallback to location configuration
                    transfer_account = config_settings.get_bank_transfer_for_location(
                        store_key, location_mapping, gateway
                    )
                    if transfer_account:
                        payment_data["TransferSum"] = payment_amount
                        payment_data["TransferAccount"] = transfer_account
                        logger.info(f"🏦 BANK TRANSFER TRANSACTION (fallback): {gateway} - {payment_amount} EGP - Account: {transfer_account}")
                    else:
                        logger.warning(f"No bank transfer account found for gateway: {gateway}")
            
            # Create invoice object for payment
            inv_obj = {
                "DocEntry": invoice_doc_entry,
                "SumApplied": payment_amount,
                "InvoiceType": "it_Invoice"
            }
            
            payment_data["PaymentInvoices"] = [inv_obj]
            
            # Add custom fields if provided
            if custom_fields:
                payment_data.update(custom_fields)
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error preparing payment data: {str(e)}")
            raise

    def _generate_address_string(self, address: Dict[str, Any]) -> str:
        """
        Generate address string from address dictionary
        """
        try:
            if not address:
                return ""
            
            parts = []
            
            # Add address lines
            if address.get('address1'):
                parts.append(address['address1'])
            if address.get('address2'):
                parts.append(address['address2'])
            
            # Add city, province, zip
            city_parts = []
            if address.get('city'):
                city_parts.append(address['city'])
            if address.get('province'):
                city_parts.append(address['province'])
            if address.get('zip'):
                city_parts.append(address['zip'])
            
            if city_parts:
                parts.append(', '.join(city_parts))
            
            # Add country
            if address.get('country'):
                parts.append(address['country'])
            
            return ' | '.join(parts) if parts else ""
            
        except Exception as e:
            logger.error(f"Error generating address string: {str(e)}")
            return ""
