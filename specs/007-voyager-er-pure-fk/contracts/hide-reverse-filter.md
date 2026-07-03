# 契约：`_add_relationship_link` 早退过滤逻辑

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md) · **Payload 契约**：[er-diagram-payload-extension.md](./er-diagram-payload-extension.md)

**位置**：`src/nexusx/voyager/er_diagram_dot.py::ErDiagramDotBuilder._add_relationship_link`（第 199-237 行）

---

## 现状（修改前）

```python
def _add_relationship_link(
    self,
    entity_kls: type,
    rel_info: RelationshipInfo,
) -> None:
    """Add a Link for a single relationship."""
    if not _is_model_like_target(rel_info.target_entity):
        return

    source_name = full_class_name(entity_kls)
    target_name = full_class_name(rel_info.target_entity)

    # Ensure target node exists
    self._add_to_node_set(rel_info.target_entity)

    # Build label with cardinality
    cardinality = f'1 {ARROW} N' if rel_info.is_list else f'1 {ARROW} 1'
    label = f'{rel_info.name}\n{cardinality}'

    # Build source anchor from relationship name field
    source_anchor = f'{source_name}::f{rel_info.name}'

    # Check for duplicates
    biz = rel_info.name
    pair = (source_anchor, self._generate_node_head(target_name), biz)
    if pair in self.link_set:
        return
    self.link_set.add(pair)

    self.links.append(Link(
        source=source_anchor,
        source_origin=source_name,
        target=self._generate_node_head(target_name),
        target_origin=target_name,
        type='schema',
        label=label,
        style='solid',
        loader_fullname=None,
    ))
```

---

## 修改后

在 `_is_model_like_target` 早退之后、`source_name = full_class_name(...)` 之前，**新增一行 direction 早退判定**：

```python
def _add_relationship_link(
    self,
    entity_kls: type,
    rel_info: RelationshipInfo,
) -> None:
    """Add a Link for a single relationship."""
    if not _is_model_like_target(rel_info.target_entity):
        return

    # Spec 007: Hide Reverse Relationships mode — skip ONETOMANY reverse mirrors.
    # MANYTOONE (FK holder side) and MANYTOMANY (through table) are preserved.
    if self.hide_reverse_relationships and rel_info.direction == 'ONETOMANY':
        return

    source_name = full_class_name(entity_kls)
    # ... 后续逻辑完全不变
```

---

## 判定逻辑

| `hide_reverse_relationships` | `rel_info.direction` | 行为 |
|------------------------------|----------------------|------|
| `False`（默认） | 任意 | 与现状一致——所有方向 relationship 都生成 Link |
| `True` | `'MANYTOONE'` | **保留**——生成 Link（持有 FK 一侧） |
| `True` | `'ONETOMANY'` | **隐藏**——早退、不生成 Link（被引用实体的反向镜像） |
| `True` | `'MANYTOMANY'` | **保留**——生成 Link（M2M 不在 back_populates 反向冗余范围） |
| `True` | 其他/异常值 | **保留**——不匹配 `'ONETOMANY'`，按"MANYTOONE/MANYTOMANY 同等保留"处理 |

---

## 不变量（Pure FK 模式开启时仍成立）

1. **`self.rel_name_set` 记录全部 relationship**：`rel_name_set` 在 `analysis()` 第 121-125 行独立构建（与 `_add_relationship_link` 解耦），不受 Pure FK 早退影响——`_get_entity_fields` 仍能渲染完整字段表（含 ONETOMANY 方向 relationship 字段），Fields tab 内容不变（spec FR-007）。
2. **`self.node_set` 包含全部实体节点**：`_add_to_node_set` 在早退之前未被调用，但实体节点本身在 `analysis()` 第 127-130 行的独立循环中已经被全部加入——Pure FK 模式不隐藏任何实体节点，只裁剪连线（spec FR-007）。
3. **`self.link_set`（dedup 集合）一致性**：被早退的 ONETOMANY relationship 不入 `link_set`，与"该 Link 不存在"语义一致。
4. **`filter_to_neighborhood`（spec 005 子图）自动继承**：在 `analysis()` 之后调用、消费已过滤的 `self.links`，子图天然跟随 Pure FK 裁剪，无需新增逻辑。

---

## 关键边界情况

### 自引用双向关系

`Tree.parent = Relationship(back_populates="children")`（MANYTOONE）+ `Tree.children = Relationship(back_populates="parent")`（ONETOMANY）：

- Pure FK 关闭：两条 Link 都生成（自环呈现为 2 条自连线）
- Pure FK 开启：只生成 `Tree::fparent → Tree::PK`，自环呈现为单条 MANYTOONE 自连线

### 单向 ONETOMANY（无 `back_populates`）

仅在 `User` 上定义 `User.posts = Relationship(...)`，`Post` 上无反向：

- Pure FK 关闭：生成 `User::fposts → Post::PK` Link
- Pure FK 开启：早退、不生成 Link（`Post` 与 `User` 之间无连线）——spec Story 1 验收场景 5

### 单向 MANYTOONE（无 `back_populates`）

仅在 `Post` 上定义 `Post.author = Relationship(...)`（指向 `User`），`User` 上无反向：

- Pure FK 关闭：生成 `Post::fauthor → User::PK` Link
- Pure FK 开启：保留（MANYTOONE 不被过滤）

### M2M 关系（`secondary="..."`）

`Post.tags = Relationship(secondary="post_tag", back_populates="posts")` + `Tag.posts = Relationship(secondary="post_tag", back_populates="tags")`：

- Pure FK 关闭：两条 Link 都生成
- Pure FK 开启：两条 Link 都保留（`direction == 'MANYTOMANY'` 不匹配 `'ONETOMANY'`）——spec FR-006

### 复合外键 / 多列 FK

Pure FK 模式不引入新行为——只要 relationship 存在且方向是 MANYTOONE，Link 照常生成。是否实际为复合 FK 不影响过滤规则。

### `rel_info.direction` 为非常规值

理论不应发生（SQLAlchemy `inspect()` 严格返回 `MANYTOONE` / `ONETOMANY` / `MANYTOMANY`）。若发生：不匹配 `'ONETOMANY'`，按"保留"处理（保守偏向"宁可不画也不要画错"的反向——这里的"画错"指漏画 MANYTOONE/M2M，与 spec 边界情况"无法判定 direction 时按 ONETOMANY 处理即隐藏"略有出入）。

**取舍说明**：spec 边界情况写"无法判定 direction 时按 ONETOMANY 处理"，但代码现实是 `direction` 字段一定是三个明确字符串之一（不会是 None 或空串）。本期实现采用字面字符串比较 `rel_info.direction == 'ONETOMANY'`——若未来 SQLAlchemy 行为变化导致 `direction` 取值集合扩展，需要重新审视这一默认值。tests 用例 5（详见 quickstart.md）覆盖此边界。
