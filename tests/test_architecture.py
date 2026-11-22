"""Only adapters/corgi.py may talk to Corgi (FR-028, FR-029)."""
import os
import re
import unittest

from tests import helpers

PACKAGE = os.path.join(helpers.LIB_DIR, "roundup")
ALLOWED = os.path.join("adapters", "corgi.py")
PATTERNS = [
    re.compile(r"CORGI_APP_EXE"),
    re.compile(r"ROUNDUP_CORGI"),
    re.compile(r"""["']corgi["']"""),  # a literal "corgi" binary name
]


class ArchitectureTest(unittest.TestCase):
    def test_only_adapter_references_corgi_binary(self):
        offenders = []
        files = 0
        for root, _dirs, names in os.walk(PACKAGE):
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, PACKAGE)
                files += 1
                if rel == ALLOWED:
                    continue
                with open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if any(p.search(line) for p in PATTERNS):
                            offenders.append("%s:%d: %s" % (rel, lineno, line.strip()))
        self.assertGreater(files, 1)
        self.assertEqual(offenders, [])

    def test_adapter_exists(self):
        self.assertTrue(os.path.exists(os.path.join(PACKAGE, ALLOWED)))


if __name__ == "__main__":
    unittest.main()
