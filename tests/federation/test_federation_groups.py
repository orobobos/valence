"""Tests for Federation Group management (Issue #73).

Tests the integration layer that links federations to MLS groups,
building on the MLS primitives from Issue #72.
"""

from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from valence.federation.groups import (
    # Classes
    FederationGroup,
    # Enums
    GroupRole,
    GroupState,
    GroupStatus,
    MemberStatus,
    # Exceptions
    add_member,
    clear_federation_store,
    # Federation Functions (Issue #73)
    create_federation_group,
    # MLS Functions
    delete_federation_group,
    get_federation_group,
    get_federation_group_info,
    get_federation_member_role,
    get_group_by_federation_id,
    list_federation_group_members,
    list_federation_groups,
    # Storage
    store_federation_group,
    verify_federation_membership,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def clear_store():
    """Clear the in-memory store before each test."""
    clear_federation_store()
    yield
    clear_federation_store()


@pytest.fixture
def federation_id():
    """Generate a test federation ID."""
    return uuid4()


@pytest.fixture
def creator_did():
    """Generate a test creator DID."""
    return "did:vkb:web:example.com"


@pytest.fixture
def creator_signing_key():
    """Generate a signing key for the creator."""
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def member_did():
    """Generate a test member DID."""
    return "did:vkb:web:member.example.com"


@pytest.fixture
def member_signing_key():
    """Generate a signing key for a member."""
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def test_federation_group(federation_id, creator_did, creator_signing_key):
    """Create a test federation group."""
    group, _ = create_federation_group(
        federation_id=federation_id,
        creator_did=creator_did,
        creator_signing_key=creator_signing_key,
        name="Test Federation Group",
        description="A test group for federation",
    )
    return group


# =============================================================================
# FEDERATION GROUP CREATION TESTS
# =============================================================================


class TestFederationGroupCreation:
    """Tests for create_federation_group function (Issue #73 core)."""

    def test_create_basic_federation_group(self, federation_id, creator_did, creator_signing_key):
        """Test creating a basic federation group."""
        group, creator_kp = create_federation_group(
            federation_id=federation_id,
            creator_did=creator_did,
            creator_signing_key=creator_signing_key,
        )

        assert group.id is not None
        assert group.federation_id == federation_id
        assert group.creator_did == creator_did
        assert group.status == GroupStatus.ACTIVE
        assert creator_kp is not None

    def test_creator_is_first_member_with_admin_role(self, test_federation_group, creator_did):
        """Test that creator becomes first member with admin role."""
        assert test_federation_group.member_count == 1
        assert test_federation_group.has_member(creator_did)

        member = test_federation_group.get_member(creator_did)
        assert member is not None
        assert member.role == GroupRole.ADMIN
        assert member.status == MemberStatus.ACTIVE

    def test_initial_epoch_is_zero(self, test_federation_group):
        """Test that group starts at epoch 0."""
        assert test_federation_group.epoch == 0

    def test_group_has_underlying_mls_state(self, test_federation_group):
        """Test that federation group wraps MLS GroupState."""
        assert test_federation_group.group_state is not None
        assert isinstance(test_federation_group.group_state, GroupState)

    def test_create_with_custom_metadata(self, federation_id, creator_did, creator_signing_key):
        """Test creating group with custom name, description, domains."""
        group, _ = create_federation_group(
            federation_id=federation_id,
            creator_did=creator_did,
            creator_signing_key=creator_signing_key,
            name="Custom Group",
            description="A custom group for testing",
            allowed_domains=["science", "technology"],
            metadata={"priority": "high"},
        )

        assert group.name == "Custom Group"
        assert group.metadata["description"] == "A custom group for testing"
        assert "science" in group.allowed_domains
        assert "technology" in group.allowed_domains
        assert group.metadata.get("priority") == "high"

    def test_create_generates_signing_key_if_not_provided(self, federation_id, creator_did):
        """Test that signing key is auto-generated if not provided."""
        group, creator_kp = create_federation_group(
            federation_id=federation_id,
            creator_did=creator_did,
        )

        assert group is not None
        assert creator_kp is not None


# =============================================================================
# FEDERATION GROUP PROPERTIES TESTS
# =============================================================================


class TestFederationGroupProperties:
    """Tests for FederationGroup properties."""

    def test_epoch_property(self, test_federation_group):
        """Test epoch property mirrors underlying group state."""
        assert test_federation_group.epoch == test_federation_group.group_state.epoch

    def test_name_property(self, test_federation_group):
        """Test name property."""
        assert test_federation_group.name == "Test Federation Group"

    def test_status_property(self, test_federation_group):
        """Test status property."""
        assert test_federation_group.status == GroupStatus.ACTIVE

    def test_creator_did_property(self, test_federation_group, creator_did):
        """Test creator_did property."""
        assert test_federation_group.creator_did == creator_did

    def test_member_count_property(self, test_federation_group):
        """Test member_count returns active members only."""
        assert test_federation_group.member_count == 1

    def test_members_property(self, test_federation_group, creator_did):
        """Test members property returns active members."""
        members = test_federation_group.members
        assert len(members) == 1
        assert members[0].did == creator_did


# =============================================================================
# FEDERATION GROUP QUERY TESTS
# =============================================================================


class TestFederationGroupQueries:
    """Tests for federation group query functions."""

    def test_get_federation_group_info(self, test_federation_group, creator_did):
        """Test getting federation group information."""
        info = get_federation_group_info(test_federation_group)

        assert info["id"] == str(test_federation_group.id)
        assert info["federation_id"] == str(test_federation_group.federation_id)
        assert info["name"] == "Test Federation Group"
        assert info["creator_did"] == creator_did
        assert info["status"] == "active"
        assert info["epoch"] == 0
        assert info["member_count"] == 1
        assert creator_did in info["admins"]

    def test_list_federation_group_members(self, test_federation_group, creator_did):
        """Test listing group members."""
        members = list_federation_group_members(test_federation_group)

        assert len(members) == 1
        assert members[0]["member_did"] == creator_did
        assert members[0]["role"] == "admin"
        assert members[0]["status"] == "active"

    def test_verify_federation_membership_true(self, test_federation_group, creator_did):
        """Test membership verification for existing member."""
        assert verify_federation_membership(test_federation_group, creator_did) is True

    def test_verify_federation_membership_false(self, test_federation_group, member_did):
        """Test membership verification for non-member."""
        assert verify_federation_membership(test_federation_group, member_did) is False

    def test_get_federation_member_role(self, test_federation_group, creator_did, member_did):
        """Test getting member role."""
        assert get_federation_member_role(test_federation_group, creator_did) == GroupRole.ADMIN
        assert get_federation_member_role(test_federation_group, member_did) is None


# =============================================================================
# FEDERATION GROUP SERIALIZATION TESTS
# =============================================================================


class TestFederationGroupSerialization:
    """Tests for FederationGroup serialization."""

    def test_to_dict_and_from_dict(self, test_federation_group):
        """Test round-trip serialization."""
        data = test_federation_group.to_dict()
        restored = FederationGroup.from_dict(data)

        assert restored.id == test_federation_group.id
        assert restored.federation_id == test_federation_group.federation_id
        assert restored.name == test_federation_group.name
        assert restored.epoch == test_federation_group.epoch
        assert restored.member_count == test_federation_group.member_count
        assert restored.allowed_domains == test_federation_group.allowed_domains

    def test_to_dict_contains_group_state(self, test_federation_group):
        """Test that to_dict includes underlying group state."""
        data = test_federation_group.to_dict()

        assert "group_state" in data
        assert data["group_state"]["epoch"] == test_federation_group.epoch


# =============================================================================
# FEDERATION GROUP STORAGE TESTS
# =============================================================================


class TestFederationGroupStorage:
    """Tests for in-memory federation group storage."""

    def test_store_and_get_group(self, test_federation_group):
        """Test storing and retrieving a federation group."""
        store_federation_group(test_federation_group)

        retrieved = get_federation_group(test_federation_group.id)
        assert retrieved is not None
        assert retrieved.id == test_federation_group.id
        assert retrieved.federation_id == test_federation_group.federation_id

    def test_get_group_by_federation_id(self, test_federation_group):
        """Test getting group by federation ID."""
        store_federation_group(test_federation_group)

        retrieved = get_group_by_federation_id(test_federation_group.federation_id)
        assert retrieved is not None
        assert retrieved.id == test_federation_group.id

    def test_get_nonexistent_group(self):
        """Test getting a group that doesn't exist."""
        assert get_federation_group(uuid4()) is None
        assert get_group_by_federation_id(uuid4()) is None

    def test_delete_group(self, test_federation_group):
        """Test deleting a federation group."""
        store_federation_group(test_federation_group)
        assert get_federation_group(test_federation_group.id) is not None

        result = delete_federation_group(test_federation_group.id)
        assert result is True
        assert get_federation_group(test_federation_group.id) is None
        assert get_group_by_federation_id(test_federation_group.federation_id) is None

    def test_delete_nonexistent_group(self):
        """Test deleting a group that doesn't exist."""
        result = delete_federation_group(uuid4())
        assert result is False

    def test_list_groups(self, creator_did, creator_signing_key):
        """Test listing all federation groups."""
        # Create multiple groups
        group1, _ = create_federation_group(uuid4(), creator_did, creator_signing_key, name="Group 1")
        group2, _ = create_federation_group(uuid4(), creator_did, creator_signing_key, name="Group 2")

        store_federation_group(group1)
        store_federation_group(group2)

        groups = list_federation_groups()
        assert len(groups) == 2


# =============================================================================
# INTEGRATION WITH MLS OPERATIONS TESTS
# =============================================================================


class TestMLSIntegration:
    """Tests for integration with underlying MLS operations."""

    def test_add_member_updates_federation_group(
        self,
        test_federation_group,
        creator_did,
        creator_signing_key,
        member_did,
        member_signing_key,
    ):
        """Test that MLS add_member updates the federation group properly."""
        from valence.federation.groups import KeyPackage

        # Generate member's key package (signing_key is already bytes)
        member_keypackage, _ = KeyPackage.generate(
            member_did=member_did,
            signing_private_key=member_signing_key,
        )

        # Get the underlying group state
        initial_epoch = test_federation_group.epoch

        # Add member using MLS add_member
        updated_state, welcome, commit = add_member(
            group=test_federation_group.group_state,
            new_member_did=member_did,
            new_member_key_package=member_keypackage,
            adder_did=creator_did,
            adder_signing_key=creator_signing_key,
        )

        # Update the federation group's state
        test_federation_group.group_state = updated_state

        # Verify the update
        assert test_federation_group.epoch == initial_epoch + 1
        assert test_federation_group.member_count == 2
        assert test_federation_group.has_member(member_did)

    def test_federation_group_reflects_mls_state_changes(self, test_federation_group, creator_did):
        """Test that federation group properties reflect MLS state changes."""
        # Get initial values
        initial_epoch = test_federation_group.epoch
        initial_members = test_federation_group.member_count

        # Verify they match underlying state
        assert initial_epoch == test_federation_group.group_state.epoch
        assert initial_members == len(test_federation_group.group_state.get_active_members())


# =============================================================================
# DOMAIN INTEGRATION TESTS
# =============================================================================


class TestDomainIntegration:
    """Tests for domain-related features."""

    def test_allowed_domains_stored(self, federation_id, creator_did, creator_signing_key):
        """Test that allowed_domains are stored correctly."""
        group, _ = create_federation_group(
            federation_id=federation_id,
            creator_did=creator_did,
            creator_signing_key=creator_signing_key,
            allowed_domains=["science.physics", "science.chemistry"],
        )

        assert len(group.allowed_domains) == 2
        assert "science.physics" in group.allowed_domains
        assert "science.chemistry" in group.allowed_domains

    def test_allowed_domains_in_serialization(self, federation_id, creator_did, creator_signing_key):
        """Test that allowed_domains survive serialization."""
        group, _ = create_federation_group(
            federation_id=federation_id,
            creator_did=creator_did,
            creator_signing_key=creator_signing_key,
            allowed_domains=["tech", "science"],
        )

        data = group.to_dict()
        restored = FederationGroup.from_dict(data)

        assert restored.allowed_domains == group.allowed_domains
