#!/usr/bin/env python3
"""Atomic publication helpers for backup archives and credential directories."""

from __future__ import annotations

import argparse
import errno
import os
import pathlib
import shutil
import uuid


def publish_no_clobber(temp_path: str, desired_path: str) -> str:
    """Atomically publish a same-filesystem temp file without replacing a peer."""
    temp = pathlib.Path(temp_path)
    desired = pathlib.Path(desired_path)
    suffixes = "".join(desired.suffixes)
    stem = desired.name.removesuffix(suffixes)
    counter = 0
    while True:
        candidate = desired if counter == 0 else desired.with_name(f"{stem}-{counter}{suffixes}")
        try:
            os.link(temp, candidate)
        except OSError as error:
            if error.errno == errno.EEXIST:
                counter += 1
                continue
            raise
        temp.unlink()
        return str(candidate)


def replace_directory(new_path: str, target_path: str) -> None:
    """Replace target atomically and roll it back if publishing new_path fails."""
    new = pathlib.Path(new_path)
    target = pathlib.Path(target_path)
    backup = target.with_name(f".{target.name}-restore-old-{uuid.uuid4().hex}")
    moved_old = False
    try:
        if target.exists() or target.is_symlink():
            os.rename(target, backup)
            moved_old = True
        os.rename(new, target)
    except BaseException:
        if moved_old and not target.exists():
            os.rename(backup, target)
        raise
    if moved_old:
        if backup.is_symlink() or backup.is_file():
            backup.unlink()
        else:
            shutil.rmtree(backup)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("temp_path")
    publish.add_argument("desired_path")
    replace = subparsers.add_parser("replace-directory")
    replace.add_argument("new_path")
    replace.add_argument("target_path")
    args = parser.parse_args()
    if args.command == "publish":
        print(publish_no_clobber(args.temp_path, args.desired_path))
    else:
        replace_directory(args.new_path, args.target_path)


if __name__ == "__main__":
    main()
