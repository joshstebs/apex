"""ApexVoice customer support tickets.

In-memory ticket store scoped by tenant. A tenant viewer can only ever
see and act on its own tenant's tickets. A platform operator viewer (the
Harbour & Main operator principal from the tenancy layer) sees all
tenants. Every status change and every escalation writes an audit entry
on the ticket itself, so the history of a request travels with the
request and survives into exports.

SLA figures in this module are INTERNAL operating targets for the
Harbour & Main support team. They are not customer promises, must not
be quoted to customers as commitments, and are not in any contract
draft. They exist so the team can spot requests that are drifting.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from tenancy.ids import generate_prefixed_id
except ImportError:  # pragma: no cover, tenancy layer is expected on the path
    import uuid

    def generate_prefixed_id(prefix, length=20):
        return prefix + uuid.uuid4().hex[:length]


CATEGORIES = ("billing", "technical", "configuration", "outage", "other")
PRIORITIES = ("low", "normal", "high", "urgent")
STATUSES = (
    "open", "acknowledged", "in_progress", "waiting_customer",
    "resolved", "closed",
)

# Internal targets only, in hours. See the module docstring.
SLA_TARGETS_HOURS = {
    "urgent": {"acknowledge": 1, "resolve": 8},
    "high": {"acknowledge": 4, "resolve": 24},
    "normal": {"acknowledge": 8, "resolve": 72},
    "low": {"acknowledge": 24, "resolve": 120},
}

# Status moves any viewer class may request are checked in the store.
# Platform operators may move a ticket between any two statuses except
# out of "closed". A tenant may close its own resolved ticket or reopen
# its own closed or resolved ticket to "open".
_PLATFORM_FREE_STATUSES = STATUSES


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SupportError(Exception):
    """Base error for the support package."""


class TicketNotVisible(SupportError):
    """Raised when a ticket does not exist or is not visible to the viewer."""


class InvalidTicketChange(SupportError):
    """Raised for an unknown category, priority, status, or illegal move."""


@dataclass(frozen=True)
class TenantViewer:
    """A viewer scoped to exactly one tenant."""

    tenant_id: str
    user_id: str = ""

    @property
    def label(self):
        return f"tenant:{self.tenant_id}:{self.user_id or 'user'}"


@dataclass(frozen=True)
class PlatformViewer:
    """The Harbour & Main platform operator. Sees every tenant."""

    operator_id: str

    @property
    def label(self):
        return f"platform:{self.operator_id}"


@dataclass
class Ticket:
    id: str
    tenant_id: str
    category: str
    priority: str
    status: str
    subject: str
    body: str
    created_at: str
    updated_at: str
    escalated: bool = False
    audit: list = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "subject": self.subject,
            "body": self.body,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "escalated": self.escalated,
            "audit": [dict(entry) for entry in self.audit],
        }


class SupportStore:
    """In-memory ticket store with tenant scoping enforced on every read."""

    def __init__(self):
        self._tickets = {}

    # -- creation ---------------------------------------------------------

    def create_ticket(self, viewer, tenant_id, category, priority, subject,
                      body, at=None):
        """Create a ticket. A tenant viewer may only create for itself."""
        if category not in CATEGORIES:
            raise InvalidTicketChange(f"unknown category: {category}")
        if priority not in PRIORITIES:
            raise InvalidTicketChange(f"unknown priority: {priority}")
        if isinstance(viewer, TenantViewer) and viewer.tenant_id != tenant_id:
            raise TicketNotVisible("a tenant cannot open tickets for another tenant")
        stamp = at or now_iso()
        ticket = Ticket(
            id=generate_prefixed_id("tkt_"),
            tenant_id=tenant_id,
            category=category,
            priority=priority,
            status="open",
            subject=subject,
            body=body,
            created_at=stamp,
            updated_at=stamp,
        )
        ticket.audit.append({
            "at": stamp, "actor": viewer.label, "action": "ticket.created",
            "detail": f"category={category} priority={priority}",
        })
        self._tickets[ticket.id] = ticket
        return ticket

    # -- reads ------------------------------------------------------------

    def _visible(self, viewer, ticket):
        if isinstance(viewer, PlatformViewer):
            return True
        return isinstance(viewer, TenantViewer) and viewer.tenant_id == ticket.tenant_id

    def get_ticket(self, viewer, ticket_id):
        ticket = self._tickets.get(ticket_id)
        if ticket is None or not self._visible(viewer, ticket):
            return None
        return ticket

    def list_tickets(self, viewer, status=None, category=None):
        result = []
        for ticket in self._tickets.values():
            if not self._visible(viewer, ticket):
                continue
            if status is not None and ticket.status != status:
                continue
            if category is not None and ticket.category != category:
                continue
            result.append(ticket)
        result.sort(key=lambda t: (t.created_at, t.id))
        return result

    # -- changes ----------------------------------------------------------

    def _must_get(self, viewer, ticket_id):
        ticket = self.get_ticket(viewer, ticket_id)
        if ticket is None:
            raise TicketNotVisible("ticket not found or not visible to this viewer")
        return ticket

    def change_status(self, viewer, ticket_id, new_status, note="", at=None):
        """Move a ticket to a new status and record the move in the audit.

        Platform operators may set any status except moving a ticket out
        of "closed" (reopening is a tenant or operator decision recorded
        as its own move to "open", which is allowed for a tenant on its
        own ticket). Tenant viewers may only close their own resolved
        ticket or reopen their own resolved or closed ticket.
        """
        if new_status not in STATUSES:
            raise InvalidTicketChange(f"unknown status: {new_status}")
        ticket = self._must_get(viewer, ticket_id)
        if isinstance(viewer, TenantViewer):
            allowed = (
                (ticket.status == "resolved" and new_status in ("closed", "open"))
                or (ticket.status == "closed" and new_status == "open")
            )
            if not allowed:
                raise InvalidTicketChange(
                    "tenant viewers may only close or reopen their own tickets")
        elif ticket.status == "closed" and new_status != "open":
            raise InvalidTicketChange("a closed ticket can only be reopened")
        stamp = at or now_iso()
        old = ticket.status
        ticket.status = new_status
        ticket.updated_at = stamp
        ticket.audit.append({
            "at": stamp, "actor": viewer.label, "action": "ticket.status_changed",
            "detail": f"{old} -> {new_status}" + (f" ({note})" if note else ""),
        })
        return ticket

    def escalate(self, viewer, ticket_id, reason, at=None):
        """Raise priority by one step (urgent stays urgent) and flag the
        ticket as escalated. A reason is required and is written to the
        audit trail. Either the owning tenant or the platform operator
        may escalate; nobody can escalate another tenant's ticket."""
        if not reason or not reason.strip():
            raise InvalidTicketChange("an escalation reason is required")
        ticket = self._must_get(viewer, ticket_id)
        stamp = at or now_iso()
        old = ticket.priority
        index = PRIORITIES.index(old)
        ticket.priority = PRIORITIES[min(index + 1, len(PRIORITIES) - 1)]
        ticket.escalated = True
        ticket.updated_at = stamp
        ticket.audit.append({
            "at": stamp, "actor": viewer.label, "action": "ticket.escalated",
            "detail": f"priority {old} -> {ticket.priority}: {reason.strip()}",
        })
        return ticket
