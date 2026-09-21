import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CloudUITests(unittest.TestCase):
    def test_run_exports_and_cleans_temporary_files(self):
        uploaded = io.BytesIO(b"Synthetic CV for testing only")
        uploaded.name = "example.txt"
        observed = []

        def fake_process(**kwargs):
            observed.extend(kwargs["cv_paths"])
            self.assertTrue(observed[0].is_file())
            reports = kwargs["output_root"] / "outputs_test"
            reports.mkdir(parents=True)
            excel = reports / "screening_results.xlsx"
            excel.write_bytes(b"synthetic workbook")
            return {"outputs_dir": str(reports), "excel_path": str(excel),
                    "processed": 1, "skipped": 0, "results": []}

        with patch.dict(os.environ, {"NIRAS_ALLOW_LOCAL_PATHS": "", "OPENAI_API_KEY": "test-only"}), \
             patch("streamlit.file_uploader", return_value=[uploaded]), \
             patch("niras_cv_screener.workflow.process_paths", side_effect=fake_process):
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
            next(item for item in app.button if item.label == "Run Screening").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.last_run["excel_download"], b"synthetic workbook")
            self.assertEqual(len(app.get("download_button")), 2)
            self.assertFalse(observed[0].exists())
            self.assertFalse(Path(app.session_state.last_run["outputs_dir"]).exists())
            app.session_state.workspace.cleanup()

    def test_cloud_defaults_and_downloads(self):
        with patch.dict(os.environ, {"NIRAS_ALLOW_LOCAL_PATHS": "", "OPENAI_API_KEY": ""}):
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(any("folder" in item.label.lower() for item in app.text_input))
            self.assertEqual(next(item for item in app.radio if item.label == "CV input").options, ["Upload files"])
            self.assertTrue(next(item for item in app.button if item.label == "Run Screening").disabled)
            app.session_state.last_run = {
                "results": [], "excel_download": b"test workbook", "zip_download": b"test archive",
                "errors": [{"file": "synthetic.pdf", "error": "Synthetic test error"}], "skipped": 1,
            }
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 2)
            workspace = Path(app.session_state.workspace.name)
            next(item for item in app.button if item.label == "Clear session files and results").click().run()
            self.assertFalse(app.exception)
            self.assertIsNone(app.session_state.last_run)
            self.assertFalse(workspace.exists())
            app.session_state.workspace.cleanup()

    def test_local_mode_retains_folder_controls(self):
        with patch.dict(os.environ, {"NIRAS_ALLOW_LOCAL_PATHS": "true"}):
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any(item.label == "Output folder on this computer" for item in app.text_input))
            self.assertIn("Folder path", next(item for item in app.radio if item.label == "CV input").options)
            app.session_state.workspace.cleanup()


if __name__ == "__main__":
    unittest.main()
