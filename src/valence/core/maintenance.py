"""Database maintenance operations: retention, archival, compaction.

Functions call stored procedures for the heavy lifting. This module provides
the Python interface and configuration for CLI and scheduled operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetentionConfig:
    """Per-table retention configuration (in days).

    None means keep forever. audit_log is always kept (GDPR 7-year minimum).
    """

    belief_retrievals_days: int = 90
    sync_events_days: int = 90
    embedding_coverage_days: int | None = None  # keep forever by default
    # audit_log: NEVER deleted (hardcoded in stored procedure)


@dataclass
class ArchivalConfig:
    """Belief archival configuration."""

    older_than_days: int = 180
    batch_size: int = 1000


@dataclass
class MaintenanceConfig:
    """Combined maintenance configuration."""

    retention: RetentionConfig = field(default_factory=RetentionConfig)
    archival: ArchivalConfig = field(default_factory=ArchivalConfig)


@dataclass
class MaintenanceResult:
    """Result from a maintenance operation."""

    operation: str
    details: dict[str, Any]
    dry_run: bool = False

    def __str__(self) -> str:
        status = " (dry run)" if self.dry_run else ""
        items = ", ".join(f"{k}={v}" for k, v in self.details.items())
        return f"{self.operation}{status}: {items}"


def apply_retention(cur, config: RetentionConfig | None = None, dry_run: bool = False) -> list[MaintenanceResult]:
    """Apply retention policies via stored procedure.

    Args:
        cur: Database cursor
        config: Retention configuration (uses defaults if None)
        dry_run: If True, only report what would be deleted

    Returns:
        List of MaintenanceResult with per-table deletion counts
    """
    config = config or RetentionConfig()

    cur.execute(
        "SELECT * FROM apply_retention_policies(%s, %s, %s, %s)",
        (
            config.belief_retrievals_days,
            config.sync_events_days,
            config.embedding_coverage_days,
            dry_run,
        ),
    )

    results = []
    for row in cur.fetchall():
        results.append(
            MaintenanceResult(
                operation="retention",
                details={"table": row["table_name"], "deleted": row["deleted_count"]},
                dry_run=dry_run,
            )
        )
    return results


def archive_beliefs(cur, config: ArchivalConfig | None = None, dry_run: bool = False) -> MaintenanceResult:
    """Archive stale superseded beliefs via stored procedure.

    Args:
        cur: Database cursor
        config: Archival configuration (uses defaults if None)
        dry_run: If True, only report what would be archived

    Returns:
        MaintenanceResult with archival counts
    """
    config = config or ArchivalConfig()

    cur.execute(
        "SELECT * FROM archive_stale_beliefs(%s, %s, %s)",
        (config.older_than_days, config.batch_size, dry_run),
    )
    row = cur.fetchone()

    return MaintenanceResult(
        operation="archival",
        details={"archived": row["archived_count"], "freed_embeddings": row["freed_embeddings"]},
        dry_run=dry_run,
    )


def cleanup_tombstones(cur, dry_run: bool = False) -> MaintenanceResult:
    """Remove expired tombstones.

    Args:
        cur: Database cursor
        dry_run: If True, only report what would be cleaned

    Returns:
        MaintenanceResult with cleanup count
    """
    cur.execute("SELECT cleanup_expired_tombstones(%s) as count", (dry_run,))
    row = cur.fetchone()

    return MaintenanceResult(
        operation="tombstone_cleanup",
        details={"removed": row["count"]},
        dry_run=dry_run,
    )


def vacuum_analyze(cur) -> MaintenanceResult:
    """Run VACUUM ANALYZE on key tables.

    Note: VACUUM cannot run inside a transaction, so the connection
    must have autocommit=True.
    """
    tables = ["beliefs", "vkb_exchanges", "vkb_sessions", "belief_retrievals", "embedding_coverage"]
    for table in tables:
        cur.execute(f"VACUUM ANALYZE {table}")  # noqa: S608 - table names are hardcoded, not user input

    return MaintenanceResult(
        operation="vacuum_analyze",
        details={"tables": len(tables)},
    )


def run_full_maintenance(
    cur,
    config: MaintenanceConfig | None = None,
    dry_run: bool = False,
    skip_vacuum: bool = False,
) -> list[MaintenanceResult]:
    """Run full maintenance cycle in the correct order.

    Order: retention -> archival -> tombstone cleanup -> vacuum -> analyze
    """
    config = config or MaintenanceConfig()
    results: list[MaintenanceResult] = []

    # 1. Retention policies
    results.extend(apply_retention(cur, config.retention, dry_run))

    # 2. Belief archival
    results.append(archive_beliefs(cur, config.archival, dry_run))

    # 3. Tombstone cleanup
    results.append(cleanup_tombstones(cur, dry_run))

    # 4. VACUUM ANALYZE (skip in dry-run mode or if requested)
    if not dry_run and not skip_vacuum:
        results.append(vacuum_analyze(cur))

    return results
