"""
Returns Tracking Database - JSON-based tracking for multiple returns per order
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class ReturnsTrackingDB:
    def __init__(self, db_path: str = "data/returns_tracking.json"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """Load tracking data from JSON file"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading returns tracking DB: {e}")
                return {}
        return {}
    
    def _save(self):
        """Save tracking data to JSON file"""
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving returns tracking DB: {e}")
    
    def get_order_tracking(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get tracking data for an order"""
        return self.data.get(order_id)
    
    def get_processed_return_ids(self, order_id: str) -> List[str]:
        """Get list of processed return IDs for an order"""
        tracking = self.get_order_tracking(order_id)
        if not tracking:
            return []
        return [r.get("return_id") for r in tracking.get("processed_returns", []) if r.get("return_id")]
    
    def get_processed_quantities(self, order_id: str) -> Dict[str, int]:
        """
        Get already processed quantities per line_item_id
        Returns: {line_item_id: total_processed_quantity}
        """
        tracking = self.get_order_tracking(order_id)
        if not tracking:
            return {}
        
        processed_qty = {}
        for processed_return in tracking.get("processed_returns", []):
            for item in processed_return.get("items", []):
                line_item_id = item.get("line_item_id", "")
                qty = item.get("returned_quantity", 0)
                if line_item_id:
                    processed_qty[line_item_id] = processed_qty.get(line_item_id, 0) + qty
        
        return processed_qty
    
    def add_processed_return(
        self, order_id: str, order_name: str, order_created_at: str,
        return_id: str, credit_note_entry: int, items: List[Dict[str, Any]],
        gift_card_id: str = None
    ):
        """Add a processed return to tracking"""
        if order_id not in self.data:
            self.data[order_id] = {
                "order_id": order_id,
                "order_name": order_name,
                "created_at": order_created_at,
                "last_checked_at": datetime.now().isoformat(),
                "processed_returns": []
            }
        
        self.data[order_id]["last_checked_at"] = datetime.now().isoformat()
        
        processed_return = {
            "return_id": return_id,
            "processed_at": datetime.now().isoformat(),
            "credit_note_entry": credit_note_entry,
            "gift_card_id": gift_card_id,
            "items": items
        }
        
        self.data[order_id]["processed_returns"].append(processed_return)
        self._save()
        logger.info(f"Added processed return {return_id} for order {order_name}")
    
    def get_processed_gift_card_ids(self, order_id: str) -> List[str]:
        """Get list of processed gift card IDs for an order"""
        tracking = self.get_order_tracking(order_id)
        if not tracking:
            return []
        gift_card_ids = []
        for processed_return in tracking.get("processed_returns", []):
            gc_id = processed_return.get("gift_card_id")
            if gc_id:
                gift_card_ids.append(gc_id)
        return gift_card_ids
    
    def is_all_returns_processed(self, order_id: str, shopify_return_ids: List[str]) -> bool:
        """Check if all Shopify returns are processed"""
        if not shopify_return_ids:
            return False
        
        processed_ids = set(self.get_processed_return_ids(order_id))
        shopify_ids = set(shopify_return_ids)
        return shopify_ids.issubset(processed_ids) and len(shopify_ids) > 0
    
    def get_orders_to_check(self, days_old: int = 30) -> List[str]:
        """Get order IDs that are within the last N days (for follow-up sync)"""
        cutoff_date = datetime.now() - timedelta(days=days_old)
        orders_to_check = []
        
        for order_id, tracking in self.data.items():
            created_at_str = tracking.get("created_at", "")
            try:
                # Handle both with and without timezone
                if 'Z' in created_at_str or '+' in created_at_str:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    created_at = created_at.replace(tzinfo=None)
                else:
                    created_at = datetime.fromisoformat(created_at_str)
                
                # Changed from <= to >= to get orders within last 30 days, not older than 30 days
                if created_at >= cutoff_date:
                    orders_to_check.append(order_id)
            except Exception as e:
                logger.warning(f"Error parsing created_at for order {order_id}: {e}")
                continue
        
        return orders_to_check

