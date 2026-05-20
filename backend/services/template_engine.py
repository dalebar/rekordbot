"""Template engine — parses and resolves folder templates against track metadata.

Pure logic module with no I/O and no database access. Handles template parsing,
variable resolution with cascading fallbacks, path component sanitisation,
and full output path construction.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Characters unsafe on macOS and Windows filesystems.
# Includes path separators, Windows-reserved punctuation, and ASCII control chars.
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

# Windows reserved device names (illegal as bare filenames even on macOS). A
# component equal to one of these (case-insensitive) gets a safe suffix appended.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Collapses a run of semicolons (and surrounding whitespace) into ", " — used to
# make multi-artist folder names readable (path layer only, never tags/XML/DB).
_ARTIST_SEMICOLON = re.compile(r"\s*;[;\s]*")

# Available template variables mapped to Track model attribute names
TEMPLATE_VARIABLES = {
    "artist",
    "album_artist",
    "album",
    "title",
    "genre",
    "subgenre",
    "year",
    "label",
}


@dataclass
class TemplateSegment:
    """A parsed segment of a folder template.

    Attributes:
        type: Segment type — "variable", "literal", or "separator".
        value: Variable name, literal text, or "/" separator.
        fallbacks: For variables: ordered fallback list (variable names or
            quoted literals like '"Singles"').
    """

    type: str  # "variable", "literal", "separator"
    value: str
    fallbacks: list[str] = field(default_factory=list)


@dataclass
class ResolvedPath:
    """Result of resolving a template against track metadata.

    Attributes:
        path: The fully resolved output path.
        fallbacks_used: Variable names that fell through to a fallback.
        unresolved: Variable names that couldn't be resolved at all.
        components: Variable name → resolved value mapping.
    """

    path: Path
    fallbacks_used: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    components: dict[str, str] = field(default_factory=dict)


def parse_template(template: str) -> list[TemplateSegment]:
    """Parse a template string into typed segments.

    Template syntax:
        - {variable} — resolved from Track model fields
        - {variable|"literal"} — fallback to literal if variable is empty
        - {variable1|variable2|"literal"} — chained fallbacks
        - / — path separator
        - anything else — literal text

    Args:
        template: Template string to parse.

    Returns:
        List of TemplateSegment instances in order.
    """
    if not template:
        return []

    segments: list[TemplateSegment] = []
    i = 0

    while i < len(template):
        if template[i] == "{":
            # Find closing brace
            end = template.index("}", i)
            inner = template[i + 1 : end]

            # Split on | to get variable and fallbacks
            parts = inner.split("|")
            variable = parts[0].strip()
            fallbacks = [p.strip() for p in parts[1:]]

            segments.append(TemplateSegment(type="variable", value=variable, fallbacks=fallbacks))
            i = end + 1
        elif template[i] == "/":
            segments.append(TemplateSegment(type="separator", value="/"))
            i += 1
        else:
            # Collect literal text until next { or /
            end = i
            while end < len(template) and template[end] not in ("{", "/"):
                end += 1
            segments.append(TemplateSegment(type="literal", value=template[i:end]))
            i = end

    return segments


def validate_template(template: str) -> tuple[bool, str]:
    """Validate a folder template against the schema.

    Args:
        template: Template string to validate.

    Returns:
        (valid, error_message). On success, error_message is "".
        On failure, error_message is a human-readable description of the
        first failure encountered.
    """
    # Rule 1: empty or whitespace-only
    if not template or not template.strip():
        return False, "Template cannot be empty."

    # Rule 5: absolute path
    if template.startswith("/"):
        return False, "Template must be relative — do not start with '/'."

    # Rule 2: unbalanced braces
    depth = 0
    for ch in template:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return False, "Unbalanced braces in template."
    if depth != 0:
        return False, "Unbalanced braces in template."

    # Rule 3: empty variable {}
    if "{}" in template:
        return False, "Empty variable: '{}' is not allowed."

    # Parse — should succeed since braces are balanced
    try:
        segments = parse_template(template)
    except Exception:
        return False, "Unbalanced braces in template."

    # Rule 4: unknown variables
    available = ", ".join(sorted(TEMPLATE_VARIABLES))
    for seg in segments:
        if seg.type == "variable":
            if seg.value not in TEMPLATE_VARIABLES:
                return (
                    False,
                    f"Unknown variable: '{{{seg.value}}}'. Available: {available}.",
                )
            for fb in seg.fallbacks:
                if fb.startswith('"') and fb.endswith('"'):
                    continue
                if fb not in TEMPLATE_VARIABLES:
                    return (
                        False,
                        f"Unknown variable: '{{{fb}}}'. Available: {available}.",
                    )

    # Rule 6: path traversal (..)
    for seg in segments:
        if seg.type == "literal" and seg.value == "..":
            return False, "Path traversal not allowed: '..' segments rejected."

    # Rule 7: adjacent non-separator segments
    for i in range(1, len(segments)):
        if segments[i].type != "separator" and segments[i - 1].type != "separator":
            return (
                False,
                "Missing '/' separator between segments in template"
                " (variables and literals must be separated by '/').",
            )

    return True, ""


def _get_track_value(track: Any, variable: str) -> str | None:
    """Get a template variable's value from a track.

    Args:
        track: Track model instance.
        variable: Variable name to look up.

    Returns:
        String value if the attribute exists and is non-empty, else None.
    """
    value = getattr(track, variable, None)
    if value is None:
        return None
    str_value = str(value)
    if not str_value.strip():
        return None
    return str_value


def resolve_template(
    template: str,
    track: Any,
    unknown_fallback: str,
) -> ResolvedPath:
    """Resolve a template against track metadata.

    Args:
        template: Template string (e.g. "{artist}/{album}/{title}").
        track: Track model instance with metadata attributes.
        unknown_fallback: Literal string to use when all fallbacks fail.

    Returns:
        ResolvedPath with the resolved path, fallback tracking, and components.
    """
    segments = parse_template(template)
    path_parts: list[str] = []
    current_part_pieces: list[str] = []
    fallbacks_used: list[str] = []
    unresolved: list[str] = []
    components: dict[str, str] = {}

    for segment in segments:
        if segment.type == "separator":
            # Flush current part — sanitise the assembled string while it is still a
            # plain string, so any embedded "/" is neutralised before Path() can read
            # it as a separator and split the component into phantom directories.
            if current_part_pieces:
                sanitised = sanitise_path_component("".join(current_part_pieces))
                # An all-unsafe component sanitises to "" — Path() silently drops empty
                # parts, collapsing structure. Fall back to unknown_fallback so the
                # component is preserved, same as unresolved metadata.
                path_parts.append(sanitised or unknown_fallback)
                current_part_pieces = []
        elif segment.type == "literal":
            current_part_pieces.append(segment.value)
        elif segment.type == "variable":
            resolved_value = _resolve_variable(
                track, segment.value, segment.fallbacks, unknown_fallback
            )

            # Track whether fallback was used or variable was unresolved
            primary_value = _get_track_value(track, segment.value)
            if primary_value is not None:
                # Primary variable resolved
                pass
            elif resolved_value != unknown_fallback:
                # A fallback resolved
                fallbacks_used.append(segment.value)
            else:
                # Nothing resolved — check if any fallback was a literal that matches
                # the unknown_fallback (edge case)
                had_fallback = False
                for fb in segment.fallbacks:
                    if fb.startswith('"') and fb.endswith('"'):
                        literal = fb[1:-1]
                        if literal == unknown_fallback:
                            fallbacks_used.append(segment.value)
                            had_fallback = True
                            break
                    else:
                        fb_value = _get_track_value(track, fb)
                        if fb_value is not None:
                            had_fallback = True
                            break
                if not had_fallback:
                    unresolved.append(segment.value)

            components[segment.value] = resolved_value

            # Artist-only: normalise ";" separators to ", " for a readable folder
            # name. Path layer only — track.artist, tags, and XML are untouched.
            piece = resolved_value
            if segment.value == "artist":
                piece = _ARTIST_SEMICOLON.sub(", ", piece)
            current_part_pieces.append(piece)

    # Flush remaining — sanitise the assembled string before it reaches Path().
    if current_part_pieces:
        sanitised = sanitise_path_component("".join(current_part_pieces))
        path_parts.append(sanitised or unknown_fallback)

    # Build path from parts
    path = Path(*path_parts) if path_parts else Path(".")

    return ResolvedPath(
        path=path,
        fallbacks_used=fallbacks_used,
        unresolved=unresolved,
        components=components,
    )


def _resolve_variable(
    track: Any,
    variable: str,
    fallbacks: list[str],
    unknown_fallback: str,
) -> str:
    """Resolve a single variable with fallback chain.

    Args:
        track: Track model instance.
        variable: Primary variable name.
        fallbacks: Ordered list of fallback variable names or quoted literals.
        unknown_fallback: Ultimate fallback string.

    Returns:
        Resolved string value.
    """
    # Try primary variable
    value = _get_track_value(track, variable)
    if value is not None:
        return value

    # Try fallbacks in order
    for fb in fallbacks:
        if fb.startswith('"') and fb.endswith('"'):
            # Quoted literal
            return fb[1:-1]
        else:
            # Variable fallback
            fb_value = _get_track_value(track, fb)
            if fb_value is not None:
                return fb_value

    # All fallbacks exhausted
    return unknown_fallback


def sanitise_path_component(component: str) -> str:
    """Clean a single path component for safe filesystem use.

    Removes characters unsafe on macOS/Windows (path separators, reserved
    punctuation, ASCII control chars), strips leading/trailing dots and spaces,
    collapses multiple spaces, neutralises Windows reserved device names, and
    trims to 255 chars. Preserves unicode characters.

    Args:
        component: Raw path component string.

    Returns:
        Sanitised path component.
    """
    # Remove unsafe characters (incl. ASCII control chars)
    result = _UNSAFE_CHARS.sub("", component)

    # Strip leading/trailing dots and spaces
    result = result.strip(". ")

    # Collapse multiple spaces
    result = re.sub(r"\s+", " ", result)

    # Neutralise Windows reserved device names (e.g. CON, NUL, COM1) so output is
    # cross-platform-safe even though we run on macOS.
    if result.upper() in _RESERVED_NAMES:
        result = result + "_"

    # Trim to filesystem limit
    if len(result) > 255:
        result = result[:255]

    return result


def build_output_path(
    template: str,
    track: Any,
    output_dir: Path,
    unknown_fallback: str,
) -> ResolvedPath:
    """Full pipeline: resolve template → sanitise → join with output dir and extension.

    Args:
        template: Folder template string.
        track: Track model instance with metadata.
        output_dir: Base output directory.
        unknown_fallback: Fallback string for unresolved variables.

    Returns:
        ResolvedPath with the fully qualified output path including extension.
    """
    resolved = resolve_template(template, track, unknown_fallback)

    # Sanitise each path component
    sanitised_parts = []
    for part in resolved.path.parts:
        sanitised = sanitise_path_component(part)
        if sanitised:
            sanitised_parts.append(sanitised)

    # Determine file extension from output format
    output_format = getattr(track, "output_format", None)
    ext = f".{output_format}" if output_format else Path(track.file_path).suffix

    # Build final path: output_dir / sanitised parts (last part gets extension)
    if sanitised_parts:
        # The last part is the filename — add extension
        sanitised_parts[-1] = sanitised_parts[-1] + ext
        final_path = output_dir / Path(*sanitised_parts)
    else:
        final_path = output_dir / f"untitled{ext}"

    resolved.path = final_path
    return resolved
