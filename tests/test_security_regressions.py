import io
import os
import tempfile
import unittest
import zipfile

from qich.security import safe_extract_zip


class SecurityRegressionTests(unittest.TestCase):
    def _zip(self, entries):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries:
                z.writestr(name, data)
        return b.getvalue()

    def test_reject_parent_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                safe_extract_zip(self._zip([("../escape", b"x")]), d)

    def test_reject_absolute_path(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                safe_extract_zip(self._zip([("/escape", b"x")]), d)

    def test_reject_too_many_files(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                safe_extract_zip(self._zip([("a", b"1"), ("b", b"2")]), d, max_files=1)

    def test_reject_uncompressed_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                safe_extract_zip(self._zip([("a", b"1234")]), d, max_total=3)

    def test_existing_symlink_cannot_escape_destination(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, os.path.join(root, "link"))
            with self.assertRaises(ValueError):
                safe_extract_zip(self._zip([("link/pwn", b"x")]), root)


if __name__ == "__main__":
    unittest.main()
