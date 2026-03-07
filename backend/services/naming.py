"""Output file naming — determines output path for converted/copied files."""

import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_output_path(source_path: Path, output_dir: Path, output_format: str) -> Path:
    """Generate the output file path for a converted or copied file.

    Output structure: {output_dir}/imports/{YYYY-MM-DD}/{filename}.{ext}
    If a collision exists, appends _1, _2, etc.

    Args:
        source_path: Original source file path.
        output_dir: Base output directory.
        output_format: Target format extension (e.g. "aiff", "mp3", "m4a").

    Returns:
        Path to the output file (parent directory is created if needed).
    """
    today = date.today().isoformat()
    dest_dir = output_dir / "imports" / today
    dest_dir.mkdir(parents=True, exist_ok=True)

    stem = source_path.stem
    ext = f".{output_format}"
    candidate = dest_dir / f"{stem}{ext}"

    counter = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem}_{counter}{ext}"
        counter += 1

    return candidate
