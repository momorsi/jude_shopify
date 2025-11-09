"""
Script to extract order IDs that failed tag removal from the invoice processing section only
"""

import re
from pathlib import Path

log_file = Path("logs/sync.log")

if not log_file.exists():
    print("Log file not found!")
    exit(1)

# Read the log file
with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Find the MOST RECENT start of invoice processing section (last occurrence)
invoice_section_start = None
for i in range(len(lines) - 1, -1, -1):  # Search backwards
    if "Processing Invoices" in lines[i]:
        # Check if next line has separator
        if i + 1 < len(lines) and "=" in lines[i + 1]:
            invoice_section_start = i
            break

if invoice_section_start is None:
    print("Invoice processing section not found in log!")
    exit(1)

# Extract only the invoice processing section
invoice_section = lines[invoice_section_start:]

# Find all order IDs that had tag removal failures in invoice section
failed_orders = set()

# Look for "Processing Invoice" followed by "Shopify Order ID" and then "Failed to remove tags"
invoice_section_text = ''.join(invoice_section)

# Pattern 1: "Processing Invoice" -> "Shopify Order ID: XXXXX" -> "Failed to remove tags"
# Match invoice processing blocks
invoice_blocks = re.finditer(
    r'--- Processing Invoice \d+ ---.*?Shopify Order ID: (\d+).*?Failed to remove tags',
    invoice_section_text,
    re.DOTALL
)
for match in invoice_blocks:
    order_id = match.group(1)
    failed_orders.add(order_id)

# Pattern 2: Direct "Failed to remove tags from order gid://shopify/Order/XXXXX" in invoice section
pattern2 = r'Failed to remove tags from order gid://shopify/Order/(\d+)'
matches = re.findall(pattern2, invoice_section_text)
failed_orders.update(matches)

# Pattern 3: "Removing tags from Shopify order XXXXX" followed by failure in invoice section
pattern3 = r'Removing tags from Shopify order (\d+).*?Failed to remove tags'
matches = re.findall(pattern3, invoice_section_text, re.DOTALL)
failed_orders.update(matches)

# Sort and print
if failed_orders:
    print("=" * 80)
    print(f"Orders with tag removal failures (from invoice processing only): {len(failed_orders)}")
    print("=" * 80)
    for order_id in sorted(failed_orders):
        print(order_id)
    print("=" * 80)
    print(f"\nTotal: {len(failed_orders)} orders")
else:
    print("No orders with tag removal failures found in invoice processing section.")

