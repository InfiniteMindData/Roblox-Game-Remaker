"""Release documentation and metadata consistency checks."""
import collections
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReleaseDocumentationTests(unittest.TestCase):
    def test_tool_tables_have_one_row_per_script(self):
        for relative in ("README.md", "skills/roblox-game-remaker/SKILL.md"):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                scripts = re.findall(r"^\| `([a-z_]+\.py)\b", text, re.MULTILINE)
                counts = collections.Counter(scripts)
                self.assertTrue(counts, "tool table must not be empty")
                self.assertEqual({name: count for name, count in counts.items() if count != 1}, {})
                for name in ("measure_compare.py", "clip_compare.py", "blender_roblox_export.py"):
                    self.assertEqual(counts[name], 1)
