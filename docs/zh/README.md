# notion-to-clean-md

将 Notion 页面导出为**可读的标准 Markdown** —— 没有 `<details>` HTML，没有 Obsidian 专有语法，不绑定任何平台。

## 问题

所有现有的 Notion 导出工具都把 toggle 输出为嵌套的 `<details><summary>` HTML。一个有 5–7 层 toggle 嵌套的页面会变成一堵不可读的 HTML 标签墙。

**Notion Markdown API 的输出**（所有工具给你的结果）：
```html
<details>
<summary>所有权（Ownership）</summary>
  <details>
  <summary>所有权的三个规则</summary>
    1. 每个值都有一个所有者。
    2. 值在任一时刻有且只有一个所有者。
    3. 当所有者离开作用域，这个值将被丢弃。
  </details>
  <details>
  <summary>变量赋值：let s2 = s1;</summary>
    <details>
    <summary>code</summary>
      ```rust
      fn main() { let s1 = String::from("hello"); let s2 = s1; }
      ```
    </details>
  </details>
</details>
```

**notion-to-clean-md 的输出**：
```markdown
## 所有权（Ownership）

### 所有权的三个规则

1. 每个值都有一个所有者。
2. 值在任一时刻有且只有一个所有者。
3. 当所有者离开作用域，这个值将被丢弃。

### 变量赋值：let s2 = s1;

code

​```rust
fn main() { let s1 = String::from("hello"); let s2 = s1; }
​```
```

## 特性

- **智能 toggle 转换** —— 根据深度、兄弟数量和内容类型自动选择标题、列表或加粗段落
- **递归导出** —— 子页面自动导出，按目录结构组织
- **图片下载** —— Notion 的临时签名 URL 保存到本地；外部图片 URL 保持原样
- **代码块和表格保留** —— 语言标识和表格结构完整保留

## 快速开始

```bash
git clone https://github.com/ai-setups/notion-to-clean-md.git
cd notion-to-clean-md
uv sync

export NOTION_KEY=ntn_...  # 从 notion.so/my-integrations 获取
uv run notion2md <页面ID或URL> -o output/MyNotes
```

输出结构：
```
output/MyNotes/
  MyNotes.md        # 主页面
  SubTopic/         # 子页面作为子目录
    SubTopic.md
    assets/         # 下载的图片
```

跳过图片下载以加快迭代：`NOTION2MD_SKIP_DOWNLOAD=1`

## 许可证

Apache-2.0
