"""Keep an operation inside the folder the author actually chose.

A deployment destination and an import folder are the two places where this
tool meets a filesystem it does not own. Checking only the final name is not
enough: a symlink at any point along the way silently moves a read, a write or
a delete somewhere else, and the escape is invisible in the path that was
approved. Every component is therefore checked before any byte moves.

Containment is decided here rather than at each call site so that writing,
verifying and cleaning up a destination cannot drift apart and disagree about
which files an operation was allowed to touch.
"""

from pathlib import Path, PurePosixPath

from .blog import require


def contained(root, relative):
    """The path `relative` names under `root`, or None when it escapes.

    `root` must already be resolved. The result is None for an absolute or
    upward path and for any component that is a symlink, so a link can never
    widen the set of files an operation reaches. A component that does not
    exist yet is allowed: that is the ordinary case for a file about to be
    written.

    This is a check, not a lock. A single local author is assumed, so nothing
    defends against the destination being rewritten mid-operation.
    """
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in ("..", ".") for p in parts):
        return None
    current = Path(root)
    for part in parts:
        current = current / part
        if current.is_symlink():
            return None
    return current


def safe_path(root, relative, message="Path escapes the destination folder: "):
    """`contained`, refusing loudly.

    Deployment has no sensible fallback for a path it cannot vouch for, so it
    stops rather than guessing which file the author meant.
    """
    path = contained(root, relative)
    require(path is not None, message + str(relative))
    return path
