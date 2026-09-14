"""Render an IR Document into standard Markdown (no HTML, no `<details>`).

Rendering strategies
====================

Toggle conversion
-----------------
See ``strategy.py`` module docstring for the full decision logic (SIMPLE,
CONTENT, CONTAINER categories and the heading/bold/list-item tiering).

Sibling heading consistency
---------------------------
All toggle siblings at the same level MUST use the same rendering style.
If any sibling is classified as CONTAINER (rendered as a heading), then
every sibling toggle — including SIMPLE and CONTENT ones — is also
rendered as a heading at the same level.  It is never acceptable for one
sibling to be a heading while another is plain text; either the whole
level uses headings or none of them do.  This mirrors how a human would
write an outline: section titles at the same depth always share the same
formatting.

Child-page references
---------------------
Markdown headings have no closing tag, so a ``[child](child.md)`` link
placed after ``## Some Section`` is visually absorbed into that section
even when it is structurally a sibling.  Two sub-strategies handle this:

- **All page refs**: when every meaningful node in a node list is a
  ``PageRefNode`` (ignoring ``EmptyNode``), the parent heading already
  groups them, so the links are emitted directly without an extra heading.
  Typical case: a Notion page whose sole purpose is to list sub-pages.
- **Mixed content**: when page refs appear alongside toggles, text, or
  other content, they are collected and flushed under a dedicated heading
  (e.g. ``## Sub Pages``) at the current heading level.  This visually
  separates them from the preceding section so the reader can tell they
  are independent pages rather than part of the last section's content.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from . import strategy
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
from .strategy import ContainerAction, ToggleKind

_LIST_INDENT = "  "


def _encode_path(path: str) -> str:
    """Percent-encode spaces in a local file path for Markdown links.

    Only spaces are encoded (``%20``).  Slashes, unicode characters, and
    other path components are left as-is so the link stays readable.
    URLs (starting with ``http``/``https``) are returned unchanged.
    """
    if path.startswith(("http://", "https://")):
        return path
    return path.replace(" ", "%20")


def _indent(block: str, prefix: str) -> str:
    return "\n".join(prefix + line if line else line for line in block.split("\n"))


class Renderer:
    """Converts a `Document` to a Markdown string.

    `image_resolver` / `page_ref_resolver` let the caller (the assets step
    and the CLI's child-page export) rewrite an image URL or a Notion page
    reference into a local relative path. Without them the original Notion
    URL/id is kept as a plain external link, which is a documented fallback
    rather than a silent drop of information.
    """

    def __init__(
        self,
        image_resolver: Callable[[str], str] | None = None,
        page_ref_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self._resolve_image = image_resolver or (lambda url: url)
        self._resolve_page_ref = page_ref_resolver or (lambda url: url)

    def render(self, document: Document) -> str:
        blocks = self._render_nodes(document.nodes, heading_level=strategy.TOP_HEADING_LEVEL)
        return "\n\n".join(blocks) + "\n"

    # -- node list rendering --------------------------------------------

    def _render_nodes(self, nodes: list[IRNode], heading_level: int) -> list[str]:
        blocks: list[str] = []
        sibling_count = strategy.container_sibling_count(nodes)
        pending_simple: list[str] = []
        pending_page_refs: list[str] = []
        # When all meaningful content in this node list is page refs, the
        # parent heading already groups them -- no extra "Sub Pages" heading.
        all_page_refs = all(
            isinstance(n, (PageRefNode, EmptyNode)) for n in nodes
        )

        def flush_simple() -> None:
            if not pending_simple:
                return
            if len(pending_simple) >= 2:
                blocks.append("\n".join(f"- {text}" for text in pending_simple))
            else:
                blocks.append(pending_simple[0])
            pending_simple.clear()

        def flush_page_refs() -> None:
            """Emit collected child-page links under a heading so they don't
            get visually absorbed into the preceding section."""
            if not pending_page_refs:
                return
            if not all_page_refs:
                level = min(heading_level, strategy.MAX_HEADING_LEVEL)
                blocks.append("#" * level + " Sub Pages")
            blocks.extend(pending_page_refs)
            pending_page_refs.clear()

        # When any sibling is a CONTAINER (rendered as heading), ALL toggle
        # siblings must use the same heading level for consistency.  A level
        # where some siblings are headings and others are plain text looks
        # broken — the plain-text ones appear to have "lost" their heading.
        has_container_sibling = sibling_count > 0

        for node in nodes:
            if isinstance(node, ToggleNode):
                kind = strategy.classify(node)
                if kind is ToggleKind.EMPTY:
                    flush_simple()
                    continue

                # If no sibling is a CONTAINER, SIMPLE toggles can stay
                # lightweight (grouped into a bullet list).
                if kind is ToggleKind.SIMPLE and not has_container_sibling:
                    text = strategy.resolve_simple_text(node)
                    if text:
                        pending_simple.append(text)
                    continue

                flush_simple()

                # When container siblings exist, promote SIMPLE/CONTENT
                # toggles to the same heading level so all siblings are
                # consistent.
                if has_container_sibling:
                    blocks.extend(self._render_as_heading(node, heading_level, sibling_count))
                elif kind is ToggleKind.CONTENT:
                    blocks.extend(self._render_content_toggle(node, heading_level))
                else:
                    blocks.extend(self._render_container_toggle(node, heading_level, sibling_count))
                continue

            flush_simple()

            # Collect page refs so they render under their own heading.
            if isinstance(node, PageRefNode):
                pending_page_refs.append(self._render_leaf(node))
                continue

            # A non-page-ref leaf breaks the page-ref group.
            flush_page_refs()
            block = self._render_leaf(node)
            if block:
                blocks.append(block)

        flush_simple()
        flush_page_refs()
        return blocks

    # -- toggle rendering --------------------------------------------

    def _render_as_heading(self, toggle: ToggleNode, heading_level: int, sibling_count: int) -> list[str]:
        """Render any toggle (SIMPLE, CONTENT, or CONTAINER) as a heading.

        Used when container siblings exist to keep all siblings at the same
        heading level.  The toggle's children are rendered below the heading.
        """
        kind = strategy.classify(toggle)
        if kind is ToggleKind.CONTAINER:
            return self._render_container_toggle(toggle, heading_level, sibling_count)

        # SIMPLE or CONTENT: emit a heading for the summary, then children.
        decision = strategy.decide_container(toggle.summary or "", heading_level, sibling_count)
        if decision.action is ContainerAction.HEADING and toggle.summary:
            level = decision.heading_level
            head = "#" * level + " " + toggle.summary
            child_blocks = self._render_nodes(toggle.children, level + 1)
            return [head, *child_blocks]
        # Fallback: bold paragraph for long summaries or deep levels.
        if toggle.summary:
            head = f"**{toggle.summary}**"
            child_blocks = self._render_nodes(toggle.children, heading_level)
            return [head, *child_blocks]
        return self._render_nodes(toggle.children, heading_level)

    def _render_content_toggle(self, toggle: ToggleNode, heading_level: int) -> list[str]:
        blocks: list[str] = []
        if toggle.summary:
            blocks.append(toggle.summary)
        blocks.extend(self._render_nodes(toggle.children, heading_level))
        return blocks

    def _render_container_toggle(self, toggle: ToggleNode, heading_level: int, sibling_count: int) -> list[str]:
        decision = strategy.decide_container(toggle.summary, heading_level, sibling_count)
        has_summary = bool(toggle.summary)

        if decision.action is ContainerAction.HEADING:
            child_blocks = self._render_nodes(toggle.children, decision.heading_level + 1)
            if not has_summary:
                return child_blocks
            head = "#" * decision.heading_level + " " + toggle.summary
            return [head, *child_blocks]

        if decision.action is ContainerAction.BOLD_PARAGRAPH:
            # A long summary doesn't consume a heading level, so a deep
            # chain of long-summary containers can still reach a heading
            # once a descendant's summary turns out to be short.
            child_blocks = self._render_nodes(toggle.children, heading_level)
            if not has_summary:
                return child_blocks
            head = f"**{toggle.summary}**"
            return [head, *child_blocks]

        # LIST_ITEM: flatten permanently (no more headings below this point)
        # and nest the children as an indented sub-list under this bullet.
        child_blocks = self._render_nodes(toggle.children, strategy.FLATTENED_HEADING_LEVEL)
        if not has_summary and not child_blocks:
            return []
        item = f"- **{toggle.summary}**" if has_summary else "-"
        nested = [_indent(block, _LIST_INDENT) for block in child_blocks]
        return ["\n\n".join([item, *nested])]

    # -- leaf rendering --------------------------------------------

    def _render_leaf(self, node: IRNode) -> str:
        if isinstance(node, TextNode):
            return node.text
        if isinstance(node, ListNode):
            return node.raw.strip()
        if isinstance(node, CodeNode):
            return f"```{node.lang}\n{node.code}\n```"
        if isinstance(node, ImageNode):
            return f"![{node.alt}]({_encode_path(self._resolve_image(node.url))})"
        if isinstance(node, TableNode):
            return node.markdown
        if isinstance(node, PageRefNode):
            return f"[{node.title}]({_encode_path(self._resolve_page_ref(node.url))})"
        if isinstance(node, EmptyNode):
            return ""
        raise TypeError(f"Unsupported IR node: {node!r}")
