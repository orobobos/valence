"""Tests for self-service data report API (Issue #84)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from valence.privacy.reports import (
    AuditRecord,
    BeliefRecord,
    DataReport,
    ExportFormat,
    InMemoryDataSource,
    InMemoryReportStore,
    ReportError,
    ReportGenerationError,
    ReportMetadata,
    ReportNotFoundError,
    ReportScope,
    ReportService,
    ReportStatus,
    ShareRecord,
    TrustRecord,
    generate_data_report,
    get_report_service,
    set_report_service,
)


class TestExportFormat:
    """Tests for ExportFormat enum."""

    def test_json_format(self):
        """Verify JSON format is defined."""
        assert ExportFormat.JSON.value == "json"

    def test_csv_format(self):
        """Verify CSV format is defined."""
        assert ExportFormat.CSV.value == "csv"

    def test_from_string(self):
        """Test creating format from string."""
        assert ExportFormat("json") == ExportFormat.JSON
        assert ExportFormat("csv") == ExportFormat.CSV


class TestReportStatus:
    """Tests for ReportStatus enum."""

    def test_all_statuses_exist(self):
        """Verify all report statuses are defined."""
        assert ReportStatus.PENDING.value == "pending"
        assert ReportStatus.GENERATING.value == "generating"
        assert ReportStatus.COMPLETED.value == "completed"
        assert ReportStatus.FAILED.value == "failed"
        assert ReportStatus.EXPIRED.value == "expired"


class TestReportScope:
    """Tests for ReportScope configuration."""

    def test_default_scope_includes_all(self):
        """Default scope includes all data types."""
        scope = ReportScope()
        assert scope.include_beliefs is True
        assert scope.include_shares_sent is True
        assert scope.include_shares_received is True
        assert scope.include_trust_outgoing is True
        assert scope.include_trust_incoming is True
        assert scope.include_audit_events is True
        assert scope.start_date is None
        assert scope.end_date is None
        assert scope.domains == []

    def test_scope_can_exclude_types(self):
        """Scope can be configured to exclude data types."""
        scope = ReportScope(
            include_beliefs=False,
            include_audit_events=False,
        )
        assert scope.include_beliefs is False
        assert scope.include_audit_events is False
        assert scope.include_shares_sent is True  # Others still default True

    def test_scope_date_filtering(self):
        """Scope can filter by date range."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        scope = ReportScope(start_date=start, end_date=end)
        assert scope.start_date == start
        assert scope.end_date == end

    def test_scope_domain_filtering(self):
        """Scope can filter by domains."""
        scope = ReportScope(domains=["health", "finance"])
        assert scope.domains == ["health", "finance"]

    def test_scope_to_dict(self):
        """Scope can be serialized to dict."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        scope = ReportScope(
            include_beliefs=True,
            include_shares_sent=False,
            start_date=start,
            domains=["health"],
        )
        d = scope.to_dict()
        assert d["include_beliefs"] is True
        assert d["include_shares_sent"] is False
        assert d["start_date"] == start.isoformat()
        assert d["domains"] == ["health"]


class TestRecordTypes:
    """Tests for individual record dataclasses."""

    def test_belief_record(self):
        """Test BeliefRecord creation."""
        now = datetime.now(UTC)
        belief = BeliefRecord(
            belief_id="belief-123",
            content="Test belief content",
            confidence=0.85,
            domains=["test", "demo"],
            created_at=now,
            metadata={"source": "user_input"},
        )
        assert belief.belief_id == "belief-123"
        assert belief.confidence == 0.85
        assert len(belief.domains) == 2
        assert belief.metadata["source"] == "user_input"

    def test_share_record(self):
        """Test ShareRecord creation."""
        now = datetime.now(UTC)
        share = ShareRecord(
            share_id="share-456",
            belief_id="belief-123",
            sharer_did="did:key:alice",
            recipient_did="did:key:bob",
            created_at=now,
            policy_level="DIRECT",
        )
        assert share.share_id == "share-456"
        assert share.sharer_did == "did:key:alice"
        assert share.revoked is False

    def test_trust_record(self):
        """Test TrustRecord creation."""
        now = datetime.now(UTC)
        trust = TrustRecord(
            source_did="did:key:alice",
            target_did="did:key:bob",
            competence=0.8,
            integrity=0.9,
            confidentiality=0.7,
            judgment=0.5,
            domain="professional",
            created_at=now,
        )
        assert trust.source_did == "did:key:alice"
        assert trust.competence == 0.8
        assert trust.domain == "professional"

    def test_audit_record(self):
        """Test AuditRecord creation."""
        now = datetime.now(UTC)
        event = AuditRecord(
            event_id="event-789",
            event_type="share",
            actor_did="did:key:alice",
            target_did="did:key:bob",
            resource="belief:123",
            action="share_belief",
            success=True,
            timestamp=now,
        )
        assert event.event_id == "event-789"
        assert event.event_type == "share"
        assert event.success is True


class TestReportMetadata:
    """Tests for ReportMetadata."""

    def test_create_metadata(self):
        """Test creating report metadata."""
        now = datetime.now(UTC)
        scope = ReportScope()
        metadata = ReportMetadata(
            report_id="report-123",
            user_did="did:key:alice",
            requested_at=now,
            scope=scope,
            format=ExportFormat.JSON,
        )
        assert metadata.report_id == "report-123"
        assert metadata.status == ReportStatus.PENDING
        assert metadata.generated_at is None
        assert metadata.record_counts == {}

    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        now = datetime.now(UTC)
        scope = ReportScope()
        metadata = ReportMetadata(
            report_id="report-123",
            user_did="did:key:alice",
            requested_at=now,
            scope=scope,
            format=ExportFormat.JSON,
            record_counts={"beliefs": 10, "shares_sent": 5},
        )
        d = metadata.to_dict()
        assert d["report_id"] == "report-123"
        assert d["status"] == "pending"
        assert d["format"] == "json"
        assert d["record_counts"]["beliefs"] == 10


class TestDataReport:
    """Tests for DataReport and export functionality."""

    @pytest.fixture
    def sample_report(self):
        """Create a sample report with test data."""
        now = datetime.now(UTC)
        metadata = ReportMetadata(
            report_id="test-report",
            user_did="did:key:alice",
            requested_at=now,
            scope=ReportScope(),
            format=ExportFormat.JSON,
        )

        report = DataReport(metadata=metadata)

        # Add beliefs
        report.beliefs.append(
            BeliefRecord(
                belief_id="belief-1",
                content="Test belief 1",
                confidence=0.9,
                domains=["test"],
                created_at=now,
            )
        )
        report.beliefs.append(
            BeliefRecord(
                belief_id="belief-2",
                content="Test belief 2",
                confidence=0.7,
                domains=["test", "demo"],
                created_at=now,
            )
        )

        # Add shares
        report.shares_sent.append(
            ShareRecord(
                share_id="share-1",
                belief_id="belief-1",
                sharer_did="did:key:alice",
                recipient_did="did:key:bob",
                created_at=now,
                policy_level="DIRECT",
            )
        )
        report.shares_received.append(
            ShareRecord(
                share_id="share-2",
                belief_id="belief-3",
                sharer_did="did:key:carol",
                recipient_did="did:key:alice",
                created_at=now,
                policy_level="BOUNDED",
            )
        )

        # Add trust edges
        report.trust_outgoing.append(
            TrustRecord(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.8,
                integrity=0.9,
                confidentiality=0.85,
                judgment=0.6,
                domain=None,
                created_at=now,
            )
        )
        report.trust_incoming.append(
            TrustRecord(
                source_did="did:key:carol",
                target_did="did:key:alice",
                competence=0.7,
                integrity=0.8,
                confidentiality=0.75,
                judgment=0.5,
                domain="professional",
                created_at=now,
            )
        )

        # Add audit events
        report.audit_events.append(
            AuditRecord(
                event_id="event-1",
                event_type="share",
                actor_did="did:key:alice",
                target_did="did:key:bob",
                resource="belief:1",
                action="share_belief",
                success=True,
                timestamp=now,
            )
        )

        return report

    def test_to_dict(self, sample_report):
        """Test report to_dict conversion."""
        d = sample_report.to_dict()
        assert "metadata" in d
        assert "beliefs" in d
        assert "shares_sent" in d
        assert "shares_received" in d
        assert "trust_outgoing" in d
        assert "trust_incoming" in d
        assert "audit_events" in d
        assert len(d["beliefs"]) == 2
        assert len(d["shares_sent"]) == 1

    def test_to_json(self, sample_report):
        """Test JSON export."""
        json_str = sample_report.to_json()
        data = json.loads(json_str)
        assert data["metadata"]["report_id"] == "test-report"
        assert len(data["beliefs"]) == 2
        assert data["beliefs"][0]["belief_id"] == "belief-1"

    def test_to_json_with_datetime_serialization(self, sample_report):
        """Test that datetimes are properly serialized in JSON."""
        json_str = sample_report.to_json()
        data = json.loads(json_str)
        # Should be ISO format string, not fail
        assert "T" in data["metadata"]["requested_at"]

    def test_to_csv_beliefs(self, sample_report):
        """Test CSV export for beliefs."""
        csvs = sample_report.to_csv()
        assert "beliefs" in csvs
        lines = csvs["beliefs"].strip().split("\n")
        assert len(lines) == 3  # Header + 2 beliefs
        assert "belief_id" in lines[0]
        assert "belief-1" in lines[1]

    def test_to_csv_shares(self, sample_report):
        """Test CSV export for shares."""
        csvs = sample_report.to_csv()
        assert "shares_sent" in csvs
        assert "shares_received" in csvs

        sent_lines = csvs["shares_sent"].strip().split("\n")
        assert len(sent_lines) == 2  # Header + 1 share

        received_lines = csvs["shares_received"].strip().split("\n")
        assert len(received_lines) == 2  # Header + 1 share

    def test_to_csv_trust(self, sample_report):
        """Test CSV export for trust edges."""
        csvs = sample_report.to_csv()
        assert "trust_outgoing" in csvs
        assert "trust_incoming" in csvs

        outgoing_lines = csvs["trust_outgoing"].strip().split("\n")
        assert len(outgoing_lines) == 2  # Header + 1 edge
        assert "competence" in outgoing_lines[0]

    def test_to_csv_audit(self, sample_report):
        """Test CSV export for audit events."""
        csvs = sample_report.to_csv()
        assert "audit_events" in csvs
        lines = csvs["audit_events"].strip().split("\n")
        assert len(lines) == 2  # Header + 1 event
        assert "event_type" in lines[0]

    def test_empty_sections_not_in_csv(self):
        """Empty sections should not appear in CSV output."""
        now = datetime.now(UTC)
        metadata = ReportMetadata(
            report_id="empty-report",
            user_did="did:key:test",
            requested_at=now,
            scope=ReportScope(),
            format=ExportFormat.CSV,
        )
        report = DataReport(metadata=metadata)
        # Leave all lists empty
        csvs = report.to_csv()
        assert csvs == {}  # No sections with data


class TestInMemoryReportStore:
    """Tests for InMemoryReportStore."""

    @pytest.fixture
    def store(self):
        """Create a fresh in-memory store."""
        return InMemoryReportStore()

    @pytest.fixture
    def sample_metadata(self):
        """Create sample metadata."""
        now = datetime.now(UTC)
        return ReportMetadata(
            report_id="test-report-123",
            user_did="did:key:alice",
            requested_at=now,
            scope=ReportScope(),
            format=ExportFormat.JSON,
        )

    @pytest.mark.asyncio
    async def test_save_and_get_metadata(self, store, sample_metadata):
        """Test saving and retrieving metadata."""
        await store.save_metadata(sample_metadata)
        retrieved = await store.get_metadata("test-report-123")
        assert retrieved is not None
        assert retrieved.report_id == "test-report-123"
        assert retrieved.user_did == "did:key:alice"

    @pytest.mark.asyncio
    async def test_get_nonexistent_metadata(self, store):
        """Getting nonexistent metadata returns None."""
        result = await store.get_metadata("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_status(self, store, sample_metadata):
        """Test updating report status."""
        await store.save_metadata(sample_metadata)

        await store.update_status("test-report-123", ReportStatus.GENERATING)
        metadata = await store.get_metadata("test-report-123")
        assert metadata.status == ReportStatus.GENERATING

        await store.update_status("test-report-123", ReportStatus.COMPLETED)
        metadata = await store.get_metadata("test-report-123")
        assert metadata.status == ReportStatus.COMPLETED
        assert metadata.generated_at is not None

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, store, sample_metadata):
        """Test updating status with error message."""
        await store.save_metadata(sample_metadata)

        await store.update_status(
            "test-report-123",
            ReportStatus.FAILED,
            "Database connection failed",
        )
        metadata = await store.get_metadata("test-report-123")
        assert metadata.status == ReportStatus.FAILED
        assert metadata.error_message == "Database connection failed"

    @pytest.mark.asyncio
    async def test_save_and_get_report(self, store, sample_metadata):
        """Test saving and retrieving a full report."""
        await store.save_metadata(sample_metadata)

        report = DataReport(metadata=sample_metadata)
        report.beliefs.append(
            BeliefRecord(
                belief_id="b1",
                content="Test",
                confidence=0.9,
                domains=["test"],
                created_at=datetime.now(UTC),
            )
        )

        await store.save_report("test-report-123", report)

        retrieved = await store.get_report("test-report-123")
        assert retrieved is not None
        assert len(retrieved.beliefs) == 1
        assert retrieved.beliefs[0].belief_id == "b1"

    @pytest.mark.asyncio
    async def test_list_reports_for_user(self, store):
        """Test listing reports for a user."""
        now = datetime.now(UTC)

        # Create reports for different users
        for i in range(3):
            m = ReportMetadata(
                report_id=f"report-alice-{i}",
                user_did="did:key:alice",
                requested_at=now,
                scope=ReportScope(),
                format=ExportFormat.JSON,
            )
            await store.save_metadata(m)

        m_bob = ReportMetadata(
            report_id="report-bob-1",
            user_did="did:key:bob",
            requested_at=now,
            scope=ReportScope(),
            format=ExportFormat.JSON,
        )
        await store.save_metadata(m_bob)

        alice_reports = await store.list_reports_for_user("did:key:alice")
        assert len(alice_reports) == 3

        bob_reports = await store.list_reports_for_user("did:key:bob")
        assert len(bob_reports) == 1

    @pytest.mark.asyncio
    async def test_delete_report(self, store, sample_metadata):
        """Test deleting a report."""
        await store.save_metadata(sample_metadata)
        report = DataReport(metadata=sample_metadata)
        await store.save_report("test-report-123", report)

        # Verify exists
        assert await store.get_metadata("test-report-123") is not None
        assert await store.get_report("test-report-123") is not None

        # Delete
        result = await store.delete_report("test-report-123")
        assert result is True

        # Verify deleted
        assert await store.get_metadata("test-report-123") is None
        assert await store.get_report("test-report-123") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_report(self, store):
        """Deleting nonexistent report returns False."""
        result = await store.delete_report("nonexistent")
        assert result is False


class TestInMemoryDataSource:
    """Tests for InMemoryDataSource."""

    @pytest.fixture
    def data_source(self):
        """Create a data source with test data."""
        ds = InMemoryDataSource()
        now = datetime.now(UTC)

        # Add beliefs
        ds.beliefs.append(
            BeliefRecord(
                belief_id="b1",
                content="Belief 1",
                confidence=0.9,
                domains=["health"],
                created_at=now - timedelta(days=10),
            )
        )
        ds.beliefs.append(
            BeliefRecord(
                belief_id="b2",
                content="Belief 2",
                confidence=0.8,
                domains=["finance"],
                created_at=now - timedelta(days=5),
            )
        )

        # Add shares
        ds.shares.append(
            ShareRecord(
                share_id="s1",
                belief_id="b1",
                sharer_did="did:key:alice",
                recipient_did="did:key:bob",
                created_at=now - timedelta(days=3),
                policy_level="DIRECT",
            )
        )
        ds.shares.append(
            ShareRecord(
                share_id="s2",
                belief_id="b2",
                sharer_did="did:key:carol",
                recipient_did="did:key:alice",
                created_at=now - timedelta(days=1),
                policy_level="BOUNDED",
            )
        )

        # Add trust edges
        ds.trust_edges.append(
            TrustRecord(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.8,
                integrity=0.9,
                confidentiality=0.85,
                judgment=0.6,
                domain="professional",
                created_at=now,
            )
        )
        ds.trust_edges.append(
            TrustRecord(
                source_did="did:key:carol",
                target_did="did:key:alice",
                competence=0.7,
                integrity=0.8,
                confidentiality=0.75,
                judgment=0.5,
                domain=None,
                created_at=now,
            )
        )

        # Add audit events
        ds.audit_events.append(
            AuditRecord(
                event_id="e1",
                event_type="share",
                actor_did="did:key:alice",
                target_did="did:key:bob",
                resource="belief:b1",
                action="share_belief",
                success=True,
                timestamp=now - timedelta(hours=2),
            )
        )

        return ds

    @pytest.mark.asyncio
    async def test_get_beliefs_for_user(self, data_source):
        """Test retrieving beliefs."""
        beliefs = []
        async for b in data_source.get_beliefs_for_user("did:key:alice"):
            beliefs.append(b)
        assert len(beliefs) == 2  # In-memory returns all for testing

    @pytest.mark.asyncio
    async def test_get_beliefs_filtered_by_domain(self, data_source):
        """Test filtering beliefs by domain."""
        beliefs = []
        async for b in data_source.get_beliefs_for_user(
            "did:key:alice", domains=["health"]
        ):
            beliefs.append(b)
        assert len(beliefs) == 1
        assert beliefs[0].belief_id == "b1"

    @pytest.mark.asyncio
    async def test_get_shares_sent(self, data_source):
        """Test retrieving shares sent."""
        shares = []
        async for s in data_source.get_shares_sent("did:key:alice"):
            shares.append(s)
        assert len(shares) == 1
        assert shares[0].share_id == "s1"

    @pytest.mark.asyncio
    async def test_get_shares_received(self, data_source):
        """Test retrieving shares received."""
        shares = []
        async for s in data_source.get_shares_received("did:key:alice"):
            shares.append(s)
        assert len(shares) == 1
        assert shares[0].share_id == "s2"

    @pytest.mark.asyncio
    async def test_get_trust_edges_from(self, data_source):
        """Test retrieving outgoing trust edges."""
        edges = []
        async for e in data_source.get_trust_edges_from("did:key:alice"):
            edges.append(e)
        assert len(edges) == 1
        assert edges[0].target_did == "did:key:bob"

    @pytest.mark.asyncio
    async def test_get_trust_edges_to(self, data_source):
        """Test retrieving incoming trust edges."""
        edges = []
        async for e in data_source.get_trust_edges_to("did:key:alice"):
            edges.append(e)
        assert len(edges) == 1
        assert edges[0].source_did == "did:key:carol"

    @pytest.mark.asyncio
    async def test_get_audit_events_for_user(self, data_source):
        """Test retrieving audit events involving user."""
        events = []
        async for e in data_source.get_audit_events_for_user("did:key:alice"):
            events.append(e)
        assert len(events) == 1
        assert events[0].actor_did == "did:key:alice"


class TestReportService:
    """Tests for ReportService."""

    @pytest.fixture
    def service(self):
        """Create a report service with in-memory stores."""
        data_source = InMemoryDataSource()
        report_store = InMemoryReportStore()
        return ReportService(data_source, report_store)

    @pytest.fixture
    def service_with_data(self):
        """Create a report service with test data."""
        data_source = InMemoryDataSource()
        now = datetime.now(UTC)

        # Add test data
        data_source.beliefs.append(
            BeliefRecord(
                belief_id="b1",
                content="Test belief",
                confidence=0.9,
                domains=["test"],
                created_at=now,
            )
        )
        data_source.shares.append(
            ShareRecord(
                share_id="s1",
                belief_id="b1",
                sharer_did="did:key:alice",
                recipient_did="did:key:bob",
                created_at=now,
                policy_level="DIRECT",
            )
        )
        data_source.trust_edges.append(
            TrustRecord(
                source_did="did:key:alice",
                target_did="did:key:bob",
                competence=0.8,
                integrity=0.9,
                confidentiality=0.85,
                judgment=0.6,
                domain=None,
                created_at=now,
            )
        )
        data_source.audit_events.append(
            AuditRecord(
                event_id="e1",
                event_type="share",
                actor_did="did:key:alice",
                target_did="did:key:bob",
                resource="belief:b1",
                action="share_belief",
                success=True,
                timestamp=now,
            )
        )

        report_store = InMemoryReportStore()
        return ReportService(data_source, report_store)

    @pytest.mark.asyncio
    async def test_request_report(self, service):
        """Test requesting a new report."""
        metadata = await service.request_report("did:key:alice")

        assert metadata.report_id is not None
        assert metadata.user_did == "did:key:alice"
        assert metadata.status == ReportStatus.PENDING
        assert metadata.format == ExportFormat.JSON
        assert metadata.expires_at is not None

    @pytest.mark.asyncio
    async def test_request_report_with_scope(self, service):
        """Test requesting a report with custom scope."""
        scope = ReportScope(
            include_beliefs=True,
            include_shares_sent=False,
            include_trust_outgoing=False,
        )
        metadata = await service.request_report(
            "did:key:alice",
            scope=scope,
            format=ExportFormat.CSV,
        )

        assert metadata.scope.include_beliefs is True
        assert metadata.scope.include_shares_sent is False
        assert metadata.format == ExportFormat.CSV

    @pytest.mark.asyncio
    async def test_generate_report(self, service_with_data):
        """Test generating a report."""
        metadata = await service_with_data.request_report("did:key:alice")
        report = await service_with_data.generate_report(metadata.report_id)

        assert report is not None
        assert len(report.beliefs) == 1
        assert len(report.shares_sent) == 1
        assert len(report.trust_outgoing) == 1
        assert len(report.audit_events) == 1

    @pytest.mark.asyncio
    async def test_generate_report_updates_status(self, service_with_data):
        """Test that generation updates status to COMPLETED."""
        metadata = await service_with_data.request_report("did:key:alice")
        await service_with_data.generate_report(metadata.report_id)

        updated_metadata = await service_with_data.get_report_status(metadata.report_id)
        assert updated_metadata.status == ReportStatus.COMPLETED
        assert updated_metadata.generated_at is not None

    @pytest.mark.asyncio
    async def test_generate_report_with_scope_filtering(self, service_with_data):
        """Test that scope filters data in the report."""
        scope = ReportScope(
            include_beliefs=True,
            include_shares_sent=False,
            include_shares_received=False,
            include_trust_outgoing=False,
            include_trust_incoming=False,
            include_audit_events=False,
        )
        metadata = await service_with_data.request_report("did:key:alice", scope=scope)
        report = await service_with_data.generate_report(metadata.report_id)

        assert len(report.beliefs) == 1
        assert len(report.shares_sent) == 0
        assert len(report.trust_outgoing) == 0
        assert len(report.audit_events) == 0

    @pytest.mark.asyncio
    async def test_generate_report_not_found(self, service):
        """Test generating a nonexistent report raises error."""
        with pytest.raises(ReportNotFoundError):
            await service.generate_report("nonexistent-report")

    @pytest.mark.asyncio
    async def test_get_report_status(self, service):
        """Test getting report status."""
        metadata = await service.request_report("did:key:alice")

        status = await service.get_report_status(metadata.report_id)
        assert status.report_id == metadata.report_id
        assert status.status == ReportStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_report_status_not_found(self, service):
        """Test getting status of nonexistent report."""
        with pytest.raises(ReportNotFoundError):
            await service.get_report_status("nonexistent")

    @pytest.mark.asyncio
    async def test_get_report(self, service_with_data):
        """Test retrieving a completed report."""
        metadata = await service_with_data.request_report("did:key:alice")
        await service_with_data.generate_report(metadata.report_id)

        report = await service_with_data.get_report(metadata.report_id)
        assert report is not None
        assert report.metadata.report_id == metadata.report_id

    @pytest.mark.asyncio
    async def test_get_report_not_completed(self, service):
        """Test getting a report that isn't completed raises error."""
        metadata = await service.request_report("did:key:alice")

        with pytest.raises(ReportGenerationError) as exc_info:
            await service.get_report(metadata.report_id)
        assert "not completed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_reports(self, service):
        """Test listing reports for a user."""
        await service.request_report("did:key:alice")
        await service.request_report("did:key:alice")
        await service.request_report("did:key:bob")

        alice_reports = await service.list_reports("did:key:alice")
        assert len(alice_reports) == 2

        bob_reports = await service.list_reports("did:key:bob")
        assert len(bob_reports) == 1

    @pytest.mark.asyncio
    async def test_delete_report(self, service):
        """Test deleting a report."""
        metadata = await service.request_report("did:key:alice")

        result = await service.delete_report(metadata.report_id, "did:key:alice")
        assert result is True

        with pytest.raises(ReportNotFoundError):
            await service.get_report_status(metadata.report_id)

    @pytest.mark.asyncio
    async def test_delete_report_wrong_user(self, service):
        """Test that users can't delete other users' reports."""
        metadata = await service.request_report("did:key:alice")

        with pytest.raises(ReportError) as exc_info:
            await service.delete_report(metadata.report_id, "did:key:bob")
        assert "another user" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_record_counts_populated(self, service_with_data):
        """Test that record counts are populated after generation."""
        metadata = await service_with_data.request_report("did:key:alice")
        await service_with_data.generate_report(metadata.report_id)

        updated = await service_with_data.get_report_status(metadata.report_id)
        assert updated.record_counts["beliefs"] == 1
        assert updated.record_counts["shares_sent"] == 1
        assert updated.record_counts["trust_outgoing"] == 1
        assert updated.record_counts["audit_events"] == 1


class TestConvenienceFunction:
    """Tests for generate_data_report convenience function."""

    @pytest.fixture
    def configured_service(self):
        """Set up global service for convenience function."""
        data_source = InMemoryDataSource()
        now = datetime.now(UTC)
        data_source.beliefs.append(
            BeliefRecord(
                belief_id="b1",
                content="Test",
                confidence=0.9,
                domains=["test"],
                created_at=now,
            )
        )

        report_store = InMemoryReportStore()
        service = ReportService(data_source, report_store)
        set_report_service(service)
        yield service
        set_report_service(None)

    @pytest.mark.asyncio
    async def test_generate_data_report(self, configured_service):
        """Test the convenience function."""
        report = await generate_data_report("did:key:alice")
        assert report is not None
        assert len(report.beliefs) == 1

    @pytest.mark.asyncio
    async def test_generate_data_report_no_service(self):
        """Test error when no service is configured."""
        set_report_service(None)
        with pytest.raises(ReportError) as exc_info:
            await generate_data_report("did:key:alice")
        assert "No report service configured" in str(exc_info.value)


class TestModuleLevelFunctions:
    """Tests for module-level getter/setter functions."""

    def test_get_set_report_service(self):
        """Test getting and setting the default service."""
        original = get_report_service()

        data_source = InMemoryDataSource()
        report_store = InMemoryReportStore()
        service = ReportService(data_source, report_store)

        set_report_service(service)
        assert get_report_service() is service

        set_report_service(None)
        assert get_report_service() is None

        # Restore original
        set_report_service(original)
