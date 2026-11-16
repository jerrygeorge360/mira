# Developer plans and billing

Plan defaults are centralized in `core/platform/plans.py`; numeric limits can be overridden with `MIRA_PLAN_LIMITS_JSON`. Prices shown by MIRA are Free (₦0), Developer (₦15,000/month), Pro (₦60,000/month), and Scale (contact MIRA). NGN is represented in kobo internally.

Create matching monthly NGN plans in Paystack and configure their plan codes. MIRA never hard-codes Paystack plan IDs:

```env
PAYSTACK_SECRET_KEY=
PAYSTACK_PUBLIC_KEY=
PAYSTACK_WEBHOOK_SECRET=
PAYSTACK_DEVELOPER_PLAN_CODE=
PAYSTACK_PRO_PLAN_CODE=
PAYSTACK_SCALE_PLAN_CODE=
```

Set these in Coolify's environment variables for the API service. Keep both secret values server-side; the frontend only initiates a backend request. Scale checkout remains unavailable until it is configured.

The backend initializes Paystack checkout with the server-selected plan code and a MIRA-generated transaction reference. The hosted checkout callback is informational; only a verified Paystack webhook can activate or change an organization's plan. MIRA handles `charge.success`, subscription creation, failed invoices, non-renewal, and subscription disable events. Webhook processing is idempotent and stores only an event identifier, type, payload digest, and processing timestamps.

For current webhook signing, configure Paystack's webhook signing secret in `PAYSTACK_WEBHOOK_SECRET`. MIRA verifies the timestamped `Paystack-Signature` over the raw body and rejects timestamps outside five minutes. During legacy Paystack integrations, MIRA also accepts `x-paystack-signature` using `PAYSTACK_SECRET_KEY`. Do not disable Paystack signing or send parsed/reserialized JSON for validation.

To cancel, MIRA asks Paystack for its hosted subscription management link. The customer confirms cancellation there; MIRA changes the subscription state only after Paystack sends the corresponding webhook. MIRA does not receive or store card details.

Official references: [Initialize a transaction with a plan code](https://paystack.com/docs/api/transaction/), [webhook signing and events](https://paystack.com/docs/payments/webhooks/), and [Paystack subscriptions](https://paystack.com/docs/payments/subscriptions/).
