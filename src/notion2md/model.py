"""Intermediate representation (IR) for a parsed Notion page.

The parser turns Notion's enhanced markdown (or the recursive block API
response) into a tree of these node types. The strategy/renderer layer then
turns the tree into standard Markdown without any knowledge of the original
Notion-specific syntax.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextNode:
    """A single paragraph/line of plain text (already inline-cleaned)."""

    text: str


@dataclass
class ListNode:
    """A raw, already-dedented block of standard markdown list syntax.

    Notion's enhanced markdown already emits valid `- ...` / `1. ...` list
    syntax, so there is no need to model individual list items in the IR.
    """

    raw: str


@dataclass
class CodeNode:
    """A fenced code block."""

    lang: str
    code: str


@dataclass
class ImageNode:
    """An image reference. ``url`` is rewritten in-place by the assets step."""

    alt: str
    url: str


@dataclass
class PageRefNode:
    """A reference to a Notion child page (``<page url="...">title</page>``)."""

    title: str
    url: str


@dataclass
class TableNode:
    """A markdown table rendered from Notion's HTML ``<table>`` block."""

    markdown: str


@dataclass
class EmptyNode:
    """A placeholder for an explicitly empty block (``<empty-block/>``)."""


@dataclass
class ToggleNode:
    """A collapsible Notion toggle block with a summary and child nodes."""

    summary: str
    children: list[IRNode] = field(default_factory=list)


IRNode = TextNode | ListNode | CodeNode | ImageNode | PageRefNode | TableNode | EmptyNode | ToggleNode


@dataclass
class Document:
    """The full IR tree for one Notion page."""

    nodes: list[IRNode] = field(default_factory=list)
