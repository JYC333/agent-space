from __future__ import annotations

import pathlib
import tempfile
import threading
import unittest
from unittest.mock import patch

import atomic_ops


class AtomicOpsTests(unittest.TestCase):
    def root(self) -> pathlib.Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return pathlib.Path(temporary.name)

    def test_concurrent_publish_never_clobbers(self) -> None:
        root = self.root()
        temps = [root / f"temp-{index}" for index in range(2)]
        for index, path in enumerate(temps):
            path.write_text(f"archive-{index}")
        barrier = threading.Barrier(2)
        results: list[str] = []

        def publish(path: pathlib.Path) -> None:
            barrier.wait()
            results.append(atomic_ops.publish_no_clobber(str(path), str(root / "backup.tar.gz")))

        threads = [threading.Thread(target=publish, args=(path,)) for path in temps]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(set(results)), 2)
        self.assertEqual({pathlib.Path(path).read_text() for path in results}, {"archive-0", "archive-1"})
        self.assertTrue(all(not path.exists() for path in temps))

    def test_directory_replace_rolls_back_on_publish_failure(self) -> None:
        root = self.root()
        target = root / "secrets"
        new = root / ".secrets-new"
        target.mkdir()
        new.mkdir()
        (target / "key").write_text("old")
        (new / "key").write_text("new")
        real_rename = atomic_ops.os.rename
        calls = 0

        def fail_second(source: pathlib.Path, destination: pathlib.Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated publish failure")
            real_rename(source, destination)

        with patch.object(atomic_ops.os, "rename", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated publish failure"):
                atomic_ops.replace_directory(str(new), str(target))
        self.assertEqual((target / "key").read_text(), "old")
        self.assertTrue(new.exists())

    def test_directory_replace_publishes_new_and_removes_old(self) -> None:
        root = self.root()
        target = root / "secrets"
        new = root / ".secrets-new"
        target.mkdir()
        new.mkdir()
        (target / "key").write_text("old")
        (new / "key").write_text("new")
        atomic_ops.replace_directory(str(new), str(target))
        self.assertEqual((target / "key").read_text(), "new")
        self.assertFalse(new.exists())
