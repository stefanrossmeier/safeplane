from __future__ import annotations

from pathlib import Path


class SafePathPolicyError(ValueError):
    pass


class SafePathPolicy:
    """Resolve paths as if the tool had cd'ed into root.

    Relative paths are resolved below root.
    Absolute paths are allowed only if they are still inside root.
    Any escape through .., symlinks, or absolute outside paths is rejected.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve(strict=False)

    def resolve(self, candidate: str | Path) -> Path:
        raw = Path(candidate)

        if raw.is_absolute():
            resolved = raw.expanduser().resolve(strict=False)
        else:
            resolved = (self.root / raw).expanduser().resolve(strict=False)

        if resolved == self.root or self.root in resolved.parents:
            return resolved

        raise SafePathPolicyError(
            f"path escapes allowed root: candidate={candidate!s}, root={self.root!s}"
        )
