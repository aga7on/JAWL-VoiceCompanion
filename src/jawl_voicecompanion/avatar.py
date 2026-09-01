"""Optional, user-supplied Live2D asset boundary."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote


MAX_ASSET_BYTES = 128 * 1024 * 1024
_MIME_TYPES = {
    ".moc3": "application/octet-stream",
    ".wasm": "application/wasm",
    ".motion3.json": "application/json",
    ".exp3.json": "application/json",
    ".physics3.json": "application/json",
}


class AvatarAssetStore:
    """Serve only files below an explicitly configured Live2D asset root."""

    def __init__(self, root: str | Path, *, model: str = "model3.json", runtime: str = "live2d-runtime.js"):
        self.root = Path(root).resolve()
        self.model = self._relative(model)
        self.runtime = self._relative(runtime)

    @property
    def enabled(self) -> bool:
        return self._file(self.model) is not None and self._file(self.runtime) is not None

    def config(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "runtime_url": f"/avatar-assets/{self.runtime.as_posix()}" if self.enabled else None,
            "model_url": f"/avatar-assets/{self.model.as_posix()}" if self.enabled else None,
            "adapter": "Live2DCompanionRuntime" if self.enabled else None,
        }

    def resolve_public(self, public_path: str) -> Path | None:
        try:
            relative = self._relative(unquote(public_path).lstrip("/"))
        except ValueError:
            return None
        return self._file(relative)

    def content_type(self, path: Path) -> str:
        for suffix, mime in _MIME_TYPES.items():
            if path.name.endswith(suffix):
                return mime
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    @staticmethod
    def _relative(value: str) -> Path:
        if not value or "\\" in value:
            raise ValueError("Live2D asset paths must be non-empty POSIX paths")
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Live2D asset path escapes the configured root")
        return relative

    def _file(self, relative: Path) -> Path | None:
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            return None
        try:
            if candidate.stat().st_size > MAX_ASSET_BYTES:
                return None
        except OSError:
            return None
        return candidate
