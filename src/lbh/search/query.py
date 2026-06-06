from __future__ import annotations

import re

DOMAIN_TERMS = {
    "결제": ["payment", "billing", "checkout", "charge", "invoice", "order", "paid", "transaction", "subscription"],
    "알림": ["notification", "notify", "email", "sms", "push", "message", "receipt", "template", "provider"],
    "로그인": ["login", "signin", "auth", "session", "token", "oauth", "jwt", "credential"],
    "권한": ["permission", "role", "policy", "access", "acl", "rbac", "authorize"],
    "대시보드": ["dashboard", "analytics", "metric", "chart", "summary", "widget"],
    "안": ["fail", "failed", "missing", "skipped", "not", "error", "exception", "retry"],
    "안가": ["not sent", "failed", "missing", "skipped", "retry", "queue", "worker"],
    "안 가": ["not sent", "failed", "missing", "skipped", "retry", "queue", "worker"],
    "메일": ["email", "mail", "smtp", "provider", "template"],
    "큐": ["queue", "job", "worker", "task", "retry", "dead_letter"],
    "웹훅": ["webhook", "callback", "event", "listener"],
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_가-힣]{2,}")


def split_identifier(token: str) -> list[str]:
    pieces = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token).replace("_", "-").replace("/", "-").split("-")
    return [p.lower() for p in pieces if len(p) >= 2]


def expand_query(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        low = t.lower().strip()
        if low and low not in seen:
            seen.add(low)
            terms.append(low)

    for m in TOKEN_RE.finditer(query):
        token = m.group(0)
        add(token)
        for piece in split_identifier(token):
            add(piece)

    for key, aliases in DOMAIN_TERMS.items():
        if key in query:
            add(key)
            for alias in aliases:
                for piece in alias.split():
                    add(piece)

    return terms
