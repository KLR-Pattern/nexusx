# 契约:ER 内省端点协议

**特性**:`specs/012-federation` | 对应 FR-005/R7

这是**被挂服务**暴露给**挂载方**的 schema 自省契约。组合数据源是 ER 图信息(非 SDL),与 Voyager/executor 同源。

## 端点

`GET /nexusx/er-introspection`(或约定的成员侧路由),返回该服务完整的 ER 片段(自身所有实体 + 关系 + 批量 root + 远程引用)。

> 也支持 `GET /nexusx/er-introspection/<typename>` 取单类型片段(挂载方传递式发现时按需拉取)。

## 响应形状

```jsonc
{
  "service_name": "reviews",                 // 成员自声明 name = 命名前缀
  "entities": [
    {
      "typename": "Review",                  // 裸类型名
      "scalar_fields": [
        {"name": "id", "type_name": "int"},
        {"name": "product_id", "type_name": "int"},
        {"name": "title", "type_name": "str"},
        {"name": "rating", "type_name": "int"}
      ],
      "relationships": [
        {
          "name": "author",
          "direction": "MANYTOONE",
          "fk_field": "author_id",
          "target_typename": "User",
          "is_list": false,
          "sort_field": null,
          "target_service": "users",          // 远程关系才填(本服务内关系为 null)
          "target_endpoint": "http://users:8000"
        }
        // 本服务内关系(如 Review.comments)同样列出,target_service=null
      ],
      "batch_roots": ["by_id", "by_product_id_in", "by_author_id_in"]
    }
  ]
}
```

## 不变量

- **`type_name` 是完整类型表达式字符串**(如 `"int"`、`"list[str]"`、`"UUID"`、`"int | None"`、`"Status"`)。成员经 `introspect._type_expr`(无损渲染)产出;挂载方经 `create_model` + `model_rebuild(_types_namespace=...)` 精确重建——`list`/`Optional`/已知标量/枚举无损往返,而非降级成 `Any`。未知名(未在挂载方注册的自定义类型)回退 `Any` + 警告;用 `federate(extra_types={...})` 注册项目公共类型/枚举以获得精确物化。
- **来源**:`ErManager.get_all_entities()` + `get_all_relationships()`(`RelationshipInfo`),与 Voyager 同源(spec 决定 1)。
- **loader 不序列化**:`RelationshipInfo.loader` 是代码对象(非数据),不进 wire。
- **远程关系**(`target_service != None`)必须携带 `target_service` + `target_endpoint`,使挂载方能传递式发现可达子图(FR-005)。
- **fk_field 保留**:与 SDL 不同,ER 片段**保留** FK 字段名(`product_id`/`author_id`),join key 确定可校验。
- `service_name` 是成员的自声明稳定 name,作为前缀;两个被挂服务不许重名(FR-013e)。

## 挂载方消费(FederatedTypeRegistry)

1. 按声明的 `RemoteRelationship.target` 取 `("srv","typename")` → 向 `srv` 端点拉片段。
2. 片段中的远程关系(`target_service != None`)→ 把 `(target_service, target_typename)` 加入待拉取队列(传递式)。
3. visited-set(规范名)去环;遇自身或已访问即停(R9/FR-013g)。
4. 片段→物化(见 [data-model.md §4/§6](../data-model.md))。

## 相关
- [remote-relationship.md](./remote-relationship.md):声明引用 `"<srv>.<typename>"`,解析依赖本端点。
- spec FR-005;plan `federation/introspect.py`、`federation/contract.py`。
