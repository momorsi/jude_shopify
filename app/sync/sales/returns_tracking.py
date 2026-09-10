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
        gift_card_id: str = None, skipped_reason: str = None
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
        if skipped_reason:
            # No SAP document was created; say why, so a null credit note entry is not
            # mistaken for a failed run.
            processed_return["skipped_reason"] = skipped_reason
        
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
    
    def get_orders_to_check(self) -> List[str]:
        """Tracked orders that could still produce a return.

        This used to drop orders older than N days, which meant a return raised
        more than N days after the sale could never reach SAP (order #9092 was
        placed 2026-07-05 and its second return came 2026-09-06). Follow-up now
        narrows on the Shopify side by updated_at instead, so the whole tracked
        set is the right scope -- minus the orders with nothing left to return.
        """
        return [oid for oid, t in self.data.items() if not t.get("fully_returned")]

    def is_fully_returned(self, order: Dict[str, Any]) -> bool:
        """Can this order still produce a return we would have to process?

        Shopify drops a line item's currentQuantity to 0 when it is returned or
        refunded, so an order whose every non-gift-card line reads 0 -- and whose
        returns are all processed -- can never produce another return.
        """
        order_id = order.get("id", "")
        tracking = self.data.get(order_id)
        if not tracking or tracking.get("fully_returned"):
            return False

        shopify_return_ids = [
            e.get("node", {}).get("id")
            for e in order.get("returns", {}).get("edges", [])
            if e.get("node", {}).get("id")
        ]
        if not self.is_all_returns_processed(order_id, shopify_return_ids):
            return False

        line_edges = order.get("lineItems", {}).get("edges", [])
        # The order query asks for 50 line items. At the cap we cannot see the whole
        # order, so we cannot say it is exhausted -- keep checking it.
        if not line_edges or len(line_edges) >= 50:
            return False

        for edge in line_edges:
            line = edge.get("node", {})
            if line.get("isGiftCard"):
                # A gift card line is never returned; it keeps its quantity for ever.
                continue
            current = line.get("currentQuantity")
            if current is None or current > 0:
                return False

        return True

    def mark_fully_returned_if_exhausted(self, order: Dict[str, Any]) -> bool:
        """Retire an order from follow-up once nothing on it can be returned again.

        Carrying a spent order through every future window costs a processing pass
        for nothing.
        """
        if not self.is_fully_returned(order):
            return False

        tracking = self.data[order.get("id", "")]
        tracking["fully_returned"] = True
        self._save()
        logger.info(
            f"Order {tracking.get('order_name')} has nothing left to return; "
            f"retiring it from follow-up"
        )
        return True

    def prune_fully_returned(self) -> int:
        """Delete retired orders outright. Returns how many rows went.

        Flagging already keeps them out of follow-up, so this only reclaims file
        size -- at the cost of the record of which returns reached SAP. Deliberately
        not called by the sync; run scripts/prune_returns_tracking.py if the file
        ever grows enough to matter.
        """
        doomed = [oid for oid, t in self.data.items() if t.get("fully_returned")]
        for oid in doomed:
            del self.data[oid]
        if doomed:
            self._save()
            logger.info(f"Pruned {len(doomed)} fully returned order(s) from tracking")
        return len(doomed)
