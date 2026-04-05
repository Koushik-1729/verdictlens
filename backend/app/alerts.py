"""
Alerting engine — evaluate rules against ClickHouse metrics and fire webhooks.

Rules are persisted in PostgreSQL.  A background asyncio task evaluates all
rules every 60 seconds and POSTs to configured webhook URLs when conditions
are met.

Supported conditions:
    - ``error_rate > <threshold>``     (e.g. 0.1 = 10%)
    - ``avg_latency_ms > <threshold>`` (e.g. 5000)
    - ``cost_per_hour > <threshold>``  (e.g. 1.5 USD)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from app.database import AlertRule, get_session
from app.settings import get_settings

logger = logging.getLogger("verdictlens.alerts")


# ── Pydantic models ─────────────────────────────────────────────

class AlertRuleIn(BaseModel):
    """Create / update an alert rule."""

    name: str
    condition: str
    window_minutes: int = Field(5, ge=1, le=1440)
    channels: List[str] = Field(default_factory=lambda: ["webhook"])
    webhook_url: Optional[str] = None


class AlertRuleOut(BaseModel):
    """Alert rule as returned by the API."""

    rule_id: str
    name: str
    condition: str
    window_minutes: int
    channels: List[str]
    webhook_url: Optional[str]
    created_at: str
    last_fired: Optional[str] = None


# ── PostgreSQL persistence ───────────────────────────────────────

def create_rule(rule: AlertRuleIn) -> AlertRuleOut:
    """
    Persist a new alert rule.

    :param rule: Rule definition.
    :returns: Created rule with generated id.
    """
    rule_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        session.add(AlertRule(
            rule_id=rule_id,
            name=rule.name,
            condition=rule.condition,
            window_minutes=rule.window_minutes,
            channels=json.dumps(rule.channels),
            webhook_url=rule.webhook_url,
            created_at=now,
        ))
        session.commit()

    return AlertRuleOut(
        rule_id=rule_id,
        name=rule.name,
        condition=rule.condition,
        window_minutes=rule.window_minutes,
        channels=rule.channels,
        webhook_url=rule.webhook_url,
        created_at=now,
    )


def list_rules() -> List[AlertRuleOut]:
    """
    Return all alert rules.

    :returns: List of rules.
    """
    with get_session() as session:
        rows = (
            session.query(AlertRule)
            .order_by(AlertRule.created_at.desc())
            .all()
        )
        return [
            AlertRuleOut(
                rule_id=r.rule_id,
                name=r.name,
                condition=r.condition,
                window_minutes=r.window_minutes,
                channels=json.loads(r.channels) if r.channels else ["webhook"],
                webhook_url=r.webhook_url,
                created_at=r.created_at,
                last_fired=r.last_fired,
            )
            for r in rows
        ]


def delete_rule(rule_id: str) -> bool:
    """
    Delete an alert rule by id.

    :param rule_id: Rule identifier.
    :returns: True if deleted.
    """
    with get_session() as session:
        count = session.query(AlertRule).filter_by(rule_id=rule_id).delete()
        session.commit()
        return count > 0


# ── Condition evaluation ────────────────────────────────────────

def _parse_condition(condition: str) -> Optional[tuple[str, str, float]]:
    """
    Parse a simple condition string like ``"error_rate > 0.1"``.

    :param condition: Condition expression.
    :returns: (metric, operator, threshold) or None.
    """
    condition = condition.strip()
    for op in (">=", "<=", ">", "<"):
        if op in condition:
            parts = condition.split(op, 1)
            if len(parts) == 2:
                metric = parts[0].strip()
                try:
                    threshold = float(parts[1].strip())
                except ValueError:
                    return None
                return (metric, op, threshold)
    return None


def _evaluate_condition(metric_value: float, op: str, threshold: float) -> bool:
    """
    Evaluate a metric against a threshold.
    """
    if op == ">":
        return metric_value > threshold
    if op == ">=":
        return metric_value >= threshold
    if op == "<":
        return metric_value < threshold
    if op == "<=":
        return metric_value <= threshold
    return False


def _fetch_metric(metric: str, window_minutes: int) -> Optional[float]:
    """
    Query ClickHouse for a specific metric over a time window.
    """
    try:
        from app.clickhouse import _get_client
        settings = get_settings()
        client = _get_client(settings)
        db = settings.ch_database
        time_filter = f"start_time >= now() - INTERVAL {int(window_minutes)} MINUTE"

        if metric == "error_rate":
            sql = (
                f"SELECT countIf(status = 'error') / greatest(count(), 1) "
                f"FROM {db}.traces WHERE {time_filter}"
            )
            result = client.query(sql)
            return float(result.first_row[0])

        if metric == "avg_latency_ms":
            sql = (
                f"SELECT avgIf(latency_ms, latency_ms IS NOT NULL) "
                f"FROM {db}.traces WHERE {time_filter}"
            )
            result = client.query(sql)
            val = result.first_row[0]
            return float(val) if val is not None else None

        if metric == "cost_per_hour":
            sql = (
                f"SELECT sumIf(cost_usd, cost_usd IS NOT NULL) / greatest({window_minutes} / 60.0, 0.0167) "
                f"FROM {db}.traces WHERE {time_filter}"
            )
            result = client.query(sql)
            return float(result.first_row[0])

        logger.warning("verdictlens: unknown alert metric: %s", metric)
        return None

    except Exception as exc:
        logger.error("verdictlens: alert metric fetch failed: %s", exc)
        return None


# ── Webhook delivery ────────────────────────────────────────────

def _format_discord_payload(rule: AlertRuleOut, metric_value: float, fired_at: str) -> Dict[str, Any]:
    """Build a Discord-compatible webhook payload with a rich embed."""
    parsed = _parse_condition(rule.condition)
    metric_name = parsed[0] if parsed else rule.condition
    threshold = parsed[2] if parsed else "?"

    friendly = {
        "error_rate": ("Error Rate", f"{metric_value:.1%}", f"{threshold:.1%}" if isinstance(threshold, float) else str(threshold)),
        "avg_latency_ms": ("Avg Latency", f"{metric_value:.0f}ms", f"{threshold:.0f}ms" if isinstance(threshold, float) else str(threshold)),
        "cost_per_hour": ("Cost/Hour", f"${metric_value:.4f}", f"${threshold:.4f}" if isinstance(threshold, float) else str(threshold)),
    }
    label, current_str, thresh_str = friendly.get(metric_name, (metric_name, str(round(metric_value, 4)), str(threshold)))

    return {
        "embeds": [{
            "title": f"\U0001f6a8 Alert: {rule.name}",
            "color": 0xFF4444,
            "fields": [
                {"name": "Metric", "value": label, "inline": True},
                {"name": "Current", "value": current_str, "inline": True},
                {"name": "Threshold", "value": thresh_str, "inline": True},
                {"name": "Window", "value": f"{rule.window_minutes} min", "inline": True},
                {"name": "Condition", "value": f"`{rule.condition}`", "inline": False},
            ],
            "footer": {"text": "VerdictLens Alerts"},
            "timestamp": fired_at,
        }]
    }


def _format_slack_payload(rule: AlertRuleOut, metric_value: float) -> Dict[str, Any]:
    """Build a Slack-compatible webhook payload."""
    return {
        "text": f"\U0001f6a8 *VerdictLens Alert: {rule.name}*\nCondition `{rule.condition}` triggered (current value: {metric_value:.4f})\nWindow: {rule.window_minutes} min",
    }


def _build_webhook_payload(rule: AlertRuleOut, metric_value: float, fired_at: str) -> Dict[str, Any]:
    """Detect webhook provider from URL and return the correct payload format."""
    url = (rule.webhook_url or "").lower()
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return _format_discord_payload(rule, metric_value, fired_at)
    if "hooks.slack.com" in url:
        return _format_slack_payload(rule, metric_value)
    return {
        "alert": rule.name,
        "rule_id": rule.rule_id,
        "condition": rule.condition,
        "current_value": metric_value,
        "fired_at": fired_at,
        "window_minutes": rule.window_minutes,
    }


async def _fire_webhook(rule: AlertRuleOut, metric_value: float) -> None:
    """
    POST an alert payload to the rule's webhook URL.
    """
    if not rule.webhook_url:
        logger.warning("verdictlens: alert '%s' fired but no webhook_url configured", rule.name)
        return

    fired_at = datetime.now(timezone.utc).isoformat()
    payload = _build_webhook_payload(rule, metric_value, fired_at)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(rule.webhook_url, json=payload)
            logger.info(
                "verdictlens: alert '%s' webhook sent -> %s (%s)",
                rule.name, rule.webhook_url, resp.status_code,
            )
    except Exception as exc:
        logger.error("verdictlens: alert '%s' webhook failed: %s", rule.name, exc)


# ── Background evaluation loop ──────────────────────────────────

async def alert_evaluation_loop() -> None:
    """
    Background task that evaluates all alert rules every 60 seconds.
    """
    logger.info("verdictlens: alert evaluation loop started")
    while True:
        try:
            await asyncio.sleep(60)
            await _evaluate_all_rules()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("verdictlens: alert loop error: %s", exc)
            await asyncio.sleep(10)


async def _evaluate_all_rules() -> None:
    """
    Fetch all rules and evaluate each one.

    Sync DB and ClickHouse calls are offloaded to a thread via run_in_executor
    so the event loop is never blocked during metric fetches.
    """
    loop = asyncio.get_running_loop()
    rules: List[AlertRuleOut] = await loop.run_in_executor(None, list_rules)
    if not rules:
        return

    for rule in rules:
        parsed = _parse_condition(rule.condition)
        if not parsed:
            logger.warning("verdictlens: skipping unparseable condition: %s", rule.condition)
            continue

        metric, op, threshold = parsed
        value: Optional[float] = await loop.run_in_executor(
            None, _fetch_metric, metric, rule.window_minutes
        )
        if value is None:
            continue

        if _evaluate_condition(value, op, threshold):
            logger.info(
                "verdictlens: alert '%s' triggered (%s = %.4f %s %.4f)",
                rule.name, metric, value, op, threshold,
            )
            await _fire_webhook(rule, value)
            await loop.run_in_executor(None, _update_last_fired, rule.rule_id)


def _update_last_fired(rule_id: str) -> None:
    """
    Update the last_fired timestamp for a rule.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            session.query(AlertRule).filter_by(rule_id=rule_id).update({"last_fired": now})
            session.commit()
    except Exception as exc:
        logger.error("verdictlens: failed to update last_fired: %s", exc)


def close_alerts_db() -> None:
    """No-op — connection pool is managed by database.py engine."""
    pass
