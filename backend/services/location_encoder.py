"""Rekordbox location encoder — converts file paths to file://localhost/ URIs.

Pure logic module with no I/O and no database access. Handles RFC 3986
percent-encoding of path components for Rekordbox XML Location attributes.
"""

from urllib.parse import quote


def encode_path_component(component: str) -> str:
    """Percent-encode a single path component per RFC 3986.

    Encodes all characters except unreserved characters (letters, digits,
    hyphen, period, underscore, tilde). Spaces become %20, special
    characters like # and & are encoded as their hex values.

    Args:
        component: A single path component (filename or directory name).

    Returns:
        Percent-encoded string safe for use in a URI path.
    """
    if not component:
        return ""
    return quote(component, safe="")


def encode_location(absolute_path: str) -> str:
    """Convert an absolute file path to a Rekordbox Location URI.

    Splits the path on '/', encodes each component individually,
    and prepends the file://localhost/ prefix.

    Args:
        absolute_path: Absolute file path (e.g. "/Users/daleb/library/track.aiff").

    Returns:
        Rekordbox-compatible Location URI string.
    """
    # Split on / and encode each non-empty component
    parts = absolute_path.split("/")
    encoded_parts = [encode_path_component(part) for part in parts]
    encoded_path = "/".join(encoded_parts)

    # Remove leading slash since the prefix already provides the path root
    if encoded_path.startswith("/"):
        encoded_path = encoded_path[1:]

    return f"file://localhost/{encoded_path}"
