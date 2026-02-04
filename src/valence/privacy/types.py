# Valence Privacy Types
"""
Common types used across the privacy module.
"""

from enum import Enum


class ShareLevel(Enum):
    """
    Content sharing/visibility levels.
    
    Ordered from most private to most public.
    """
    
    PRIVATE = "private"        # Owner only
    DIRECT = "direct"          # Explicitly shared with specific recipients  
    BOUNDED = "bounded"        # Shared within a defined group/boundary
    CASCADING = "cascading"    # Can be re-shared by recipients
    PUBLIC = "public"          # Publicly accessible


# Ordered list for validation
SHARE_LEVEL_ORDER = [level.value for level in ShareLevel]
