from notion2md.model import CodeNode, ListNode, TextNode, ToggleNode
from notion2md.strategy import (
    ContainerAction,
    ToggleKind,
    classify,
    container_sibling_count,
    decide_container,
    resolve_simple_text,
)


def test_classify_empty_toggle_with_no_summary_is_empty():
    assert classify(ToggleNode(summary="", children=[])) is ToggleKind.EMPTY


def test_classify_empty_toggle_with_summary_is_simple():
    assert classify(ToggleNode(summary="hello", children=[])) is ToggleKind.SIMPLE


def test_classify_single_text_child_is_simple():
    toggle = ToggleNode(summary="label", children=[TextNode(text="value")])
    assert classify(toggle) is ToggleKind.SIMPLE


def test_classify_leaf_only_children_is_content():
    toggle = ToggleNode(summary="code", children=[CodeNode(lang="rust", code="fn f() {}")])
    assert classify(toggle) is ToggleKind.CONTENT


def test_classify_with_nested_toggle_is_container():
    toggle = ToggleNode(summary="parent", children=[ToggleNode(summary="child", children=[TextNode("x")])])
    assert classify(toggle) is ToggleKind.CONTAINER


def test_blank_separator_toggle_does_not_force_container():
    # An empty `<details></details>` with no summary is just a blank-line
    # placeholder and must not turn a leaf-content toggle into a CONTAINER.
    toggle = ToggleNode(
        summary="caption",
        children=[ToggleNode(summary="", children=[]), ListNode(raw="- item")],
    )
    assert classify(toggle) is ToggleKind.CONTENT


def test_resolve_simple_text_merges_summary_and_child():
    toggle = ToggleNode(summary="Label:", children=[TextNode(text="value")])
    assert resolve_simple_text(toggle) == "Label: value"


def test_resolve_simple_text_empty_toggle_uses_summary_only():
    toggle = ToggleNode(summary="just this", children=[])
    assert resolve_simple_text(toggle) == "just this"


def test_decide_container_short_summary_top_level_is_heading():
    # heading_level 2 -> depth_tier 0 ("top-level")
    decision = decide_container("Intro", heading_level=2, sibling_count=1)
    assert decision.action is ContainerAction.HEADING
    assert decision.heading_level == 2


def test_decide_container_long_summary_is_bold_paragraph():
    long_summary = "x" * 41
    decision = decide_container(long_summary, heading_level=2, sibling_count=1)
    assert decision.action is ContainerAction.BOLD_PARAGRAPH


def test_decide_container_mid_depth_many_siblings_becomes_list():
    # heading_level 4 -> depth_tier 2 ("mid-level")
    decision = decide_container("Short", heading_level=4, sibling_count=8)
    assert decision.action is ContainerAction.LIST_ITEM


def test_decide_container_mid_depth_few_siblings_stays_heading():
    decision = decide_container("Short", heading_level=4, sibling_count=3)
    assert decision.action is ContainerAction.HEADING


def test_decide_container_deep_short_summary_becomes_list_item():
    # heading_level 6 -> depth_tier 4 ("deep")
    decision = decide_container("Short", heading_level=6, sibling_count=1)
    assert decision.action is ContainerAction.LIST_ITEM


def test_decide_container_deep_long_summary_becomes_bold_paragraph():
    decision = decide_container("x" * 41, heading_level=6, sibling_count=1)
    assert decision.action is ContainerAction.BOLD_PARAGRAPH


def test_container_sibling_count_ignores_non_container_toggles():
    nodes = [
        ToggleNode(summary="simple", children=[]),
        ToggleNode(summary="container", children=[ToggleNode(summary="c", children=[TextNode("x")])]),
        TextNode(text="plain"),
    ]
    assert container_sibling_count(nodes) == 1
