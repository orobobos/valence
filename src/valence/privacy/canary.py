# Valence Canary Token System
"""
Canary tokens detect unauthorized sharing by embedding trackable markers
in shared content. When a canary is detected externally, an alert is raised.

This is an EXPERIMENTAL feature for privacy-conscious sharing.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional


class EmbedStrategy(Enum):
    """Strategies for embedding canary tokens in content."""
    
    VISIBLE = "visible"  # Human-readable marker at end of content
    INVISIBLE_UNICODE = "invisible_unicode"  # Zero-width Unicode characters
    WORD_PATTERN = "word_pattern"  # Specific word choices encode the token
    WHITESPACE = "whitespace"  # Trailing spaces encode bits


# Zero-width characters for steganographic encoding
ZERO_WIDTH_CHARS = {
    "0": "\u200b",  # Zero-width space
    "1": "\u200c",  # Zero-width non-joiner
    "2": "\u200d",  # Zero-width joiner
    "3": "\ufeff",  # Zero-width no-break space
}

# Reverse mapping for decoding
ZERO_WIDTH_REVERSE = {v: k for k, v in ZERO_WIDTH_CHARS.items()}


@dataclass
class CanaryToken:
    """A canary token that can be embedded in shared content."""
    
    token_id: str
    share_id: str  # Which share this canary belongs to
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    secret_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def generate(cls, share_id: str, metadata: Optional[dict] = None) -> "CanaryToken":
        """Generate a new canary token for a share."""
        return cls(
            token_id=str(uuid.uuid4()),
            share_id=share_id,
            metadata=metadata or {},
        )
    
    def signature(self) -> str:
        """Generate HMAC signature for verification."""
        message = f"{self.token_id}:{self.share_id}".encode()
        return hmac.new(self.secret_key, message, hashlib.sha256).hexdigest()[:16]
    
    def to_marker(self) -> str:
        """Convert token to a compact marker string (for visible embedding)."""
        sig = self.signature()
        # Format: v1:<short_token_id>:<signature>
        short_id = self.token_id.replace("-", "")[:12]
        return f"v1:{short_id}:{sig}"
    
    @classmethod
    def marker_pattern(cls) -> re.Pattern:
        """Regex pattern to find canary markers in content."""
        return re.compile(r"v1:([a-f0-9]{12}):([a-f0-9]{16})")


@dataclass
class CanaryDetection:
    """Record of a canary being detected (potential leak)."""
    
    token_id: str
    share_id: str
    detected_at: datetime
    source: str  # Where the canary was found
    context: str  # Surrounding content
    confidence: float  # 0.0-1.0, how confident we are this is our canary
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "token_id": self.token_id,
            "share_id": self.share_id,
            "detected_at": self.detected_at.isoformat(),
            "source": self.source,
            "context": self.context[:500],  # Truncate context
            "confidence": self.confidence,
        }


class CanaryEmbedder:
    """Embeds canary tokens into content using various strategies."""
    
    @staticmethod
    def embed(content: str, token: CanaryToken, strategy: EmbedStrategy) -> str:
        """Embed a canary token into content."""
        if strategy == EmbedStrategy.VISIBLE:
            return CanaryEmbedder._embed_visible(content, token)
        elif strategy == EmbedStrategy.INVISIBLE_UNICODE:
            return CanaryEmbedder._embed_invisible(content, token)
        elif strategy == EmbedStrategy.WHITESPACE:
            return CanaryEmbedder._embed_whitespace(content, token)
        elif strategy == EmbedStrategy.WORD_PATTERN:
            # Word pattern is complex and content-dependent
            # Fall back to invisible for now
            return CanaryEmbedder._embed_invisible(content, token)
        else:
            raise ValueError(f"Unknown embed strategy: {strategy}")
    
    @staticmethod
    def _embed_visible(content: str, token: CanaryToken) -> str:
        """Add a visible marker at the end of content."""
        marker = token.to_marker()
        # Add marker as a comment-style suffix
        return f"{content}\n\n[ref:{marker}]"
    
    @staticmethod
    def _embed_invisible(content: str, token: CanaryToken) -> str:
        """Embed token using zero-width Unicode characters."""
        marker = token.to_marker()
        # Convert marker to base-4 encoding using zero-width chars
        invisible = ""
        for char in marker:
            # Encode each character's hex value
            code = ord(char)
            # Use base-4 representation (2 chars per byte)
            for _ in range(4):
                digit = str(code % 4)
                invisible += ZERO_WIDTH_CHARS[digit]
                code //= 4
        
        # Insert invisible marker after first paragraph
        paragraphs = content.split("\n\n", 1)
        if len(paragraphs) > 1:
            return f"{paragraphs[0]}{invisible}\n\n{paragraphs[1]}"
        return f"{content}{invisible}"
    
    @staticmethod
    def _embed_whitespace(content: str, token: CanaryToken) -> str:
        """Embed token using trailing whitespace patterns."""
        marker = token.to_marker()
        lines = content.split("\n")
        
        # Convert marker to bits
        bits = "".join(format(ord(c), "08b") for c in marker)
        
        # Add trailing spaces to encode bits (2 spaces = 0, 4 spaces = 1)
        result_lines = []
        bit_idx = 0
        for line in lines:
            stripped = line.rstrip()
            if bit_idx < len(bits):
                spaces = "  " if bits[bit_idx] == "0" else "    "
                result_lines.append(stripped + spaces)
                bit_idx += 1
            else:
                result_lines.append(stripped)
        
        return "\n".join(result_lines)


class CanaryExtractor:
    """Extracts canary tokens from content."""
    
    @staticmethod
    def extract_all(content: str) -> list[dict]:
        """Extract all potential canary markers from content."""
        results = []
        
        # Try visible markers
        visible = CanaryExtractor._extract_visible(content)
        if visible:
            results.extend(visible)
        
        # Try invisible Unicode
        invisible = CanaryExtractor._extract_invisible(content)
        if invisible:
            results.extend(invisible)
        
        return results
    
    @staticmethod
    def _extract_visible(content: str) -> list[dict]:
        """Extract visible canary markers."""
        results = []
        pattern = re.compile(r"\[ref:(v1:[a-f0-9]{12}:[a-f0-9]{16})\]")
        
        for match in pattern.finditer(content):
            marker = match.group(1)
            parts = marker.split(":")
            if len(parts) == 3:
                results.append({
                    "strategy": EmbedStrategy.VISIBLE,
                    "marker": marker,
                    "short_id": parts[1],
                    "signature": parts[2],
                    "confidence": 1.0,  # Visible markers are definitive
                })
        
        return results
    
    @staticmethod
    def _extract_invisible(content: str) -> list[dict]:
        """Extract invisible Unicode canary markers."""
        results = []
        
        # Find sequences of zero-width characters
        invisible_chars = "".join(ZERO_WIDTH_CHARS.values())
        pattern = re.compile(f"[{re.escape(invisible_chars)}]{{20,}}")
        
        for match in pattern.finditer(content):
            sequence = match.group(0)
            try:
                # Decode the sequence
                decoded = ""
                i = 0
                while i + 3 < len(sequence):
                    code = 0
                    multiplier = 1
                    for j in range(4):
                        if i + j < len(sequence):
                            char = sequence[i + j]
                            if char in ZERO_WIDTH_REVERSE:
                                digit = int(ZERO_WIDTH_REVERSE[char])
                                code += digit * multiplier
                                multiplier *= 4
                    decoded += chr(code)
                    i += 4
                
                # Check if it looks like a canary marker
                if decoded.startswith("v1:"):
                    marker_match = CanaryToken.marker_pattern().match(decoded)
                    if marker_match:
                        results.append({
                            "strategy": EmbedStrategy.INVISIBLE_UNICODE,
                            "marker": decoded,
                            "short_id": marker_match.group(1),
                            "signature": marker_match.group(2),
                            "confidence": 0.95,  # Slightly less than visible
                        })
            except (ValueError, IndexError):
                continue
        
        return results


class CanaryRegistry:
    """
    Registry for tracking canary tokens and their detections.
    
    In production, this would be backed by a database.
    This implementation uses in-memory storage for demonstration.
    """
    
    def __init__(self):
        self._tokens: dict[str, CanaryToken] = {}  # token_id -> token
        self._by_share: dict[str, list[str]] = {}  # share_id -> [token_ids]
        self._detections: list[CanaryDetection] = []
        self._alert_callbacks: list[Callable[[CanaryDetection], None]] = []
    
    def register(self, token: CanaryToken) -> None:
        """Register a canary token."""
        self._tokens[token.token_id] = token
        if token.share_id not in self._by_share:
            self._by_share[token.share_id] = []
        self._by_share[token.share_id].append(token.token_id)
    
    def get(self, token_id: str) -> Optional[CanaryToken]:
        """Get a token by ID."""
        return self._tokens.get(token_id)
    
    def get_by_share(self, share_id: str) -> list[CanaryToken]:
        """Get all tokens for a share."""
        token_ids = self._by_share.get(share_id, [])
        return [self._tokens[tid] for tid in token_ids if tid in self._tokens]
    
    def lookup_by_marker(self, short_id: str, signature: str) -> Optional[CanaryToken]:
        """Look up a token by its short ID and verify signature."""
        for token in self._tokens.values():
            marker = token.to_marker()
            parts = marker.split(":")
            if len(parts) == 3 and parts[1] == short_id:
                # Verify signature
                if parts[2] == signature:
                    return token
        return None
    
    def add_alert_callback(self, callback: Callable[[CanaryDetection], None]) -> None:
        """Add a callback to be invoked when a canary is detected."""
        self._alert_callbacks.append(callback)
    
    def report_detection(
        self,
        marker: str,
        source: str,
        context: str = "",
    ) -> Optional[CanaryDetection]:
        """
        Report a potential canary detection.
        
        Returns the CanaryDetection if verified, None if not a valid canary.
        """
        # Parse the marker
        match = CanaryToken.marker_pattern().match(marker)
        if not match:
            return None
        
        short_id = match.group(1)
        signature = match.group(2)
        
        # Look up the token
        token = self.lookup_by_marker(short_id, signature)
        if not token:
            return None
        
        # Create detection record
        detection = CanaryDetection(
            token_id=token.token_id,
            share_id=token.share_id,
            detected_at=datetime.now(timezone.utc),
            source=source,
            context=context,
            confidence=1.0 if signature == token.signature()[:16] else 0.5,
        )
        
        self._detections.append(detection)
        
        # Fire alert callbacks
        for callback in self._alert_callbacks:
            try:
                callback(detection)
            except Exception:
                pass  # Don't let callback failures break detection
        
        return detection
    
    def scan_content(
        self,
        content: str,
        source: str,
    ) -> list[CanaryDetection]:
        """
        Scan content for any embedded canaries and report detections.
        
        This is the main detection endpoint.
        """
        detections = []
        
        extracted = CanaryExtractor.extract_all(content)
        for item in extracted:
            detection = self.report_detection(
                marker=item["marker"],
                source=source,
                context=content[:500],
            )
            if detection:
                detections.append(detection)
        
        return detections
    
    def get_detections(self, share_id: Optional[str] = None) -> list[CanaryDetection]:
        """Get all detections, optionally filtered by share ID."""
        if share_id:
            return [d for d in self._detections if d.share_id == share_id]
        return list(self._detections)


# Module-level default registry
_default_registry: Optional[CanaryRegistry] = None


def get_registry() -> CanaryRegistry:
    """Get the default canary registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CanaryRegistry()
    return _default_registry


def create_canary(
    share_id: str,
    metadata: Optional[dict] = None,
    register: bool = True,
) -> CanaryToken:
    """
    Create a new canary token for a share.
    
    Args:
        share_id: The ID of the share to track
        metadata: Optional metadata about the share
        register: Whether to register with the default registry
    
    Returns:
        The created CanaryToken
    """
    token = CanaryToken.generate(share_id, metadata)
    if register:
        get_registry().register(token)
    return token


def embed_canary(
    content: str,
    token: CanaryToken,
    strategy: EmbedStrategy = EmbedStrategy.INVISIBLE_UNICODE,
) -> str:
    """
    Embed a canary token into content.
    
    Args:
        content: The content to embed the canary in
        token: The canary token to embed
        strategy: The embedding strategy to use
    
    Returns:
        Content with embedded canary
    """
    return CanaryEmbedder.embed(content, token, strategy)


def detect_canaries(content: str, source: str = "unknown") -> list[CanaryDetection]:
    """
    Scan content for canary tokens and report any detections.
    
    Args:
        content: The content to scan
        source: Where the content was found
    
    Returns:
        List of canary detections
    """
    return get_registry().scan_content(content, source)
