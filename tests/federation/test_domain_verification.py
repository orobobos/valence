"""Tests for cross-federation domain verification (Issue #87).

Comprehensive tests for:
- DNS-based verification with challenge tokens
- Mutual attestation (federations vouching for each other)
- External authority verification
- Challenge creation and checking
- DomainVerificationResult with evidence

Run with:
    python -m pytest tests/federation/test_domain_verification.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from valence.federation.domain_verification import (
    CHALLENGE_PREFIX,
    # Constants
    CHALLENGE_TTL_HOURS,
    DNS_CHALLENGE_SUBDOMAIN,
    AttestationStore,
    AttestationType,
    ChallengeStatus,
    # Stores
    ChallengeStore,
    DomainAttestation,
    DomainChallenge,
    # Enums
    DomainVerificationMethod,
    DomainVerificationResult,
    # External authority
    ExternalAuthorityClient,
    # Data classes
    VerificationEvidence,
    check_challenge,
    cleanup_expired_challenges,
    # Attestation functions
    create_attestation,
    # Main functions
    create_challenge,
    # Sync wrappers
    create_challenge_sync,
    get_attestation_stats,
    get_attestation_store,
    get_challenge_stats,
    get_challenge_store,
    revoke_attestation,
    set_external_client,
    verify_domain,
    verify_domain_sync,
    # Batch operations
    verify_multiple_domains,
)
from valence.federation.verification import VerificationStatus

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def local_fed_did() -> str:
    """Local federation DID for testing."""
    return "did:vkb:web:local.example"


@pytest.fixture
def remote_fed_did() -> str:
    """Remote federation DID for testing."""
    return "did:vkb:web:remote.example"


@pytest.fixture
def test_domain() -> str:
    """Test domain for verification."""
    return "verified.example.com"


@pytest.fixture
def challenge_store() -> ChallengeStore:
    """Fresh challenge store for testing."""
    return ChallengeStore()


@pytest.fixture
def attestation_store() -> AttestationStore:
    """Fresh attestation store for testing."""
    return AttestationStore()


@pytest.fixture
def mock_external_client():
    """Mock external authority client."""
    client = MagicMock(spec=ExternalAuthorityClient)
    client.verify_domain = AsyncMock(return_value=(False, None, "Not verified"))
    return client


@pytest.fixture(autouse=True)
def reset_global_stores():
    """Reset global stores before each test."""
    import valence.federation.domain_verification as dv

    dv._challenge_store = None
    dv._attestation_store = None
    dv._external_client = None
    yield


# =============================================================================
# VERIFICATION EVIDENCE TESTS
# =============================================================================


class TestVerificationEvidence:
    """Tests for VerificationEvidence dataclass."""

    def test_create_dns_evidence(self):
        """Test creating DNS-based evidence."""
        evidence = VerificationEvidence(
            method=DomainVerificationMethod.DNS_TXT,
            dns_record="valence-federation=did:vkb:web:example",
            dns_query_domain="example.com",
        )

        assert evidence.method == DomainVerificationMethod.DNS_TXT
        assert evidence.dns_record is not None
        assert evidence.timestamp is not None

    def test_create_attestation_evidence(self):
        """Test creating attestation-based evidence."""
        evidence = VerificationEvidence(
            method=DomainVerificationMethod.MUTUAL_ATTESTATION,
            attester_did="did:vkb:web:trusted-fed",
            attestation_signature="sig123",
            attestation_chain=["did:vkb:web:chain1", "did:vkb:web:chain2"],
        )

        assert evidence.method == DomainVerificationMethod.MUTUAL_ATTESTATION
        assert evidence.attester_did == "did:vkb:web:trusted-fed"
        assert len(evidence.attestation_chain) == 2

    def test_create_external_authority_evidence(self):
        """Test creating external authority evidence."""
        evidence = VerificationEvidence(
            method=DomainVerificationMethod.EXTERNAL_AUTHORITY,
            authority_url="https://verify.example.com",
            authority_response={"verified": True, "certificate": "..."},
        )

        assert evidence.method == DomainVerificationMethod.EXTERNAL_AUTHORITY
        assert evidence.authority_url is not None
        assert evidence.authority_response["verified"] is True

    def test_to_dict_and_from_dict(self):
        """Test serialization and deserialization."""
        original = VerificationEvidence(
            method=DomainVerificationMethod.DNS_TXT,
            dns_record="test-record",
            dns_query_domain="test.example.com",
        )

        d = original.to_dict()
        restored = VerificationEvidence.from_dict(d)

        assert restored.method == original.method
        assert restored.dns_record == original.dns_record
        assert restored.dns_query_domain == original.dns_query_domain


# =============================================================================
# DOMAIN VERIFICATION RESULT TESTS
# =============================================================================


class TestDomainVerificationResult:
    """Tests for DomainVerificationResult dataclass."""

    def test_create_successful_result(self, test_domain: str, remote_fed_did: str):
        """Test creating a successful verification result."""
        evidence = VerificationEvidence(
            method=DomainVerificationMethod.DNS_TXT,
            dns_record="test-record",
        )

        result = DomainVerificationResult(
            domain=test_domain,
            federation_did=remote_fed_did,
            verified=True,
            status=VerificationStatus.VERIFIED,
            method=DomainVerificationMethod.DNS_TXT,
            evidence=[evidence],
        )

        assert result.verified is True
        assert result.status == VerificationStatus.VERIFIED
        assert result.method == DomainVerificationMethod.DNS_TXT
        assert len(result.evidence) == 1
        assert result.error is None

    def test_create_failed_result(self, test_domain: str, remote_fed_did: str):
        """Test creating a failed verification result."""
        result = DomainVerificationResult(
            domain=test_domain,
            federation_did=remote_fed_did,
            verified=False,
            status=VerificationStatus.FAILED,
            method=DomainVerificationMethod.DNS_TXT,
            error="No matching DNS record found",
        )

        assert result.verified is False
        assert result.status == VerificationStatus.FAILED
        assert result.error is not None
        assert len(result.evidence) == 0

    def test_combined_method_result(self, test_domain: str, remote_fed_did: str):
        """Test result with multiple verification methods."""
        evidence = [
            VerificationEvidence(method=DomainVerificationMethod.DNS_TXT),
            VerificationEvidence(method=DomainVerificationMethod.MUTUAL_ATTESTATION),
        ]

        result = DomainVerificationResult(
            domain=test_domain,
            federation_did=remote_fed_did,
            verified=True,
            status=VerificationStatus.VERIFIED,
            method=DomainVerificationMethod.COMBINED,
            evidence=evidence,
        )

        assert result.method == DomainVerificationMethod.COMBINED
        assert len(result.evidence) == 2

    def test_to_dict_and_from_dict(self, test_domain: str, remote_fed_did: str):
        """Test serialization and deserialization."""
        original = DomainVerificationResult(
            domain=test_domain,
            federation_did=remote_fed_did,
            verified=True,
            status=VerificationStatus.VERIFIED,
            method=DomainVerificationMethod.DNS_TXT,
            evidence=[
                VerificationEvidence(
                    method=DomainVerificationMethod.DNS_TXT,
                    dns_record="test",
                )
            ],
            trust_level=0.85,
        )

        d = original.to_dict()
        restored = DomainVerificationResult.from_dict(d)

        assert restored.domain == original.domain
        assert restored.verified == original.verified
        assert restored.method == original.method
        assert len(restored.evidence) == 1
        assert restored.trust_level == 0.85


# =============================================================================
# DOMAIN CHALLENGE TESTS
# =============================================================================


class TestDomainChallenge:
    """Tests for DomainChallenge dataclass."""

    def test_create_challenge(self, test_domain: str, remote_fed_did: str):
        """Test creating a domain challenge."""
        challenge = DomainChallenge(
            challenge_id="test-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="abc123token",
        )

        assert challenge.challenge_id == "test-123"
        assert challenge.domain == test_domain
        assert challenge.status == ChallengeStatus.PENDING
        assert challenge.dns_subdomain == DNS_CHALLENGE_SUBDOMAIN
        assert challenge.token in challenge.dns_txt_value

    def test_challenge_expiration(self, test_domain: str, remote_fed_did: str):
        """Test challenge expiration detection."""
        # Create an already-expired challenge
        expired_time = datetime.now() - timedelta(hours=CHALLENGE_TTL_HOURS + 1)
        challenge = DomainChallenge(
            challenge_id="expired-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
            created_at=expired_time,
        )
        # Manually set expires_at since __post_init__ ran with expired_time
        challenge.expires_at = expired_time + timedelta(hours=CHALLENGE_TTL_HOURS)

        assert challenge.is_expired is True

    def test_challenge_not_expired(self, test_domain: str, remote_fed_did: str):
        """Test non-expired challenge."""
        challenge = DomainChallenge(
            challenge_id="fresh-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
        )

        assert challenge.is_expired is False

    def test_full_dns_record(self, test_domain: str, remote_fed_did: str):
        """Test full DNS record name generation."""
        challenge = DomainChallenge(
            challenge_id="dns-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
        )

        expected = f"{DNS_CHALLENGE_SUBDOMAIN}.{test_domain}"
        assert challenge.full_dns_record == expected

    def test_instructions(self, test_domain: str, remote_fed_did: str):
        """Test human-readable instructions."""
        challenge = DomainChallenge(
            challenge_id="instr-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="mytoken123",
        )

        instructions = challenge.instructions
        assert test_domain in instructions
        assert "TXT" in instructions
        assert challenge.dns_txt_value in instructions

    def test_to_dict_and_from_dict(self, test_domain: str, remote_fed_did: str):
        """Test serialization and deserialization."""
        original = DomainChallenge(
            challenge_id="serial-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token123",
        )

        d = original.to_dict()
        restored = DomainChallenge.from_dict(d)

        assert restored.challenge_id == original.challenge_id
        assert restored.domain == original.domain
        assert restored.token == original.token
        assert restored.dns_txt_value == original.dns_txt_value


# =============================================================================
# DOMAIN ATTESTATION TESTS
# =============================================================================


class TestDomainAttestation:
    """Tests for DomainAttestation dataclass."""

    def test_create_attestation(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test creating a domain attestation."""
        attestation = DomainAttestation(
            attestation_id="att-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )

        assert attestation.attestation_id == "att-123"
        assert attestation.domain == test_domain
        assert attestation.subject_did == remote_fed_did
        assert attestation.attester_did == local_fed_did
        assert attestation.attestation_type == AttestationType.DIRECT
        assert attestation.is_valid is True

    def test_attestation_expiration(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test attestation expiration."""
        past_time = datetime.now() - timedelta(days=400)
        attestation = DomainAttestation(
            attestation_id="exp-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
            created_at=past_time,
        )
        attestation.expires_at = past_time + timedelta(days=365)

        assert attestation.is_valid is False

    def test_attestation_revocation(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test attestation revocation."""
        attestation = DomainAttestation(
            attestation_id="rev-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )

        assert attestation.is_valid is True

        # Revoke it
        attestation.revoked_at = datetime.now() - timedelta(seconds=1)
        attestation.attestation_type = AttestationType.REVOKED

        assert attestation.is_valid is False

    def test_to_dict_and_from_dict(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test serialization and deserialization."""
        original = DomainAttestation(
            attestation_id="serial-att-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
            signature="sig123",
        )

        d = original.to_dict()
        restored = DomainAttestation.from_dict(d)

        assert restored.attestation_id == original.attestation_id
        assert restored.domain == original.domain
        assert restored.signature == original.signature


# =============================================================================
# CHALLENGE STORE TESTS
# =============================================================================


class TestChallengeStore:
    """Tests for ChallengeStore."""

    def test_add_and_get(self, challenge_store: ChallengeStore, test_domain: str, remote_fed_did: str):
        """Test adding and retrieving challenges."""
        challenge = DomainChallenge(
            challenge_id="store-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
        )

        challenge_store.add(challenge)
        retrieved = challenge_store.get("store-123")

        assert retrieved is not None
        assert retrieved.challenge_id == "store-123"

    def test_get_for_domain(self, challenge_store: ChallengeStore, test_domain: str, remote_fed_did: str):
        """Test getting challenges by domain."""
        for i in range(3):
            challenge = DomainChallenge(
                challenge_id=f"multi-{i}",
                domain=test_domain,
                federation_did=remote_fed_did,
                token=f"token{i}",
            )
            challenge_store.add(challenge)

        challenges = challenge_store.get_for_domain(test_domain)
        assert len(challenges) == 3

    def test_update(self, challenge_store: ChallengeStore, test_domain: str, remote_fed_did: str):
        """Test updating a challenge."""
        challenge = DomainChallenge(
            challenge_id="update-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
        )
        challenge_store.add(challenge)

        # Update status
        challenge.status = ChallengeStatus.VERIFIED
        challenge_store.update(challenge)

        retrieved = challenge_store.get("update-123")
        assert retrieved.status == ChallengeStatus.VERIFIED

    def test_remove(self, challenge_store: ChallengeStore, test_domain: str, remote_fed_did: str):
        """Test removing a challenge."""
        challenge = DomainChallenge(
            challenge_id="remove-123",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
        )
        challenge_store.add(challenge)

        challenge_store.remove("remove-123")

        assert challenge_store.get("remove-123") is None

    def test_cleanup_expired(self, challenge_store: ChallengeStore, test_domain: str, remote_fed_did: str):
        """Test cleaning up expired challenges."""
        # Add an expired challenge
        expired_time = datetime.now() - timedelta(hours=CHALLENGE_TTL_HOURS + 1)
        expired = DomainChallenge(
            challenge_id="expired-cleanup",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
            created_at=expired_time,
        )
        expired.expires_at = expired_time + timedelta(hours=CHALLENGE_TTL_HOURS)
        challenge_store.add(expired)

        # Add a fresh challenge
        fresh = DomainChallenge(
            challenge_id="fresh-cleanup",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token2",
        )
        challenge_store.add(fresh)

        removed = challenge_store.cleanup_expired()

        assert removed == 1
        assert challenge_store.get("expired-cleanup") is None
        assert challenge_store.get("fresh-cleanup") is not None


# =============================================================================
# ATTESTATION STORE TESTS
# =============================================================================


class TestAttestationStore:
    """Tests for AttestationStore."""

    def test_add_and_get(
        self,
        attestation_store: AttestationStore,
        test_domain: str,
        remote_fed_did: str,
        local_fed_did: str,
    ):
        """Test adding and retrieving attestations."""
        attestation = DomainAttestation(
            attestation_id="att-store-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )

        attestation_store.add(attestation)
        retrieved = attestation_store.get("att-store-123")

        assert retrieved is not None
        assert retrieved.attestation_id == "att-store-123"

    def test_get_for_domain(
        self,
        attestation_store: AttestationStore,
        test_domain: str,
        remote_fed_did: str,
        local_fed_did: str,
    ):
        """Test getting attestations by domain."""
        for i in range(3):
            attestation = DomainAttestation(
                attestation_id=f"att-domain-{i}",
                domain=test_domain,
                subject_did=remote_fed_did,
                attester_did=f"did:vkb:web:attester-{i}",
            )
            attestation_store.add(attestation)

        attestations = attestation_store.get_for_domain(test_domain)
        assert len(attestations) == 3

    def test_get_for_domain_with_subject_filter(
        self,
        attestation_store: AttestationStore,
        test_domain: str,
        remote_fed_did: str,
        local_fed_did: str,
    ):
        """Test filtering attestations by subject."""
        attestation1 = DomainAttestation(
            attestation_id="att-subj-1",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )
        attestation2 = DomainAttestation(
            attestation_id="att-subj-2",
            domain=test_domain,
            subject_did="did:vkb:web:other-fed",
            attester_did=local_fed_did,
        )

        attestation_store.add(attestation1)
        attestation_store.add(attestation2)

        filtered = attestation_store.get_for_domain(test_domain, subject_did=remote_fed_did)
        assert len(filtered) == 1
        assert filtered[0].subject_did == remote_fed_did

    def test_revoke(
        self,
        attestation_store: AttestationStore,
        test_domain: str,
        remote_fed_did: str,
        local_fed_did: str,
    ):
        """Test revoking an attestation."""
        attestation = DomainAttestation(
            attestation_id="att-revoke-123",
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )
        attestation_store.add(attestation)

        result = attestation_store.revoke("att-revoke-123")

        assert result is True
        retrieved = attestation_store.get("att-revoke-123")
        assert retrieved.attestation_type == AttestationType.REVOKED
        assert retrieved.is_valid is False

    def test_get_for_subject(
        self,
        attestation_store: AttestationStore,
        test_domain: str,
        remote_fed_did: str,
        local_fed_did: str,
    ):
        """Test getting all attestations for a subject."""
        for i in range(2):
            attestation = DomainAttestation(
                attestation_id=f"att-for-subj-{i}",
                domain=f"domain{i}.example.com",
                subject_did=remote_fed_did,
                attester_did=f"did:vkb:web:attester-{i}",
            )
            attestation_store.add(attestation)

        attestations = attestation_store.get_for_subject(remote_fed_did)
        assert len(attestations) == 2


# =============================================================================
# CREATE CHALLENGE TESTS
# =============================================================================


class TestCreateChallenge:
    """Tests for create_challenge function."""

    @pytest.mark.asyncio
    async def test_create_challenge_basic(self, test_domain: str, remote_fed_did: str):
        """Test basic challenge creation."""
        challenge = await create_challenge(test_domain, remote_fed_did)

        assert challenge.domain == test_domain.lower()
        assert challenge.federation_did == remote_fed_did
        assert challenge.status == ChallengeStatus.PENDING
        assert len(challenge.token) > 0
        assert challenge.challenge_id is not None

    @pytest.mark.asyncio
    async def test_create_challenge_stored(self, test_domain: str, remote_fed_did: str):
        """Test that challenge is stored in global store."""
        challenge = await create_challenge(test_domain, remote_fed_did)

        store = get_challenge_store()
        retrieved = store.get(challenge.challenge_id)

        assert retrieved is not None
        assert retrieved.challenge_id == challenge.challenge_id

    @pytest.mark.asyncio
    async def test_create_challenge_dns_value_format(self, test_domain: str, remote_fed_did: str):
        """Test DNS TXT value format."""
        challenge = await create_challenge(test_domain, remote_fed_did)

        assert challenge.dns_txt_value.startswith(CHALLENGE_PREFIX)
        assert challenge.token in challenge.dns_txt_value

    def test_create_challenge_sync(self, test_domain: str, remote_fed_did: str):
        """Test synchronous challenge creation."""
        challenge = create_challenge_sync(test_domain, remote_fed_did)

        assert challenge.domain == test_domain.lower()
        assert challenge.status == ChallengeStatus.PENDING


# =============================================================================
# CHECK CHALLENGE TESTS
# =============================================================================


class TestCheckChallenge:
    """Tests for check_challenge function."""

    @pytest.mark.asyncio
    async def test_check_nonexistent_challenge(self):
        """Test checking a challenge that doesn't exist."""
        result = await check_challenge("nonexistent-id")

        assert result.verified is False
        assert result.status == VerificationStatus.ERROR
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_expired_challenge(self, test_domain: str, remote_fed_did: str):
        """Test checking an expired challenge."""
        # Create a challenge that's already expired
        store = get_challenge_store()
        expired_time = datetime.now() - timedelta(hours=CHALLENGE_TTL_HOURS + 1)
        challenge = DomainChallenge(
            challenge_id="expired-check",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
            created_at=expired_time,
        )
        challenge.expires_at = expired_time + timedelta(hours=CHALLENGE_TTL_HOURS)
        store.add(challenge)

        result = await check_challenge("expired-check")

        assert result.verified is False
        assert result.status == VerificationStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_check_already_verified_challenge(self, test_domain: str, remote_fed_did: str):
        """Test checking an already-verified challenge."""
        store = get_challenge_store()
        challenge = DomainChallenge(
            challenge_id="already-verified",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
            status=ChallengeStatus.VERIFIED,
        )
        challenge.verified_at = datetime.now()
        store.add(challenge)

        result = await check_challenge("already-verified")

        assert result.verified is True
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_check_challenge_dns_not_found(self, test_domain: str, remote_fed_did: str):
        """Test checking challenge when DNS record not found."""
        challenge = await create_challenge(test_domain, remote_fed_did)

        import dns.resolver

        with patch("dns.resolver.Resolver") as mock_resolver:
            mock_resolver.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()

            result = await check_challenge(challenge.challenge_id)

            assert result.verified is False
            assert result.status == VerificationStatus.PENDING
            assert "not found" in result.error.lower()


# =============================================================================
# VERIFY DOMAIN TESTS
# =============================================================================


class TestVerifyDomain:
    """Tests for verify_domain function."""

    @pytest.mark.asyncio
    async def test_verify_domain_via_dns(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification via DNS TXT record."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (True, f"valence-federation={remote_fed_did}", None)

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[DomainVerificationMethod.DNS_TXT],
                    use_cache=False,
                )

                assert result.verified is True
                assert result.method == DomainVerificationMethod.DNS_TXT
                assert len(result.evidence) == 1
                assert result.evidence[0].method == DomainVerificationMethod.DNS_TXT

    @pytest.mark.asyncio
    async def test_verify_domain_via_did_document(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification via DID document."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (False, None, "Not found")

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (True, f"https://{test_domain}", None)

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[DomainVerificationMethod.DID_DOCUMENT],
                    use_cache=False,
                )

                assert result.verified is True
                assert result.method == DomainVerificationMethod.DID_DOCUMENT

    @pytest.mark.asyncio
    async def test_verify_domain_via_attestation(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification via mutual attestation."""
        # Create an attestation
        await create_attestation(
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did="did:vkb:web:trusted-attester",
        )

        with patch("valence.federation.domain_verification.get_federation_trust") as mock_trust:
            mock_trust.return_value = 0.8  # High trust

            with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
                mock_dns.return_value = (False, None, "Not found")

                with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                    mock_did.return_value = (False, None, "Not found")

                    result = await verify_domain(
                        test_domain,
                        remote_fed_did,
                        local_did=local_fed_did,
                        methods=[DomainVerificationMethod.MUTUAL_ATTESTATION],
                        use_cache=False,
                    )

                    assert result.verified is True
                    assert result.method == DomainVerificationMethod.MUTUAL_ATTESTATION

    @pytest.mark.asyncio
    async def test_verify_domain_combined_methods(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification with multiple methods succeeding."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (True, f"valence-federation={remote_fed_did}", None)

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (True, f"https://{test_domain}", None)

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[
                        DomainVerificationMethod.DNS_TXT,
                        DomainVerificationMethod.DID_DOCUMENT,
                    ],
                    use_cache=False,
                )

                assert result.verified is True
                assert result.method == DomainVerificationMethod.COMBINED
                assert len(result.evidence) == 2

    @pytest.mark.asyncio
    async def test_verify_domain_require_all(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification requiring all methods to pass."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (True, f"valence-federation={remote_fed_did}", None)

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[
                        DomainVerificationMethod.DNS_TXT,
                        DomainVerificationMethod.DID_DOCUMENT,
                    ],
                    require_all=True,
                    use_cache=False,
                )

                # Should fail because DID didn't pass
                assert result.verified is False

    @pytest.mark.asyncio
    async def test_verify_domain_all_fail(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test domain verification when all methods fail."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (False, None, "DNS error")

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "DID error")

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[
                        DomainVerificationMethod.DNS_TXT,
                        DomainVerificationMethod.DID_DOCUMENT,
                    ],
                    use_cache=False,
                )

                assert result.verified is False
                assert result.status == VerificationStatus.FAILED
                assert result.error is not None

    def test_verify_domain_sync(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test synchronous domain verification."""
        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (True, f"valence-federation={remote_fed_did}", None)

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                result = verify_domain_sync(
                    test_domain,
                    remote_fed_did,
                    local_did=local_fed_did,
                    methods=[DomainVerificationMethod.DNS_TXT],
                    use_cache=False,
                )

                assert result.verified is True


# =============================================================================
# ATTESTATION FUNCTION TESTS
# =============================================================================


class TestAttestationFunctions:
    """Tests for attestation-related functions."""

    @pytest.mark.asyncio
    async def test_create_attestation(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test creating an attestation."""
        attestation = await create_attestation(
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
            signature="test-signature",
        )

        assert attestation.domain == test_domain.lower()
        assert attestation.subject_did == remote_fed_did
        assert attestation.attester_did == local_fed_did
        assert attestation.signature == "test-signature"
        assert attestation.is_valid is True

    @pytest.mark.asyncio
    async def test_revoke_attestation(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test revoking an attestation."""
        attestation = await create_attestation(
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=local_fed_did,
        )

        result = await revoke_attestation(attestation.attestation_id)

        assert result is True

        # Verify it's revoked in the store
        store = get_attestation_store()
        retrieved = store.get(attestation.attestation_id)
        assert retrieved.is_valid is False

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_attestation(self):
        """Test revoking a non-existent attestation."""
        result = await revoke_attestation("nonexistent-id")
        assert result is False


# =============================================================================
# EXTERNAL AUTHORITY TESTS
# =============================================================================


class TestExternalAuthority:
    """Tests for external authority verification."""

    @pytest.mark.asyncio
    async def test_external_client_success(self, test_domain: str, remote_fed_did: str):
        """Test successful external authority verification."""
        mock_client = MagicMock(spec=ExternalAuthorityClient)
        mock_client.verify_domain = AsyncMock(return_value=(True, {"verified": True, "authority": "test"}, None))

        set_external_client(mock_client)

        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (False, None, "Not found")

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    methods=[DomainVerificationMethod.EXTERNAL_AUTHORITY],
                    use_cache=False,
                )

                assert result.verified is True
                assert result.method == DomainVerificationMethod.EXTERNAL_AUTHORITY

    @pytest.mark.asyncio
    async def test_external_client_failure(self, test_domain: str, remote_fed_did: str):
        """Test failed external authority verification."""
        mock_client = MagicMock(spec=ExternalAuthorityClient)
        mock_client.verify_domain = AsyncMock(return_value=(False, None, "Authority rejected claim"))

        set_external_client(mock_client)

        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            mock_dns.return_value = (False, None, "Not found")

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                result = await verify_domain(
                    test_domain,
                    remote_fed_did,
                    methods=[DomainVerificationMethod.EXTERNAL_AUTHORITY],
                    use_cache=False,
                )

                assert result.verified is False


# =============================================================================
# BATCH OPERATIONS TESTS
# =============================================================================


class TestBatchOperations:
    """Tests for batch verification operations."""

    @pytest.mark.asyncio
    async def test_verify_multiple_domains(self, local_fed_did: str):
        """Test verifying multiple domains concurrently."""
        claims = [
            ("domain1.example.com", "did:vkb:web:fed1"),
            ("domain2.example.com", "did:vkb:web:fed2"),
            ("domain3.example.com", "did:vkb:web:fed3"),
        ]

        with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
            # First two succeed, third fails
            mock_dns.side_effect = [
                (True, "record1", None),
                (True, "record2", None),
                (False, None, "Error"),
            ]

            with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                mock_did.return_value = (False, None, "Not found")

                results = await verify_multiple_domains(
                    claims,
                    local_did=local_fed_did,
                    methods=[DomainVerificationMethod.DNS_TXT],
                )

                assert len(results) == 3
                assert results[0].verified is True
                assert results[1].verified is True
                assert results[2].verified is False


# =============================================================================
# UTILITY FUNCTION TESTS
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_challenges(self, test_domain: str, remote_fed_did: str):
        """Test cleaning up expired challenges."""
        store = get_challenge_store()

        # Add expired challenge
        expired_time = datetime.now() - timedelta(hours=CHALLENGE_TTL_HOURS + 1)
        expired = DomainChallenge(
            challenge_id="exp-util",
            domain=test_domain,
            federation_did=remote_fed_did,
            token="token",
            created_at=expired_time,
        )
        expired.expires_at = expired_time + timedelta(hours=CHALLENGE_TTL_HOURS)
        store.add(expired)

        # Add fresh challenge
        fresh = await create_challenge(test_domain, remote_fed_did)

        removed = cleanup_expired_challenges()

        assert removed == 1
        assert store.get("exp-util") is None
        assert store.get(fresh.challenge_id) is not None

    @pytest.mark.asyncio
    async def test_get_challenge_stats(self, test_domain: str, remote_fed_did: str):
        """Test getting challenge statistics."""
        # Create various challenges
        await create_challenge(test_domain, remote_fed_did)  # pending
        await create_challenge("other.example.com", remote_fed_did)  # pending

        stats = get_challenge_stats()

        assert stats["total"] == 2
        assert stats["pending"] == 2
        assert stats["verified"] == 0

    @pytest.mark.asyncio
    async def test_get_attestation_stats(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test getting attestation statistics."""
        # Create attestations
        await create_attestation(test_domain, remote_fed_did, local_fed_did)
        att2 = await create_attestation("other.example.com", remote_fed_did, local_fed_did)
        await revoke_attestation(att2.attestation_id)

        stats = get_attestation_stats()

        assert stats["total"] == 2
        assert stats["valid"] == 1
        assert stats["revoked"] == 1


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegration:
    """Integration tests for the complete verification flow."""

    @pytest.mark.asyncio
    async def test_challenge_flow_complete(self, test_domain: str, remote_fed_did: str):
        """Test the complete challenge verification flow."""
        # Step 1: Create challenge
        challenge = await create_challenge(test_domain, remote_fed_did)

        assert challenge.status == ChallengeStatus.PENDING

        # Step 2: Simulate DNS record being added by mocking the check
        with patch("dns.resolver.Resolver") as MockResolver:  # noqa: N806
            mock_resolver_instance = MagicMock()
            MockResolver.return_value = mock_resolver_instance

            # Mock the TXT record response
            mock_rdata = MagicMock()
            mock_rdata.__str__ = lambda self: f'"{challenge.dns_txt_value}"'
            mock_resolver_instance.resolve.return_value = [mock_rdata]

            # Step 3: Check challenge
            result = await check_challenge(challenge.challenge_id)

            assert result.verified is True
            assert result.status == VerificationStatus.VERIFIED
            assert result.method == DomainVerificationMethod.DNS_CHALLENGE

            # Step 4: Verify challenge status updated
            store = get_challenge_store()
            updated = store.get(challenge.challenge_id)
            assert updated.status == ChallengeStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_attestation_flow_complete(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test the complete attestation verification flow."""
        # Step 1: Trusted federation creates attestation
        trusted_fed = "did:vkb:web:highly-trusted-federation"
        attestation = await create_attestation(
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did=trusted_fed,
        )

        # Step 2: Verify domain via attestation (with mock trust)
        with patch("valence.federation.domain_verification.get_federation_trust") as mock_trust:
            mock_trust.return_value = 0.9  # High trust

            with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
                mock_dns.return_value = (False, None, "Not found")

                with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                    mock_did.return_value = (False, None, "Not found")

                    result = await verify_domain(
                        test_domain,
                        remote_fed_did,
                        local_did=local_fed_did,
                        methods=[DomainVerificationMethod.MUTUAL_ATTESTATION],
                        use_cache=False,
                    )

                    assert result.verified is True
                    assert result.method == DomainVerificationMethod.MUTUAL_ATTESTATION

        # Step 3: Revoke attestation
        revoked = await revoke_attestation(attestation.attestation_id)
        assert revoked is True

        # Step 4: Verification should now fail
        with patch("valence.federation.domain_verification.get_federation_trust") as mock_trust:
            mock_trust.return_value = 0.9

            with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
                mock_dns.return_value = (False, None, "Not found")

                with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                    mock_did.return_value = (False, None, "Not found")

                    result = await verify_domain(
                        test_domain,
                        remote_fed_did,
                        local_did=local_fed_did,
                        methods=[DomainVerificationMethod.MUTUAL_ATTESTATION],
                        use_cache=False,
                    )

                    assert result.verified is False

    @pytest.mark.asyncio
    async def test_fallback_verification_chain(self, test_domain: str, remote_fed_did: str, local_fed_did: str):
        """Test verification trying multiple methods until one succeeds."""
        # DNS fails, DID fails, but attestation succeeds
        await create_attestation(
            domain=test_domain,
            subject_did=remote_fed_did,
            attester_did="did:vkb:web:trusted",
        )

        with patch("valence.federation.domain_verification.get_federation_trust") as mock_trust:
            mock_trust.return_value = 0.8

            with patch("valence.federation.domain_verification.verify_dns_txt_record") as mock_dns:
                mock_dns.return_value = (False, None, "DNS error")

                with patch("valence.federation.domain_verification.verify_did_document_claim") as mock_did:
                    mock_did.return_value = (False, None, "DID error")

                    result = await verify_domain(
                        test_domain,
                        remote_fed_did,
                        local_did=local_fed_did,
                        methods=[
                            DomainVerificationMethod.DNS_TXT,
                            DomainVerificationMethod.DID_DOCUMENT,
                            DomainVerificationMethod.MUTUAL_ATTESTATION,
                        ],
                        use_cache=False,
                    )

                    assert result.verified is True
                    # Only attestation should have evidence
                    assert len(result.evidence) == 1
                    assert result.evidence[0].method == DomainVerificationMethod.MUTUAL_ATTESTATION
