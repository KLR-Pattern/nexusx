"""Type compatibility checking for implicit auto-loading.

Validates that a DTO field type is compatible with a relationship's
target entity before auto-loading. Adapted from pydantic-resolve's
``class_util.is_compatible_type``.
"""

from __future__ import annotations

from typing import Any

from nexusx import annotation_utils as au
from nexusx.subset import SUBSET_REFERENCE


def is_compatible_type(src_type: Any, target_type: Any) -> bool:
    """Check if src_type is compatible with target_type for auto-loading.

    Compatible means one of:
    1. Same type (after unwrapping Optional from src)
    2. src is a DefineSubset of target (follows __nexusx_subset_source__ chain)
    3. src is a subclass of target
    4. list[src_element] is compatible with list[target] (recursive check)

    Args:
        src_type: The DTO field annotation type (e.g. UserDTO, list[UserDTO]).
        target_type: The relationship's target entity class (e.g. User).

    Returns:
        True if src_type can receive data loaded from target_type.
    """

    def is_subset_of(src: Any, tgt: Any) -> bool:
        """Walk the subset source chain to check if src derives from tgt."""
        current = src
        while current is not None:
            if current is tgt:
                return True
            current = getattr(current, SUBSET_REFERENCE, None)
        return False

    def is_list_compatible(src: Any, tgt: Any) -> bool:
        if au.is_list(src) and au.is_list(tgt):
            src_inner, tgt_inner = au.list_inner(src), au.list_inner(tgt)
            if src_inner is src or tgt_inner is tgt:
                return False  # bare ``list`` — no element type to compare
            return is_compatible_type(src_inner, tgt_inner)
        return False

    # Unwrap Optional in src (strict: a real union is not an Optional)
    src = au.unwrap_optional_strict(src_type)
    tgt = target_type

    # Non-optional unions are incompatible
    if au.is_union(src) or au.is_union(tgt):
        return False

    # list[SrcDTO] vs list[Target]
    if is_list_compatible(src, tgt):
        return True

    # Direct equality
    if src is tgt:
        return True

    # Subset chain: SrcDTO → __subset_source__ → ... → Target
    try:
        if is_subset_of(src, tgt):
            return True
    except Exception:
        pass

    # Subclass check
    try:
        if au.safe_issubclass(src, tgt):
            return True
    except Exception:
        pass

    return False
