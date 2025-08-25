"""
Sales Module for Shopify-SAP Integration
Handles gift cards sync (SAP → Shopify) and orders sync (Shopify → SAP)
"""


from .orders_sync import OrdersSalesSync
from .customers import CustomerManager

__all__ = ['OrdersSalesSync', 'CustomerManager'] 