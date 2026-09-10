"""
Refuse to start if another sync process is already running.

Two processes racing each other duplicate everything they write: both pass
check_order_exists_in_sap for the same new order before either has posted, so both
create an invoice and an incoming payment. Orders #10528, #10559 and #10560 were
invoiced twice this way on 23-24 Aug 2026, by which point four instances were live
at once - SAP's negative-inventory check is the only reason the rest of that day's
orders were not doubled too.

Binding a fixed loopback port is atomic and the OS drops it when the process dies,
so unlike a lock file there is nothing to clean up after a crash.
"""
import logging
import os
import socket
import sys

# Same name app/utils/logging configures, so this lands in sync.log without
# importing that module (kept dependency-free so the check runs anywhere).
logger = logging.getLogger("sync_service")

# Picked from the dynamic range; it is a lock, nothing ever listens on it.
LOCK_PORT = 50607

_lock = None


def claim_single_instance():
    """Exit(1) if another instance holds the lock. ALLOW_MULTIPLE_INSTANCES=1 bypasses."""
    global _lock
    if os.environ.get("ALLOW_MULTIPLE_INSTANCES") == "1" or _lock:
        return
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # no SO_REUSEADDR: the bind must fail
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        lock.close()
        logger.error("Another sync instance is already running - exiting to avoid duplicate documents")
        print("❌ Another sync instance is already running on this machine. Stop it first.")
        sys.exit(1)
    _lock = lock  # held for the life of the process
