# 地图与路径能力说明

本文档说明 TerraMow Home Assistant 集成当前支持的地图与路径接口，包括接入方式、主要数据内容以及客户端处理建议。

本文档以接口使用为中心，描述开发者在接入和渲染地图与路径能力时需要关注的信息，不展开设备端内部实现细节。

<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [能力概览](#能力概览)
- [版本要求](#版本要求)
- [接入流程](#接入流程)
- [MQTT 元数据](#mqtt-元数据)
- [HTTP 正文获取](#http-正文获取)
- [地图正文](#地图正文)
- [路径正文](#路径正文)
- [客户端处理建议](#客户端处理建议)
- [历史兼容说明](#历史兼容说明)

<!-- /code_chunk_output -->

## 能力概览

当前地图相关能力由三条输入通道组成：

| 能力 | MQTT Topic | HTTP Path | Schema | 说明 |
|------|------------|-----------|--------|------|
| 当前地图 | `map/current/meta` | `/ha/map/current.json.gz` | `ha_map_v1` | 当前地图正文 |
| 当前路径 | `path/current/meta` | `/ha/path/current.json.gz` | `ha_path_v1` | 当前实时路径 |
| 历史路径 | `path/history/meta` | `/ha/path/history.json.gz` | `ha_path_v1` | 历史路径 |

这三条通道统一采用“MQTT 元数据通知 + HTTP 正文拉取”的模式：

- MQTT 负责通知“有一份新数据可以取”
- HTTP 负责传输实际地图或路径正文
- 路径的“当前”和“历史”共用同一个 schema，语义由 topic/path 区分

本文档不覆盖以下能力：

- `pose/current`
- `model/name`
- `data_point/*`

## 版本要求

地图与路径能力需要设备端 `home_assistant` 兼容版本号 `>= 3`。

如果设备上报的兼容版本低于这个要求，开发者应将地图与路径能力视为“当前未兼容”，并给出明确提示，而不是把这些能力当成正常可用。

## 接入流程

推荐按以下顺序接入：

1. 订阅 `map/current/meta`、`path/current/meta`、`path/history/meta`
2. 收到 MQTT 元数据后，读取 `seq`、`http_port`、`http_path`、`schema`、`token`
3. 当 `seq` 变化时，向 `http://<device_ip>:<http_port><http_path>` 发起 HTTP 请求
4. 请求头中携带 `Authorization: Bearer <token>`
5. 按响应头的 `Content-Encoding: gzip` 解压正文
6. 根据 `schema` 解析正文：
   - `ha_map_v1` 对应地图
   - `ha_path_v1` 对应路径

因此，MQTT 主要承担变更通知职责，地图或路径正文应通过对应的 HTTP 接口获取。

## MQTT 元数据

当前地图与路径元数据都使用 JSON，字段语义如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 地图固定为 `map`，路径固定为 `path` |
| `seq` | uint64 | 设备侧递增序号，可用于判断是否有新数据 |
| `timestamp_ms` | uint64 | 元数据生成时间戳，单位毫秒 |
| `http_port` | int | HTTP 服务端口 |
| `http_path` | string | 对应正文拉取路径 |
| `content_type` | string | 固定为 `application/json` |
| `content_encoding` | string | 固定为 `gzip` |
| `schema` | string | 地图固定为 `ha_map_v1`，路径固定为 `ha_path_v1` |
| `token` | string | HTTP Bearer Token |

说明：

- 这些 MQTT topic 当前使用 retained 消息，新连接的客户端通常可以立即拿到最新元数据
- 当前路径与历史路径虽然语义不同，但 `schema` 都是 `ha_path_v1`
- 当前路径与历史路径的区别，依赖的是 topic 和 HTTP path，而不是 schema 名称变化

示例：

```json
{
  "type": "path",
  "seq": 35,
  "timestamp_ms": 1760000006000,
  "http_port": 8090,
  "http_path": "/ha/path/history.json.gz",
  "content_type": "application/json",
  "content_encoding": "gzip",
  "schema": "ha_path_v1",
  "token": "0123456789abcdef..."
}
```

## HTTP 正文获取

HTTP 正文请求要求如下：

- 请求头必须带 `Authorization: Bearer <token>`
- 成功时返回：
  - `Content-Type: application/json`
  - `Content-Encoding: gzip`
  - `Cache-Control: no-cache`

常见状态码：

| 状态码 | 含义 |
|--------|------|
| `401` | token 无效或未携带认证信息 |
| `404` | 当前没有可用地图或路径正文 |
| `500` | 设备端生成正文失败 |

## 地图正文

`ha_map_v1` 表示当前地图正文，用于统一承载地图、区域、禁区、通道以及作业上下文等信息。

### 你可以拿到的主要能力

| 能力分组 | 代表字段 | 用途 |
|----------|----------|------|
| 地图基础信息 | `id`、`name`、`width`、`height`、`resolution`、`origin` | 建立地图坐标系和基础信息展示 |
| 基站与视图信息 | `has_station`、`station_pose`、`has_bird_view`、`bird_view_index`、`map_view_rotate_angle` | 绘制基站、显示地图视图状态 |
| 区域结构 | `regions`、`sub_regions` | 绘制主区域、子区域、选区信息 |
| 障碍与限制区域 | `obstacles`、`forbidden_zones`、`virtual_walls`、`physical_forbidden_zones` | 绘制障碍物、禁区、虚拟墙等 |
| 通道与辅助区域 | `cross_boundary_tunnels`、`virtual_cross_boundary_tunnels`、`pass_through_zones`、`required_zones` | 绘制跨区通道、通行区、必要区域 |
| 标记与维护点 | `cross_boundary_markers`、`trapped_points`、`maintenance_points` | 绘制辅助标记或异常点位 |
| 地图状态与作业上下文 | `map_state`、`total_area`、`clean_info`、`mow_param`、`type` | 展示地图状态、当前作业模式和作业参数 |
| 备份与边界状态 | `has_backup`、`backup_info_list`、`is_boundary_locked`、`enable_advanced_edge_cutting`、`is_able_to_run_build_map` | 展示地图管理和边界能力状态 |

### 常见几何对象

地图正文里常见的空间对象包括：

- `Point`：点位，通常包含 `x`、`y`
- `Pose`：姿态，通常包含 `x`、`y`、`theta`
- `Polygon`：多边形
- `Line`：线段或折线
- `Ellipse`：椭圆

### 使用时需要注意

- 字段名使用 `snake_case`
- 枚举值是字符串枚举名，例如 `MAP_STATE_COMPLETE`
- 64 位整数可能以字符串形式出现，例如 `file_size`
- 某些嵌套对象或数组可能缺失，客户端需要按“可选字段”处理
- JSON 中可能出现文档未列出的附加字段，建议忽略未知字段，不要把它们当成解析错误

### 渲染相关提醒

- `map_view_rotate_angle` 更适合作为地图视图状态或配置值使用
- 在当前能力模型下，接收端通常不需要再根据这个字段对地图几何整体做一次旋转
- 地图正文本身不包含实时机器人姿态；如果需要实时机器人位置，应结合 `pose/current`

地图正文示例：

```json
{
  "id": 1,
  "name": "Home",
  "width": 1000,
  "height": 800,
  "resolution": 10,
  "origin": {
    "x": 0,
    "y": 0
  },
  "has_station": true,
  "station_pose": {
    "x": 1200,
    "y": 3400,
    "theta": 1570
  },
  "map_state": "MAP_STATE_COMPLETE",
  "regions": [],
  "forbidden_zones": [],
  "virtual_walls": [],
  "pass_through_zones": []
}
```

## 路径正文

`ha_path_v1` 同时用于“当前路径”和“历史路径”。这两个通道的正文结构完全一致，语义区分依赖 MQTT topic 与 HTTP path。

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int32 | 路径 ID |
| `map_id` | int32 | 路径所属地图 ID |
| `type` | string | 路径类型枚举名 |
| `end_pose` | object | 路径终点姿态 |
| `points` | array | 路径点列表 |

### 路径点结构

每个路径点当前包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `position` | object | 点位，类型为 `Point` |
| `type` | string | 路径点类型枚举名 |

`points[].type` 的常见取值包括：

- `PATH_POINT_TYPE_CLEANING`
- `PATH_POINT_TYPE_RETURN`
- `PATH_POINT_TYPE_RESUME`
- `PATH_POINT_TYPE_CROSS_BOUDARY`
- `PATH_POINT_TYPE_MOVE`
- `PATH_POINT_TYPE_MAPPING`
- `PATH_POINT_TYPE_SEMI_AUTO_MANUAL_MAPPING`

### 使用时需要注意

- 当前路径与历史路径都读取 `points`
- 并不是所有路径点类型都必须渲染
- 如果客户端只需要展示割草轨迹，通常优先关注 `PATH_POINT_TYPE_CLEANING`
- `end_pose` 可用于路径语义理解，但很多地图界面并不需要单独渲染它

路径正文示例：

```json
{
  "id": 101,
  "map_id": 1,
  "type": "NAVIGATION_PATH_TYPE_HISTORY",
  "points": [
    {
      "position": {
        "x": 100,
        "y": 200
      },
      "type": "PATH_POINT_TYPE_CLEANING"
    },
    {
      "position": {
        "x": 150,
        "y": 260
      },
      "type": "PATH_POINT_TYPE_MOVE"
    }
  ]
}
```

## 客户端处理建议

为保证地图展示的稳定性，客户端可按以下方式处理数据：

### 路径组织

- 分别缓存“当前路径”和“历史路径”
- 不要让历史路径覆盖当前路径，也不要让当前路径覆盖历史路径
- 渲染时优先绘制历史路径，再拼接当前路径尾部
- 如果历史路径最后一个点和当前路径第一个点重复，可以在客户端去重

### 回退策略

- 当旧设备没有 `path/history/meta` 时，应退化为只显示当前路径
- 当 `path/current` 暂时为空，但 `path/history` 有内容时，仍然可以显示历史路径
- 当路径的 `map_id` 与当前地图不匹配时，建议不要直接叠加渲染

### 解析策略

- 对未知字段保持向前兼容，直接忽略
- 对缺失的对象或数组做空值保护
- 不要依赖字段顺序

建议将这组接口按“可持续扩展”的能力模型接入，避免编写对字段数量和结构变化过于敏感的硬编码解析逻辑。

## 历史兼容说明

历史上曾有 `map/current/info` 这种直接通过 MQTT 发布地图内容的方式。这个入口可以继续作为兼容路径理解，但它不是当前推荐的正式地图能力入口。

对于新的插件、前端或第三方对接，建议统一以以下正式入口为准：

- `map/current/meta`
- `path/current/meta`
- `path/history/meta`

采用上述正式入口的主要收益如下：

- 地图大对象通过 HTTP 拉取，更适合地图类数据
- 当前路径和历史路径语义清晰分离
- 后续扩展能力时，客户端更容易保持兼容
