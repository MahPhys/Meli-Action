"""Publish completed files without overwriting existing repository files."""
import argparse
import errno
import os
from pathlib import Path
import shutil
import sys


def move_outputs(source: Path, destination: Path) -> list[Path]:
    if not source.is_dir():
        raise ValueError(f'Output directory does not exist: {source}')
    files = sorted(source.iterdir())
    if not files:
        raise ValueError('No files to publish')
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Only regular files can be published: {path}')
    destination.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = destination / path.name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f'Refusing to overwrite existing file: {target}')

    created = []
    try:
        for path in files:
            target = destination / path.name
            try:
                # Hard links are atomic and do not overwrite an existing path.
                os.link(path, target, follow_symlinks=False)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # Cross-filesystem fallback still creates exclusively.
                with open(path, 'rb') as src, open(target, 'xb') as dst:
                    created.append(target)
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                continue
            created.append(target)
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    for path in files:
        path.unlink()
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        files = move_outputs(args.source, args.destination)
    except (OSError, ValueError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    print(f'Published {len(files)} file(s) to {args.destination}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
