"""Reject staged blobs over GitHub's per-file limit before repository pushes."""
import subprocess
import sys

MAX_BYTES = 100 * 1024 * 1024


def find_oversized(limit=MAX_BYTES):
    changed = set(filter(None, subprocess.check_output([
        'git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'
    ]).split(b'\0')))
    if not changed:
        return []
    index = subprocess.check_output(['git', 'ls-files', '--stage', '-z'])
    objects = {}
    for entry in filter(None, index.split(b'\0')):
        info, sep, name = entry.partition(b'\t')
        if not sep:
            raise RuntimeError('Invalid Git index entry')
        mode, object_id, stage = info.split(b' ')
        if name in changed and stage == b'0':
            objects[name] = object_id
    missing = changed.difference(objects)
    if missing:
        raise RuntimeError(f'Cannot inspect staged paths: {sorted(missing)!r}')

    # Hashes, unlike filenames, are safe to pass to the newline-delimited batch
    # protocol. One Git subprocess handles the whole index, not one per file.
    unique_ids = sorted(set(objects.values()))
    data = b''.join(oid + b'\n' for oid in unique_ids)
    result = subprocess.run(['git', 'cat-file', '--batch-check'], input=data,
                            capture_output=True, check=True)
    lines = result.stdout.splitlines()
    if len(lines) != len(unique_ids):
        raise RuntimeError('Unexpected Git object metadata')
    sizes = {}
    for oid, line in zip(unique_ids, lines):
        fields = line.split(b' ')
        if len(fields) != 3 or fields[0] != oid or not fields[2].isdigit():
            raise RuntimeError(f'Cannot inspect staged object {oid.decode()}')
        sizes[oid] = (fields[1], int(fields[2]))
    return [(name.decode(errors='replace'), sizes[oid][1])
            for name, oid in sorted(objects.items())
            if sizes[oid][0] == b'blob' and sizes[oid][1] > limit]


def main():
    try:
        oversized = find_oversized()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    for name, size in oversized:
        print(f'::error::Staged file exceeds GitHub 100 MiB limit: {name!r} ({size} bytes)', file=sys.stderr)
    return 1 if oversized else 0


if __name__ == '__main__':
    sys.exit(main())
