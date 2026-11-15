"""Capture a web page with Chromium and save it as a ZIP containing MHTML."""
import argparse
import asyncio
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
import zipfile

from scripts.validate_workflow import validate_url


def sanitize_filename(name: str) -> str:
    """Return a portable, bounded single filename, never a path."""
    name = re.sub(r'[\\/*?:"<>|\x00-\x1f\x7f]', '_', name).strip(' .')
    # Limit UTF-8 bytes as well as characters for common filesystem limits.
    while len(name.encode('utf-8')) > 180:
        name = name[:-1]
    return name or 'webpage'


def filename_for(url: str, title: str | None = None) -> str:
    validate_url(url)
    parsed = urlparse(url)
    return sanitize_filename(title if title else parsed.path.strip('/').replace('/', '_') or parsed.hostname)


async def save_mhtml(url: str, output_file: str, *, executable_path: str | None = None) -> None:
    """Render a page and capture a Chromium MHTML snapshot, closing on failure."""
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=executable_path)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            response = await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            if response is not None and response.status >= 400:
                raise RuntimeError(f'Page returned HTTP {response.status}')
            # Some sites never become idle (polling/streaming); don't wait forever.
            try:
                await page.wait_for_load_state('networkidle', timeout=10000)
            except PlaywrightTimeout:
                pass
            client = await context.new_cdp_session(page)
            snapshot = await client.send('Page.captureSnapshot', {'format': 'mhtml'})
            Path(output_file).write_text(snapshot['data'], encoding='utf-8')
        finally:
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Download a webpage as MHTML.')
    parser.add_argument('--url', required=True, help='HTTP(S) URL of the page to download')
    parser.add_argument('--title', help='Optional title for the output file')
    args = parser.parse_args()
    try:
        base_name = filename_for(args.url, args.title)
    except ValueError as exc:
        parser.error(str(exc))

    download_dir = Path('download')
    download_dir.mkdir(parents=True, exist_ok=True)
    mhtml_filename = f'{base_name}.mhtml'
    zip_path = download_dir / f'{base_name}.zip'
    print(f'Downloading page → {mhtml_filename}')
    # A private temporary directory avoids deleting or overwriting user files.
    # Stage the archive beside its destination so os.replace is atomic.
    with tempfile.TemporaryDirectory() as temp_dir:
        mhtml_path = Path(temp_dir) / mhtml_filename
        asyncio.run(save_mhtml(args.url, str(mhtml_path)))
        with tempfile.NamedTemporaryFile(dir=download_dir, suffix='.tmp', delete=False) as temp_zip:
            temp_zip_path = Path(temp_zip.name)
        try:
            with zipfile.ZipFile(temp_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(mhtml_path, arcname=mhtml_filename)
            os.replace(temp_zip_path, zip_path)
        finally:
            temp_zip_path.unlink(missing_ok=True)
    print(f'Created {zip_path} (contains {mhtml_filename})')


if __name__ == '__main__':
    main()
