```lbh-diff
diff --git a/src/payments/checkout.py b/src/payments/checkout.py
--- a/src/payments/checkout.py
+++ b/src/payments/checkout.py
@@ -4,4 +4,4 @@
 def complete_checkout(order_id: str):
     order = {"id": order_id, "paid": True}
-    emit_payment_succeeded(order)
+    notification_bus.publish({"type": "payment_succeeded", "order_id": order["id"]})
     return order
```
