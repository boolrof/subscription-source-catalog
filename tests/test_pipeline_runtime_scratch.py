import unittest
from pathlib import Path


class PipelineRuntimeScratchTests(unittest.TestCase):
    def test_runtime_scratch_is_excluded_before_publication_allowlist(self):
        script = (Path(__file__).parents[1] / "deploy/vps/catalog-pipeline").read_text()
        self.assertIn("grep -vE '^\\.catalog-runtime/'", script)
        self.assertIn("stage publication allowlist", script)
        self.assertNotIn("git add .catalog-runtime", script)
        self.assertEqual(script.count("cleanup warning: housekeeping incomplete; published catalog remains valid"), 2)
        self.assertEqual(script.count("if ! CATALOG_CLEANUP_FROM_PIPELINE=1"), 2)


if __name__ == "__main__":
    unittest.main()
