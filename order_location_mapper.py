#!/usr/bin/env python3
"""
Order Location Mapper
Extracts location information from Shopify orders and maps to SAP configuration
"""

import re
from typing import Dict, Any, Optional, Tuple
from app.core.config import config_settings

class OrderLocationMapper:
    """
    Maps Shopify order source information to SAP location configuration
    """
    
    @staticmethod
    def extract_location_from_source_identifier(source_identifier: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract location ID and receipt number from source identifier
        
        Args:
            source_identifier: Source identifier like "70074892354-1-1003"
            
        Returns:
            Tuple of (location_id, receipt_number)
        """
        if not source_identifier:
            return None, None
            
        # Pattern to match: location_id-receipt_number
        # Example: "70074892354-1-1003" -> location_id="70074892354", receipt="1-1003"
        pattern = r'^(\d+)-(.+)$'
        match = re.match(pattern, source_identifier)
        
        if match:
            location_id = match.group(1)
            receipt_full = match.group(2)
            
            # Extract just the last part of the receipt number
            # Example: "1-1005" -> "1005", "2-1003" -> "1003"
            receipt_parts = receipt_full.split('-')
            receipt_number = receipt_parts[-1] if receipt_parts else receipt_full
            
            return location_id, receipt_number
        
        return None, None
    
    @staticmethod
    def get_sap_location_mapping(store_key: str, source_name: str, source_identifier: str) -> Optional[Dict[str, str]]:
        """
        Get SAP location mapping based on order source information
        
        Args:
            store_key: Store key (local/international)
            source_name: Source name from order (pos/web/etc)
            source_identifier: Source identifier from order
            
        Returns:
            Dictionary with SAP mapping or None if not found
        """
        try:
            # Get store configuration
            store_config = config_settings.get_store_by_name(store_key)
            if not store_config:
                print(f"Store config not found for {store_key}")
                return None
            
            # Get location mapping
            location_mapping = getattr(store_config, 'location_warehouse_mapping', {})
            if store_key not in location_mapping:
                return None
            
            locations = location_mapping[store_key].get('locations', {})
            
            # Handle web orders (source_name = "web", source_identifier = null)
            if source_name == "web" and not source_identifier:
                if "web" in locations:
                    return locations["web"]
                return None
            
            # Handle POS orders (extract location from source_identifier)
            if source_identifier:
                location_id, receipt_number = OrderLocationMapper.extract_location_from_source_identifier(source_identifier)
                if location_id and location_id in locations:
                    location_info = locations[location_id].copy()
                    location_info['receipt_number'] = receipt_number
                    return location_info
            
            return None
            
        except Exception as e:
            print(f"Error getting SAP location mapping: {str(e)}")
            return None
    
    @staticmethod
    def get_sap_costing_codes(location_mapping: Dict[str, str]) -> Dict[str, str]:
        """
        Get SAP costing codes from location mapping
        
        Args:
            location_mapping: Location mapping dictionary
            
        Returns:
            Dictionary with SAP costing codes
        """
        if not location_mapping:
            return {}
        
        return {
            # Item costing codes
            'COGSCostingCode': location_mapping.get('location_cc', ''),
            'CostingCode': location_mapping.get('location_cc', ''),
            'COGSCostingCode2': location_mapping.get('department_cc', ''),
            'CostingCode2': location_mapping.get('department_cc', ''),
            'COGSCostingCode3': location_mapping.get('activity_cc', ''),
            'CostingCode3': location_mapping.get('activity_cc', ''),
            
            # Expense line distribution rules
            'DistributionRule': location_mapping.get('location_cc', ''),
            'DistributionRule2': location_mapping.get('department_cc', ''),
            'DistributionRule3': location_mapping.get('activity_cc', ''),
            
            # Warehouse
            'Warehouse': location_mapping.get('warehouse', ''),
            
            # Additional info
            'ReceiptNumber': location_mapping.get('receipt_number', ''),
        }
    
    @staticmethod
    def analyze_order_source(order_data: Dict[str, Any], store_key: str) -> Dict[str, Any]:
        """
        Analyze order source and return complete SAP mapping
        
        Args:
            order_data: Order data from Shopify
            store_key: Store key (local/international)
            
        Returns:
            Complete analysis with SAP mapping
        """
        # Handle both GraphQL and REST API field names
        source_name = order_data.get('sourceName', order_data.get('source_name', ''))
        source_identifier = order_data.get('sourceIdentifier', order_data.get('source_identifier', ''))
        
        # Extract location information
        location_id, receipt_number = OrderLocationMapper.extract_location_from_source_identifier(source_identifier)
        
        # Get SAP location mapping
        location_mapping = OrderLocationMapper.get_sap_location_mapping(
            store_key, source_name, source_identifier
        )
        
        # Get SAP costing codes
        sap_codes = OrderLocationMapper.get_sap_costing_codes(location_mapping) if location_mapping else {}
        
        return {
            'source_name': source_name,
            'source_identifier': source_identifier,
            'extracted_location_id': location_id,
            'extracted_receipt_number': receipt_number,
            'location_mapping': location_mapping,
            'sap_codes': sap_codes,
            'is_web_order': source_name == "web" and not source_identifier,
            'is_pos_order': source_name == "pos" and source_identifier is not None and source_identifier != ""
        }

def print_order_analysis(analysis: Dict[str, Any]):
    """
    Print formatted order analysis
    """
    print("\n" + "="*60)
    print("ORDER SOURCE ANALYSIS")
    print("="*60)
    
    print(f"Source Name: {analysis.get('source_name', 'N/A')}")
    print(f"Source Identifier: {analysis.get('source_identifier', 'N/A')}")
    print(f"Extracted Location ID: {analysis.get('extracted_location_id', 'N/A')}")
    print(f"Extracted Receipt Number: {analysis.get('extracted_receipt_number', 'N/A')}")
    print(f"Is Web Order: {analysis.get('is_web_order', False)}")
    print(f"Is POS Order: {analysis.get('is_pos_order', False)}")
    
    location_mapping = analysis.get('location_mapping')
    if location_mapping:
        print("\n" + "-"*40)
        print("LOCATION MAPPING")
        print("-"*40)
        print(f"Warehouse: {location_mapping.get('warehouse', 'N/A')}")
        print(f"Location CC: {location_mapping.get('location_cc', 'N/A')}")
        print(f"Department CC: {location_mapping.get('department_cc', 'N/A')}")
        print(f"Activity CC: {location_mapping.get('activity_cc', 'N/A')}")
        if location_mapping.get('receipt_number'):
            print(f"Receipt Number: {location_mapping.get('receipt_number', 'N/A')}")
        
        sap_codes = analysis.get('sap_codes', {})
        if sap_codes:
            print("\n" + "-"*40)
            print("SAP COSTING CODES")
            print("-"*40)
            print("Item Costing Codes:")
            print(f"  COGSCostingCode: {sap_codes.get('COGSCostingCode', 'N/A')}")
            print(f"  CostingCode: {sap_codes.get('CostingCode', 'N/A')}")
            print(f"  COGSCostingCode2: {sap_codes.get('COGSCostingCode2', 'N/A')}")
            print(f"  CostingCode2: {sap_codes.get('CostingCode2', 'N/A')}")
            print(f"  COGSCostingCode3: {sap_codes.get('COGSCostingCode3', 'N/A')}")
            print(f"  CostingCode3: {sap_codes.get('CostingCode3', 'N/A')}")
            print("\nExpense Distribution Rules:")
            print(f"  DistributionRule: {sap_codes.get('DistributionRule', 'N/A')}")
            print(f"  DistributionRule2: {sap_codes.get('DistributionRule2', 'N/A')}")
            print(f"  DistributionRule3: {sap_codes.get('DistributionRule3', 'N/A')}")
            print(f"\nWarehouse: {sap_codes.get('Warehouse', 'N/A')}")
    else:
        print("\n❌ No location mapping found")
    
    print("\n" + "="*60)

# Test function
def test_order_analysis():
    """
    Test the order analysis with the provided order data
    """
    # Test data from the provided order
    test_order_data = {
        'sourceName': 'pos',
        'sourceIdentifier': '70074892354-1-1003'
    }
    
    print("Testing Order Analysis:")
    print("="*40)
    
    # Test extraction
    location_id, receipt_number = OrderLocationMapper.extract_location_from_source_identifier(
        test_order_data['sourceIdentifier']
    )
    print(f"Extracted Location ID: {location_id}")
    print(f"Extracted Receipt Number: {receipt_number}")
    
    # Test mapping
    analysis = OrderLocationMapper.analyze_order_source(test_order_data, 'local')
    print_order_analysis(analysis)

if __name__ == "__main__":
    test_order_analysis()
