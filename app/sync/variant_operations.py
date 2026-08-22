"""
Variant Operations Sync Module
Processes queued variant restructuring requests from the SAP U_VARIANT_OPERATIONS UDT:
- to_master: convert a variant into a standalone Shopify product
- move: move a variant from one parent product to another

U_NewParent holds the target parent's COMMERCIAL NAME (not an item code), matching how
parent products are keyed in U_SHOPIFY_MAPPING_2 (U_SAP_Code = MainProduct).
U_Shopify_Store optionally limits the operation to one store; blank = every enabled
store where the variant exists. Note the SAP item parent PATCH is global either way
(there is one U_ParentCommercialName per item, not one per store).

Per pending row the sync:
1. Resolves the variant in Shopify (and existing mapping rows in U_SHOPIFY_MAPPING_2)
2. For moves, resolves the target parent from the mapping table and VERIFIES the mapped
   product still exists in Shopify
3. Deletes the variant from its old product (or the whole product if it was the last variant)
4. Cleans up the old mapping rows
5. Patches the SAP item's parent field (new commercial name for move, cleared for to_master)
6. Recreates the item in Shopify and writes fresh mapping rows

Special move cases:
- Repair-only: the variant is already under the verified target product in Shopify
  (SAP mapping was the only thing wrong) -> mapping rows are rewritten, Shopify untouched.
- Cleanup-and-defer: the target parent is unmapped OR mapped to a product that no longer
  exists in Shopify (someone deleted it manually). The sync deletes the misplaced variant,
  removes the stale product mapping row and any orphaned sibling mapping rows (SKUs that
  share the target parent in SAP but no longer exist in Shopify), and does NOT recreate
  anything - the next new-items sync cycle recreates the parent with all its variants.
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.services.sap.client import sap_client
from app.services.shopify.multi_store_client import multi_store_shopify_client
from app.sync.new_items_multi_store import multi_store_new_items_sync
from app.core.config import config_settings
from app.utils.logging import logger, log_sync_event
from app.services.sap.api_logger import sl_add_log

VALID_OPERATIONS = ("to_master", "move")


class VariantOperationsSync:
    # SAP Items UDF that holds the parent COMMERCIAL NAME (feeds MainProduct in the
    # new-items view and matches U_SAP_Code of product rows in U_SHOPIFY_MAPPING_2).
    # Adjust here if the UDF name differs in your SAP setup.
    SAP_PARENT_FIELD = "U_ParentCommercialName"

    def __init__(self):
        self.batch_size = config_settings.variant_operations_batch_size

    async def sync_variant_operations(self) -> Dict[str, Any]:
        """
        Main entry point. Fetches pending rows from U_VARIANT_OPERATIONS and processes them.
        """
        logger.info("Starting variant operations sync")

        try:
            result = await sap_client.get_pending_variant_operations(batch_size=self.batch_size)
            if result["msg"] == "failure":
                logger.error(f"Failed to fetch pending variant operations: {result.get('error')}")
                return {"msg": "failure", "error": result.get("error")}

            rows = result.get("data", {}).get("value", [])
            if not rows:
                logger.info("No pending variant operations found")
                return {"msg": "success", "processed": 0, "success": 0, "errors": 0}

            logger.info(f"Found {len(rows)} pending variant operation(s)")

            processed = 0
            success = 0
            errors = 0

            for row in rows:
                row_code = row.get("Code", "")
                processed += 1
                try:
                    op_result = await self._process_operation(row)
                except Exception as e:
                    logger.error(f"Unhandled exception processing variant operation {row_code}: {str(e)}")
                    op_result = {"msg": "failure", "error": str(e)}

                if op_result["msg"] == "success":
                    success += 1
                    await self._mark_row(row_code, "done")
                else:
                    errors += 1
                    logger.error(f"Variant operation {row_code} failed: {op_result.get('error')}")
                    await self._mark_row(row_code, "error", op_result.get("error", "Unknown error"))

                await asyncio.sleep(0.5)

            log_sync_event(
                sync_type="variant_operations",
                items_processed=processed,
                success_count=success,
                error_count=errors
            )

            logger.info(f"Variant operations sync completed: {processed} processed, {success} successful, {errors} errors")
            return {"msg": "success", "processed": processed, "success": success, "errors": errors}

        except Exception as e:
            logger.error(f"Error in variant operations sync: {str(e)}")
            await sl_add_log(
                server="system",
                endpoint="/sync/variant_operations",
                response_data={"error": str(e)},
                status="failure",
                action="sync_error",
                value=f"Error in variant operations sync: {str(e)}"
            )
            return {"msg": "failure", "error": str(e)}

    async def _mark_row(self, row_code: str, status: str, error_message: str = None):
        """Update a queue row's status so it is not reprocessed."""
        if config_settings.test_mode:
            logger.info(f"[TEST MODE] Would mark variant operation {row_code} as '{status}'"
                        + (f" with error: {error_message}" if error_message else ""))
            return

        update_data = {
            "U_Status": status,
            "U_ProcessDT": datetime.now().strftime('%Y-%m-%d')
        }
        if error_message:
            # U_Error is an alphanumeric UDF; keep within typical 254-char limit
            update_data["U_Error"] = str(error_message)[:250]

        result = await sap_client.update_variant_operation(str(row_code), update_data)
        if result["msg"] == "failure":
            logger.error(f"Failed to update variant operation row {row_code}: {result.get('error')}")

    async def _process_operation(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single queue row across all relevant stores.
        Validates everything first, then patches SAP, then executes per-store Shopify changes.
        """
        row_code = row.get("Code", "")
        item_code = (row.get("U_ItemCode") or "").strip()
        operation = (row.get("U_Operation") or "").strip().lower()
        # U_NewParent holds the parent COMMERCIAL NAME (not an item code) - this is how
        # parents are keyed in U_SHOPIFY_MAPPING_2 product rows (U_SAP_Code = MainProduct)
        new_parent = (row.get("U_NewParent") or "").strip()
        store_filter = (row.get("U_Shopify_Store") or "").strip()

        # Validate the request
        if not item_code:
            return {"msg": "failure", "error": "U_ItemCode is empty"}
        if operation not in VALID_OPERATIONS:
            return {"msg": "failure", "error": f"Invalid U_Operation '{operation}'. Must be one of {VALID_OPERATIONS}"}
        if operation == "move" and not new_parent:
            return {"msg": "failure", "error": "U_NewParent (parent commercial name) is required for 'move' operations"}

        # Blank U_Shopify_Store = apply to every enabled store where the variant exists;
        # a specific store key limits the operation to that store only
        enabled_stores = multi_store_shopify_client.get_enabled_stores()
        if store_filter:
            if store_filter not in enabled_stores:
                return {"msg": "failure", "error": f"Store '{store_filter}' is not an enabled store. Enabled: {list(enabled_stores.keys())}"}
            stores = {store_filter: enabled_stores[store_filter]}
        else:
            stores = enabled_stores

        logger.info(f"Processing variant operation {row_code}: {operation} for {item_code}"
                    + (f" -> parent {new_parent}" if operation == "move" else "")
                    + f" (stores: {list(stores.keys())})")

        # Phase 1: resolve the variant and validate targets in every store BEFORE deleting anything,
        # so a bad request never leaves the variant deleted with nowhere to go.
        store_plans = {}
        for store_key, store_config in stores.items():
            plan_result = await self._resolve_store_plan(store_key, item_code, operation, new_parent)
            if plan_result["msg"] == "failure":
                return plan_result
            if plan_result.get("skip"):
                logger.info(f"Skipping store {store_key} for {item_code}: {plan_result.get('reason')}")
                continue
            store_plans[store_key] = plan_result["plan"]

        if not store_plans:
            return {"msg": "failure", "error": f"Variant {item_code} not found in Shopify or mapping table for any store"}

        if config_settings.test_mode:
            for store_key, plan in store_plans.items():
                if plan.get("repair_only"):
                    logger.info(
                        f"[TEST MODE] {store_key}: {item_code} already under target product "
                        f"{plan['target_product_id']} - would only rewrite its "
                        f"{len(plan['mapping_codes_to_delete'])} mapping row(s) (Shopify untouched)"
                    )
                elif plan.get("cleanup_and_defer"):
                    orphan_desc = ", ".join(
                        f"{o['sku']} ({len(o['mapping_codes'])} row(s))" for o in plan.get("orphaned_siblings", [])
                    ) or "none"
                    logger.info(
                        f"[TEST MODE] {store_key}: target parent '{new_parent}' is "
                        + ("mapped but GONE from Shopify (stale)" if plan.get("stale_target_mapping_codes") else "not mapped")
                        + ". Would "
                        + (f"delete product {plan['product_id']}" if plan["delete_whole_product"]
                           else f"delete variant {plan['variant_id']} from product {plan['product_id']}"
                           if plan["variant_id"] else "delete nothing from Shopify (variant already gone)")
                        + f", clean {len(plan['mapping_codes_to_delete'])} mapping row(s) for {item_code}, "
                        f"delete {len(plan.get('stale_target_mapping_codes', []))} stale product mapping row(s), "
                        f"clean orphaned sibling(s): {orphan_desc}, then DEFER recreation to the new-items sync"
                    )
                else:
                    logger.info(
                        f"[TEST MODE] {store_key}: would "
                        + (f"delete product {plan['product_id']}" if plan["delete_whole_product"]
                           else f"delete variant {plan['variant_id']} from product {plan['product_id']}"
                           if plan["variant_id"] else "delete nothing (stale/missing in Shopify)")
                        + f", clean {len(plan['mapping_codes_to_delete'])} mapping row(s), then "
                        + (f"recreate {item_code} as standalone product" if operation == "to_master"
                           else f"add {item_code} as variant to product {plan.get('target_product_id')}")
                    )
            logger.info(f"[TEST MODE] Would PATCH Items('{item_code}') {self.SAP_PARENT_FIELD} = "
                        f"'{'' if operation == 'to_master' else new_parent}'")
            return {"msg": "success"}

        # Phase 2: patch the SAP item's parent field (store-agnostic, done once).
        # The field holds the parent commercial name; for to_master it is cleared so the
        # item becomes standalone (the new-items view groups parentless items by itemcode).
        parent_value = "" if operation == "to_master" else new_parent
        patch_result = await sap_client.update_item(item_code, {self.SAP_PARENT_FIELD: parent_value})
        if patch_result["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to update SAP item {self.SAP_PARENT_FIELD}: {patch_result.get('error')}"}
        logger.info(f"Updated SAP item {item_code}: {self.SAP_PARENT_FIELD} = '{parent_value}'")

        # Phase 3: per-store delete + mapping cleanup + recreate + mapping write
        store_errors = []
        for store_key, plan in store_plans.items():
            store_result = await self._execute_store_plan(
                store_key, stores[store_key], plan, item_code, operation, new_parent
            )
            if store_result["msg"] == "failure":
                store_errors.append(f"{store_key}: {store_result.get('error')}")

        if store_errors:
            return {"msg": "failure", "error": "; ".join(store_errors)}

        return {"msg": "success"}

    async def _resolve_store_plan(self, store_key: str, item_code: str, operation: str,
                                  new_parent: str) -> Dict[str, Any]:
        """
        Build the execution plan for one store: locate the variant in Shopify,
        collect mapping rows to clean up, and validate the move target.
        """
        # Existing mapping rows for this SKU (variant + variant_inventory)
        mapping_codes_to_delete = []
        for shopify_type in ("variant", "variant_inventory"):
            mapping_result = await sap_client.get_shopify_mapping(
                sap_code=item_code, store_key=store_key, shopify_type=shopify_type
            )
            if mapping_result["msg"] == "failure":
                return {"msg": "failure", "error": f"Failed to read mapping table for {item_code} in {store_key}: {mapping_result.get('error')}"}
            for mapping_row in mapping_result.get("data", {}).get("value", []):
                mapping_codes_to_delete.append(mapping_row.get("Code"))

        # Shopify is the source of truth for what actually exists
        shopify_lookup = await multi_store_shopify_client.get_variant_by_sku(store_key, item_code)
        if shopify_lookup["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to look up SKU {item_code} in Shopify store {store_key}: {shopify_lookup.get('error')}"}

        if not shopify_lookup.get("found"):
            if not mapping_codes_to_delete:
                # Not in Shopify and not in the mapping table -> this store never had it
                return {"msg": "success", "skip": True, "reason": "not found in Shopify or mapping table"}
            # Stale mapping: variant was removed from Shopify manually. Clean up and recreate.
            logger.warning(f"SKU {item_code} has mapping rows in {store_key} but no Shopify variant (stale mapping); will clean up and recreate")
            plan = {
                "variant_id": None,
                "inventory_item_id": None,
                "product_id": None,
                "delete_whole_product": False,
                "product_mapping_codes_to_delete": [],
                "mapping_codes_to_delete": mapping_codes_to_delete,
                "target_product_id": None,
            }
        else:
            delete_whole_product = shopify_lookup.get("product_variants_count", 0) <= 1
            product_mapping_codes = []
            if delete_whole_product and shopify_lookup.get("product_id"):
                product_numeric_id = shopify_lookup["product_id"].split("/")[-1]
                product_mapping_result = await sap_client.get_shopify_mapping(
                    store_key=store_key, shopify_type="product", code=product_numeric_id
                )
                if product_mapping_result["msg"] == "success":
                    for mapping_row in product_mapping_result.get("data", {}).get("value", []):
                        product_mapping_codes.append(mapping_row.get("Code"))
            plan = {
                "variant_id": shopify_lookup["variant_id"],
                "inventory_item_id": shopify_lookup.get("inventory_item_id"),
                "product_id": shopify_lookup.get("product_id"),
                "delete_whole_product": delete_whole_product,
                "product_mapping_codes_to_delete": product_mapping_codes,
                "mapping_codes_to_delete": mapping_codes_to_delete,
                "target_product_id": None,
            }

        # For moves, resolve the target parent from the mapping table and VERIFY the mapped
        # product still exists in Shopify (validated BEFORE any deletion)
        if operation == "move":
            target_result = await sap_client.get_shopify_mapping(
                sap_code=new_parent, store_key=store_key, shopify_type="product"
            )
            if target_result["msg"] == "failure":
                return {"msg": "failure", "error": f"Failed to look up parent '{new_parent}' in mapping table for {store_key}: {target_result.get('error')}"}

            target_rows = target_result.get("data", {}).get("value", [])
            target_exists = False
            stale_target_mapping_codes = []

            if target_rows:
                target_product_numeric = target_rows[0].get("Code")
                candidate_id = f"gid://shopify/Product/{target_product_numeric}"
                # The mapping row may be stale (product manually deleted from Shopify) - verify
                product_check = await multi_store_shopify_client.get_product_by_id(store_key, candidate_id)
                if product_check["msg"] == "failure":
                    return {"msg": "failure", "error": f"Failed to verify parent product {candidate_id} in Shopify {store_key}: {product_check.get('error')}"}
                if product_check.get("data", {}).get("product"):
                    target_exists = True
                    plan["target_product_id"] = candidate_id
                else:
                    stale_target_mapping_codes = [r.get("Code") for r in target_rows]
                    logger.warning(f"Parent '{new_parent}' is mapped to product {target_product_numeric} in {store_key} "
                                   f"but that product no longer exists in Shopify (stale mapping)")

            if target_exists:
                if plan["product_id"] and plan["product_id"] == plan["target_product_id"]:
                    # Variant is already under the target product in Shopify - the SAP mapping
                    # is what's wrong. Repair mode: no delete/recreate, just rewrite mapping rows.
                    plan["repair_only"] = True
                    logger.info(f"{item_code} is already under '{new_parent}' in Shopify ({store_key}); will repair mapping rows only")
            else:
                # Target parent is unmapped or its mapped product is gone from Shopify.
                # Cleanup-and-defer: remove the misplaced variant + all stale mapping rows
                # (parent product row and orphaned siblings), then let the new-items sync
                # recreate the parent with all its variants.
                siblings_result = await self._find_orphaned_siblings(store_key, new_parent, item_code)
                if siblings_result["msg"] == "failure":
                    return siblings_result
                plan["cleanup_and_defer"] = True
                plan["stale_target_mapping_codes"] = stale_target_mapping_codes
                plan["orphaned_siblings"] = siblings_result["orphans"]
                logger.info(f"Cleanup-and-defer for {item_code} in {store_key}: parent '{new_parent}' "
                            f"{'stale in mapping table' if stale_target_mapping_codes else 'not mapped'}, "
                            f"{len(siblings_result['orphans'])} orphaned sibling(s) to clean")

        return {"msg": "success", "plan": plan}

    async def _find_orphaned_siblings(self, store_key: str, new_parent: str,
                                      exclude_item_code: str) -> Dict[str, Any]:
        """
        Find SKUs that share the target parent in SAP but no longer exist in Shopify
        for this store, while still having mapping rows (orphans left behind by manual
        deletions - e.g. FG-0000830 after its product was deleted from Shopify).
        Siblings that DO exist in Shopify are left untouched (logged as a warning,
        because they may sit under another product and will not be re-synced).
        """
        escaped_parent = new_parent.replace("'", "''")
        items_result = await sap_client._make_request(
            'GET', 'Items',
            params={
                '$filter': f"{self.SAP_PARENT_FIELD} eq '{escaped_parent}'",
                '$select': 'ItemCode',
                '$top': 200
            }
        )
        if items_result["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to find sibling items of parent '{new_parent}': {items_result.get('error')}"}

        orphans = []
        for item_row in items_result.get("data", {}).get("value", []):
            sibling_sku = item_row.get("ItemCode", "")
            if not sibling_sku or sibling_sku == exclude_item_code:
                continue

            sibling_mapping_codes = []
            for shopify_type in ("variant", "variant_inventory"):
                mapping_result = await sap_client.get_shopify_mapping(
                    sap_code=sibling_sku, store_key=store_key, shopify_type=shopify_type
                )
                if mapping_result["msg"] == "failure":
                    return {"msg": "failure", "error": f"Failed to read mapping rows for sibling {sibling_sku} in {store_key}: {mapping_result.get('error')}"}
                for mapping_row in mapping_result.get("data", {}).get("value", []):
                    sibling_mapping_codes.append(mapping_row.get("Code"))

            if not sibling_mapping_codes:
                continue  # nothing to clean for this sibling

            sibling_lookup = await multi_store_shopify_client.get_variant_by_sku(store_key, sibling_sku)
            if sibling_lookup["msg"] == "failure":
                return {"msg": "failure", "error": f"Failed to look up sibling {sibling_sku} in Shopify {store_key}: {sibling_lookup.get('error')}"}

            if sibling_lookup.get("found"):
                logger.warning(f"Sibling {sibling_sku} of parent '{new_parent}' still exists in Shopify {store_key} "
                               f"(product {sibling_lookup.get('product_id')}); leaving its mapping rows untouched")
                continue

            orphans.append({"sku": sibling_sku, "mapping_codes": sibling_mapping_codes})

        return {"msg": "success", "orphans": orphans}

    async def _execute_store_plan(self, store_key: str, store_config: Any, plan: Dict[str, Any],
                                  item_code: str, operation: str, new_parent: str) -> Dict[str, Any]:
        """
        Execute the plan for one store: delete old Shopify entity, clean mappings,
        recreate, and write new mapping rows.
        """
        # Repair-only mode: Shopify is already correct (variant is under the target
        # product); just rewrite the mapping rows without touching Shopify products.
        if plan.get("repair_only"):
            for mapping_code in plan["mapping_codes_to_delete"]:
                if not mapping_code:
                    continue
                delete_mapping_result = await sap_client.delete_shopify_mapping(str(mapping_code))
                if delete_mapping_result["msg"] == "failure":
                    logger.warning(f"Failed to delete mapping row {mapping_code}: {delete_mapping_result.get('error')}")

            variant_numeric_id = plan["variant_id"].split("/")[-1]
            await self._write_mapping(variant_numeric_id, "variant", item_code, store_key)
            if plan.get("inventory_item_id"):
                inventory_numeric_id = plan["inventory_item_id"].split("/")[-1]
                await self._write_mapping(inventory_numeric_id, "variant_inventory", item_code, store_key)

            logger.info(f"Repaired mapping rows for {item_code} in {store_key} (Shopify untouched)")
            return {"msg": "success"}

        # Step 1: delete from Shopify
        if plan["variant_id"]:
            if plan["delete_whole_product"]:
                logger.info(f"Deleting whole product {plan['product_id']} in {store_key} (variant {item_code} was the last one)")
                delete_result = await multi_store_shopify_client.delete_product(store_key, plan["product_id"])
                if delete_result["msg"] == "failure":
                    return {"msg": "failure", "error": f"Failed to delete product {plan['product_id']}: {delete_result.get('error')}"}
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data=delete_result,
                    status="success",
                    action="variant_op_delete_product",
                    value=f"Deleted product {plan['product_id']} (last variant {item_code}) in {store_key}"
                )
            else:
                logger.info(f"Deleting variant {plan['variant_id']} from product {plan['product_id']} in {store_key}")
                delete_result = await multi_store_shopify_client.delete_product_variants(
                    store_key, plan["product_id"], [plan["variant_id"]]
                )
                if delete_result["msg"] == "failure":
                    return {"msg": "failure", "error": f"Failed to delete variant {plan['variant_id']}: {delete_result.get('error')}"}
                await sl_add_log(
                    server="shopify",
                    endpoint=f"/admin/api/graphql_{store_key}",
                    response_data=delete_result,
                    status="success",
                    action="variant_op_delete_variant",
                    value=f"Deleted variant {item_code} ({plan['variant_id']}) from product {plan['product_id']} in {store_key}"
                )

        # Step 2: clean up old mapping rows
        for mapping_code in plan["mapping_codes_to_delete"] + plan["product_mapping_codes_to_delete"]:
            if not mapping_code:
                continue
            delete_mapping_result = await sap_client.delete_shopify_mapping(str(mapping_code))
            if delete_mapping_result["msg"] == "failure":
                logger.warning(f"Failed to delete mapping row {mapping_code}: {delete_mapping_result.get('error')}")

        # Cleanup-and-defer: the target parent product is gone from Shopify. Remove all
        # remaining stale mapping rows (parent product row + orphaned siblings) and STOP -
        # no recreation. The item(s) are now unmapped and absent from Shopify, so the next
        # new-items sync cycle recreates the parent product with all its variants.
        if plan.get("cleanup_and_defer"):
            for mapping_code in plan.get("stale_target_mapping_codes", []):
                if not mapping_code:
                    continue
                delete_mapping_result = await sap_client.delete_shopify_mapping(str(mapping_code))
                if delete_mapping_result["msg"] == "failure":
                    logger.warning(f"Failed to delete stale product mapping row {mapping_code}: {delete_mapping_result.get('error')}")
                else:
                    logger.info(f"Deleted stale product mapping row {mapping_code} for parent '{new_parent}' in {store_key}")

            for orphan in plan.get("orphaned_siblings", []):
                for mapping_code in orphan["mapping_codes"]:
                    if not mapping_code:
                        continue
                    delete_mapping_result = await sap_client.delete_shopify_mapping(str(mapping_code))
                    if delete_mapping_result["msg"] == "failure":
                        logger.warning(f"Failed to delete orphaned sibling mapping row {mapping_code} ({orphan['sku']}): {delete_mapping_result.get('error')}")
                    else:
                        logger.info(f"Deleted orphaned mapping row {mapping_code} for sibling {orphan['sku']} in {store_key}")

            logger.info(f"Cleanup complete for {item_code} in {store_key}; recreation of parent "
                        f"'{new_parent}' deferred to the new-items sync")
            return {"msg": "success"}

        # Step 3: fetch the item payload from the new-items view (reuses existing pricing/naming logic)
        view_result = await sap_client.get_new_item_by_code(item_code, store_key)
        if view_result["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to fetch item {item_code} from new-items view: {view_result.get('error')}"}

        view_rows = view_result.get("data", {}).get("value", [])
        if not view_rows:
            return {
                "msg": "failure",
                "error": (f"Item {item_code} was deleted from Shopify ({store_key}) but the new-items view "
                          f"returned no row for it, so it could not be recreated. Verify the item appears in "
                          f"MASHURA_New_ItemsB1SLQuery, then reset this request to 'pending'")
            }
        sap_item = view_rows[0]

        # Step 4: recreate in Shopify
        if operation == "to_master":
            recreate_result = await self._recreate_as_master(store_key, store_config, sap_item, item_code)
        else:
            recreate_result = await self._recreate_under_parent(store_key, store_config, sap_item, item_code, plan["target_product_id"])

        return recreate_result

    async def _recreate_as_master(self, store_key: str, store_config: Any,
                                  sap_item: Dict[str, Any], item_code: str) -> Dict[str, Any]:
        """Create the item as a standalone product and write fresh mapping rows."""
        product_info = multi_store_new_items_sync._create_single_product(sap_item, store_config)
        create_result = await multi_store_new_items_sync.create_product_with_variants_two_step(
            store_key, product_info, store_config
        )
        if create_result["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to create standalone product for {item_code}: {create_result.get('error')}"}

        product_numeric_id = create_result["shopify_product_id"].split("/")[-1]
        logger.info(f"Created standalone product {product_numeric_id} for {item_code} in {store_key}")

        # Product mapping row (standalone products are keyed by SKU, matching items_init convention)
        await self._write_mapping(product_numeric_id, "product", item_code, store_key)

        # Variant + inventory mapping rows
        for variant in create_result.get("shopify_variants", []):
            if variant.get("sku") != item_code:
                continue
            variant_numeric_id = variant["id"].split("/")[-1]
            inventory_numeric_id = variant["inventory_item_id"].split("/")[-1]
            await self._write_mapping(variant_numeric_id, "variant", item_code, store_key)
            await self._write_mapping(inventory_numeric_id, "variant_inventory", item_code, store_key)

        return {"msg": "success"}

    async def _recreate_under_parent(self, store_key: str, store_config: Any, sap_item: Dict[str, Any],
                                     item_code: str, target_product_id: str) -> Dict[str, Any]:
        """Add the item as a variant to the target parent's product and write fresh mapping rows."""
        price = multi_store_new_items_sync._get_store_price(sap_item, store_config.price_list)
        sale_price = multi_store_new_items_sync._get_store_sale_price(sap_item, store_config.price_list)
        variant_data = multi_store_new_items_sync._create_variant(sap_item, store_config, price, sale_price, 0)
        color = variant_data.pop("_color", None)

        add_result = await multi_store_new_items_sync.add_variant_to_existing_product(
            store_key, target_product_id, variant_data, color
        )
        if add_result["msg"] == "failure":
            return {"msg": "failure", "error": f"Failed to add {item_code} to product {target_product_id}: {add_result.get('error')}"}

        variant_numeric_id = add_result["shopify_variant_id"].split("/")[-1]
        inventory_numeric_id = add_result["shopify_inventory_item_id"].split("/")[-1]
        logger.info(f"Added variant {variant_numeric_id} ({item_code}) to product {target_product_id} in {store_key}")

        await self._write_mapping(variant_numeric_id, "variant", item_code, store_key)
        await self._write_mapping(inventory_numeric_id, "variant_inventory", item_code, store_key)

        return {"msg": "success"}

    async def _write_mapping(self, code: str, shopify_type: str, sap_code: str, store_key: str):
        """Write a mapping row to U_SHOPIFY_MAPPING_2."""
        mapping_data = {
            "Code": code,
            "Name": code,
            "U_Shopify_Type": shopify_type,
            "U_SAP_Code": sap_code,
            "U_Shopify_Store": store_key,
            "U_SAP_Type": "item",
            "U_CreateDT": datetime.now().strftime('%Y-%m-%d')
        }
        result = await sap_client.add_shopify_mapping(mapping_data)
        if result["msg"] == "failure":
            logger.error(f"Failed to write {shopify_type} mapping for {sap_code} -> {code} in {store_key}: {result.get('error')}")
        else:
            logger.info(f"Wrote {shopify_type} mapping for {sap_code} -> {code} in {store_key}")


# Create singleton instance
variant_operations_sync = VariantOperationsSync()
