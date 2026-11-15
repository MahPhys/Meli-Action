"""Identify supported music providers from URL hostnames, not substrings."""
from urllib.parse import urlsplit
import sys

# This file runs as a script and is also importable from tests.
try:
    from scripts.validate_workflow import validate_url
except ModuleNotFoundError:
    from validate_workflow import validate_url


def media_provider(url):
    validate_url(url)
    host = urlsplit(url).hostname.lower().rstrip('.')
    if host == 'spotify.com' or host.endswith('.spotify.com'):
        return 'spotify'
    if host in ('soundcloud.com', 'snd.sc') or host.endswith('.soundcloud.com'):
        return 'soundcloud'
    raise ValueError('URL must belong to Spotify or SoundCloud')


def main():
    try:
        print('provider=' + media_provider(sys.argv[1]))
    except (ValueError, IndexError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
