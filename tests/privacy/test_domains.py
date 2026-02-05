"""Tests for Domain schema and DomainService."""

import hashlib
from datetime import UTC, datetime

import pytest

from valence.privacy.domains import (
    AdminSignatureVerifier,
    DNSTxtVerifier,
    Domain,
    DomainExistsError,
    DomainMembership,
    DomainNotFoundError,
    DomainRole,
    DomainService,
    MembershipExistsError,
    MembershipNotFoundError,
    PermissionDeniedError,
    VerificationMethod,
    VerificationRequirement,
    VerificationResult,
)


class TestDomainRole:
    """Tests for DomainRole enum."""

    def test_all_roles_exist(self):
        """Verify all roles are defined."""
        assert DomainRole.OWNER.value == "owner"
        assert DomainRole.ADMIN.value == "admin"
        assert DomainRole.MEMBER.value == "member"

    def test_role_from_string(self):
        """Test creating role from string value."""
        assert DomainRole("owner") == DomainRole.OWNER
        assert DomainRole("admin") == DomainRole.ADMIN
        assert DomainRole("member") == DomainRole.MEMBER


class TestDomain:
    """Tests for Domain dataclass."""

    def test_create_domain(self):
        """Test basic domain creation."""
        domain = Domain(
            domain_id="test-uuid",
            name="research-team",
            owner_did="did:example:owner",
            description="A research team domain",
        )

        assert domain.domain_id == "test-uuid"
        assert domain.name == "research-team"
        assert domain.owner_did == "did:example:owner"
        assert domain.description == "A research team domain"
        assert domain.created_at is not None

    def test_domain_to_dict(self):
        """Test serialization to dict."""
        created = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        domain = Domain(
            domain_id="test-uuid",
            name="family",
            owner_did="did:example:alice",
            description="Family domain",
            created_at=created,
        )

        data = domain.to_dict()
        assert data["domain_id"] == "test-uuid"
        assert data["name"] == "family"
        assert data["owner_did"] == "did:example:alice"
        assert data["description"] == "Family domain"
        assert "2025-06-15" in data["created_at"]

    def test_domain_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "domain_id": "test-uuid",
            "name": "team",
            "owner_did": "did:example:bob",
            "description": None,
            "created_at": "2025-01-01T00:00:00+00:00",
        }

        domain = Domain.from_dict(data)
        assert domain.domain_id == "test-uuid"
        assert domain.name == "team"
        assert domain.owner_did == "did:example:bob"
        assert domain.description is None
        assert domain.created_at.year == 2025

    def test_domain_roundtrip(self):
        """Test serialization roundtrip."""
        original = Domain(
            domain_id="roundtrip-id",
            name="test-domain",
            owner_did="did:example:test",
            description="Test description",
        )

        restored = Domain.from_dict(original.to_dict())
        assert restored.domain_id == original.domain_id
        assert restored.name == original.name
        assert restored.owner_did == original.owner_did
        assert restored.description == original.description


class TestDomainMembership:
    """Tests for DomainMembership dataclass."""

    def test_create_membership(self):
        """Test basic membership creation."""
        membership = DomainMembership(
            domain_id="domain-uuid",
            member_did="did:example:member",
            role=DomainRole.MEMBER,
        )

        assert membership.domain_id == "domain-uuid"
        assert membership.member_did == "did:example:member"
        assert membership.role == DomainRole.MEMBER
        assert membership.joined_at is not None

    def test_membership_to_dict(self):
        """Test serialization to dict."""
        joined = datetime(2025, 3, 20, 10, 30, 0, tzinfo=UTC)
        membership = DomainMembership(
            domain_id="domain-uuid",
            member_did="did:example:admin",
            role=DomainRole.ADMIN,
            joined_at=joined,
        )

        data = membership.to_dict()
        assert data["domain_id"] == "domain-uuid"
        assert data["member_did"] == "did:example:admin"
        assert data["role"] == "admin"
        assert "2025-03-20" in data["joined_at"]

    def test_membership_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "domain_id": "domain-uuid",
            "member_did": "did:example:owner",
            "role": "owner",
            "joined_at": "2025-02-15T08:00:00+00:00",
        }

        membership = DomainMembership.from_dict(data)
        assert membership.domain_id == "domain-uuid"
        assert membership.member_did == "did:example:owner"
        assert membership.role == DomainRole.OWNER
        assert membership.joined_at.month == 2

    def test_membership_roundtrip(self):
        """Test serialization roundtrip."""
        original = DomainMembership(
            domain_id="roundtrip-domain",
            member_did="did:example:roundtrip",
            role=DomainRole.ADMIN,
        )

        restored = DomainMembership.from_dict(original.to_dict())
        assert restored.domain_id == original.domain_id
        assert restored.member_did == original.member_did
        assert restored.role == original.role


class MockDomainDatabase:
    """In-memory mock database for testing DomainService."""

    def __init__(self):
        self.domains: dict[str, dict] = {}
        self.memberships: dict[str, dict[str, dict]] = {}  # domain_id -> member_did -> membership
        self.verification_results: dict[str, dict[str, dict]] = {}  # domain_id -> member_did -> result

    async def create_domain(
        self,
        domain_id: str,
        name: str,
        owner_did: str,
        description: str | None,
    ) -> None:
        self.domains[domain_id] = {
            "domain_id": domain_id,
            "name": name,
            "owner_did": owner_did,
            "description": description,
            "created_at": datetime.now(UTC).isoformat(),
            "verification_requirement": None,
        }
        self.memberships[domain_id] = {}
        self.verification_results[domain_id] = {}

    async def get_domain(self, domain_id: str) -> dict | None:
        return self.domains.get(domain_id)

    async def get_domain_by_name(self, name: str, owner_did: str) -> dict | None:
        for domain in self.domains.values():
            if domain["name"] == name and domain["owner_did"] == owner_did:
                return domain
        return None

    async def delete_domain(self, domain_id: str) -> bool:
        if domain_id in self.domains:
            del self.domains[domain_id]
            if domain_id in self.memberships:
                del self.memberships[domain_id]
            return True
        return False

    async def add_membership(
        self,
        domain_id: str,
        member_did: str,
        role: str,
    ) -> None:
        if domain_id not in self.memberships:
            self.memberships[domain_id] = {}
        self.memberships[domain_id][member_did] = {
            "domain_id": domain_id,
            "member_did": member_did,
            "role": role,
            "joined_at": datetime.now(UTC).isoformat(),
        }

    async def remove_membership(self, domain_id: str, member_did: str) -> bool:
        if domain_id in self.memberships and member_did in self.memberships[domain_id]:
            del self.memberships[domain_id][member_did]
            return True
        return False

    async def get_membership(self, domain_id: str, member_did: str) -> dict | None:
        if domain_id in self.memberships:
            return self.memberships[domain_id].get(member_did)
        return None

    async def list_memberships(self, domain_id: str) -> list[dict]:
        if domain_id in self.memberships:
            return list(self.memberships[domain_id].values())
        return []

    async def list_domains_for_member(self, member_did: str) -> list[dict]:
        result = []
        for domain_id, members in self.memberships.items():
            if member_did in members:
                domain = self.domains.get(domain_id)
                if domain:
                    result.append(domain)
        return result

    async def set_verification_requirement(
        self,
        domain_id: str,
        requirement: dict | None,
    ) -> None:
        if domain_id in self.domains:
            self.domains[domain_id]["verification_requirement"] = requirement

    async def store_verification_result(
        self,
        domain_id: str,
        member_did: str,
        result: dict,
    ) -> None:
        if domain_id not in self.verification_results:
            self.verification_results[domain_id] = {}
        self.verification_results[domain_id][member_did] = result

    async def get_verification_result(
        self,
        domain_id: str,
        member_did: str,
    ) -> dict | None:
        if domain_id in self.verification_results:
            return self.verification_results[domain_id].get(member_did)
        return None


@pytest.fixture
def mock_db():
    """Create a mock database for testing."""
    return MockDomainDatabase()


@pytest.fixture
def domain_service(mock_db):
    """Create a DomainService with mock database."""
    return DomainService(mock_db)


class TestDomainService:
    """Tests for DomainService."""

    @pytest.mark.asyncio
    async def test_create_domain(self, domain_service):
        """Test creating a domain."""
        domain = await domain_service.create_domain(
            name="test-team",
            owner_did="did:example:alice",
            description="Test team",
        )

        assert domain.name == "test-team"
        assert domain.owner_did == "did:example:alice"
        assert domain.description == "Test team"
        assert domain.domain_id is not None

    @pytest.mark.asyncio
    async def test_create_domain_adds_owner_as_member(self, domain_service, mock_db):
        """Test that creating a domain automatically adds owner as member."""
        domain = await domain_service.create_domain(
            name="auto-member-test",
            owner_did="did:example:owner",
        )

        # Owner should be added as a member with OWNER role
        membership = await mock_db.get_membership(domain.domain_id, "did:example:owner")
        assert membership is not None
        assert membership["role"] == "owner"

    @pytest.mark.asyncio
    async def test_create_duplicate_domain_fails(self, domain_service):
        """Test that creating a domain with same name/owner fails."""
        await domain_service.create_domain(
            name="unique-name",
            owner_did="did:example:owner",
        )

        with pytest.raises(DomainExistsError):
            await domain_service.create_domain(
                name="unique-name",
                owner_did="did:example:owner",
            )

    @pytest.mark.asyncio
    async def test_same_name_different_owners_allowed(self, domain_service):
        """Test that different owners can have domains with the same name."""
        domain1 = await domain_service.create_domain(
            name="team",
            owner_did="did:example:alice",
        )
        domain2 = await domain_service.create_domain(
            name="team",
            owner_did="did:example:bob",
        )

        assert domain1.domain_id != domain2.domain_id

    @pytest.mark.asyncio
    async def test_get_domain(self, domain_service):
        """Test getting a domain by ID."""
        created = await domain_service.create_domain(
            name="get-test",
            owner_did="did:example:owner",
        )

        retrieved = await domain_service.get_domain(created.domain_id)
        assert retrieved.name == "get-test"
        assert retrieved.owner_did == "did:example:owner"

    @pytest.mark.asyncio
    async def test_get_nonexistent_domain_fails(self, domain_service):
        """Test that getting a non-existent domain raises error."""
        with pytest.raises(DomainNotFoundError):
            await domain_service.get_domain("nonexistent-uuid")

    @pytest.mark.asyncio
    async def test_add_member(self, domain_service):
        """Test adding a member to a domain."""
        domain = await domain_service.create_domain(
            name="member-test",
            owner_did="did:example:owner",
        )

        membership = await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:newmember",
            role=DomainRole.MEMBER,
        )

        assert membership.domain_id == domain.domain_id
        assert membership.member_did == "did:example:newmember"
        assert membership.role == DomainRole.MEMBER

    @pytest.mark.asyncio
    async def test_add_admin_member(self, domain_service):
        """Test adding an admin member."""
        domain = await domain_service.create_domain(
            name="admin-test",
            owner_did="did:example:owner",
        )

        membership = await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:admin",
            role=DomainRole.ADMIN,
        )

        assert membership.role == DomainRole.ADMIN

    @pytest.mark.asyncio
    async def test_add_duplicate_member_fails(self, domain_service):
        """Test that adding the same member twice fails."""
        domain = await domain_service.create_domain(
            name="dup-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        with pytest.raises(MembershipExistsError):
            await domain_service.add_member(
                domain_id=domain.domain_id,
                member_did="did:example:member",
            )

    @pytest.mark.asyncio
    async def test_add_member_to_nonexistent_domain_fails(self, domain_service):
        """Test that adding member to non-existent domain fails."""
        with pytest.raises(DomainNotFoundError):
            await domain_service.add_member(
                domain_id="nonexistent",
                member_did="did:example:member",
            )

    @pytest.mark.asyncio
    async def test_remove_member(self, domain_service):
        """Test removing a member from a domain."""
        domain = await domain_service.create_domain(
            name="remove-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        result = await domain_service.remove_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        assert result is True

        # Verify member is gone
        is_member = await domain_service.is_member(domain.domain_id, "did:example:member")
        assert is_member is False

    @pytest.mark.asyncio
    async def test_cannot_remove_owner(self, domain_service):
        """Test that the domain owner cannot be removed."""
        domain = await domain_service.create_domain(
            name="owner-protect-test",
            owner_did="did:example:owner",
        )

        with pytest.raises(PermissionDeniedError):
            await domain_service.remove_member(
                domain_id=domain.domain_id,
                member_did="did:example:owner",
            )

    @pytest.mark.asyncio
    async def test_list_members(self, domain_service):
        """Test listing all members of a domain."""
        domain = await domain_service.create_domain(
            name="list-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member1",
        )
        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member2",
            role=DomainRole.ADMIN,
        )

        members = await domain_service.list_members(domain.domain_id)

        # Should have owner + 2 members
        assert len(members) == 3

        member_dids = {m.member_did for m in members}
        assert "did:example:owner" in member_dids
        assert "did:example:member1" in member_dids
        assert "did:example:member2" in member_dids

    @pytest.mark.asyncio
    async def test_get_member_role(self, domain_service):
        """Test getting a member's role."""
        domain = await domain_service.create_domain(
            name="role-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:admin",
            role=DomainRole.ADMIN,
        )

        owner_role = await domain_service.get_member_role(domain.domain_id, "did:example:owner")
        admin_role = await domain_service.get_member_role(domain.domain_id, "did:example:admin")
        nonmember_role = await domain_service.get_member_role(domain.domain_id, "did:example:stranger")

        assert owner_role == DomainRole.OWNER
        assert admin_role == DomainRole.ADMIN
        assert nonmember_role is None

    @pytest.mark.asyncio
    async def test_is_member(self, domain_service):
        """Test checking membership."""
        domain = await domain_service.create_domain(
            name="ismember-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        assert await domain_service.is_member(domain.domain_id, "did:example:owner")
        assert await domain_service.is_member(domain.domain_id, "did:example:member")
        assert not await domain_service.is_member(domain.domain_id, "did:example:stranger")

    @pytest.mark.asyncio
    async def test_list_domains_for_member(self, domain_service):
        """Test listing domains a member belongs to."""
        domain1 = await domain_service.create_domain(
            name="domain1",
            owner_did="did:example:owner1",
        )
        domain2 = await domain_service.create_domain(
            name="domain2",
            owner_did="did:example:owner2",
        )

        # Add same member to both domains
        await domain_service.add_member(
            domain_id=domain1.domain_id,
            member_did="did:example:member",
        )
        await domain_service.add_member(
            domain_id=domain2.domain_id,
            member_did="did:example:member",
        )

        domains = await domain_service.list_domains_for_member("did:example:member")

        assert len(domains) == 2
        domain_names = {d.name for d in domains}
        assert "domain1" in domain_names
        assert "domain2" in domain_names

    @pytest.mark.asyncio
    async def test_permission_check_owner_can_manage(self, domain_service):
        """Test that owner can manage members."""
        domain = await domain_service.create_domain(
            name="perm-test",
            owner_did="did:example:owner",
        )

        # Owner should be able to add members
        membership = await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:newmember",
            requester_did="did:example:owner",
        )

        assert membership is not None

    @pytest.mark.asyncio
    async def test_permission_check_admin_can_manage(self, domain_service):
        """Test that admin can manage members."""
        domain = await domain_service.create_domain(
            name="admin-perm-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:admin",
            role=DomainRole.ADMIN,
        )

        # Admin should be able to add members
        membership = await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:newmember",
            requester_did="did:example:admin",
        )

        assert membership is not None

    @pytest.mark.asyncio
    async def test_permission_check_member_cannot_manage(self, domain_service):
        """Test that regular members cannot manage other members."""
        domain = await domain_service.create_domain(
            name="member-perm-test",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
            role=DomainRole.MEMBER,
        )

        # Regular member should NOT be able to add members
        with pytest.raises(PermissionDeniedError):
            await domain_service.add_member(
                domain_id=domain.domain_id,
                member_did="did:example:unauthorized",
                requester_did="did:example:member",
            )


class TestVerificationRequirement:
    """Tests for VerificationRequirement dataclass."""

    def test_create_requirement_admin_sig(self):
        """Test creating admin signature requirement."""
        req = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
            config={"admin_did": "did:example:admin"},
            required=True,
        )

        assert req.method == VerificationMethod.ADMIN_SIGNATURE
        assert req.config["admin_did"] == "did:example:admin"
        assert req.required is True

    def test_create_requirement_dns(self):
        """Test creating DNS TXT requirement."""
        req = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={
                "dns_domain": "example.com",
                "expected_prefix": "valence-member=",
            },
        )

        assert req.method == VerificationMethod.DNS_TXT
        assert req.config["dns_domain"] == "example.com"

    def test_requirement_to_dict(self):
        """Test serialization to dict."""
        req = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
            config={"key": "value"},
            required=False,
        )

        data = req.to_dict()
        assert data["method"] == "admin_sig"
        assert data["config"] == {"key": "value"}
        assert data["required"] is False

    def test_requirement_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "method": "dns_txt",
            "config": {"dns_domain": "test.com"},
            "required": True,
        }

        req = VerificationRequirement.from_dict(data)
        assert req.method == VerificationMethod.DNS_TXT
        assert req.config["dns_domain"] == "test.com"
        assert req.required is True

    def test_requirement_roundtrip(self):
        """Test serialization roundtrip."""
        original = VerificationRequirement(
            method=VerificationMethod.CUSTOM,
            config={"custom_key": "custom_value"},
            required=True,
        )

        restored = VerificationRequirement.from_dict(original.to_dict())
        assert restored.method == original.method
        assert restored.config == original.config
        assert restored.required == original.required


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful verification result."""
        result = VerificationResult(
            verified=True,
            method=VerificationMethod.ADMIN_SIGNATURE,
            details="Signature verified",
            evidence={"admin_did": "did:example:admin"},
        )

        assert result.verified is True
        assert result.method == VerificationMethod.ADMIN_SIGNATURE
        assert result.details == "Signature verified"
        assert result.evidence["admin_did"] == "did:example:admin"
        assert result.timestamp is not None

    def test_create_failure_result(self):
        """Test creating a failed verification result."""
        result = VerificationResult(
            verified=False,
            method=VerificationMethod.DNS_TXT,
            details="No matching TXT record found",
        )

        assert result.verified is False
        assert result.method == VerificationMethod.DNS_TXT

    def test_result_to_dict(self):
        """Test serialization to dict."""
        result = VerificationResult(
            verified=True,
            method=VerificationMethod.NONE,
            details="No verification required",
        )

        data = result.to_dict()
        assert data["verified"] is True
        assert data["method"] == "none"
        assert data["details"] == "No verification required"
        assert "timestamp" in data

    def test_result_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "verified": True,
            "method": "admin_sig",
            "timestamp": "2025-06-15T12:00:00+00:00",
            "details": "OK",
            "evidence": {"test": "data"},
        }

        result = VerificationResult.from_dict(data)
        assert result.verified is True
        assert result.method == VerificationMethod.ADMIN_SIGNATURE
        assert result.timestamp.year == 2025
        assert result.evidence["test"] == "data"


class TestAdminSignatureVerifier:
    """Tests for AdminSignatureVerifier."""

    @pytest.mark.asyncio
    async def test_verify_no_evidence(self):
        """Test verification fails without evidence."""
        verifier = AdminSignatureVerifier()
        requirement = VerificationRequirement(method=VerificationMethod.ADMIN_SIGNATURE)

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence=None,
        )

        assert result.verified is False
        assert "No evidence" in result.details

    @pytest.mark.asyncio
    async def test_verify_missing_signature(self):
        """Test verification fails with missing signature."""
        verifier = AdminSignatureVerifier()
        requirement = VerificationRequirement(method=VerificationMethod.ADMIN_SIGNATURE)

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence={"admin_did": "did:example:admin"},  # No signature
        )

        assert result.verified is False
        assert "Missing" in result.details

    @pytest.mark.asyncio
    async def test_verify_valid_signature(self):
        """Test verification succeeds with valid signature."""
        verifier = AdminSignatureVerifier()
        requirement = VerificationRequirement(method=VerificationMethod.ADMIN_SIGNATURE)

        domain_id = "domain-123"
        member_did = "did:example:member"
        admin_did = "did:example:admin"

        # Generate expected signature (simple mode)
        expected_sig = hashlib.sha256(f"{domain_id}:{member_did}:{admin_did}".encode()).hexdigest()

        result = await verifier.verify(
            domain_id=domain_id,
            member_did=member_did,
            requirement=requirement,
            evidence={
                "admin_did": admin_did,
                "signature": expected_sig,
            },
        )

        assert result.verified is True
        assert "Signature verified" in result.details

    @pytest.mark.asyncio
    async def test_verify_invalid_signature(self):
        """Test verification fails with invalid signature."""
        verifier = AdminSignatureVerifier()
        requirement = VerificationRequirement(method=VerificationMethod.ADMIN_SIGNATURE)

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence={
                "admin_did": "did:example:admin",
                "signature": "invalid-signature",
            },
        )

        assert result.verified is False
        assert "mismatch" in result.details


class TestDNSTxtVerifier:
    """Tests for DNSTxtVerifier."""

    @pytest.mark.asyncio
    async def test_verify_no_dns_domain(self):
        """Test verification fails without DNS domain."""
        verifier = DNSTxtVerifier()
        requirement = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={},  # No dns_domain
        )

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence=None,
        )

        assert result.verified is False
        assert "No DNS domain" in result.details

    @pytest.mark.asyncio
    async def test_verify_with_mock_resolver_success(self):
        """Test verification succeeds with matching TXT record."""
        member_did = "did:example:member"

        async def mock_resolver(hostname):
            return [f"valence-member={member_did}"]

        verifier = DNSTxtVerifier(dns_resolver=mock_resolver)
        requirement = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={
                "dns_domain": "example.com",
                "expected_prefix": "valence-member=",
            },
        )

        result = await verifier.verify(
            domain_id="domain-123",
            member_did=member_did,
            requirement=requirement,
            evidence={"dns_domain": "example.com"},
        )

        assert result.verified is True
        assert "Found matching TXT record" in result.details

    @pytest.mark.asyncio
    async def test_verify_with_mock_resolver_no_match(self):
        """Test verification fails without matching TXT record."""

        async def mock_resolver(hostname):
            return ["some-other-record"]

        verifier = DNSTxtVerifier(dns_resolver=mock_resolver)
        requirement = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={"dns_domain": "example.com"},
        )

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence={"dns_domain": "example.com"},
        )

        assert result.verified is False
        assert "No matching TXT record" in result.details

    @pytest.mark.asyncio
    async def test_verify_dns_lookup_error(self):
        """Test verification handles DNS errors gracefully."""

        async def mock_resolver(hostname):
            raise Exception("DNS timeout")

        verifier = DNSTxtVerifier(dns_resolver=mock_resolver)
        requirement = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={"dns_domain": "example.com"},
        )

        result = await verifier.verify(
            domain_id="domain-123",
            member_did="did:example:member",
            requirement=requirement,
            evidence={"dns_domain": "example.com"},
        )

        assert result.verified is False
        assert "DNS lookup failed" in result.details


class TestDomainServiceVerification:
    """Tests for DomainService verification methods."""

    @pytest.mark.asyncio
    async def test_set_verification_requirement(self, domain_service):
        """Test setting a verification requirement on a domain."""
        domain = await domain_service.create_domain(
            name="verified-domain",
            owner_did="did:example:owner",
        )

        requirement = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
            config={"admin_did": "did:example:admin"},
        )

        updated = await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        assert updated.verification_requirement is not None
        assert updated.verification_requirement.method == VerificationMethod.ADMIN_SIGNATURE

    @pytest.mark.asyncio
    async def test_set_verification_requirement_owner_only(self, domain_service):
        """Test that only owner can set verification requirements."""
        domain = await domain_service.create_domain(
            name="owner-only-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:admin",
            role=DomainRole.ADMIN,
        )

        requirement = VerificationRequirement(method=VerificationMethod.ADMIN_SIGNATURE)

        # Admin cannot set verification requirements
        with pytest.raises(PermissionDeniedError):
            await domain_service.set_verification_requirement(
                domain_id=domain.domain_id,
                requirement=requirement,
                requester_did="did:example:admin",
            )

    @pytest.mark.asyncio
    async def test_clear_verification_requirement(self, domain_service):
        """Test clearing a verification requirement."""
        domain = await domain_service.create_domain(
            name="clear-req-domain",
            owner_did="did:example:owner",
        )

        # Set requirement
        requirement = VerificationRequirement(method=VerificationMethod.DNS_TXT)
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        # Clear requirement
        updated = await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=None,
        )

        assert updated.verification_requirement is None

    @pytest.mark.asyncio
    async def test_verify_membership_no_requirement(self, domain_service):
        """Test verification auto-succeeds when no requirement set."""
        domain = await domain_service.create_domain(
            name="no-req-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        result = await domain_service.verify_membership(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        assert result.verified is True
        assert result.method == VerificationMethod.NONE

    @pytest.mark.asyncio
    async def test_verify_membership_not_a_member(self, domain_service):
        """Test verification fails for non-members."""
        domain = await domain_service.create_domain(
            name="member-only-domain",
            owner_did="did:example:owner",
        )

        with pytest.raises(MembershipNotFoundError):
            await domain_service.verify_membership(
                domain_id=domain.domain_id,
                member_did="did:example:stranger",
            )

    @pytest.mark.asyncio
    async def test_verify_membership_with_admin_signature(self, domain_service):
        """Test verification with admin signature."""
        domain = await domain_service.create_domain(
            name="sig-verify-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        # Set admin signature requirement
        requirement = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
        )
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        admin_did = "did:example:owner"
        member_did = "did:example:member"

        # Generate valid signature
        expected_sig = hashlib.sha256(f"{domain.domain_id}:{member_did}:{admin_did}".encode()).hexdigest()

        result = await domain_service.verify_membership(
            domain_id=domain.domain_id,
            member_did=member_did,
            evidence={
                "admin_did": admin_did,
                "signature": expected_sig,
            },
        )

        assert result.verified is True

    @pytest.mark.asyncio
    async def test_get_verification_status(self, domain_service):
        """Test getting verification status."""
        domain = await domain_service.create_domain(
            name="status-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        # Before verification
        status = await domain_service.get_verification_status(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )
        assert status is None

        # After verification
        await domain_service.verify_membership(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        status = await domain_service.get_verification_status(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )
        assert status is not None
        assert status.verified is True

    @pytest.mark.asyncio
    async def test_is_verified_member_no_requirement(self, domain_service):
        """Test is_verified_member when no verification required."""
        domain = await domain_service.create_domain(
            name="no-verify-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        is_verified = await domain_service.is_verified_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        assert is_verified is True

    @pytest.mark.asyncio
    async def test_is_verified_member_required(self, domain_service):
        """Test is_verified_member with required verification."""
        domain = await domain_service.create_domain(
            name="required-verify-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        # Set required verification
        requirement = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
            required=True,
        )
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        # Before verification
        is_verified = await domain_service.is_verified_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )
        assert is_verified is False

        # After verification
        admin_did = "did:example:owner"
        member_did = "did:example:member"
        expected_sig = hashlib.sha256(f"{domain.domain_id}:{member_did}:{admin_did}".encode()).hexdigest()

        await domain_service.verify_membership(
            domain_id=domain.domain_id,
            member_did=member_did,
            evidence={
                "admin_did": admin_did,
                "signature": expected_sig,
            },
        )

        is_verified = await domain_service.is_verified_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )
        assert is_verified is True

    @pytest.mark.asyncio
    async def test_is_verified_member_optional(self, domain_service):
        """Test is_verified_member with optional verification."""
        domain = await domain_service.create_domain(
            name="optional-verify-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        # Set optional verification
        requirement = VerificationRequirement(
            method=VerificationMethod.ADMIN_SIGNATURE,
            required=False,  # Optional
        )
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        # Even without verification, should be considered verified (optional)
        is_verified = await domain_service.is_verified_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )
        assert is_verified is True

    @pytest.mark.asyncio
    async def test_is_verified_member_not_a_member(self, domain_service):
        """Test is_verified_member for non-members returns False."""
        domain = await domain_service.create_domain(
            name="non-member-domain",
            owner_did="did:example:owner",
        )

        is_verified = await domain_service.is_verified_member(
            domain_id=domain.domain_id,
            member_did="did:example:stranger",
        )

        assert is_verified is False

    @pytest.mark.asyncio
    async def test_verify_with_custom_verifier(self, domain_service):
        """Test verification with custom verifier."""
        domain = await domain_service.create_domain(
            name="custom-verify-domain",
            owner_did="did:example:owner",
        )

        await domain_service.add_member(
            domain_id=domain.domain_id,
            member_did="did:example:member",
        )

        requirement = VerificationRequirement(
            method=VerificationMethod.CUSTOM,
        )
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        # Create a custom verifier that always succeeds
        class AlwaysSuccessVerifier:
            async def verify(self, domain_id, member_did, requirement, evidence=None):
                return VerificationResult(
                    verified=True,
                    method=VerificationMethod.CUSTOM,
                    details="Custom verification passed",
                )

        result = await domain_service.verify_membership(
            domain_id=domain.domain_id,
            member_did="did:example:member",
            verifier=AlwaysSuccessVerifier(),
        )

        assert result.verified is True
        assert result.method == VerificationMethod.CUSTOM

    @pytest.mark.asyncio
    async def test_domain_with_verification_roundtrip(self, domain_service, mock_db):
        """Test domain serialization preserves verification requirement."""
        domain = await domain_service.create_domain(
            name="roundtrip-domain",
            owner_did="did:example:owner",
        )

        requirement = VerificationRequirement(
            method=VerificationMethod.DNS_TXT,
            config={"dns_domain": "example.com"},
            required=True,
        )
        await domain_service.set_verification_requirement(
            domain_id=domain.domain_id,
            requirement=requirement,
        )

        # Simulate roundtrip through database
        stored = mock_db.domains[domain.domain_id]
        restored = Domain.from_dict(stored)

        assert restored.verification_requirement is not None
        assert restored.verification_requirement.method == VerificationMethod.DNS_TXT
        assert restored.verification_requirement.config["dns_domain"] == "example.com"
