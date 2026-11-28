# 地图编辑协议

DP120 用于发送地图编辑请求和接收回复。本文介绍角落彻底切割开关和高草沿边模式。
两项设置都属于指定地图，保存在该地图的 `mow_param` 对象中。

<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [固件能力](#固件能力)
- [通信方式与请求字段](#通信方式与请求字段)
- [角落彻底切割](#角落彻底切割)
- [高草沿边模式](#高草沿边模式)
- [回复与状态核对](#回复与状态核对)

<!-- /code_chunk_output -->

## 固件能力

相关功能的兼容版本由 DP127 上报：

| 字段 | 版本 | 接口 |
| --- | --- | --- |
| `module.thorough_corner_cutting` | 0 | 不支持 |
| `module.thorough_corner_cutting` | 1 | DP150 中的旧全局设置 |
| `module.thorough_corner_cutting` | 2+ | 通过 DP120 修改地图级设置 |
| `module.high_grass_edge_trim` | 0 | 不支持 |
| `module.high_grass_edge_trim` | 1 | DP150 中的旧布尔开关 |
| `module.high_grass_edge_trim` | 2 | DP150 中的旧三档模式 |
| `module.high_grass_edge_trim` | 3+ | 通过 DP120 修改地图级三档模式 |

这些数字是功能兼容版本号，不是固件发布版本号。MP510 9.9.0 固件维护版本的当前实现
已经使用本文介绍的地图级接口。兼容旧固件时，应根据上报的功能版本区分接口。

读取地图所需的设备端 HA 兼容版本是另一项能力。HA v3+ 的地图正文接口见
[地图与路径能力说明](./map_path.md)，HA v2 的兼容入口见开发者指南中的
[旧地图主题](../developers.md#地图信息)。

DP155 不包含这两项设置。对于已经使用地图级设置的固件，DP150 中旧的
`enable_high_grass_edge_trim` 布尔开关仍可能被保存和上报，但不会修改地图中的
三档模式。收到旧值回报不能作为当前地图设置已修改的依据。

## 通信方式与请求字段

发送请求前，先订阅回复主题 `data_point/120/robot`，再向 `data_point/120/app`
发布请求。两种报文都使用 protobuf JSON，字段名采用下文所示的 `snake_case` 格式。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `seq` | uint32 | 请求标识，回复中原样返回；每个新请求使用不同的非零值 |
| `map_id` | int32 | 要编辑的地图 ID |
| `command` | 枚举 | 地图编辑命令名 |
| 对应的参数对象 | 对象 | 下表中与命令对应的参数字段 |

`map_id` 取目标地图的 `id`，不要使用分区 ID。示例中的地图 ID 为 `1`，发送时需替换为
实际地图 ID。编辑当前地图时，应同时记录所展示设置对应的地图 ID，避免地图切换后将
尚未完成的请求或其结果关联到另一张地图。

每个请求只携带与命令对应的参数对象。该对象与 `seq`、`map_id`、`command` 同属报文
顶层字段，无需额外增加 `param` 包装层。

| 操作 | `command` | 数值 | 参数字段 |
| --- | --- | --- | --- |
| 设置角落彻底切割开关 | `MAP_EDIT_COMMAND_SET_THOROUGH_CORNER_CUTTING` | 51 | `set_thorough_corner_cutting_param` |
| 设置高草沿边模式 | `MAP_EDIT_COMMAND_SET_HIGH_GRASS_EDGE_TRIM_MODE` | 52 | `set_high_grass_edge_trim_mode_param` |

## 角落彻底切割

`set_thorough_corner_cutting_param.enable_thorough_corner_cutting` 为布尔值。
发送 `true` 可为指定地图开启该功能：

```json
{
  "seq": 1001,
  "map_id": 1,
  "command": "MAP_EDIT_COMMAND_SET_THOROUGH_CORNER_CUTTING",
  "set_thorough_corner_cutting_param": {
    "enable_thorough_corner_cutting": true
  }
}
```

关闭时发送 `false`，并使用新的请求标识：

```json
{
  "seq": 1002,
  "map_id": 1,
  "command": "MAP_EDIT_COMMAND_SET_THOROUGH_CORNER_CUTTING",
  "set_thorough_corner_cutting_param": {
    "enable_thorough_corner_cutting": false
  }
}
```

修改后的值从目标地图的 `mow_param.enable_thorough_corner_cutting` 读取。

## 高草沿边模式

将嵌套字段 `set_high_grass_edge_trim_mode_param.high_grass_edge_trim_mode.mode`
设为以下枚举之一：

| 枚举名 | 数值 | 含义 |
| --- | --- | --- |
| `HIGH_GRASS_EDGE_TRIM_DISABLED` | 0 | 禁用高草优化 |
| `HIGH_GRASS_EDGE_TRIM_STANDARD` | 1 | 标准高草优化 |
| `HIGH_GRASS_EDGE_TRIM_ENHANCED` | 2 | 增强高草优化 |

例如，选择增强模式：

```json
{
  "seq": 1003,
  "map_id": 1,
  "command": "MAP_EDIT_COMMAND_SET_HIGH_GRASS_EDGE_TRIM_MODE",
  "set_high_grass_edge_trim_mode_param": {
    "high_grass_edge_trim_mode": {
      "mode": "HIGH_GRASS_EDGE_TRIM_ENHANCED"
    }
  }
}
```

其他两档沿用相同结构，将模式替换为 `HIGH_GRASS_EDGE_TRIM_DISABLED` 或
`HIGH_GRASS_EDGE_TRIM_STANDARD`。修改后的值从目标地图的
`mow_param.high_grass_edge_trim_mode.mode` 读取。

## 回复与状态核对

根据请求的 `seq` 匹配 `data_point/120/robot` 上的回复，忽略 retained（保留消息）
回复及其他请求的回复。地图编辑回复通过 `code` 表示结果，不使用部分其他命令中的
`ret` 字段。有效 protobuf JSON 回复中的 `code` 为零时可能省略；缺少有效 `seq`
不能视为请求成功。

例如，请求 `1003` 对应的成功回复为：

```json
{
  "seq": 1003,
  "code": 0
}
```

| `code` | 含义 |
| --- | --- |
| 0 | 成功 |
| 201 | 命令参数无效 |
| 202 | 地图参数无效，客户端地图数据可能已不同步 |
| 203 | 地图数据发送失败 |

`203` 不能证明设置没有修改：编辑可能已经完成，随后才发生地图数据发送失败。
应先获取新的地图状态并核对设置，再决定是否重试。其他非零返回码、超时及 MQTT
断连也不能作为编辑成功的依据。

回复不包含修改后的设置值。MQTT 发布确认只表示消息传输，仍需通过
[地图正文接口](./map_path.md#地图正文)或适用版本的旧 `map/current/info` 主题，
在同一张地图的新快照中核对结果。相关字段节选如下：

```json
{
  "id": 1,
  "mow_param": {
    "enable_thorough_corner_cutting": false,
    "high_grass_edge_trim_mode": {
      "mode": "HIGH_GRASS_EDGE_TRIM_ENHANCED"
    }
  }
}
```

核对结果时应保留目标地图 ID 的关联。当前地图切换后，展示新地图自己的设置，
不要使用另一张地图的快照确认之前的编辑结果。
