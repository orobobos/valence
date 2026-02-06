"""Resource sharing service with trust gating and safety checks.

Enables sharing of operational knowledge (prompts, configs, patterns) between
federation peers with trust-based access control and safety scanning.

Key differences from belief sharing:
- Resources are measured by usefulness, not truth.
- Risks: prompt injection, data exfiltration (not misinformation).
- Validation: usage attestations (not corroboration).

Part of Issue #270: Resource sharing with trust gating.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from .exceptions import NotFoundError, ValidationException
from .resources import (
    Resource,
    ResourceReport,
    ResourceType,
    SafetyStatus,
    UsageAttestation,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SAFETY SCANNING
# =============================================================================

# Patterns that suggest prompt injection attempts
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"<\s*/?(?:system|prompt|instruction)\s*>", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all)\s+(you|that)", re.IGNORECASE),
    re.compile(r"\bDAN\b.*\bmode\b", re.IGNORECASE),
    re.compile(r"jailbreak|do\s+anything\s+now", re.IGNORECASE),
]

# Patterns that suggest data exfiltration attempts
EXFIL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"send\s+.*\s+to\s+https?://", re.IGNORECASE),
    re.compile(r"fetch\s+https?://", re.IGNORECASE),
    re.compile(r"curl\s+", re.IGNORECASE),
    re.compile(r"wget\s+", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"exec\s*\(", re.IGNORECASE),
    re.compile(r"import\s+(?:os|subprocess|shutil)", re.IGNORECASE),
    re.compile(r"__import__\s*\(", re.IGNORECASE),
    re.compile(
        r"(?:api[_-]?key|secret|password|token|credential)s?\s*[:=]",
        re.IGNORECASE,
    ),
    re.compile(r"base64\.(?:encode|decode|b64encode|b64decode)", re.IGNORECASE),
]

# Report count threshold to auto-block
REPORT_BLOCK_THRESHOLD = 3
# Report count threshold to mark suspicious
REPORT_SUSPICIOUS_THRESHOLD = 1

# Minimum trust level to share resources (author must meet this)
MIN_SHARE_TRUST = 0.3
# Default minimum trust level to access a resource
DEFAULT_ACCESS_TRUST = 0.5
# Maximum trust level that can be required
MAX_TRUST_REQUIRED = 1.0


@dataclass
class SafetyScanResult:
    """Result of a safety scan on resource content."""

    is_safe: bool
    injection_matches: list[str] = field(default_factory=list)
    exfil_matches: list[str] = field(default_factory=list)

    @property
    def status(self) -> SafetyStatus:
        """Determine safety status from scan results."""
        if self.injection_matches or self.exfil_matches:
            return SafetyStatus.SUSPICIOUS
        return SafetyStatus.SAFE


def scan_content(content: str) -> SafetyScanResult:
    """Scan resource content for injection and exfiltration patterns.

    Args:
        content: The resource content to scan.

    Returns:
        SafetyScanResult with detected issues.
    """
    injection_matches: list[str] = []
    exfil_matches: list[str] = []

    for pattern in INJECTION_PATTERNS:
        match = pattern.search(content)
        if match:
            injection_matches.append(match.group())

    for pattern in EXFIL_PATTERNS:
        match = pattern.search(content)
        if match:
            exfil_matches.append(match.group())

    is_safe = not injection_matches and not exfil_matches
    return SafetyScanResult(
        is_safe=is_safe,
        injection_matches=injection_matches,
        exfil_matches=exfil_matches,
    )


# =============================================================================
# TRUST PROVIDER PROTOCOL
# =============================================================================


class TrustProvider(Protocol):
    """Protocol for checking trust levels between peers."""

    def get_trust_level(self, did: str) -> float:
        """Get trust level for a DID (0.0 to 1.0)."""
        ...


class DefaultTrustProvider:
    """Default trust provider — returns a configurable default trust level.

    Used when no federation trust registry is available.
    """

    def __init__(self, default_level: float = 0.5) -> None:
        self._default = default_level
        self._overrides: dict[str, float] = {}

    def set_trust(self, did: str, level: float) -> None:
        """Set explicit trust level for a DID."""
        self._overrides[did] = max(0.0, min(1.0, level))

    def get_trust_level(self, did: str) -> float:
        """Get trust level for a DID."""
        return self._overrides.get(did, self._default)


# =============================================================================
# RESOURCE STORE PROTOCOL
# =============================================================================


class ResourceStore(Protocol):
    """Protocol for resource persistence."""

    def get(self, resource_id: UUID) -> Resource | None:
        """Get a resource by ID."""
        ...

    def list_all(
        self,
        resource_type: ResourceType | None = None,
        author_did: str | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        """List resources with optional filters."""
        ...

    def save(self, resource: Resource) -> None:
        """Save or update a resource."""
        ...

    def delete(self, resource_id: UUID) -> bool:
        """Delete a resource. Returns True if deleted."""
        ...


class InMemoryResourceStore:
    """In-memory resource store for testing and local use."""

    def __init__(self) -> None:
        self._resources: dict[UUID, Resource] = {}

    def get(self, resource_id: UUID) -> Resource | None:
        return self._resources.get(resource_id)

    def list_all(
        self,
        resource_type: ResourceType | None = None,
        author_did: str | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        results = list(self._resources.values())
        if resource_type is not None:
            results = [r for r in results if r.type == resource_type]
        if author_did is not None:
            results = [r for r in results if r.author_did == author_did]
        # Sort by created_at descending (newest first)
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def save(self, resource: Resource) -> None:
        self._resources[resource.id] = resource

    def delete(self, resource_id: UUID) -> bool:
        return self._resources.pop(resource_id, None) is not None


# =============================================================================
# RESOURCE SHARING SERVICE
# =============================================================================


@dataclass
class ShareResult:
    """Result of a share operation."""

    resource_id: UUID
    safety_scan: SafetyScanResult
    shared: bool
    message: str


@dataclass
class AccessResult:
    """Result of a resource access request."""

    resource: Resource | None
    granted: bool
    reason: str


class ResourceSharingService:
    """Service for sharing resources with trust gating and safety checks.

    Manages the lifecycle of shared resources:
    - Publishing with safety scanning and trust gates
    - Access control based on requester trust level
    - Reporting and automatic blocking of harmful resources
    - Usage attestation tracking
    """

    def __init__(
        self,
        store: ResourceStore | None = None,
        trust_provider: TrustProvider | None = None,
    ) -> None:
        self._store: ResourceStore = store or InMemoryResourceStore()
        self._trust: TrustProvider = trust_provider or DefaultTrustProvider()
        self._reports: dict[UUID, list[ResourceReport]] = {}
        self._attestations: dict[UUID, list[UsageAttestation]] = {}

    # -------------------------------------------------------------------------
    # SHARING
    # -------------------------------------------------------------------------

    def share_resource(
        self,
        resource: Resource,
        trust_level_required: float | None = None,
    ) -> ShareResult:
        """Publish a resource for sharing with trust gating.

        Performs safety scanning and sets trust requirements.

        Args:
            resource: The resource to share.
            trust_level_required: Minimum trust level to access (0.0-1.0).
                Defaults to the resource's existing trust_level_required.

        Returns:
            ShareResult indicating success/failure and safety scan details.

        Raises:
            ValidationException: If resource or trust level is invalid.
        """
        # Validate trust level
        if trust_level_required is not None:
            if not (0.0 <= trust_level_required <= MAX_TRUST_REQUIRED):
                raise ValidationException(
                    f"trust_level_required must be between 0.0 and {MAX_TRUST_REQUIRED}",
                    field="trust_level_required",
                    value=trust_level_required,
                )
            resource.trust_level_required = trust_level_required

        # Validate content is non-empty
        if not resource.content or not resource.content.strip():
            raise ValidationException(
                "Resource content cannot be empty",
                field="content",
            )

        # Check author trust — authors must meet minimum trust to share
        author_trust = self._trust.get_trust_level(resource.author_did)
        if author_trust < MIN_SHARE_TRUST:
            return ShareResult(
                resource_id=resource.id,
                safety_scan=SafetyScanResult(is_safe=True),
                shared=False,
                message=(f"Author trust level ({author_trust:.2f}) is below minimum sharing threshold ({MIN_SHARE_TRUST:.2f})"),
            )

        # Run safety scan
        scan = scan_content(resource.content)
        resource.safety_status = scan.status

        # Block resources that fail safety scan
        if not scan.is_safe:
            resource.safety_status = SafetyStatus.SUSPICIOUS
            self._store.save(resource)
            logger.warning(
                "Resource %s flagged as suspicious: injection=%s, exfil=%s",
                resource.id,
                scan.injection_matches,
                scan.exfil_matches,
            )
            return ShareResult(
                resource_id=resource.id,
                safety_scan=scan,
                shared=False,
                message="Resource flagged as suspicious by safety scan",
            )

        # Save the resource
        self._store.save(resource)
        logger.info(
            "Resource %s shared by %s (type=%s, trust_required=%.2f)",
            resource.id,
            resource.author_did,
            resource.type,
            resource.trust_level_required,
        )

        return ShareResult(
            resource_id=resource.id,
            safety_scan=scan,
            shared=True,
            message="Resource shared successfully",
        )

    # -------------------------------------------------------------------------
    # ACCESS
    # -------------------------------------------------------------------------

    def request_resource(
        self,
        resource_id: UUID,
        requester_did: str,
    ) -> AccessResult:
        """Request access to a resource with trust gating.

        Checks that the requester meets the resource's trust requirements
        and that the resource hasn't been blocked.

        Args:
            resource_id: ID of the resource to access.
            requester_did: DID of the requester.

        Returns:
            AccessResult with the resource (if granted) and reason.
        """
        resource = self._store.get(resource_id)
        if resource is None:
            return AccessResult(
                resource=None,
                granted=False,
                reason=f"Resource {resource_id} not found",
            )

        # Blocked resources are inaccessible
        if resource.safety_status == SafetyStatus.BLOCKED:
            return AccessResult(
                resource=None,
                granted=False,
                reason="Resource has been blocked",
            )

        # Check requester trust level
        requester_trust = self._trust.get_trust_level(requester_did)
        if requester_trust < resource.trust_level_required:
            return AccessResult(
                resource=None,
                granted=False,
                reason=(f"Insufficient trust level ({requester_trust:.2f} < {resource.trust_level_required:.2f})"),
            )

        # Grant access — update usage count
        resource.usage_count += 1
        resource.modified_at = datetime.now()
        self._store.save(resource)

        logger.info(
            "Resource %s accessed by %s (trust=%.2f)",
            resource_id,
            requester_did,
            requester_trust,
        )

        return AccessResult(
            resource=resource,
            granted=True,
            reason="Access granted",
        )

    # -------------------------------------------------------------------------
    # REPORTING
    # -------------------------------------------------------------------------

    def report_resource(
        self,
        resource_id: UUID,
        reporter_did: str,
        reason: str,
    ) -> ResourceReport:
        """Report a resource as suspicious or harmful.

        If report count exceeds thresholds, the resource is automatically
        flagged as suspicious or blocked.

        Args:
            resource_id: ID of the resource to report.
            reporter_did: DID of the reporter.
            reason: Reason for the report.

        Returns:
            The created ResourceReport.

        Raises:
            NotFoundError: If the resource doesn't exist.
            ValidationException: If the reason is empty.
        """
        if not reason or not reason.strip():
            raise ValidationException(
                "Report reason cannot be empty",
                field="reason",
            )

        resource = self._store.get(resource_id)
        if resource is None:
            raise NotFoundError("Resource", str(resource_id))

        # Create report
        report = ResourceReport(
            id=uuid4(),
            resource_id=resource_id,
            reporter_did=reporter_did,
            reason=reason,
        )

        if resource_id not in self._reports:
            self._reports[resource_id] = []
        self._reports[resource_id].append(report)

        # Update resource report count and safety status
        resource.report_count = len(self._reports[resource_id])

        if resource.report_count >= REPORT_BLOCK_THRESHOLD:
            resource.safety_status = SafetyStatus.BLOCKED
            logger.warning(
                "Resource %s blocked after %d reports",
                resource_id,
                resource.report_count,
            )
        elif resource.report_count >= REPORT_SUSPICIOUS_THRESHOLD:
            resource.safety_status = SafetyStatus.SUSPICIOUS
            logger.info(
                "Resource %s marked suspicious after %d reports",
                resource_id,
                resource.report_count,
            )

        resource.modified_at = datetime.now()
        self._store.save(resource)

        return report

    def get_reports(self, resource_id: UUID) -> list[ResourceReport]:
        """Get all reports for a resource."""
        return list(self._reports.get(resource_id, []))

    # -------------------------------------------------------------------------
    # ATTESTATIONS
    # -------------------------------------------------------------------------

    def attest_usage(
        self,
        resource_id: UUID,
        user_did: str,
        success: bool = True,
        feedback: str | None = None,
    ) -> UsageAttestation:
        """Record a usage attestation for a resource.

        Usage attestations validate resource quality — analogous to how
        corroboration validates belief truth.

        Args:
            resource_id: ID of the resource used.
            user_did: DID of the user.
            success: Whether the usage was successful.
            feedback: Optional feedback text.

        Returns:
            The created UsageAttestation.

        Raises:
            NotFoundError: If the resource doesn't exist.
        """
        resource = self._store.get(resource_id)
        if resource is None:
            raise NotFoundError("Resource", str(resource_id))

        attestation = UsageAttestation(
            id=uuid4(),
            resource_id=resource_id,
            user_did=user_did,
            success=success,
            feedback=feedback,
        )

        if resource_id not in self._attestations:
            self._attestations[resource_id] = []
        self._attestations[resource_id].append(attestation)

        # Update success rate
        attestations = self._attestations[resource_id]
        total = len(attestations)
        successes = sum(1 for a in attestations if a.success)
        resource.success_rate = successes / total if total > 0 else None
        resource.modified_at = datetime.now()
        self._store.save(resource)

        return attestation

    def get_attestations(self, resource_id: UUID) -> list[UsageAttestation]:
        """Get all attestations for a resource."""
        return list(self._attestations.get(resource_id, []))

    # -------------------------------------------------------------------------
    # LISTING
    # -------------------------------------------------------------------------

    def list_resources(
        self,
        resource_type: ResourceType | None = None,
        author_did: str | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        """List available resources with optional filters.

        Args:
            resource_type: Filter by resource type.
            author_did: Filter by author DID.
            limit: Maximum number of results.

        Returns:
            List of resources matching the filters.
        """
        return self._store.list_all(
            resource_type=resource_type,
            author_did=author_did,
            limit=limit,
        )

    def get_resource(self, resource_id: UUID) -> Resource | None:
        """Get a resource by ID (no trust check)."""
        return self._store.get(resource_id)
