from __future__ import annotations

import io
import pathlib
import tarfile
import tempfile
import unittest

from safe_extract import safe_extract


class SafeExtractTests(unittest.TestCase):
    def make_archive(self, members: list[tuple[tarfile.TarInfo, bytes]]) -> pathlib.Path:
        root = pathlib.Path(self.addCleanupDirectory())
        archive_path = root / "archive.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for member, content in members:
                archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
        return archive_path

    def addCleanupDirectory(self) -> str:
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        return directory

    def test_extracts_allowed_regular_files(self) -> None:
        member = tarfile.TarInfo("secrets/provider_keys.key")
        member.size = 3
        archive = self.make_archive([(member, b"key")])
        destination = self.addCleanupDirectory()
        safe_extract(str(archive), destination, {"secrets"})
        self.assertEqual(pathlib.Path(destination, member.name).read_bytes(), b"key")

    def test_rejects_traversal_and_absolute_paths(self) -> None:
        for name in ("../../escape", "/tmp/escape"):
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.size = 1
                archive = self.make_archive([(member, b"x")])
                with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                    safe_extract(str(archive), self.addCleanupDirectory(), {"secrets"})

    def test_rejects_escaping_links_and_special_files(self) -> None:
        link = tarfile.TarInfo("secrets/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive = self.make_archive([(link, b"")])
        with self.assertRaises((tarfile.FilterError, ValueError)):
            safe_extract(str(archive), self.addCleanupDirectory(), {"secrets"})

        fifo = tarfile.TarInfo("secrets/fifo")
        fifo.type = tarfile.FIFOTYPE
        archive = self.make_archive([(fifo, b"")])
        with self.assertRaisesRegex(ValueError, "unsupported archive member type"):
            safe_extract(str(archive), self.addCleanupDirectory(), {"secrets"})

    def test_rejects_unexpected_roots(self) -> None:
        member = tarfile.TarInfo("other/value")
        member.size = 1
        archive = self.make_archive([(member, b"x")])
        with self.assertRaisesRegex(ValueError, "unexpected archive path"):
            safe_extract(str(archive), self.addCleanupDirectory(), {"secrets"})


if __name__ == "__main__":
    unittest.main()
