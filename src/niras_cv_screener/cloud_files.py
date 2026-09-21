"""Session-local browser uploads and portable result downloads."""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .extraction import SUPPORTED_EXTENSIONS, safe_stem


def remove_legacy_cloud_files(app_root: Path, temp_root: Path) -> bool:
    """Remove only known output locations used by earlier cloud versions."""
    locations = [(temp_root, "niras_session_*"), (temp_root, "niras_cv_uploads_*"),
                 (app_root / "outputs", "outputs_*"),
                 (app_root / "outputs", ".cv_screener_cache")]
    try:
        for parent, pattern in locations:
            if parent.is_symlink():
                return False
            for candidate in parent.glob(pattern):
                if candidate.is_symlink() or candidate.resolve().parent != parent.resolve():
                    return False
                if candidate.is_dir():
                    shutil.rmtree(candidate.resolve())
        return True
    except OSError:
        return False


@dataclass
class MemoryCV:
    name: str
    data: bytes

    def read_bytes(self) -> bytes:
        return self.data


def memory_uploads(uploaded_files) -> list[MemoryCV]:
    files = []
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
        files.append(MemoryCV(f"cv_{candidate}{extension}", bytes(uploaded.getbuffer())))
    return files


def save_uploads(uploaded_files, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for uploaded in memory_uploads(uploaded_files):
        path = directory / uploaded.name
        path.write_bytes(uploaded.data)
        paths.append(path)
    return paths


def memory_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def results_zip(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(directory).as_posix())
    return buffer.getvalue()
