import io
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from niras_cv_screener.cloud_files import save_uploads, results_zip


def upload(name, content=b"synthetic CV"):
    value = io.BytesIO(content)
    value.name = name
    return value


class CloudFilesTests(unittest.TestCase):
    def test_paths_and_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = save_uploads([
                upload("../../example.pdf", b"first"),
                upload("C:\\Users\\person\\example.pdf", b"second"),
                upload("example.docx", b"third"),
                upload("EXAMPLE.pdf", b"fourth"),
            ], root)
            self.assertEqual(len({p.stem.casefold() for p in paths}), 4)
            self.assertTrue(all(p.parent == root for p in paths))
            self.assertEqual([p.read_bytes() for p in paths], [b"first", b"second", b"third", b"fourth"])

    def test_unsupported_file(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                save_uploads([upload("program.exe")], Path(temp))

    def test_zip_is_portable_and_excludes_sibling_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "outputs_run"
            (report / "raw_results").mkdir(parents=True)
            (report / "raw_results" / "example.json").write_text("{}")
            (root / "cache.json").write_text("private")
            payload = results_zip(report)
        with ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(archive.namelist(), ["raw_results/example.json"])
            self.assertEqual(archive.read("raw_results/example.json"), b"{}")

    def test_sessions_do_not_share_uploads(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = save_uploads([upload("example.txt", b"one")], Path(first))[0]
            b = save_uploads([upload("example.txt", b"two")], Path(second))[0]
            self.assertEqual(a.read_bytes(), b"one")
            self.assertEqual(b.read_bytes(), b"two")


if __name__ == "__main__":
    unittest.main()
