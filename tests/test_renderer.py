from notion2md.model import (
    CodeNode,
    Document,
    EmptyNode,
    ImageNode,
    PageRefNode,
    TextNode,
    ToggleNode,
)
from notion2md.renderer import Renderer


def render(nodes):
    return Renderer().render(Document(nodes=nodes))


def test_no_html_tags_survive_rendering():
    doc = Document(
        nodes=[
            ToggleNode(
                summary="Section",
                children=[ToggleNode(summary="Sub", children=[TextNode("hello")])],
            )
        ]
    )
    out = Renderer().render(doc)
    for tag in ("<details>", "</details>", "<summary>", "</summary>", "<span"):
        assert tag not in out


def test_short_top_level_toggle_becomes_heading():
    sub = ToggleNode(summary="Sub", children=[ToggleNode(summary="inner", children=[TextNode("x")])])
    out = render([ToggleNode(summary="Intro", children=[sub])])
    assert out.startswith("## Intro")
    assert "### Sub" in out


def test_long_summary_toggle_becomes_bold_paragraph_not_heading():
    long_summary = "This is a very long explanatory sentence that exceeds forty characters easily"
    sub = ToggleNode(summary="s", children=[ToggleNode(summary="inner", children=[TextNode("x")])])
    out = render([ToggleNode(summary=long_summary, children=[sub])])
    assert "#" not in out.split("\n")[0]
    assert f"**{long_summary}**" in out


def test_code_toggle_renders_context_paragraph_then_fenced_code():
    out = render([ToggleNode(summary="code", children=[CodeNode(lang="python", code="print(1)")])])
    assert out == "code\n\n```python\nprint(1)\n```\n"


def test_image_toggle_renders_caption_then_image():
    out = render([ToggleNode(summary="A diagram", children=[ImageNode(alt="", url="http://x/img.png")])])
    assert out == "A diagram\n\n![](http://x/img.png)\n"


def test_empty_toggle_without_summary_is_dropped():
    out = render([ToggleNode(summary="", children=[]), TextNode("kept")])
    assert out == "kept\n"


def test_consecutive_simple_toggles_become_a_list():
    out = render(
        [
            ToggleNode(summary="one", children=[]),
            ToggleNode(summary="two", children=[]),
            ToggleNode(summary="three", children=[]),
        ]
    )
    assert out == "- one\n- two\n- three\n"


def test_single_simple_toggle_is_plain_paragraph_not_list():
    out = render([ToggleNode(summary="alone", children=[])])
    assert out == "alone\n"


def test_image_url_is_rewritten_via_resolver():
    doc = Document(nodes=[ImageNode(alt="cap", url="http://original/x.png")])
    out = Renderer(image_resolver=lambda url: "assets/local.png").render(doc)
    assert out == "![cap](assets/local.png)\n"


def test_page_ref_is_rewritten_via_resolver():
    # When all nodes are page refs, no extra heading is added.
    doc = Document(nodes=[PageRefNode(title="Child", url="notion://raw-id")])
    out = Renderer(page_ref_resolver=lambda url: "child.md").render(doc)
    assert out == "[Child](child.md)\n"


def test_page_ref_gets_heading_when_mixed_with_other_content():
    # When page refs appear alongside other content, a "Sub Pages" heading
    # prevents them from being visually absorbed into the preceding section.
    doc = Document(nodes=[TextNode("some text"), PageRefNode(title="Child", url="x")])
    out = Renderer(page_ref_resolver=lambda url: "child.md").render(doc)
    assert out == "some text\n\n## Sub Pages\n\n[Child](child.md)\n"


def test_empty_node_produces_no_output():
    out = render([TextNode("a"), EmptyNode(), TextNode("b")])
    assert out == "a\n\nb\n"


def test_many_siblings_with_rich_content_at_mid_depth_become_nested_list():
    # 8 CONTAINER siblings at local_depth 2 must collapse into list items
    # instead of eight same-level headings.
    grandchild = ToggleNode(summary="leaf", children=[TextNode("v")])
    mid_children = [
        ToggleNode(summary=f"child-{i}", children=[ToggleNode(summary="inner", children=[grandchild])])
        for i in range(8)
    ]
    doc = Document(
        nodes=[
            ToggleNode(  # local_depth 0 -> heading
                summary="Top",
                children=[
                    ToggleNode(  # local_depth 0 within Top -> heading, resets to local_depth 0 for its children
                        summary="Mid",
                        children=mid_children,  # these are local_depth... see below
                    )
                ],
            )
        ]
    )
    out = Renderer().render(doc)
    assert "- **child-0**" in out
    assert out.count("- **child-") == 8
