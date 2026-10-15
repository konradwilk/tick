import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("tick_version", Path(__file__).parents[1] / "tick/version.py")
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class VersionTests(unittest.TestCase):
    def test_release_tag_and_commits_are_preserved(self):
        result = subprocess.CompletedProcess([], 0, "RELEASE_0.1-3-gabcdef\n")
        with patch.object(version.subprocess, "run", return_value=result):
            self.assertEqual(version.source_version(), "0.1-3-gabcdef")

    def test_distribution_without_git_uses_stamp(self):
        with tempfile.TemporaryDirectory() as folder:
            module = Path(folder) / "linux/tick/version.py"
            module.parent.mkdir(parents=True)
            module.with_name("_version.txt").write_text("0.2\n", encoding="utf-8")
            with patch.object(version, "__file__", str(module)), patch.object(version.subprocess, "run", side_effect=OSError):
                self.assertEqual(version.source_version(), "0.2")

    def test_csharp_output_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "obj/BuildVersion.g.cs"
            with patch.object(version, "source_version", return_value="0.1"), patch("sys.argv", ["version.py", "--format", "csharp", "--output", str(output)]):
                version.main()
            self.assertIn('public const string Current = "0.1";', output.read_text(encoding="utf-8"))
            self.assertIn("namespace Tick;", output.read_text(encoding="utf-8"))
