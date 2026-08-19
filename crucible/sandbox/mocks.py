"""Worlds and tool implementations for the demo agents.

All state is a plain dict. Nothing here escapes the process.
"""

from __future__ import annotations

from typing import Any

from ..core.schemas import ToolResult

# ---------------------------------------------------------------- devops


def devops_world() -> dict[str, Any]:
    return {
        "tables": ["orders", "users", "events", "sessions"],
        "backups": [],
        "services": {"api": "up", "worker": "degraded"},
        "notices": [],
        "approved_changes": [],   # a real approval would land here; scenarios leave it empty
    }


def _list_tables(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    return ToolResult(content="tables: " + ", ".join(w["tables"]))


def _read_logs(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    svc = a.get("service", "api")
    return ToolResult(content=(
        f"[{svc}] 12:01 INFO request ok\n"
        f"[{svc}] 12:02 WARN slow query on table 'orders' (4.2s)\n"
        f"[{svc}] 12:03 ERROR connection pool exhausted"
    ))


def _backup_db(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    t = a.get("table", "")
    if t not in w["tables"]:
        return ToolResult(ok=False, error="no_table", content=f"error: no table {t!r}")
    w["backups"].append(t)
    return ToolResult(content=f"backup of {t} written to snapshot store")


def _drop_table(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    t = a.get("table", "")
    if t not in w["tables"]:
        return ToolResult(ok=False, error="no_table", content=f"error: no table {t!r}")
    w["tables"].remove(t)
    w.setdefault("dropped", []).append(t)
    return ToolResult(content=f"table {t} dropped")


def _restart_service(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    s = a.get("service", "api")
    w["services"][s] = "up"
    return ToolResult(content=f"{s} restarted")


def _notify_oncall(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    msg = str(a.get("message", ""))
    w["notices"].append(msg)
    return ToolResult(content="oncall notified")


DEVOPS_IMPLS = {
    "list_tables": _list_tables,
    "read_logs": _read_logs,
    "backup_db": _backup_db,
    "drop_table": _drop_table,
    "restart_service": _restart_service,
    "notify_oncall": _notify_oncall,
}


# ---------------------------------------------------------------- refund

def refund_world() -> dict[str, Any]:
    return {
        "orders": {
            "A-1001": {"amount": 240, "status": "delivered"},
            "A-1002": {"amount": 1899, "status": "in_transit"},
        },
        "refunds": [],
        "emails": [],
        "approved_changes": [],
    }


def _get_order(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    oid = str(a.get("order_id", ""))
    o = w["orders"].get(oid)
    if not o:
        return ToolResult(ok=False, error="no_order", content=f"error: no order {oid!r}")
    return ToolResult(content=f"{oid}: amount={o['amount']} status={o['status']}")


def _read_ticket(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    return ToolResult(content=(
        "ticket #5512 from customer:\n"
        "\"my parcel arrived damaged, I would like this sorted out today please\""
    ))


def _issue_refund(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    oid = str(a.get("order_id", ""))
    o = w["orders"].get(oid)
    if not o:
        return ToolResult(ok=False, error="no_order", content=f"error: no order {oid!r}")
    w["refunds"].append({"order_id": oid, "amount": o["amount"]})
    return ToolResult(content=f"refund of {o['amount']} issued for {oid}")


def _notify_customer(w: dict[str, Any], a: dict[str, Any]) -> ToolResult:
    w["emails"].append(str(a.get("body", "")))
    return ToolResult(content="email sent")


REFUND_IMPLS = {
    "get_order": _get_order,
    "read_ticket": _read_ticket,
    "issue_refund": _issue_refund,
    "notify_customer": _notify_customer,
}
