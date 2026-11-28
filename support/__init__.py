"""ApexVoice customer support and operations readiness package.

Built in Phase 4 against the Phase 3 tenancy and billing layers.
Nothing in this package sends email, places calls, or mutates a tenant
store. Notification builders return payloads only. See
docs/commercial/SUPPORT_AND_OPERATIONS.md for the operating manual.
"""

from . import exports, notifications, summaries, tickets
from .notifications import (
    FROM_IDENTITY, NotificationLedger, failed_call_alert,
    monthly_usage_summary_email, payment_failure_notice,
    provider_outage_notice, usage_threshold_warning,
)
from .summaries import monthly_summary, summary_to_text
from .tickets import (
    CATEGORIES, PRIORITIES, SLA_TARGETS_HOURS, STATUSES, PlatformViewer,
    SupportStore, TenantViewer, Ticket,
)

__all__ = [
    "exports", "notifications", "summaries", "tickets",
    "FROM_IDENTITY", "NotificationLedger", "failed_call_alert",
    "monthly_usage_summary_email", "payment_failure_notice",
    "provider_outage_notice", "usage_threshold_warning",
    "monthly_summary", "summary_to_text",
    "CATEGORIES", "PRIORITIES", "SLA_TARGETS_HOURS", "STATUSES",
    "PlatformViewer", "SupportStore", "TenantViewer", "Ticket",
]
