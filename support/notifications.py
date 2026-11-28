"""Notification payload builders for ApexVoice operations.

PURE BUILDERS. Nothing in this module sends anything. Each builder
returns a payload dict shaped for the existing Harbour & Main email
infrastructure: Resend sending from the harbourandmain.com domain, the
same infrastructure used for Harbour & Main outreach. Service mail uses
the from identity josh@harbourandmain.com.

To send for real, a future backend step must wire these payloads to
that Resend sender. That wiring is a separate, approved change. During
all testing, payloads are built and inspected only, and no customer
communication is sent. See docs/commercial/SUPPORT_AND_OPERATIONS.md.

Suppression rules, enforced by NotificationLedger:

* Provider outage notices deduplicate per incident id. A second build
  for the same incident id returns None.
* Usage threshold warnings fire once per tenant, per billing period,
  per threshold (80 and 100 percent). A repeat build returns None.
* Failed call alerts fire once per tenant per window key.
* Monthly summaries and payment failure notices are built per event by
  the caller and are not ledger suppressed here; their callers run them
  once per period or once per verified billing event.
"""

try:
    from billing.state import DEFAULT_GRACE_DAYS
except ImportError:  # pragma: no cover, billing package expected on the path
    DEFAULT_GRACE_DAYS = 7

FROM_IDENTITY = "josh@harbourandmain.com"
SENDER_DOMAIN = "harbourandmain.com"

USAGE_THRESHOLDS_PERCENT = (80, 100)
DEFAULT_FAILED_CALL_THRESHOLD = 3


class NotificationLedger:
    """Records which notifications have already been built, so repeat
    builds for the same event are suppressed instead of duplicated."""

    def __init__(self):
        self._keys = set()

    def seen(self, key):
        return key in self._keys

    def record(self, key):
        self._keys.add(key)

    def build_once(self, key):
        """Return True the first time a key is presented, False after."""
        if key in self._keys:
            return False
        self._keys.add(key)
        return True


def _payload(kind, tenant_id, to, subject, body, meta=None):
    return {
        "kind": kind,
        "tenant_id": tenant_id,
        "from": FROM_IDENTITY,
        "from_domain": SENDER_DOMAIN,
        "to": list(to),
        "subject": subject,
        "body": body,
        "meta": meta or {},
    }


def provider_outage_notice(tenant_id, business_name, recipients, incident,
                           ledger):
    """Notice that a provider outage is affecting the tenant's service.

    incident is a dict with incident_id, provider, summary, and
    optionally started_at and status. Suppressed per incident id.
    """
    incident_id = incident.get("incident_id", "")
    key = ("provider_outage", tenant_id, incident_id)
    if not ledger.build_once(key):
        return None
    provider = incident.get("provider", "a service provider")
    summary = incident.get("summary", "")
    started = incident.get("started_at", "")
    body = (
        f"Hello {business_name},\n\n"
        f"We are writing about a service problem affecting your ApexVoice "
        f"receptionist. Our provider {provider} is experiencing an outage"
        + (f" that began at {started}" if started else "")
        + f".\n\n{summary}\n\n"
        "While this lasts, some calls may not be answered by the "
        "receptionist. Callers who cannot reach the receptionist should "
        "call your main business number directly. We will write again "
        "when the provider confirms service is restored.\n\n"
        "Harbour & Main, ApexVoice support"
    )
    return _payload(
        "provider_outage", tenant_id, recipients,
        f"ApexVoice service notice: {provider} outage affecting your receptionist",
        body, {"incident_id": incident_id, "provider": provider})


def failed_call_alert(tenant_id, business_name, recipients, failed_count,
                      window_label, window_key, ledger,
                      threshold=DEFAULT_FAILED_CALL_THRESHOLD):
    """Alert the business when failed calls in a window reach a threshold.

    Returns None when the count is below the threshold, and None when an
    alert for this tenant and window was already built.
    """
    if failed_count < threshold:
        return None
    key = ("failed_call_alert", tenant_id, window_key)
    if not ledger.build_once(key):
        return None
    body = (
        f"Hello {business_name},\n\n"
        f"ApexVoice recorded {failed_count} failed calls during "
        f"{window_label}. A failed call means the receptionist could not "
        "complete handling the call, for example because of a provider "
        "problem or a caller hanging up during setup.\n\n"
        "No action is needed from you unless this continues. If callers "
        "tell you they could not get through, please reply to this email "
        "with the approximate times so we can investigate.\n\n"
        "Harbour & Main, ApexVoice support"
    )
    return _payload(
        "failed_call_alert", tenant_id, recipients,
        f"ApexVoice alert: {failed_count} failed calls in {window_label}",
        body, {"failed_count": failed_count, "window_key": window_key,
               "threshold": threshold})


def usage_threshold_warning(tenant_id, business_name, recipients, plan_tier,
                            used_minutes, limit_minutes, period, ledger):
    """Warning at 80 percent and at 100 percent of included minutes.

    Fires at most once per tenant, per period, per threshold. Returns
    None when usage is below 80 percent or when the applicable
    threshold notice was already built for this period.
    """
    if not limit_minutes:
        return None
    percent = (used_minutes / float(limit_minutes)) * 100.0
    reached = None
    for threshold in sorted(USAGE_THRESHOLDS_PERCENT, reverse=True):
        if percent >= threshold:
            reached = threshold
            break
    if reached is None:
        return None
    key = ("usage_threshold", tenant_id, period, reached)
    if not ledger.build_once(key):
        return None
    if reached >= 100:
        headline = (
            f"Your ApexVoice plan has reached its included minutes for "
            f"{period}.")
        detail = (
            "Calls are still answered. Minutes beyond the included amount "
            "are billed as overage at your plan rate, and the hard limit "
            "in your configuration, if one is set, still applies.")
    else:
        headline = (
            f"Your ApexVoice plan has used {reached} percent of its "
            f"included minutes for {period}.")
        detail = (
            "No action is needed. This notice is so the usage does not "
            "come as a surprise on your next invoice.")
    body = (
        f"Hello {business_name},\n\n{headline}\n\n"
        f"Plan: {plan_tier}. Minutes used: {used_minutes:g} of "
        f"{limit_minutes:g} included.\n\n{detail}\n\n"
        "Harbour & Main, ApexVoice support"
    )
    return _payload(
        "usage_threshold", tenant_id, recipients,
        f"ApexVoice usage notice: {reached} percent of included minutes used",
        body, {"period": period, "threshold_percent": reached,
               "used_minutes": used_minutes, "limit_minutes": limit_minutes})


def monthly_usage_summary_email(tenant_id, business_name, recipients,
                                summary_text, period):
    """Wrap a summaries.py plain text summary as an email payload."""
    body = (
        f"Hello {business_name},\n\n"
        "Here is your ApexVoice usage summary for this month.\n\n"
        f"{summary_text}\n\n"
        "Questions about this summary: reply to this email.\n\n"
        "Harbour & Main, ApexVoice support"
    )
    return _payload(
        "monthly_usage_summary", tenant_id, recipients,
        f"Your ApexVoice usage summary for {period}",
        body, {"period": period})


def payment_failure_notice(tenant_id, business_name, recipients,
                           grace_days=DEFAULT_GRACE_DAYS, grace_expires_on="",
                           amount_due_text=""):
    """Notice that a subscription payment failed.

    References the billing grace policy implemented in billing/state.py:
    the subscription moves to past due, service continues during the
    grace period, and only if the grace period expires with no
    successful payment does the billing layer recommend suspension to a
    human. Nothing is suspended automatically.
    """
    body = (
        f"Hello {business_name},\n\n"
        "A payment for your ApexVoice subscription did not go through"
        + (f" ({amount_due_text})" if amount_due_text else "")
        + ".\n\n"
        f"Your receptionist keeps working during a {grace_days} day grace "
        "period while the payment is retried and you update your payment "
        "method."
        + (f" The grace period ends on {grace_expires_on}." if grace_expires_on else "")
        + "\n\nIf the payment is still outstanding when the grace period "
        "ends, your account may be suspended after a review by our team. "
        "Nothing is suspended automatically by the billing system.\n\n"
        "To fix this, update the payment method in your billing portal "
        "or reply to this email and we will help.\n\n"
        "Harbour & Main, ApexVoice support"
    )
    return _payload(
        "payment_failure", tenant_id, recipients,
        "ApexVoice billing: a payment needs your attention",
        body, {"grace_days": grace_days, "grace_expires_on": grace_expires_on})
