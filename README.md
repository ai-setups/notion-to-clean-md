# notion-to-clean-md

[Chinese Documentation](docs/zh/README.md)

Export Notion pages to **readable, standard Markdown** — no `<details>` HTML, no Obsidian-specific syntax, no platform lock-in.

## The Problem

Every existing Notion export tool outputs toggles as nested `<details><summary>` HTML. A page with 5–7 layers of toggle nesting becomes an unreadable wall of HTML tags.

**Notion Markdown API output** (what every tool gives you):
```html
<details>
<summary>Ownership</summary>
  <details>
  <summary>The three rules</summary>
    1. Each value has an owner.
    2. One owner at a time.
    3. Owner leaves scope → value dropped.
  </details>
  <details>
  <summary>Variable assignment: let s2 = s1;</summary>
    <details>
    <summary>code</summary>
      ```rust
      fn main() { let s1 = String::from("hello"); let s2 = s1; }
      ```
    </details>
  </details>
</details>
```

**notion-to-clean-md output**:
```markdown
## Ownership

### The three rules

1. Each value has an owner.
2. One owner at a time.
3. Owner leaves scope → value dropped.

### Variable assignment: let s2 = s1;

code

​```rust
fn main() { let s1 = String::from("hello"); let s2 = s1; }
​```
```

## Features

- **Smart toggle conversion** — Headings, lists, or bold paragraphs based on depth, sibling count, and content type
- **Recursive export** — Child pages automatically exported with proper directory structure
- **Image download** — Notion's expiring S3 URLs saved locally; external URLs kept as-is
- **Code & table preservation** — Language identifiers and table structure intact

## Quick Start

```bash
git clone https://github.com/ai-setups/notion-to-clean-md.git
cd notion-to-clean-md
uv sync

export NOTION_KEY=ntn_...  # from notion.so/my-integrations
uv run notion2md <page-id-or-url> -o output/MyNotes
```

Output:
```
output/MyNotes/
  MyNotes.md        # Main page
  SubTopic/         # Child pages as subdirectories
    SubTopic.md
    assets/         # Downloaded images
```

Skip image downloads for fast iteration: `NOTION2MD_SKIP_DOWNLOAD=1`

## License

Apache-2.0
