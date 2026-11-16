"""Paystack checkout and signed-webhook boundary for organization billing."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from core.db.repositories import repository_connection
from core.platform.service import get_owned_organization, now_iso

PAYSTACK_API = "https://api.paystack.co"


class BillingError(RuntimeError):
    """Safe billing error suitable for an API response."""


def initialize_checkout(
    user_id: str, organization_id: str, plan: str, email: str
) -> dict[str, str]:
    organization = get_owned_organization(user_id, organization_id)
    if organization is None:
        raise LookupError("organization not found")
    plan_code = _plan_code(plan)
    secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "").strip()
    if not secret_key:
        raise BillingError("Paystack billing is not configured")
    if "@" not in email or len(email) > 254:
        raise ValueError("a valid billing email is required")
    if str(organization.get("plan")) != "free":
        raise BillingError("Plan changes for paid subscriptions must be managed with MIRA support")

    # Paystack references allow alphanumerics and - . =; keep generated references portable.
    reference = f"mira-{secrets.token_hex(24)}"
    now = now_iso()
    with repository_connection() as connection:
        expired_before = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        connection.execute(
            """UPDATE billing_checkouts SET status = 'expired', updated_at = ?
               WHERE organization_id = ? AND status = 'pending' AND created_at < ?""",
            (now, organization_id, expired_before),
        )
        pending = connection.execute(
            """SELECT reference, target_plan, authorization_url FROM billing_checkouts
               WHERE organization_id = ? AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (organization_id,),
        ).fetchone()
        if pending is not None:
            if str(pending["target_plan"]) != plan:
                raise BillingError("Another plan checkout is pending for this organization")
            if pending["authorization_url"]:
                return {
                    "authorization_url": str(pending["authorization_url"]),
                    "reference": str(pending["reference"]),
                }
            raise BillingError("The current Paystack checkout is still being initialized")
        connection.execute(
            """
            INSERT INTO billing_checkouts (
                reference, organization_id, target_plan, paystack_plan_code,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (reference, organization_id, plan, plan_code, now, now),
        )
    payload: dict[str, object] = {
        "email": email.strip(),
        "currency": str(organization.get("billing_currency") or "NGN"),
        "plan": plan_code,
        "reference": reference,
        "metadata": {"organization_id": organization_id, "mira_plan": plan},
    }
    callback_url = os.environ.get("PAYSTACK_CALLBACK_URL", "").strip()
    if callback_url:
        payload["callback_url"] = callback_url
    try:
        response = httpx.post(
            f"{PAYSTACK_API}/transaction/initialize",
            headers={"Authorization": f"Bearer {secret_key}"},
            json=payload,
            timeout=20.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as error:
        _mark_checkout_failed(reference)
        raise BillingError("Paystack checkout could not be initialized") from error
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(body, dict) or not body.get("status") or not isinstance(data, dict):
        _mark_checkout_failed(reference)
        raise BillingError("Paystack checkout could not be initialized")
    authorization_url = data.get("authorization_url")
    if not isinstance(authorization_url, str) or not authorization_url.startswith(
        "https://checkout.paystack.com/"
    ):
        _mark_checkout_failed(reference)
        raise BillingError("Paystack returned an invalid checkout URL")
    with repository_connection() as connection:
        connection.execute(
            """UPDATE billing_checkouts SET authorization_url = ?, updated_at = ?
               WHERE reference = ?""",
            (authorization_url, now_iso(), reference),
        )
    return {"authorization_url": authorization_url, "reference": reference}


def cancel_subscription(user_id: str, organization_id: str) -> dict[str, str]:
    organization = get_owned_organization(user_id, organization_id)
    if organization is None:
        raise LookupError("organization not found")
    subscription_code = organization.get("paystack_subscription_code")
    secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "").strip()
    if not secret_key:
        raise BillingError("Paystack billing is not configured")
    if not subscription_code:
        raise BillingError("This subscription cannot be cancelled through MIRA yet")
    try:
        response = httpx.get(
            f"{PAYSTACK_API}/subscription/{subscription_code}/manage/link",
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=20.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise BillingError("Paystack could not process the cancellation request") from error
    if not isinstance(body, dict) or not body.get("status"):
        raise BillingError("Paystack could not process the cancellation request")
    data = body.get("data") if isinstance(body, dict) else None
    link = data.get("link") if isinstance(data, dict) else None
    if not isinstance(link, str) or not link.startswith("https://paystack.com/manage/"):
        raise BillingError("Paystack returned an invalid subscription management URL")
    return {"status": "manage_subscription", "manage_url": link}


def verify_webhook_signature(raw_body: bytes, headers: Any) -> bool:
    """Verify current timestamped signatures or the legacy Paystack header."""
    signing_header = headers.get("Paystack-Signature")
    webhook_secret = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "").strip()
    if signing_header and webhook_secret:
        values: dict[str, list[str]] = {}
        for segment in str(signing_header).split(","):
            key, separator, value = segment.strip().partition("=")
            if separator:
                values.setdefault(key, []).append(value)
        timestamps = values.get("t", [])
        signatures = values.get("v1", [])
        if len(timestamps) != 1 or not signatures:
            return False
        try:
            timestamp = int(timestamps[0])
        except ValueError:
            return False
        if abs(int(datetime.now(UTC).timestamp()) - timestamp) > 300:
            return False
        expected = hmac.new(
            webhook_secret.encode(), timestamps[0].encode() + b"." + raw_body, hashlib.sha512
        ).hexdigest()
        if any(_constant_time_hex(expected, value.rpartition(":")[2]) for value in signatures):
            return True

    legacy_signature = headers.get("x-paystack-signature")
    secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "").strip()
    if not legacy_signature or not secret_key:
        return False
    expected = hmac.new(secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
    return _constant_time_hex(expected, str(legacy_signature))


def process_webhook(event: dict[str, object], raw_body: bytes) -> bool:
    """Idempotently apply a verified Paystack event; returns false for a duplicate."""
    event_type = str(event.get("event") or "")
    data = event.get("data")
    data = data if isinstance(data, dict) else {}
    reference = str(data.get("reference") or data.get("subscription_code") or data.get("id") or "")
    event_id = f"{event_type}:{reference or hashlib.sha256(raw_body).hexdigest()}"
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    now = now_iso()
    with repository_connection() as connection:
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO billing_webhook_events (
                event_id, event_type, payload_sha256, received_at
            ) VALUES (?, ?, ?, ?)
            """,
            (event_id, event_type, payload_hash, now),
        )
        if inserted.rowcount == 0:
            return False

        organization_id: str | None = None
        checkout = None
        if event_type == "charge.success" and reference:
            checkout = connection.execute(
                "SELECT * FROM billing_checkouts WHERE reference = ?",
                (reference,),
            ).fetchone()
            if checkout is not None:
                organization_id = str(checkout["organization_id"])
                customer = _dict(data.get("customer"))
                subscription = _dict(data.get("subscription"))
                with connection:
                    connection.execute(
                        """
                        UPDATE organizations SET
                            plan = ?, subscription_status = 'active',
                            paystack_customer_code = COALESCE(?, paystack_customer_code),
                            paystack_subscription_code = COALESCE(?, paystack_subscription_code),
                            paystack_plan_code = ?,
                            current_period_end = COALESCE(?, current_period_end),
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            str(checkout["target_plan"]),
                            _optional_str(customer.get("customer_code") or customer.get("code")),
                            _optional_str(
                                subscription.get("subscription_code") or subscription.get("code")
                            ),
                            str(checkout["paystack_plan_code"]),
                            _optional_str(subscription.get("next_payment_date")),
                            now,
                            organization_id,
                        ),
                    )
                    connection.execute(
                        """UPDATE billing_checkouts SET status = 'paid', updated_at = ?
                           WHERE reference = ?""",
                        (now, reference),
                    )
        if organization_id is None:
            organization_id = _organization_for_event(connection, data)
        if organization_id is not None and event_type != "charge.success":
            _apply_subscription_event(connection, organization_id, event_type, data, now)
        connection.execute(
            "UPDATE billing_webhook_events SET processed_at = ? WHERE event_id = ?",
            (now, event_id),
        )
    return True


def _apply_subscription_event(
    connection: Any,
    organization_id: str,
    event_type: str,
    data: dict[str, object],
    now: str,
) -> None:
    subscription = _dict(data.get("subscription"))
    subscription_code = _optional_str(
        data.get("subscription_code") or subscription.get("subscription_code")
    )
    period_end = _optional_str(data.get("next_payment_date"))
    if event_type == "invoice.payment_failed":
        connection.execute(
            """UPDATE organizations SET subscription_status = 'past_due', updated_at = ?
               WHERE id = ?""",
            (now, organization_id),
        )
    elif event_type == "subscription.not_renew":
        connection.execute(
            """UPDATE organizations SET subscription_status = 'cancelled',
               current_period_end = COALESCE(?, current_period_end), updated_at = ? WHERE id = ?""",
            (period_end, now, organization_id),
        )
    elif event_type == "subscription.disable":
        connection.execute(
            """UPDATE organizations SET plan = 'free', subscription_status = 'cancelled',
               paystack_subscription_code = NULL,
               updated_at = ? WHERE id = ?""",
            (now, organization_id),
        )
    elif event_type in {"subscription.create", "invoice.update", "charge.success"}:
        customer = _dict(data.get("customer"))
        plan = _dict(data.get("plan"))
        connection.execute(
            """UPDATE organizations SET subscription_status = 'active',
               paystack_subscription_code = COALESCE(?, paystack_subscription_code),
               paystack_customer_code = COALESCE(?, paystack_customer_code),
               paystack_plan_code = COALESCE(?, paystack_plan_code),
               current_period_end = COALESCE(?, current_period_end), updated_at = ? WHERE id = ?""",
            (
                subscription_code,
                _optional_str(customer.get("customer_code") or customer.get("code")),
                _optional_str(plan.get("plan_code") or plan.get("code")),
                period_end,
                now,
                organization_id,
            ),
        )


def _organization_for_event(connection: Any, data: dict[str, object]) -> str | None:
    customer = _dict(data.get("customer"))
    subscription = _dict(data.get("subscription"))
    customer_code = _optional_str(customer.get("customer_code") or customer.get("code"))
    subscription_code = _optional_str(
        data.get("subscription_code")
        or subscription.get("subscription_code")
        or subscription.get("code")
    )
    row = connection.execute(
        """SELECT id FROM organizations
           WHERE (? IS NOT NULL AND paystack_subscription_code = ?)
              OR (? IS NOT NULL AND paystack_customer_code = ?)
           LIMIT 1""",
        (subscription_code, subscription_code, customer_code, customer_code),
    ).fetchone()
    return None if row is None else str(row["id"])


def _plan_code(plan: str) -> str:
    env_name = {
        "developer": "PAYSTACK_DEVELOPER_PLAN_CODE",
        "pro": "PAYSTACK_PRO_PLAN_CODE",
        "scale": "PAYSTACK_SCALE_PLAN_CODE",
    }.get(plan)
    if env_name is None:
        raise ValueError("unsupported plan")
    code = os.environ.get(env_name, "").strip()
    if not code:
        raise BillingError(f"Paystack {plan} plan is not configured")
    return code


def _mark_checkout_failed(reference: str) -> None:
    with repository_connection() as connection:
        connection.execute(
            "UPDATE billing_checkouts SET status = 'failed', updated_at = ? WHERE reference = ?",
            (now_iso(), reference),
        )


def _constant_time_hex(expected: str, received: str) -> bool:
    if len(received) != 128 or any(char not in "0123456789abcdef" for char in received):
        return False
    return hmac.compare_digest(expected, received)


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
