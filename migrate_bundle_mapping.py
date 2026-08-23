#!/usr/bin/env python3
"""
One-off migration: repoint @SHOPIFY_MAPPING_2 from the old pendant products to the new
combo products, then delete the old products from Shopify.

The new products sell a pendant on its own or bundled with a chain/cord. A bundle variant's
SKU is a comma-separated list of the SAP item codes it contains ("MOD-0000007,FG-0000909"),
and that string is what goes into U_SAP_Code - the price/stock views split it back apart.

Order matters: new rows are inserted BEFORE the old ones are deleted, so no item is ever
without a mapping row and the new-items sync can never see one as unmapped mid-migration.

    python migrate_bundle_mapping.py            # dry run, prints the full plan
    python migrate_bundle_mapping.py --apply    # execute
"""

import argparse
import asyncio
import sys
from datetime import date

from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client as shopify

# The 10 pendants. Their old Shopify products are replaced by the new combo products.
FG_ITEMS = [f"FG-00009{n:02d}" for n in range(4, 14)]

# Old pendant products to delete, per store. Verified to hold only FG_ITEMS SKUs
# (plus empty-SKU variants from an earlier abandoned combo attempt).
OLD_PRODUCTS = {
    "local": ["8303372435522", "8303372468290", "8303372501058",
              "8303372533826", "8303372566594", "8303372599362"],
    "international": ["7999681429594", "7999681462362", "7999681495130",
                      "7999681527898", "7999681560666", "7999681593434"],
}

# Old product-level mapping rows, keyed by U_ParentCommercialName. The House Chain and
# Cord parents are deliberately absent - those products stay, MOD items still sell standalone.
OLD_PRODUCT_ROW_KEYS = [
    "Drape Pendant Gold", "Drape Pendant Rhodium",
    "Hoop Pendant Gold", "Hoop Pendant Rhodium",
    "Cascade Tassle Gold", "Cascade Tassle Rhodium",
]

# The new combo products, created by hand in Shopify on 2026-08-17 (local) / 08-18 (international).
NEW_PRODUCTS = {
    "local": ["8352539082818", "8352830554178", "8352843595842", "8352844152898", "8352867450946",
              "8352877183042", "8352880033858", "8352885112898", "8352898318402", "8352901398594"],
    "international": ["8073343533146", "8073343631450", "8073343696986", "8073343729754", "8073343762522",
                      "8073343795290", "8073343860826", "8073343893594", "8073344024666", "8073344057434"],
}

PRODUCT_QUERY = """
query($id: ID!) {
  product(id: $id) { id title
    variants(first: 50) { edges { node { id sku inventoryItem { id } } } } }
}
"""


def gid_num(gid):
    return gid.split("/")[-1]


async def fetch_new_products(store_key):
    """The new combo products and their SKU-bearing variants."""
    products = []
    for product_id in NEW_PRODUCTS[store_key]:
        result = await shopify.execute_query(
            store_key, PRODUCT_QUERY, {"id": f"gid://shopify/Product/{product_id}"}
        )
        if result.get("msg") == "failure":
            raise RuntimeError(f"Failed to read {store_key} product {product_id}: {result.get('error')}")
        node = result["data"]["product"]
        if not node:
            raise RuntimeError(f"{store_key} product {product_id} not found")
        variants = [v["node"] for v in node["variants"]["edges"] if v["node"]["sku"]]
        products.append({"id": gid_num(node["id"]), "title": node["title"], "variants": variants})
    return products


def plan_new_rows(store_key, products):
    """Mapping rows for the new products: one product row, then variant + inventory per SKU."""
    today = date.today().isoformat()
    rows = []
    for product in products:
        # One Shopify product per SAP pendant now, so the product row is keyed by the
        # pendant's ItemCode. The price view prefers that over the parent-name row.
        plain = [v for v in product["variants"] if "," not in v["sku"]]
        if len(plain) != 1:
            raise RuntimeError(
                f"{store_key} product {product['id']} has {len(plain)} non-bundle variants, expected 1"
            )
        item_code = plain[0]["sku"]
        if item_code not in FG_ITEMS:
            raise RuntimeError(f"{store_key} product {product['id']} anchors on unexpected item {item_code}")

        rows.append({"Code": product["id"], "Name": product["id"], "U_SAP_Code": item_code,
                     "U_SAP_Type": "item", "U_Shopify_Type": "product",
                     "U_Shopify_Store": store_key, "U_CreateDT": today})

        for variant in product["variants"]:
            variant_id = gid_num(variant["id"])
            inventory_id = gid_num(variant["inventoryItem"]["id"])
            for code, row_type in ((variant_id, "variant"), (inventory_id, "variant_inventory")):
                rows.append({"Code": code, "Name": code, "U_SAP_Code": variant["sku"],
                             "U_SAP_Type": "item", "U_Shopify_Type": row_type,
                             "U_Shopify_Store": store_key, "U_CreateDT": today})
    return rows


async def fetch_rows(filter_query):
    """All @SHOPIFY_MAPPING_2 rows matching a filter (the Service Layer pages at 20)."""
    rows, skip = [], 0
    while True:
        result = await sap_client._make_request(
            "GET", "U_SHOPIFY_MAPPING_2",
            params={"$filter": filter_query, "$orderby": "Code", "$skip": skip}
        )
        if result.get("msg") == "failure":
            raise RuntimeError(f"Failed to read mapping rows: {result.get('error')}")
        page = (result.get("data") or {}).get("value", [])
        rows += page
        skip += len(page)
        if len(page) < 20:
            return rows


async def plan_old_rows(new_codes):
    """Old rows to delete: the FG item rows and the pendant product rows.

    Anything already claimed by a new row is left alone - re-running the migration must
    not delete what the previous run just inserted.
    """
    item_filter = " or ".join(f"U_SAP_Code eq '{code}'" for code in FG_ITEMS)
    product_filter = " or ".join(f"U_SAP_Code eq '{key}'" for key in OLD_PRODUCT_ROW_KEYS)
    rows = await fetch_rows(item_filter) + await fetch_rows(product_filter)
    return [row for row in rows if row["Code"] not in new_codes]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="execute (default is a dry run)")
    args = parser.parse_args()

    # --- plan -------------------------------------------------------------------
    new_rows = []
    for store_key in ("local", "international"):
        products = await fetch_new_products(store_key)
        if len(products) != 10:
            raise RuntimeError(f"Expected 10 new products in {store_key}, found {len(products)}")
        new_rows += plan_new_rows(store_key, products)

    old_rows = await plan_old_rows({row["Code"] for row in new_rows})

    print(f"\nPHASE 1  insert {len(new_rows)} mapping rows")
    for row in new_rows:
        print(f"    + {row['U_Shopify_Store']:<14} {row['U_Shopify_Type']:<18} "
              f"Code={row['Code']:<16} U_SAP_Code={row['U_SAP_Code']}")

    print(f"\nPHASE 2  delete {len(old_rows)} stale mapping rows")
    for row in old_rows:
        print(f"    - {row['U_Shopify_Store']:<14} {row['U_Shopify_Type']:<18} "
              f"Code={row['Code']:<16} U_SAP_Code={row['U_SAP_Code']}")

    old_count = sum(len(ids) for ids in OLD_PRODUCTS.values())
    print(f"\nPHASE 3  delete {old_count} old Shopify products")
    for store_key, ids in OLD_PRODUCTS.items():
        for product_id in ids:
            print(f"    - {store_key:<14} product {product_id}")

    if not args.apply:
        print("\nDry run - nothing changed. Re-run with --apply to execute.")
        return

    # --- apply ------------------------------------------------------------------
    failures = []

    print(f"\nPHASE 1  inserting {len(new_rows)} rows...")
    for row in new_rows:
        result = await sap_client.add_shopify_mapping(row)
        if result.get("msg") == "failure":
            failures.append(f"insert {row['Code']}: {result.get('error')}")
    if failures:
        print(f"  {len(failures)} insert(s) failed - STOPPING before any deletion:")
        for failure in failures:
            print(f"    {failure}")
        sys.exit(1)
    print("  done")

    print(f"\nPHASE 2  deleting {len(old_rows)} stale rows...")
    for row in old_rows:
        result = await sap_client.delete_shopify_mapping(row["Code"])
        if result.get("msg") == "failure":
            failures.append(f"delete row {row['Code']}: {result.get('error')}")
    print("  done")

    print(f"\nPHASE 3  deleting {old_count} Shopify products...")
    for store_key, ids in OLD_PRODUCTS.items():
        for product_id in ids:
            result = await shopify.delete_product(store_key, f"gid://shopify/Product/{product_id}")
            if result.get("msg") == "failure":
                failures.append(f"delete product {store_key}/{product_id}: {result.get('error')}")
    print("  done")

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for failure in failures:
            print(f"  {failure}")
        sys.exit(1)
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
