"""Fetch a Notion page's content: primarily via the Markdown API, falling
back to the recursive Block API when the Markdown API response is truncated.
"""

from __future__ import annotations

import re
import time
from typing import Self

import httpx

from .model import Document
from .parser import parse_blocks, parse_markdown

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"

_HEX32_RE = re.compile(r"[0-9a-fA-F]{32}")
_DASHED_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def normalize_page_id(raw: str) -> str:
    """Normalize a Notion page id, page URL, or app.notion.com URL into the
    canonical dashed UUID form Notion's REST API expects.
    """
    if _DASHED_UUID_RE.match(raw):
        return raw
    match = _HEX32_RE.search(raw.replace("-", ""))
    if not match:
        raise ValueError(f"Could not extract a Notion page id from: {raw!r}")
    hex32 = match.group(0)
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


class NotionClient:
    """Thin HTTP client for the Notion REST API used by this tool."""

    def __init__(self, api_key: str, max_retries: int = 3) -> None:
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": NOTION_VERSION,
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        for attempt in range(self._max_retries):
            response = self._client.request(method, path, **kwargs)
            if response.status_code == 429 and attempt < self._max_retries - 1:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError(f"Exhausted retries calling {method} {path}")

    def fetch_markdown(self, page_id: str) -> dict:
        """Call `GET /v1/pages/{page_id}/markdown`."""
        return self._request("GET", f"/pages/{page_id}/markdown").json()

    def fetch_page_title(self, page_id: str) -> str | None:
        """Best-effort lookup of a page's title via `GET /v1/pages/{page_id}`."""
        try:
            data = self._request("GET", f"/pages/{page_id}").json()
        except httpx.HTTPStatusError:
            return None
        for prop in data.get("properties", {}).values():
            if prop.get("type") == "title":
                text = "".join(seg.get("plain_text", "") for seg in prop.get("title", []))
                return text or None
        return None

    def fetch_block_children(self, block_id: str) -> list[dict]:
        """Fetch all children of a block, handling pagination."""
        results: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"page_size": 100}  # noqa: bare-dict HTTP query parameters, not a domain model
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/blocks/{block_id}/children", params=params).json()
            results.extend(data["results"])
            if not data.get("has_more"):
                return results
            cursor = data["next_cursor"]

    def fetch_blocks_recursive(self, block_id: str) -> list[dict]:
        """Fetch a block's children and recursively populate `children` for
        every block that has nested content, matching the shape produced by
        the reference fixture (`/tmp/notion_block_api.json`).
        """
        blocks = self.fetch_block_children(block_id)
        for block in blocks:
            block["children"] = self.fetch_blocks_recursive(block["id"]) if block.get("has_children") else []
        return blocks


def fetch_document(client: NotionClient, page_id: str) -> Document:
    """Fetch a page and parse it into the IR, using the Block API fallback
    only when the Markdown API response was truncated.
    """
    response = client.fetch_markdown(page_id)
    if not response.get("truncated"):
        return parse_markdown(response["markdown"])

    blocks = client.fetch_blocks_recursive(page_id)
    return parse_blocks(blocks)
