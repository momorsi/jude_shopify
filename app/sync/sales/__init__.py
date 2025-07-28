"""
Sales Module for Shopify-SAP Integration
Handles gift cards sync (SAP → Shopify) and orders sync (Shopify → SAP)
"""

from .gift_cards_sync import GiftCardsSalesSync
from .orders_sync import OrdersSalesSync
from .customers import CustomerManager

__all__ = ['GiftCardsSalesSync', 'OrdersSalesSync', 'CustomerManager'] 