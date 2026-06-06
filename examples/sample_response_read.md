```lbh-tool
{
  "type": "context_request",
  "requests": [
    {
      "op": "READ",
      "path": "src/payments/checkout.py",
      "ranges": [{"start": 1, "end": 120}],
      "why": "Need to inspect checkout completion flow."
    },
    {
      "op": "GREP",
      "pattern": "payment_succeeded|notification_bus|email",
      "globs": ["src/**", "tests/**"],
      "max_results": 40,
      "why": "Need all references to payment success notification."
    }
  ]
}
```
