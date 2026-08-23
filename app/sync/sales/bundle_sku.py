"""
Bundle SKU splitting for combo variants.

Shopify sells pendant+chain / pendant+cord combos as a single variant whose SKU is a
comma-separated list of the SAP item codes it contains (e.g. "MOD-0000007,FG-0000909").
SAP has no such item, so every document line built from one of these SKUs must be
expanded into one line per component.

Shopify only gives us the combined price, so the line total is split across the
components in the ratio of their SAP price-list prices (list 1 for local / EGP,
list 7 for international / USD, per configurations.json). The last component absorbs
the rounding remainder so the split always adds back up to what the customer paid.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Tuple

from app.core.config import config_settings
from app.services.sap.client import sap_client
from app.utils.logging import logger

# (item_code, price_list) -> price. Prices change rarely and a sync run is short-lived.
# ponytail: process-lifetime cache, add TTL/invalidation if a run ever spans a price update.
_price_cache: Dict[Tuple[str, int], Decimal] = {}

_CENT = Decimal("0.01")


def is_bundle(sku: Any) -> bool:
    """True if this SKU packs more than one SAP item code."""
    return bool(sku) and "," in str(sku)


def split_sku(sku: Any) -> List[str]:
    """["MOD-0000007", "FG-0000909"] — a plain SKU yields a single-element list."""
    return [code.strip() for code in str(sku or "").split(",") if code.strip()]


def _price_list_for(store_key: str) -> int:
    store = config_settings.get_store_by_name(store_key)
    return getattr(store, "price_list", 1) if store else 1


def _collect_skus(order_node: Dict[str, Any]) -> Iterable[str]:
    for item_edge in order_node.get("lineItems", {}).get("edges", []):
        item = item_edge.get("node", {})
        sku = item.get("sku") or (item.get("variant") or {}).get("sku")
        if sku:
            yield sku


async def prefetch_prices(order_node: Dict[str, Any], store_key: str) -> None:
    """Warm the price cache for every bundle component in an order, in one SAP call.

    Best-effort: a failure here is not fatal, split_line() raises later if a price
    it needs is genuinely unavailable.
    """
    price_list = _price_list_for(store_key)
    codes = {
        code
        for sku in _collect_skus(order_node)
        if is_bundle(sku)
        for code in split_sku(sku)
    }
    missing = sorted(code for code in codes if (code, price_list) not in _price_cache)
    if not missing:
        return

    filter_query = " or ".join(f"ItemCode eq '{code}'" for code in missing)
    result = await sap_client._make_request(
        "GET", "Items",
        params={"$filter": filter_query, "$select": "ItemCode,ItemPrices"}
    )
    if result.get("msg") != "success":
        logger.error(f"Failed to load SAP prices for bundle components {missing}: {result.get('error')}")
        return

    for item in (result.get("data") or {}).get("value", []):
        for entry in item.get("ItemPrices", []):
            if entry.get("PriceList") == price_list:
                _price_cache[(item["ItemCode"], price_list)] = Decimal(str(entry.get("Price") or 0))

    logger.info(f"Loaded SAP price list {price_list} for bundle components: {missing}")


def split_line(sku: Any, unit_price: Decimal, store_key: str) -> List[Tuple[str, Decimal, Decimal]]:
    """Split one line into [(item_code, unit_price, share)] — one tuple per component.

    `share` is the component's fraction of the line, for splitting amount fields that
    ride alongside the price (discount amounts). Percentages need no splitting.

    A plain (non-bundle) SKU comes back unchanged as a single component with share 1.
    Raises ValueError if a component's SAP price is unavailable, so the caller fails the
    document loudly rather than posting a wrong split.
    """
    codes = split_sku(sku)
    if len(codes) <= 1:
        return [(codes[0] if codes else str(sku), Decimal(unit_price), Decimal(1))]

    price_list = _price_list_for(store_key)
    prices = [_price_cache.get((code, price_list)) for code in codes]
    if any(price is None for price in prices):
        unknown = [code for code, price in zip(codes, prices) if price is None]
        raise ValueError(
            f"No SAP price list {price_list} entry for bundle component(s) {unknown} of SKU '{sku}'"
        )

    reference_total = sum(prices)
    if reference_total <= 0:
        raise ValueError(
            f"SAP price list {price_list} totals {reference_total} for bundle SKU '{sku}' - cannot split"
        )

    unit_price = Decimal(unit_price)
    lines: List[Tuple[str, Decimal, Decimal]] = []
    allocated = Decimal(0)
    for index, (code, price) in enumerate(zip(codes, prices)):
        share = price / reference_total
        if index == len(codes) - 1:
            component_price = unit_price - allocated  # absorbs the rounding remainder
        else:
            component_price = (unit_price * share).quantize(_CENT, rounding=ROUND_HALF_UP)
            allocated += component_price
        lines.append((code, component_price, share))

    logger.info(
        f"Split bundle SKU '{sku}' @ {unit_price} into "
        + ", ".join(f"{code}={price}" for code, price, _ in lines)
    )
    return lines


def demo():
    """Self-check: run with `python -m app.sync.sales.bundle_sku`."""
    _price_cache[("MOD-0000007", 1)] = Decimal("1500")
    _price_cache[("FG-0000909", 1)] = Decimal("3900")

    # Plain SKU passes through untouched.
    assert split_line("FG-0000909", Decimal("3900"), "local") == [("FG-0000909", Decimal("3900"), Decimal(1))]

    # Bundle at list price splits into the exact component prices.
    split = split_line("MOD-0000007,FG-0000909", Decimal("5400"), "local")
    assert [(c, p) for c, p, _ in split] == [("MOD-0000007", Decimal("1500")), ("FG-0000909", Decimal("3900"))], split

    # Discounted bundle still adds back up to what was paid.
    for paid in ("4860", "5400", "0.03", "1234.57", "999.99"):
        split = split_line("MOD-0000007,FG-0000909", Decimal(paid), "local")
        assert sum(p for _, p, _ in split) == Decimal(paid), (paid, split)

    # Order of the codes in the SKU does not matter.
    reversed_split = split_line("FG-0000909,MOD-0000007", Decimal("5400"), "local")
    assert dict((c, p) for c, p, _ in reversed_split) == {"MOD-0000007": Decimal("1500"), "FG-0000909": Decimal("3900")}

    # An unpriced component fails loudly instead of guessing.
    try:
        split_line("MOD-0000007,FG-9999999", Decimal("5400"), "local")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unpriced component")

    print("bundle_sku demo OK")


if __name__ == "__main__":
    demo()
