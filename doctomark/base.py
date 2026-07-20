"""Base converter and shared utilities."""

import hashlib
import mimetypes
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversionResult:
    """Result of converting a document."""

    markdown: str
    assets: list[Path] = field(default_factory=list)

    title: Optional[str] = None


class BaseConverter:
    """Abstract base for format-specific converters."""

    # Override in subclasses to declare supported extensions
    SUPPORTED_EXTENSIONS: tuple[str, ...] = ()

    def __init__(self, assets_dir: Path | str):
        self.assets_dir = Path(assets_dir)
        self._image_counter = 0
        self._hashes: set[str] = set()  # dedup by content hash

    def convert(self, input_path: Path) -> ConversionResult:
        raise NotImplementedError

    def _save_image(self, data: bytes, content_type: str = "") -> str:
        """Save image blob to assets_dir, return relative path for markdown."""
        content_hash = hashlib.sha256(data).hexdigest()
        if content_hash in self._hashes:
            return ""  # Duplicate, skip
        self._hashes.add(content_hash)

        ext = self._guess_ext(content_type, data)
        self._image_counter += 1
        filename = f"image_{self._image_counter}{ext}"
        path = self.assets_dir / filename

        self.assets_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        return f"{self.assets_dir.name}/{filename}"

    @staticmethod
    def _guess_ext(content_type: str, data: bytes) -> str:
        """Guess file extension from content_type or magic bytes."""
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext

        # Fallback: check magic bytes
        if data[:4] == b"\x89PNG":
            return ".png"
        if data[:2] == b"\xff\xd8":
            return ".jpg"
        if data[:3] == b"GIF":
            return ".gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        if data[:2] in (b"BM",):
            return ".bmp"

        return ".bin"

    def supports(self, extension: str) -> bool:
        return extension.lower() in self.SUPPORTED_EXTENSIONS
