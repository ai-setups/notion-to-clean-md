"""Decide how each Notion toggle subtree should be rendered as plain Markdown.

Standard Markdown has no equivalent of a collapsible toggle, so every toggle
must be re-expressed as a heading, a bold paragraph, a list item, or inline
text. The right choice depends only on the toggle's own summary length and
its *local* children -- never on the toggle's absolute nesting depth in the
page -- which is why every function here takes an explicit `heading_level`
/ `sibling_count` threaded per recursive branch rather than a single global
counter. Two sibling toggle subtrees never influence each other's decision.

Three toggle categories:

- SIMPLE:    no children (an empty toggle) or a single plain-text child.
             Collapses to one line of text; several SIMPLE siblings in a row
             are grouped into one bullet list.
- CONTENT:   children contain no nested toggles (e.g. a code block, an
             image, a list, or a couple of paragraphs). The summary becomes
             a lead-in paragraph followed directly by its content -- no
             heading is introduced, this is not a structural section.
- CONTAINER: children include at least one nested toggle, i.e. this toggle
             is itself a section of the outline. Rendered as a heading, a
             bold paragraph, or (when there are many such siblings) a list
             item, based on `heading_level`.

`heading_level` doubles as the "how deep is this subtree" signal: it starts
at 2 for the page's top-level toggles and increases by one every time a
CONTAINER actually consumes a heading. A CONTAINER rendered as a bold
paragraph does not consume a level (so a long summary doesn't eat into the
heading budget), while one flattened into a list item forces every
descendant into the "deep" tier (see `FLATTENED_HEADING_LEVEL`), matching
"no more heading levels once flattened".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .model import IRNode, TextNode, ToggleNode

SHORT_SUMMARY_LIMIT = 40
MANY_SIBLINGS_THRESHOLD = 8
MAX_HEADING_LEVEL = 6
# Depth tiers are `heading_level - TOP_HEADING_LEVEL`: 0-1 = top, 2-3 = mid, 4+ = deep.
TOP_HEADING_LEVEL = 2
# Sentinel heading_level passed to descendants of a LIST_ITEM, permanently
# placing them in the "deep" tier so no heading resurfaces inside a list.
FLATTENED_HEADING_LEVEL = 100


class ToggleKind(Enum):
    EMPTY = auto()  # no children, no summary -> drop entirely
    SIMPLE = auto()  # no children (summary only) or a single plain-text child
    CONTENT = auto()  # leaf-only children (code/image/list/text), no nested toggles
    CONTAINER = auto()  # has at least one nested toggle child


def _is_blank_separator(node: IRNode) -> bool:
    """An empty nested toggle with no summary is just Notion's encoding of a
    blank line, not real nested structure -- ignore it when classifying.
    """
    return isinstance(node, ToggleNode) and not node.summary and not node.children


def classify(toggle: ToggleNode) -> ToggleKind:
    children = [child for child in toggle.children if not _is_blank_separator(child)]
    if not children:
        return ToggleKind.EMPTY if not toggle.summary else ToggleKind.SIMPLE
    if len(children) == 1 and isinstance(children[0], TextNode):
        return ToggleKind.SIMPLE
    if any(isinstance(child, ToggleNode) for child in children):
        return ToggleKind.CONTAINER
    return ToggleKind.CONTENT


def resolve_simple_text(toggle: ToggleNode) -> str:
    """Collapse a SIMPLE toggle into a single line of text."""
    children = [child for child in toggle.children if not _is_blank_separator(child)]
    if not children:
        return toggle.summary
    child_text = children[0].text  # TextNode, see classify()
    if toggle.summary:
        return f"{toggle.summary} {child_text}".strip()
    return child_text


class ContainerAction(Enum):
    HEADING = auto()
    BOLD_PARAGRAPH = auto()
    LIST_ITEM = auto()


@dataclass
class ContainerDecision:
    action: ContainerAction
    heading_level: int | None = None


def decide_container(summary: str, heading_level: int, sibling_count: int) -> ContainerDecision:
    """Decide how to render a CONTAINER toggle.

    `sibling_count` is the number of CONTAINER toggles among this node's
    immediate siblings (see `container_sibling_count`).
    """
    depth_tier = heading_level - TOP_HEADING_LEVEL
    is_short = len(summary) <= SHORT_SUMMARY_LIMIT
    can_heading = heading_level <= MAX_HEADING_LEVEL

    if depth_tier >= 4:
        # Too deep for another heading level; keep the outline readable by
        # flattening into list items (or bold text for long summaries).
        return ContainerDecision(ContainerAction.LIST_ITEM if is_short else ContainerAction.BOLD_PARAGRAPH)

    if depth_tier in (2, 3) and sibling_count >= MANY_SIBLINGS_THRESHOLD:
        # Many sibling sections at once read better as a list than as a
        # wall of same-level headings.
        return ContainerDecision(ContainerAction.LIST_ITEM)

    if is_short and can_heading:
        return ContainerDecision(ContainerAction.HEADING, heading_level=heading_level)

    return ContainerDecision(ContainerAction.BOLD_PARAGRAPH)


def container_sibling_count(nodes: list[IRNode]) -> int:
    return sum(1 for node in nodes if isinstance(node, ToggleNode) and classify(node) is ToggleKind.CONTAINER)
