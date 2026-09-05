"""Optional, user-supplied Live2D asset boundary."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote


MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_MODEL_JSON_BYTES = 2 * 1024 * 1024
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
        model_file = self._file(self.model)
        runtime_file = self._file(self.runtime)
        validation = self._validate_model(model_file)
        return {
            "enabled": model_file is not None and runtime_file is not None,
            "ready": model_file is not None and runtime_file is not None and validation["renderable"],
            "runtime_url": f"/avatar-assets/{self.runtime.as_posix()}" if runtime_file else None,
            "model_url": f"/avatar-assets/{self.model.as_posix()}" if model_file else None,
            "adapter": "Live2DCompanionRuntime" if runtime_file else None,
            "capabilities": {
                "expressions": int(validation["expression_count"]),
                "motion_groups": list(validation["motion_groups"]),
                "physics": bool(validation["physics"]),
                "pose": bool(validation["pose"]),
                "display_info": bool(validation["display_info"]),
                "lip_sync": True,
                "fallback_expressions": [
                    "neutral", "attentive", "concerned", "confused",
                    "happy", "sad", "angry", "surprised",
                ],
            },
            "validation": validation,
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

    def _validate_model(self, model_file: Path | None) -> dict[str, object]:
        """Validate model references without exposing local filesystem paths."""
        result: dict[str, object] = {
            "valid": False,
            "renderable": False,
            "missing": [],
            "warnings": [],
            "motion_groups": [],
            "expression_count": 0,
            "physics": False,
            "pose": False,
            "display_info": False,
        }
        if model_file is None:
            result["warnings"] = ["model file is missing"]
            return result
        try:
            if model_file.stat().st_size > MAX_MODEL_JSON_BYTES:
                result["warnings"] = ["model JSON is too large"]
                return result
            settings = json.loads(model_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            result["warnings"] = ["model JSON is invalid"]
            return result
        if not isinstance(settings, dict):
            result["warnings"] = ["model JSON must be an object"]
            return result
        references = settings.get("FileReferences")
        if not isinstance(references, dict):
            result["warnings"] = ["FileReferences is missing"]
            result["valid"] = True
            return result

        missing: list[dict[str, object]] = []

        def check(kind: str, file_name: object, fatal: bool) -> None:
            if not isinstance(file_name, str) or not file_name:
                return
            try:
                relative = self._relative(file_name)
            except ValueError:
                missing.append({"type": kind, "file": file_name[:160], "fatal": fatal})
                return
            if self._model_file(model_file, relative) is None:
                missing.append({"type": kind, "file": file_name[:160], "fatal": fatal})

        check("Moc", references.get("Moc"), True)
        textures = references.get("Textures", [])
        if isinstance(textures, list):
            for texture in textures[:64]:
                check("Texture", texture, True)
        for kind, capability in (
            ("Physics", "physics"),
            ("Pose", "pose"),
            ("DisplayInfo", "display_info"),
        ):
            reference = references.get(kind)
            check(kind, reference, False)
            if isinstance(reference, str) and reference:
                try:
                    relative = self._relative(reference)
                except ValueError:
                    continue
                result[capability] = self._model_file(model_file, relative) is not None

        expressions = references.get("Expressions", [])
        if isinstance(expressions, list):
            result["expression_count"] = min(len(expressions), 64)
            for item in expressions[:64]:
                if isinstance(item, dict):
                    check("Expression", item.get("File"), False)
        motions = references.get("Motions", {})
        if isinstance(motions, dict):
            groups = [str(group)[:80] for group in list(motions)[:64]]
            result["motion_groups"] = groups
            for group, items in list(motions.items())[:64]:
                if not isinstance(items, list):
                    continue
                for item in items[:64]:
                    if isinstance(item, dict):
                        check(f"Motion:{str(group)[:80]}", item.get("File"), False)

        result["missing"] = missing[:128]
        result["valid"] = not any(item["fatal"] for item in missing)
        result["renderable"] = bool(references.get("Moc")) and isinstance(textures, list) and bool(textures) and result["valid"]
        if any(not item["fatal"] for item in missing):
            result["warnings"] = ["some optional motion or metadata files are missing"]
        return result

    def _model_file(self, model_file: Path, relative: Path) -> Path | None:
        candidate = (model_file.parent / relative).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            return None
        try:
            if candidate.stat().st_size > MAX_ASSET_BYTES:
                return None
        except OSError:
            return None
        return candidate
