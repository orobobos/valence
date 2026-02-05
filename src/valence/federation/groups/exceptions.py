"""Exceptions for MLS-style group encryption."""


class MLSError(Exception):
    """Base exception for MLS-related errors."""

    pass


class GroupNotFoundError(MLSError):
    """Group does not exist."""

    pass


class MemberExistsError(MLSError):
    """Member is already in the group."""

    pass


class MemberNotFoundError(MLSError):
    """Member is not in the group."""

    pass


class InvalidKeyPackageError(MLSError):
    """KeyPackage is invalid or expired."""

    pass


class GroupFullError(MLSError):
    """Group has reached maximum capacity."""

    pass


class PermissionDeniedError(MLSError):
    """Member does not have required permission."""

    pass


class EpochMismatchError(MLSError):
    """Epoch does not match expected value."""

    pass
