"""Price alerts CRUD + trigger evaluation.

Alerts are scoped to the active profile's database (same as transactions).
When `evaluate_alerts()` runs after a price refresh, any alert whose
threshold has been crossed gets `triggered=True`; the frontend's bell badge
then shows the count of triggered-but-not-dismissed alerts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import delete, insert, select, update

from backend import db, market_data
from backend._time import utcnow_naive as _now
from backend.models import PriceAlert, PriceAlertCreate


def list_alerts(include_dismissed: bool = False) -> list[PriceAlert]:
    """List every price alert for the active profile. With include_dismissed=False (default), exclude alerts the user has acknowledged."""
    engine = db.get_engine()
    stmt = select(db.price_alerts).order_by(db.price_alerts.c.created_at.desc())
    if not include_dismissed:
        stmt = stmt.where(db.price_alerts.c.dismissed == 0)
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    out: list[PriceAlert] = []
    for r in rows:
        # Best-effort current price (from cache only — don't go online here).
        q = market_data.get_quote(r["ticker"], max_age_minutes=24 * 60)
        out.append(
            PriceAlert(
                id=r["id"],
                ticker=r["ticker"],
                alert_type=r["alert_type"],
                target_price=r["target_price"],
                currency=r["currency"],
                triggered=bool(r["triggered"]),
                triggered_at=r["triggered_at"],
                dismissed=bool(r["dismissed"]),
                created_at=r["created_at"],
                current_price=q.price,
            )
        )
    return out


def create_alert(req: PriceAlertCreate) -> PriceAlert:
    """Persist a new price alert. Returns the saved row with its assigned id."""
    engine = db.get_engine()
    now = _now()
    with engine.begin() as conn:
        result = conn.execute(
            insert(db.price_alerts).values(
                ticker=req.ticker.upper(),
                alert_type=req.alert_type,
                target_price=float(req.target_price),
                currency=req.currency,
                triggered=0,
                triggered_at=None,
                dismissed=0,
                created_at=now,
            )
        )
        new_id = int(result.inserted_primary_key[0])
    return PriceAlert(
        id=new_id,
        ticker=req.ticker.upper(),
        alert_type=req.alert_type,
        target_price=float(req.target_price),
        currency=req.currency,
        triggered=False,
        triggered_at=None,
        dismissed=False,
        created_at=now,
    )


def delete_alert(alert_id: int) -> bool:
    """Permanently remove an alert by id. Returns True if a row was deleted."""
    engine = db.get_engine()
    with engine.begin() as conn:
        result = conn.execute(delete(db.price_alerts).where(db.price_alerts.c.id == alert_id))
    return result.rowcount > 0


def dismiss_alert(alert_id: int) -> bool:
    """Mark an alert as dismissed without deleting the row. Returns True if the alert existed."""
    engine = db.get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            update(db.price_alerts)
            .where(db.price_alerts.c.id == alert_id)
            .values(dismissed=1)
        )
    return result.rowcount > 0


def evaluate_alerts() -> list[PriceAlert]:
    """Check every active alert against the latest cached price. Mark crossed
    alerts as triggered. Returns the list of newly-triggered alerts."""
    engine = db.get_engine()
    stmt = (
        select(db.price_alerts)
        .where(db.price_alerts.c.dismissed == 0)
        .where(db.price_alerts.c.triggered == 0)
    )
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    newly_triggered: list[PriceAlert] = []
    now = _now()
    for r in rows:
        q = market_data.get_quote(r["ticker"], max_age_minutes=24 * 60)
        if q.price is None:
            continue
        crossed = (
            (r["alert_type"] == "above" and q.price >= r["target_price"]) or
            (r["alert_type"] == "below" and q.price <= r["target_price"])
        )
        if not crossed:
            continue
        with engine.begin() as conn:
            conn.execute(
                update(db.price_alerts)
                .where(db.price_alerts.c.id == r["id"])
                .values(triggered=1, triggered_at=now)
            )
        newly_triggered.append(
            PriceAlert(
                id=r["id"],
                ticker=r["ticker"],
                alert_type=r["alert_type"],
                target_price=r["target_price"],
                currency=r["currency"],
                triggered=True,
                triggered_at=now,
                dismissed=False,
                created_at=r["created_at"],
                current_price=q.price,
            )
        )
    return newly_triggered
