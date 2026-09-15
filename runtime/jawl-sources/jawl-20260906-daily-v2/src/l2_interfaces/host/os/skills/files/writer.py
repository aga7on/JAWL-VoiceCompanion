"""
Skills for writing, creating, moving, and deleting files and directories.
"""

import ast
import shutil
import asyncio
import os
import tempfile
import uuid
from typing import Union, List

from src.utils.logger import main_logger
from src.utils._tools import format_size

from src.l2_interfaces.host.os.client import HostOSClient, HostOSAccessLevel
from src.l2_interfaces.host.os.decorators import require_access

from src.l3_agent.skills.registry import SkillResult, skill
from src.l3_agent.swarm.roles import Subagents


class HostOSWriter:
    """Agent skills for file modifications and management."""

    def __init__(self, host_os_client: HostOSClient):
        self.host_os = host_os_client

    @staticmethod
    def _atomic_write(path, content: str) -> None:
        """Write UTF-8 text through a same-directory atomic replacement."""

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=f".{uuid.uuid4().hex}.tmp", dir=path.parent
        )
        temporary = type(path)(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                os.chmod(temporary, path.stat().st_mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @skill(swarm=[Subagents.CODER, Subagents.QA_ENGINEER, Subagents.SYSADMIN])
    @require_access(HostOSAccessLevel.SANDBOX)
    async def write_file(
        self, filepath: str, content: str, description: str = None
    ) -> SkillResult:
        """
        Creates or fully overwrites file.

        description: Brief content summary.
        """

        try:
            safe_path = self.host_os.validate_path(filepath, is_write=True)
            safe_path.parent.mkdir(parents=True, exist_ok=True)

            def _write():
                # ReAct/provider recovery can legitimately redeclare the same
                # write after a successful tool result.  Treat an exact byte
                # match as an idempotent no-op: this preserves the requested
                # state without replaying a filesystem side effect.
                requested = content.encode("utf-8")
                if safe_path.is_file() and safe_path.read_bytes() == requested:
                    return False
                self._atomic_write(safe_path, content)
                return True

            changed = await asyncio.to_thread(_write)

            desc_msg = ""
            if description:
                try:
                    rel_path = safe_path.relative_to(self.host_os.sandbox_dir).as_posix()
                    clean_desc = description.replace("\n", " ").strip()
                    await asyncio.to_thread(
                        self.host_os.set_file_metadata, rel_path, clean_desc
                    )
                    desc_msg = " File description successfully saved."
                except Exception as e:
                    desc_msg = f" (Failed to save metadata: {e})"

            if changed:
                main_logger.info(f"[Host OS] Overwrote file: {safe_path.name}{desc_msg}")
                return SkillResult.ok("True")
            main_logger.info(f"[Host OS] Write skipped; content already matched: {safe_path.name}{desc_msg}")
            return SkillResult.ok("True (idempotent no-op; requested content already matched)")

        except PermissionError as e:
            return SkillResult.fail(str(e))

        except Exception as e:
            return SkillResult.fail(f"Error overwriting file: {e}")

    @skill(swarm=[Subagents.CODER, Subagents.QA_ENGINEER, Subagents.SYSADMIN])
    @require_access(HostOSAccessLevel.SANDBOX)
    async def append_to_file(self, filepath: str, content: str) -> SkillResult:
        """
        Safely appends text to file end.
        """

        try:
            safe_path = self.host_os.validate_path(filepath, is_write=True)
            safe_path.parent.mkdir(parents=True, exist_ok=True)

            def _append():
                existing_content = (
                    safe_path.read_text(encoding="utf-8")
                    if safe_path.exists()
                    else ""
                )
                prefix = "\n" if existing_content and not existing_content.endswith("\n") else ""

                HostOSWriter._atomic_write(
                    safe_path,
                    existing_content + prefix + content,
                )

            await asyncio.to_thread(_append)

            main_logger.info(f"[Host OS] Appended to file (append): {safe_path.name}")
            return SkillResult.ok("True")

        except PermissionError as e:
            return SkillResult.fail(str(e))

        except Exception as e:
            return SkillResult.fail(f"Error appending to file: {e}")

    @skill()
    @require_access(HostOSAccessLevel.SANDBOX)
    async def delete_file(self, filepath: str) -> SkillResult:
        """
        Deletes file (not directories).
        """

        try:
            safe_path = self.host_os.validate_path(filepath, is_write=True)

            if not safe_path.exists():
                return SkillResult.fail(f"Error: File does not exist ({filepath}).")

            if not safe_path.is_file():
                return SkillResult.fail(
                    "Error: This is not a file, deleting directories via this tool is forbidden."
                )

            size_str = format_size(safe_path.stat().st_size)
            quarantine = self.host_os.quarantine_path(safe_path)

            main_logger.info(
                f"[Host OS] Quarantined file: {safe_path.name} ({size_str}) -> {quarantine.name}"
            )
            return SkillResult.ok("True (moved to recoverable quarantine)")

        except PermissionError as e:
            return SkillResult.fail(str(e))

        except Exception as e:
            return SkillResult.fail(f"Error deleting file: {e}")

    @skill()
    @require_access(HostOSAccessLevel.SANDBOX)
    async def delete_directory(self, path: str) -> SkillResult:
        """
        Deletes directory and all contents.
        """

        try:
            safe_path = self.host_os.validate_path(path, is_write=True)

            if not safe_path.exists():
                return SkillResult.fail(f"Error: Directory does not exist ({path}).")
            if not safe_path.is_dir():
                return SkillResult.fail(
                    "Error: This is not a directory. To delete files, use delete_file."
                )

            if (
                safe_path == self.host_os.sandbox_dir
                or safe_path == self.host_os.framework_dir
            ):
                return SkillResult.fail(
                    "Error: Access denied. Deleting the root sandbox or framework directory is forbidden."
                )

            quarantine = await asyncio.to_thread(self.host_os.quarantine_path, safe_path)
            main_logger.info(
                f"[Host OS] Quarantined directory: {safe_path.name} -> {quarantine.name}"
            )
            return SkillResult.ok("True (moved to recoverable quarantine)")

        except PermissionError as e:
            return SkillResult.fail(str(e))

        except Exception as e:
            return SkillResult.fail(f"Error deleting directory: {e}")

    @skill(swarm=[Subagents.CODER, Subagents.QA_ENGINEER, Subagents.SYSADMIN])
    @require_access(HostOSAccessLevel.SANDBOX)
    async def create_directories(self, paths: Union[str, List[str]]) -> SkillResult:
        """
        Creates directory/directories.
        """

        if isinstance(paths, str):
            try:
                parsed = ast.literal_eval(paths.strip())
                if isinstance(parsed, list):
                    paths = parsed
                else:
                    paths = [paths]
            except Exception:
                paths = [paths]

        if not paths or not isinstance(paths, list):
            return SkillResult.fail("Error: Path list is empty or has invalid format.")

        created, errors = [], []

        for path in paths:
            try:
                safe_path = self.host_os.validate_path(path, is_write=True)
                await asyncio.to_thread(safe_path.mkdir, parents=True, exist_ok=True)
                created.append(safe_path.name)

            except PermissionError as e:
                errors.append(f"{path}: {e}")

            except Exception as e:
                errors.append(f"{path}: Creation error ({e})")

        if not created and errors:
            return SkillResult.fail("Failed to create directories:\n" + "\n".join(errors))

        msg = f"Successfully created directories: {', '.join(created)}."
        if errors:
            msg += "\n\nBut errors occurred with these paths:\n" + "\n".join(errors)

        main_logger.info(f"[Host OS] Created directories: {', '.join(created)}")

        return SkillResult.ok("True")

    @skill()
    @require_access(HostOSAccessLevel.SANDBOX)
    async def move_or_rename(self, source_path: str, destination_path: str) -> SkillResult:
        """
        Moves/renames file or directory.
        """

        try:
            safe_src = self.host_os.validate_path(source_path, is_write=True)
            safe_dst = self.host_os.validate_path(destination_path, is_write=True)

            if not safe_src.exists():
                return SkillResult.fail(f"Error: Source object not found ({source_path}).")

            safe_dst.parent.mkdir(parents=True, exist_ok=True)

            def _move():
                shutil.move(str(safe_src), str(safe_dst))

            await asyncio.to_thread(_move)

            main_logger.info(
                f"[Host OS] Moved/renamed object: {safe_src.name} -> {safe_dst.name}"
            )
            return SkillResult.ok("True")

        except PermissionError as e:
            return SkillResult.fail(str(e))
        except Exception as e:
            return SkillResult.fail(f"Error moving/renaming: {e}")
