from notion2md.model import (
    CodeNode,
    EmptyNode,
    ImageNode,
    ListNode,
    PageRefNode,
    TextNode,
    ToggleNode,
)
from notion2md.parser import parse_blocks, parse_markdown


def test_parses_nested_toggle_with_summary():
    md = "<details>\n<summary>Parent</summary>\n\t<details>\n\t<summary>Child</summary>\n\t</details>\n</details>"
    doc = parse_markdown(md)
    assert len(doc.nodes) == 1
    parent = doc.nodes[0]
    assert isinstance(parent, ToggleNode)
    assert parent.summary == "Parent"
    assert len(parent.children) == 1
    child = parent.children[0]
    assert isinstance(child, ToggleNode)
    assert child.summary == "Child"
    assert child.children == []


def test_parses_empty_toggle_without_summary():
    md = "<details>\n</details>"
    doc = parse_markdown(md)
    assert isinstance(doc.nodes[0], ToggleNode)
    assert doc.nodes[0].summary == ""
    assert doc.nodes[0].children == []


def test_parses_fenced_code_block_inside_toggle():
    md = (
        "<details>\n<summary>code</summary>\n"
        "\t```rust\nfn main() {\n    let x = 1;\n}\n\t```\n"
        "</details>"
    )
    doc = parse_markdown(md)
    toggle = doc.nodes[0]
    assert len(toggle.children) == 1
    code = toggle.children[0]
    assert isinstance(code, CodeNode)
    assert code.lang == "rust"
    assert code.code == "fn main() {\n    let x = 1;\n}"


def test_parses_list_with_wrapped_continuation_line():
    md = "<details>\n<summary>Types</summary>\n\t- one\n\t- two, but wraps\n\t\tcontinuation\n</details>"
    doc = parse_markdown(md)
    lst = doc.nodes[0].children[0]
    assert isinstance(lst, ListNode)
    assert lst.raw == "- one\n- two, but wraps\n  continuation"


def test_parses_image_and_empty_block_and_page_ref():
    md = '![alt text](http://example.com/x.png)\n<empty-block/>\n<page url="http://example.com/p">Child Page</page>'
    doc = parse_markdown(md)
    assert isinstance(doc.nodes[0], ImageNode)
    assert doc.nodes[0].alt == "alt text"
    assert doc.nodes[0].url == "http://example.com/x.png"
    assert isinstance(doc.nodes[1], EmptyNode)
    assert isinstance(doc.nodes[2], PageRefNode)
    assert doc.nodes[2].title == "Child Page"
    assert doc.nodes[2].url == "http://example.com/p"


def test_strips_color_span_tags():
    md = '<details>\n<summary>Note: <span color="red">read-only</span></summary>\n</details>'
    doc = parse_markdown(md)
    assert doc.nodes[0].summary == "Note: read-only"


def test_parse_blocks_from_block_api_tree():
    blocks = [
        {
            "type": "toggle",
            "toggle": {"rich_text": [{"plain_text": "Section"}]},
            "children": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Hello"}]},
                    "children": [],
                },
                {
                    "type": "code",
                    "code": {"language": "python", "rich_text": [{"plain_text": "print(1)"}]},
                    "children": [],
                },
            ],
        },
        {
            "type": "child_page",
            "id": "fff2ea6e-fc01-80ca-baa0-f6b903dbb32c",
            "child_page": {"title": "Child"},
            "children": [],
        },
    ]
    doc = parse_blocks(blocks)
    toggle = doc.nodes[0]
    assert isinstance(toggle, ToggleNode)
    assert toggle.summary == "Section"
    assert isinstance(toggle.children[0], TextNode)
    assert toggle.children[0].text == "Hello"
    assert isinstance(toggle.children[1], CodeNode)
    assert toggle.children[1].lang == "python"

    page_ref = doc.nodes[1]
    assert isinstance(page_ref, PageRefNode)
    assert page_ref.title == "Child"
    assert page_ref.url == "fff2ea6e-fc01-80ca-baa0-f6b903dbb32c"
