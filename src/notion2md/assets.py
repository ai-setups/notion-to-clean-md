"""Download images referenced by a Document and rewrite their URLs to local
relative paths.

Notion image URLs are short-lived signed S3 links, so they must be
downloaded during export; leaving the signed URL in the output would break
as soon as it expires.

Downloads are submitted to a background thread pool so the main export flow
(API calls, parsing, rendering) is never blocked by image I/O.  The
URL-to-local-path mapping is computed deterministically from the URL hash,
so it is available immediately — before any bytes are fetched.  The caller
must invoke ``close()`` (or ``wait()``) before the process exits to ensure
every image has been written to disk.
"""

from __future__ import annotations

import hashlib
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .model import Document, ImageNode, IRNode, ToggleNode

ASSETS_DIRNAME = "assets"
DEFAULT_WORKERS = 5


def _collect_image_urls(nodes: list[IRNode]) -> list[str]:
    urls: list[str] = []
    for node in nodes:
        if isinstance(node, ImageNode):
            urls.append(node.url)
        elif isinstance(node, ToggleNode):
            urls.extend(_collect_image_urls(node.children))
    return urls


def _local_filename(url: str) -> str:
    """Derive a stable, collision-resistant filename for an image URL.

    Notion frequently reuses generic basenames (e.g. `Untitled.png`) across
    many images in the same page, so the path+basename alone is not unique
    enough; a short hash of the full URL (including the S3 object key) is
    prefixed to keep filenames stable and non-colliding.
    """
    parsed = urlparse(url)
    basename = Path(parsed.path).name or "image"
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    return f"{digest}_{basename}"


class AssetDownloader:
    """Downloads images into ``<output_dir>/assets/`` via a background pool.

    ``download_all`` returns the URL → relative-path mapping immediately;
    actual fetches run in background threads.  Call ``close()`` to block
    until every pending download finishes.
    """

    def __init__(
        self,
        output_dir: Path,
        client: httpx.Client | None = None,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        self._output_dir = output_dir
        self._assets_dir = output_dir / ASSETS_DIRNAME
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self._owns_client = client is None
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._futures: list[Future[None]] = []

    def download_all(self, document: Document) -> dict[str, str]:
        """Compute the URL → local path mapping and submit downloads.

        Returns immediately — downloads proceed in the background.
        """
        unique_urls = list(dict.fromkeys(_collect_image_urls(document.nodes)))
        if not unique_urls:
            return {}

        self._assets_dir.mkdir(parents=True, exist_ok=True)
        mapping: dict[str, str] = {}
        for url in unique_urls:
            rel_path = f"{ASSETS_DIRNAME}/{_local_filename(url)}"
            mapping[url] = rel_path
            self._futures.append(self._pool.submit(self._download_one, url, rel_path))
        return mapping

    def wait(self) -> None:
        """Block until all pending downloads complete, reporting errors."""
        for future in self._futures:
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"Image download failed: {exc}", file=sys.stderr)
        self._futures.clear()

    def close(self) -> None:
        """Wait for pending downloads, then release resources."""
        self.wait()
        self._pool.shutdown(wait=False)
        if self._owns_client:
            self._client.close()

    def _download_one(self, url: str, rel_path: str) -> None:
        target = self._output_dir / rel_path
        if not target.exists():
            response = self._client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
