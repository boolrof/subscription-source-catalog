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


    def test_pipeline_emits_compute_stage_and_shard_timings(self):
        script = (Path(__file__).parents[1] / "deploy/vps/catalog-pipeline").read_text()
        self.assertIn('timing compute_shard=$shard duration_seconds=', script)
        self.assertIn('timing compute_total duration_seconds=', script)

    def test_cleanup_runs_git_gc_directly_for_catalog_service_user(self):
        script = (Path(__file__).parents[1] / "deploy/vps/catalog-cleanup").read_text()
        self.assertIn('if [[ "$(id -un)" == "catalog" ]]', script)
        self.assertIn('git -C "$REPO" gc --auto --no-detach --prune=2.weeks.ago', script)
        self.assertNotIn('--prune=now', script)
        self.assertIn('elif [[ "$EUID" -eq 0 ]]', script)

if __name__ == "__main__":
    unittest.main()
