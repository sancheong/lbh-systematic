#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: create_demo_repo.py /path/to/demo")
        return 2
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    w(root / "src/payments/checkout.py", """
from src.notifications.bus import notification_bus


def complete_checkout(order_id: str):
    order = {"id": order_id, "paid": True}
    emit_payment_succeeded(order)
    return order


def emit_payment_succeeded(order):
    notification_bus.publish({"type": "payment_succeeded", "order_id": order["id"]})
""".lstrip())
    w(root / "src/notifications/bus.py", """
class NotificationBus:
    def publish(self, event):
        return True

notification_bus = NotificationBus()
""".lstrip())
    w(root / "tests/test_checkout.py", """
from src.payments.checkout import complete_checkout


def test_complete_checkout():
    assert complete_checkout("ord_1")["paid"] is True
""".lstrip())
    w(root / "pyproject.toml", "[project]\nname='demo'\nversion='0.0.1'\n")
    subprocess.run(["git", "init"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
