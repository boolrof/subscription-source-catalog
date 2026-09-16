import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("local_publisher",Path(__file__).resolve().parents[1]/"deploy/vps/publish-local-snapshot.py")
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)

class SnapshotPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.repo=self.base/"repo";self.repo.mkdir()
        self.root=self.base/"published"
        self.git("init","-q");self.git("config","user.name","Test");self.git("config","user.email","test@example.invalid")
        self.data={"data/sources.json":{"schema":"vgm-subscription-catalog-v1","sources":[{"source_id":"a"*24}]},
          "exports/country_handoff_v4.json":{"schema":"subscription-source-country-handoff-v4","countries":{"HR":[]}},
          "exports/countries/HR.json":{"schema":"subscription-source-country-ranking-v3","country":"HR","nodes":[]}}
        self.commit()
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):
        return subprocess.check_output(["git","-C",str(self.repo),*args],stderr=subprocess.DEVNULL).decode().strip()
    def commit(self):
        for name,payload in self.data.items():
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(payload))
        self.git("add",".");self.git("commit","-qm","fixture")
        self.sha=self.git("rev-parse","HEAD");self.tree=self.git("rev-parse","HEAD^{tree}")

    def test_immutable_tree_ignores_dirty_working_tree_and_repeat_is_idempotent(self):
        (self.repo/"data/sources.json").write_text("dirty partial data")
        first=publisher.publish(self.repo,self.tree,self.root,self.sha)
        current=(self.root/"current").resolve()
        before=(current/"manifest.json").read_bytes()
        self.assertEqual(json.loads((current/"data/sources.json").read_text()),self.data["data/sources.json"])
        second=publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertEqual(first,second)
        self.assertEqual((current/"manifest.json").read_bytes(),before)

    def test_invalid_next_generation_preserves_current(self):
        publisher.publish(self.repo,self.tree,self.root,self.sha)
        old=(self.root/"current").resolve()
        self.data["exports/countries/HR.json"]["nodes"]=[{"source_id":"b"*24}]
        self.commit()
        with self.assertRaises(ValueError):publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertEqual((self.root/"current").resolve(),old)

    def test_current_switch_occurs_only_after_complete_generation(self):
        original=publisher.os.replace
        def checked(src,dst):
            if Path(dst).name=="current":
                target=(Path(src).parent/Path(src).readlink()).resolve()
                manifest=json.loads((target/"manifest.json").read_text())
                for name,entry in manifest["files"].items():
                    self.assertEqual((target/name).stat().st_size,entry["bytes"])
            return original(src,dst)
        with patch.object(publisher.os,"replace",side_effect=checked):
            publisher.publish(self.repo,self.tree,self.root,self.sha)

    def test_credential_bearing_artifact_is_rejected(self):
        self.data["data/sources.json"]["test_only"]="trojan://fixture@example.invalid:443"
        self.commit()
        with self.assertRaises(ValueError):publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertFalse((self.root/"current").exists())

    def test_retention_preserves_recent_current_previous_and_eight_generations(self):
        import os
        base=self.root/"generations";base.mkdir(parents=True)
        names=[f"{n:040x}" for n in range(11)]
        for n,name in enumerate(names):
            path=base/name;path.mkdir()
            (path/"manifest.json").write_text(json.dumps({"schema":publisher.SCHEMA,"generation":name}))
            os.utime(path,(n,n))
        removed=publisher.prune_generations(self.root,names[0],names[1],now=200000)
        self.assertEqual(removed,1)
        self.assertTrue((base/names[0]).exists())
        self.assertTrue((base/names[1]).exists())
        self.assertEqual(len(list(base.iterdir())),10)

    def test_reader_lease_survives_retention_until_released(self):
        import fcntl, os
        base=self.root/"generations";base.mkdir(parents=True)
        names=[f"{n:040x}" for n in range(11)]
        for n,name in enumerate(names):
            path=base/name;path.mkdir()
            (path/"manifest.json").write_text(json.dumps({"schema":publisher.SCHEMA,"generation":name}))
            os.utime(path,(n,n))
        with (base/names[2]/"manifest.json").open("rb") as reader:
            fcntl.flock(reader,fcntl.LOCK_SH)
            self.assertEqual(publisher.prune_generations(self.root,names[0],names[1]),0)
            self.assertTrue((base/names[2]).is_dir())
        self.assertEqual(publisher.prune_generations(self.root,names[0],names[1]),1)

    def test_existing_manifest_symlink_rejected_and_current_preserved(self):
        publisher.publish(self.repo,self.tree,self.root,self.sha)
        current=(self.root/"current").readlink()
        manifest=self.root/current/"manifest.json"
        outside=self.base/"manifest-copy";outside.write_bytes(manifest.read_bytes())
        manifest.unlink();manifest.symlink_to(outside)
        with self.assertRaises(OSError):publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertEqual((self.root/"current").readlink(),current)

    def test_existing_artifact_tampering_rejected(self):
        publisher.publish(self.repo,self.tree,self.root,self.sha)
        current=(self.root/"current").readlink()
        (self.root/current/"data/sources.json").write_text("{}")
        with self.assertRaises(ValueError):publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertEqual((self.root/"current").readlink(),current)

    def test_generations_symlink_rejected_without_chmod_target(self):
        import os
        self.root.mkdir()
        outside=self.base/"outside";outside.mkdir(mode=0o700)
        (self.root/"generations").symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):publisher.publish(self.repo,self.tree,self.root,self.sha)
        self.assertEqual(outside.stat().st_mode & 0o777,0o700)
