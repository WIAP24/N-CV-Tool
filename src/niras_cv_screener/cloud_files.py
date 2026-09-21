"""Session-local browser uploads and portable result downloads."""
from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .extraction import SUPPORTED_EXTENSIONS, safe_stem


def save_uploads(uploaded_files, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    used = set()
    for uploaded in uploaded_files:
        # Treat both Windows and POSIX names as untrusted browser metadata.
        original = uploaded.name.replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(original).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported CV file: {original}")
        stem = safe_stem(original)[:100]
        candidate = stem
        count = 1
        while candidate.casefold() in used:
            count += 1
            candidate = f"{stem}_{count}"
        used.add(candidate.casefold())
        path = directory / f"cv_{candidate}{extension}"
        path.write_bytes(uploaded.getbuffer())
        paths.append(path)
    return paths


def results_zip(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(directory).as_posix())
    return buffer.getvalue()
