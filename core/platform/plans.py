"""Central plan definitions for the MIRA developer platform."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import TypedDict


class Plan(TypedDict):
    name: str
    monthly_price_minor: int | None
    currency: str
    memory_writes_monthly: int
    retrievals_monthly: int
    projects: int
    api_keys: int
    rate_limit_per_minute: int


_DEFAULT_PLANS: dict[str, Plan] = {
    "free": {
        "name": "Free",
        "monthly_price_minor": 0,
        "currency": "NGN",
        "memory_writes_monthly": 5_000,
        "retrievals_monthly": 25_000,
        "projects": 1,
        "api_keys": 3,
        "rate_limit_per_minute": 60,
    },
    "developer": {
        "name": "Developer",
        "monthly_price_minor": 1_500_000,
        "currency": "NGN",
        "memory_writes_monthly": 25_000,
        "retrievals_monthly": 150_000,
        "projects": 5,
        "api_keys": 10,
        "rate_limit_per_minute": 300,
    },
    "pro": {
        "name": "Pro",
        "monthly_price_minor": 6_000_000,
        "currency": "NGN",
        "memory_writes_monthly": 150_000,
        "retrievals_monthly": 1_000_000,
        "projects": 20,
        "api_keys": 50,
        "rate_limit_per_minute": 1_000,
    },
    "scale": {
        "name": "Scale",
        "monthly_price_minor": None,
        "currency": "NGN",
        "memory_writes_monthly": 1_000_000,
        "retrievals_monthly": 10_000_000,
        "projects": 100,
        "api_keys": 500,
        "rate_limit_per_minute": 3_000,
    },
}


def plans() -> dict[str, Plan]:
    """Return defaults with optional numeric limit overrides from JSON environment config."""
    configured = deepcopy(_DEFAULT_PLANS)
    raw = os.environ.get("MIRA_PLAN_LIMITS_JSON", "").strip()
    if not raw:
        return configured
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("MIRA_PLAN_LIMITS_JSON must contain a JSON object") from error
    if not isinstance(overrides, dict):
        raise ValueError("MIRA_PLAN_LIMITS_JSON must contain a JSON object")
    for plan_name, plan_values in overrides.items():
        if plan_name not in configured or not isinstance(plan_values, dict):
            continue
        for field in (
            "memory_writes_monthly",
            "retrievals_monthly",
            "projects",
            "api_keys",
            "rate_limit_per_minute",
        ):
            if field in plan_values:
                value = plan_values[field]
                if not isinstance(value, int) or value < 1:
                    raise ValueError(f"plan limit {plan_name}.{field} must be a positive integer")
                configured[plan_name][field] = value
    return configured


def plan_for(name: str) -> Plan:
    """Resolve a plan, falling back to the safe free tier for unknown stored values."""
    return plans().get(name, plans()["free"])
