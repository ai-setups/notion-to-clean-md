"""Parse Notion's enhanced markdown (or the raw block API tree) into the IR.

Enhanced markdown mixes HTML tags (``<details>``, ``<summary>``, ``<table>``,
``<page>``, ``<empty-block/>``, ``<span>``) with standard markdown (code
fences, images, lists, plain text).  Rather than hand-rolling a line-by-line
parser that reimplements HTML tag matching, we use **BeautifulSoup** to parse
the HTML structure and then extract markdown content from the text nodes.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from .model import (
    CodeNode,
    Document,
    EmptyNode,
    ImageNode,
    IRNode,
    ListNode,
    PageRefNode,
    TableNode,
    TextNode,
    ToggleNode,
)

_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]*)\)\s*$")
_SPAN_RE = re.compile(r'<span color="[^"]*">(.*?)</span>')
_LIST_ITEM_RE = re.compile(r"^(-\s|\d+\.\s)")
_EMPTY_LIST_MARKER_RE = re.compile(r"^-\s*$")


def _clean_inline(text: str) -> str:
    """Strip Notion's inline color tags while keeping their text content."""
    return _SPAN_RE.sub(r"\1", text)


# ---------------------------------------------------------------------------
# Markdown API parser (BeautifulSoup-based)
# ---------------------------------------------------------------------------

def parse_markdown(markdown: str) -> Document:
    """Parse a full enhanced-markdown page string into a Document."""
    soup = BeautifulSoup(markdown, "html.parser")
    nodes = _parse_children(soup)
    return Document(nodes=nodes)


def _parse_children(parent: Tag | BeautifulSoup) -> list[IRNode]:
    """Walk direct children of a BS4 element and convert to IR nodes."""
    nodes: list[IRNode] = []
    for child in parent.children:
        if isinstance(child, Tag):
            nodes.extend(_parse_tag(child))
        elif isinstance(child, NavigableString):
            nodes.extend(_parse_text_block(str(child)))
    return nodes


def _parse_tag(tag: Tag) -> list[IRNode]:
    """Convert one HTML tag into IR node(s)."""
    name = tag.name

    if name == "details":
        return [_parse_details(tag)]

    if name == "table":
        return [_parse_table(tag)]

    if name == "page":
        url = tag.get("url", "")
        title = _clean_inline(tag.get_text())
        return [PageRefNode(title=title, url=url)]

    if name == "empty-block":
        return [EmptyNode()]

    if name == "span":
        # Inline color span — keep text content, drop the tag.
        return [TextNode(text=tag.get_text())]

    if name == "br":
        return []

    # Unknown HTML tags: extract text content so nothing is silently dropped.
    text = tag.get_text().strip()
    return [TextNode(text=text)] if text else []


def _parse_details(tag: Tag) -> ToggleNode:
    """Convert a ``<details>`` tag into a ToggleNode."""
    summary = ""
    summary_tag = tag.find("summary", recursive=False)
    if summary_tag:
        summary = _clean_inline(summary_tag.get_text()).strip()

    children: list[IRNode] = []
    for child in tag.children:
        if isinstance(child, Tag):
            if child.name == "summary":
                continue  # already extracted
            children.extend(_parse_tag(child))
        elif isinstance(child, NavigableString):
            children.extend(_parse_text_block(str(child)))
    return ToggleNode(summary=summary, children=children)


def _parse_table(tag: Tag) -> TableNode:
    """Convert a ``<table>`` tag into a TableNode with markdown syntax."""
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = [_clean_inline(td.get_text().strip()) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    if not rows:
        return TableNode(markdown=tag.get_text())

    col_count = max(len(r) for r in rows)
    for row in rows:
        row.extend([""] * (col_count - len(row)))
    widths = [max(len(rows[r][c]) for r in range(len(rows))) for c in range(col_count)]
    widths = [max(w, 3) for w in widths]

    def fmt_row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    md_lines = [fmt_row(rows[0])]
    md_lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    for row in rows[1:]:
        md_lines.append(fmt_row(row))
    return TableNode(markdown="\n".join(md_lines))


def _parse_text_block(text: str) -> list[IRNode]:
    """Parse a block of raw text (between HTML tags) into IR nodes.

    This handles the markdown parts of enhanced markdown: code fences,
    images, lists, and plain paragraphs.  HTML nesting is already resolved
    by BeautifulSoup, so this function only sees flat text.
    """
    nodes: list[IRNode] = []
    # Strip common leading tab indentation (Notion uses tabs to indent
    # content inside <details> tags; BeautifulSoup preserves them).
    lines = text.split("\n")
    # Compute the minimum tab-indent across non-empty lines.
    min_tabs = float("inf")
    for ln in lines:
        if ln.strip():
            tabs = len(ln) - len(ln.lstrip("\t"))
            min_tabs = min(min_tabs, tabs)
    if min_tabs == float("inf"):
        min_tabs = 0
    lines = [ln[int(min_tabs):] for ln in lines]
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Empty list marker from Notion empty toggles — skip.
        if _EMPTY_LIST_MARKER_RE.match(line):
            i += 1
            continue

        # Fenced code block.
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1  # skip closing fence
            nodes.append(CodeNode(lang=lang, code="\n".join(code_lines)))
            continue

        # Image.
        image_match = _IMAGE_RE.match(line)
        if image_match:
            alt, url = image_match.group(1), image_match.group(2)
            nodes.append(ImageNode(alt=_clean_inline(alt), url=url))
            i += 1
            continue

        # List block: consecutive lines starting with `- ` or `N. `.
        if _LIST_ITEM_RE.match(line):
            list_lines: list[str] = []
            while i < n:
                ln = lines[i].strip()
                if not ln:
                    break
                # A list item or a continuation (indented) line.
                raw = lines[i]
                dedented = raw.replace("\t", "  ")
                stripped = dedented.strip()
                if not stripped:
                    break
                # Stop if we hit a non-list construct.
                if stripped.startswith("```") or _IMAGE_RE.match(stripped) or stripped.startswith("<"):
                    break
                if _EMPTY_LIST_MARKER_RE.match(stripped):
                    i += 1
                    continue
                is_list_start = _LIST_ITEM_RE.match(stripped)
                is_continuation = dedented.startswith("  ") and not is_list_start
                if not is_list_start and not is_continuation:
                    break
                list_lines.append(dedented.rstrip())
                i += 1
            if list_lines:
                nodes.append(ListNode(raw=_clean_inline("\n".join(list_lines))))
            continue

        # Plain text paragraph.
        nodes.append(TextNode(text=_clean_inline(line)))
        i += 1

    return nodes


# ---------------------------------------------------------------------------
# Block API fallback
# ---------------------------------------------------------------------------
# Used only when the Markdown API response is truncated.  The block API
# returns the same page as a recursive tree of typed block objects, which we
# convert directly into the IR.

_LIST_ITEM_TYPES = {"bulleted_list_item", "numbered_list_item"}


def _rich_text_plain(rich_text: list[dict]) -> str:
    return _clean_inline("".join(segment.get("plain_text", "") for segment in rich_text))


def parse_blocks(blocks: list[dict]) -> Document:
    """Parse a recursive block API response into a Document."""
    return Document(nodes=_parse_block_list(blocks))


def _parse_block_list(blocks: list[dict]) -> list[IRNode]:
    nodes: list[IRNode] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        block_type = block["type"]

        if block_type in _LIST_ITEM_TYPES:
            group_lines: list[str] = []
            while i < n and blocks[i]["type"] in _LIST_ITEM_TYPES:
                group_lines.append(_render_list_item(blocks[i]))
                i += 1
            nodes.append(ListNode(raw="\n".join(group_lines)))
            continue

        nodes.append(_parse_single_block(block))
        i += 1

    return nodes


def _render_list_item(block: dict, indent: int = 0) -> str:
    block_type = block["type"]
    marker = "-" if block_type == "bulleted_list_item" else "1."
    text = _rich_text_plain(block[block_type].get("rich_text", []))
    prefix = "  " * indent
    line = f"{prefix}{marker} {text}"
    children = block.get("children") or []
    nested_lines = [
        _render_list_item(child, indent + 1)
        for child in children
        if child["type"] in _LIST_ITEM_TYPES
    ]
    return "\n".join([line, *nested_lines])


def _parse_single_block(block: dict) -> IRNode:
    block_type = block["type"]
    children = block.get("children") or []

    if block_type == "toggle":
        summary = _rich_text_plain(block["toggle"].get("rich_text", []))
        return ToggleNode(summary=summary, children=_parse_block_list(children))

    if block_type == "paragraph":
        text = _rich_text_plain(block["paragraph"].get("rich_text", []))
        return TextNode(text=text) if text else EmptyNode()

    if block_type == "code":
        code_data = block["code"]
        return CodeNode(
            lang=code_data.get("language", ""),
            code=_rich_text_plain(code_data.get("rich_text", [])),
        )

    if block_type == "image":
        image_data = block["image"]
        url = image_data.get(image_data["type"], {}).get("url", "")
        alt = _rich_text_plain(image_data.get("caption", []))
        return ImageNode(alt=alt, url=url)

    if block_type == "child_page":
        title = block["child_page"].get("title", "")
        return PageRefNode(title=title, url=block["id"])

    rich_text = block.get(block_type, {}).get("rich_text", []) if isinstance(block.get(block_type), dict) else []
    text = _rich_text_plain(rich_text)
    return TextNode(text=f"[unsupported block: {block_type}] {text}".strip())
