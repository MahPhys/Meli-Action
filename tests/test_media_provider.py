import unittest
from scripts.media_provider import media_provider


class MediaProviderTests(unittest.TestCase):
    def test_supported_hosts(self):
        for url, expected in [('https://open.spotify.com/track/example', 'spotify'),
                              ('https://m.soundcloud.com/artist/song', 'soundcloud'),
                              ('https://snd.sc/test', 'soundcloud')]:
            with self.subTest(url=url): self.assertEqual(media_provider(url), expected)

    def test_rejects_spoofed_hosts(self):
        for url in ('https://example.com/?url=spotify.com', 'https://spotify.com.evil.com/',
                    'https://soundcloud.com@evil.com/', 'file:///tmp/soundcloud.com'):
            with self.subTest(url=url), self.assertRaises(ValueError): media_provider(url)
