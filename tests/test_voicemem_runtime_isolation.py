import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jawl_voicecompanion import __main__ as companion_main
from jawl_voicecompanion.composition import _voicemem_sidecar_args


class VoiceMemRuntimeIsolationTests(unittest.TestCase):
    @staticmethod
    def _config(memory_root=None):
        return SimpleNamespace(
            voicemem_mode="normal",
            voicemem_audio_rate=16000,
            voicemem_local_memory=True,
            voicemem_memory_root=memory_root,
        )

    def test_owned_profiles_get_distinct_explicit_roots_even_with_inherited_env(self):
        inherited_root = r"G:\AI\VoiceMem\memory"
        profile_roots = (
            Path(r"G:\AI\JAWL-VoiceCompanion\runtime\instances\alpha\data\sensory\voicemem"),
            Path(r"G:\AI\JAWL-VoiceCompanion\runtime\instances\beta\data\sensory\voicemem"),
        )
        with patch.dict("os.environ", {"VOICEMEM_MEMORY_ROOT": inherited_root}):
            args_by_profile = [
                _voicemem_sidecar_args(self._config(root)) for root in profile_roots
            ]

        self.assertNotEqual(args_by_profile[0], args_by_profile[1])
        for args, root in zip(args_by_profile, profile_roots):
            root_index = args.index("--memory-root")
            self.assertEqual(args[root_index + 1], str(root))
            self.assertNotEqual(args[root_index + 1], inherited_root)

    def test_memory_root_option_forwards_a_path_with_spaces_as_one_value(self):
        memory_root = r"G:\JAWL profiles\daily\data\sensory\voicemem"
        captured = {}

        class Runtime:
            control = SimpleNamespace(
                url_scheme="http", server_port=2367, presentation_url="http://127.0.0.1:8766"
            )

            def serve_forever(self):
                raise KeyboardInterrupt

            def close(self):
                pass

        def build_runtime(args, **_kwargs):
            captured["args"] = _voicemem_sidecar_args(args)
            return Runtime()

        argv = [
            "jawl_voicecompanion", "--voicemem-python", "G:\\AI\\VoiceMem\\python.exe",
            "--voicemem-memory-root", memory_root,
        ]
        with patch.object(sys, "argv", argv), patch.object(
            companion_main, "build_companion_runtime", side_effect=build_runtime
        ), contextlib.redirect_stdout(io.StringIO()):
            companion_main.main()

        sidecar_args = captured["args"]
        root_index = sidecar_args.index("--memory-root")
        self.assertEqual(sidecar_args[root_index + 1], memory_root)

    def test_standalone_without_root_keeps_voice_mem_default_behavior(self):
        args = _voicemem_sidecar_args(self._config())
        self.assertNotIn("--memory-root", args)
        self.assertIn("--local-memory", args)


if __name__ == "__main__":
    unittest.main()
