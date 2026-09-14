"""CLI entry point: export a Notion page (and its child pages) to standard
Markdown files with locally-downloaded images.

Output naming
=============
The ``-o`` / ``--output`` directory is the final destination.  The main page
is named after the last path component of that directory (e.g.
``output/Rust`` → ``output/Rust/Rust.md``).

Directory vs Content page
=========================
Each page is classified as either a **directory page** or a **content page**.
The classification determines how its child pages are laid out on disk.

A page is a **directory page** when BOTH conditions hold:

1. It has at least one first-level child page reference (``PageRefNode``
   among the ``Document.nodes`` — nested refs inside toggles don't count).
2. The total number of non-child-page elements in the page is below
   ``INDEX_PAGE_THRESHOLD`` (default 30).  "Total" means a recursive count
   over toggles/lists/etc within the current page, but NOT crossing into
   child pages.

If either condition is false the page is a **content page**.

Layout behaviour:

- **Directory page**: each first-level child page gets its own subdirectory
  named after the child page's Notion title; the current page becomes an
  index file linking into those subdirectories.  This is applied recursively
  — every child page independently makes the same directory-vs-content
  decision when it is exported.
- **Content page**: child pages are written as sibling ``.md`` files in the
  same directory (flat, the original behaviour).

A page with NO first-level child pages is always a content page, even if it
has very few elements.  The rationale: without child pages there is nothing
to split into subdirectories.

Why this matters: Notion users commonly create "table of contents" pages
that are nearly empty except for links to sub-pages.  Exporting them flat
would dump dozens of unrelated files into one directory.  The threshold
check is cheap — once the count exceeds ``INDEX_PAGE_THRESHOLD`` the
recursion short-circuits immediately.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from .assets import AssetDownloader
from .fetcher import NotionClient, fetch_document, normalize_page_id
from .model import Document, EmptyNode, IRNode, PageRefNode, ToggleNode
from .renderer import Renderer

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
_MAX_FILENAME_LEN = 80

# A page with fewer non-child-page elements than this (and at least one
# first-level child page) is treated as a "directory page".  See module
# docstring for the full explanation.
INDEX_PAGE_THRESHOLD = 30


def _slugify(title: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", title).strip()
    return (cleaned or "untitled")[:_MAX_FILENAME_LEN]


def _has_first_level_child_pages(doc: Document) -> bool:
    """Check whether any top-level node is a child-page reference."""
    return any(isinstance(n, PageRefNode) for n in doc.nodes)


def _count_non_page_elements(nodes: list[IRNode], limit: int) -> int:
    """Recursively count non-PageRefNode, non-EmptyNode elements.

    Recurses into ToggleNode children but NOT into child pages.
    Short-circuits as soon as ``limit`` is reached for efficiency.
    """
    count = 0
    for node in nodes:
        if isinstance(node, (PageRefNode, EmptyNode)):
            continue
        count += 1
        if count >= limit:
            return count
        if isinstance(node, ToggleNode):
            count += _count_non_page_elements(node.children, limit - count)
            if count >= limit:
                return count
    return count


def _is_directory_page(doc: Document) -> bool:
    """Determine if a page should create subdirectories for its child pages."""
    if not _has_first_level_child_pages(doc):
        return False
    return _count_non_page_elements(doc.nodes, INDEX_PAGE_THRESHOLD) < INDEX_PAGE_THRESHOLD


class Exporter:
    """Recursively exports a page and every Notion child page it links to.

    The main page filename is determined by the last segment of the output
    directory (e.g. ``Rust/`` -> ``Rust.md``), so the caller controls naming
    via the directory path rather than via a separate ``--name`` flag.
    """

    def __init__(self, client: NotionClient, output_dir: Path, main_filename: str) -> None:
        self._client = client
        self._output_dir = output_dir
        self._main_filename = main_filename
        self._downloader = AssetDownloader(output_dir)
        self._exported: dict[str, str] = {}  # page_id -> relative path already written

    def close(self) -> None:
        self._downloader.close()

    def export_page(self, page_id: str) -> str:
        """Export ``page_id`` and return its path relative to ``_output_dir``."""
        page_id = normalize_page_id(page_id)
        if page_id in self._exported:
            return self._exported[page_id]

        title = self._client.fetch_page_title(page_id) or page_id
        document = fetch_document(self._client, page_id)

        if _is_directory_page(document):
            return self._export_directory_page(page_id, title, document)
        return self._export_content_page(page_id, title, document)

    def _export_content_page(self, page_id: str, title: str, document: Document) -> str:
        """Export a content-rich page: child pages are flat siblings."""
        filename = self._reserve_filename(page_id, title)

        image_map = self._downloader.download_all(document)
        renderer = Renderer(
            image_resolver=lambda url, m=image_map: m.get(url, url),
            page_ref_resolver=self._resolve_child_page_flat,
        )
        markdown = renderer.render(document)
        (self._output_dir / filename).write_text(markdown, encoding="utf-8")
        print(f"Exported {title!r} -> {filename}", file=sys.stderr)
        return filename

    def _export_directory_page(self, page_id: str, title: str, document: Document) -> str:
        """Export a directory page: each child page gets its own subdirectory."""
        filename = self._reserve_filename(page_id, title)

        def resolve_child_as_subdir(child_url: str) -> str:
            child_id = normalize_page_id(child_url)
            child_title = self._client.fetch_page_title(child_id) or child_id
            subdir_name = _slugify(child_title)
            subdir = self._output_dir / subdir_name
            subdir.mkdir(parents=True, exist_ok=True)

            # Create a sub-exporter for the child page's own directory.
            sub_exporter = Exporter(self._client, subdir, subdir_name + ".md")
            sub_exporter._exported = self._exported  # share cycle guard
            try:
                child_filename = sub_exporter.export_page(child_id)
            finally:
                sub_exporter.close()
            # Return path relative to current output_dir.
            return f"{subdir_name}/{child_filename}"

        image_map = self._downloader.download_all(document)
        renderer = Renderer(
            image_resolver=lambda url, m=image_map: m.get(url, url),
            page_ref_resolver=resolve_child_as_subdir,
        )
        markdown = renderer.render(document)
        (self._output_dir / filename).write_text(markdown, encoding="utf-8")
        print(f"Exported {title!r} -> {filename} (directory page)", file=sys.stderr)
        return filename

    def _resolve_child_page_flat(self, child_url: str) -> str:
        """Resolve a child page as a flat sibling file."""
        return self.export_page(child_url)

    def _reserve_filename(self, page_id: str, title: str) -> str:
        """Pick a unique filename and register it in the cycle guard."""
        if page_id in self._exported:
            return self._exported[page_id]
        # First page exported uses the directory-derived main filename.
        if not self._exported:
            filename = self._main_filename
        else:
            filename = self._unique_filename(title)
        self._exported[page_id] = filename
        return filename

    def _unique_filename(self, title: str) -> str:
        base = _slugify(title)
        candidate = f"{base}.md"
        used = set(self._exported.values())
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}.md"
            suffix += 1
        return candidate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="notion2md", description="Convert a Notion page to standard Markdown.")
    parser.add_argument("page", help="Notion page id or URL to export")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Output directory. The last path segment becomes the main document name "
        "(e.g. output/Rust -> Rust/Rust.md).",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("NOTION_KEY")
    if not api_key:
        parser.error("NOTION_KEY environment variable is required")

    output_dir: Path = args.output
    main_filename = output_dir.name + ".md"
    output_dir.mkdir(parents=True, exist_ok=True)

    with NotionClient(api_key) as client:
        exporter = Exporter(client, output_dir, main_filename)
        try:
            exporter.export_page(args.page)
        finally:
            exporter.close()

    print(f"Main page written to {output_dir / main_filename}")


if __name__ == "__main__":
    main()
