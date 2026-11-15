"""Validate workflow inputs before they reach downloaders or filesystem operations."""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def validate_url(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError
        _ = url.port
    except ValueError:
        raise ValueError('URL must be an absolute HTTP(S) URL without control characters') from None


def validate_folder(value):
    p = Path(value)
    if (not value or p.is_absolute() or any(part in ('.', '..') or part.startswith(('.', '-')) for part in value.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('output folder must be a non-hidden relative path without . or .. components')
    root = Path.cwd().resolve()
    resolved = p.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('output folder must be inside the repository')


def validate_size(value, maximum, allow_zero=False):
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,3})', value or ''):
        raise ValueError('part size must be a whole number')
    number = int(value)
    if number < (0 if allow_zero else 1) or number > maximum:
        raise ValueError(f'part size must be between {0 if allow_zero else 1} and {maximum} MiB')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url')
    parser.add_argument('--folder')
    parser.add_argument('--size')
    parser.add_argument('--max-size', type=int, default=95)
    parser.add_argument('--allow-zero', action='store_true')
    args = parser.parse_args()
    try:
        if args.url is not None: validate_url(args.url)
        if args.folder is not None: validate_folder(args.folder)
        if args.size is not None: validate_size(args.size, args.max_size, args.allow_zero)
    except ValueError as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__': main()
