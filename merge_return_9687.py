"""
One-off: record return #2 of order #9687 in the live tracking file.

The SAP documents were created from a workstation, so the server's
data/returns_tracking.json does not know about them. Until it does, the
follow-up sync will treat the return as unprocessed and issue a DUPLICATE
credit note. Merges in place, does not overwrite other entries. Idempotent.

Run on the sync server, in the sync's working directory:
    python merge_return_9687.py
"""
import json
from pathlib import Path

PATH = Path("data/returns_tracking.json")
ORDER = "gid://shopify/Order/7207304691778"
ENTRY = {
    "return_id": "gid://shopify/Return/26162397250",
    "processed_at": "2026-08-25T19:05:34.966537",
    "credit_note_entry": 3222,
    "gift_card_id": "gid://shopify/GiftCard/555630526530",
    "items": [{
        "line_item_id": "gid://shopify/LineItem/17634990751810",
        "sku": "FG-0000682",
        "returned_quantity": 1,
    }],
}

data = json.loads(PATH.read_text(encoding="utf-8"))
order = data.get(ORDER)
if order is None:
    raise SystemExit(f"{ORDER} not found in {PATH.resolve()} -- wrong working directory?")

if any(r.get("return_id") == ENTRY["return_id"] for r in order["processed_returns"]):
    print("already recorded, nothing to do")
else:
    PATH.with_suffix(".json.bak").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    order["processed_returns"].append(ENTRY)
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"recorded {ENTRY['return_id']} (backup: {PATH.with_suffix('.json.bak')})")

print("processed returns for #9687:", [r["return_id"] for r in order["processed_returns"]])
