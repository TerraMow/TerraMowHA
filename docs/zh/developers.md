# TerraMow 开发者指南

本文档提供了有关 TerraMow Home Assistant 集成组件的开发信息，帮助开发者理解代码结构并进行功能扩展。


<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [通信方式](#通信方式)
- [MQTT Topics 定义](#mqtt-topics-定义)

<!-- /code_chunk_output -->

## 通信方式

TerraMow 和 Home Assistant 之间的通信主要通过 MQTT 协议进行。为了简化配置，我们并没有使用 Home Assistant 侧的 MQTT Broker，而是内置了一个轻量的 MQTT Broker 在 TerraMow 中。这样一来在设置时就只需要填入 TerraMow 的 IP 和密码即可。

值得注意的是，TerraMow 的 MQTT Broker 使用了默认端口 1883，且没有启用 SSL/TLS 加密，因此最好在局域网内使用，并确保你的 Wifi 网络进行了合适的加密（WPA/WPA2）。

## MQTT Topics 定义

在 TerraMow 中，主要的数据协议是以 Data Point 为单元定义的。为了实现数据的双向通信，TerraMow 需要将数据点的状态通过 MQTT Topic 发布到 Home Assistant 中，同时也需要监听 Home Assistant 发布的 Topic 来接收指令。

有关于 Data Point 的相关的 Topic 定义如下：

| Topic | 描述 |
| ------- | ------ |
| data_point/{dp_id}/robot | 机器人发布消息的方向（从机器人到应用） |
| data_point/{dp_id}/app | 应用发布消息给机器人的方向（从应用到机器人） |

其中 `{dp_id}` 是 Data Point 的 ID，类型为整数，范围为 0-200。

具体 Data Point 的定义可以参考 [Data Point 定义](./developers/data_point.md)。

## 特殊主题

除了 Data Point 相关的主题外，TerraMow 还提供了一些特殊用途的 MQTT 主题。

> **版本兼容性说明**  
> 以下特殊主题功能需要设备端HA兼容性版本号为 2 或以上才能正常使用。  
> 如果您的设备版本低于此要求，这些功能将不可用。

### 特殊主题索引表

| 主题 | Topic | 数据方向 | 描述 | 最低版本要求 |
|------|-------|---------|------|--------------|
| [地图信息](#地图信息) | map/current/info | 机器人→HA | 地图完整信息（仅变化时发布） | HA v2+ |
| [设备型号](#设备型号) | model/name | 机器人→HA | 设备商业型号名称 | HA v2+ |

### 地图信息

> **版本要求**：需要设备端HA兼容性版本号 ≥ 2

地图信息通过专门的 MQTT 主题 `map/current/info` 发布，包含完整的地图信息数据。该主题的发布策略如下：

- **消息类型**：使用 QoS 1 和 retained 标志，确保新连接的客户端能获取最新地图信息
- **数据格式**：JSON 格式，包含地图状态、区域信息、作业参数等

#### 数据结构说明

地图信息 JSON 包含以下主要字段：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| id | number | 地图唯一标识符 |
| name | string | 地图名称 |
| total_area | number | 地图总面积（单位：0.1平方米） |
| map_state | string | 地图状态：MAP_STATE_EMPTY（空）、MAP_STATE_INCOMPLETE（不完整）、MAP_STATE_COMPLETE（完整） |
| regions | array | 区域列表，包含主区域信息 |
| mow_param | object | 全局割草参数设置 |
| clean_info | object | 当前作业信息 |

#### 区域结构（regions）

每个区域包含：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| id | number | 区域ID |
| name | string | 区域名称 |
| sub_regions | array | 子区域列表 |

子区域（sub_regions）包含：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| id | number | 子区域ID |
| name | string | 子区域名称 |
| is_selected_for_mow | boolean | 是否选中进行割草 |
| selected_for_mow_order | number | 割草顺序 |
| adjacent_sub_regions_id | array | 相邻子区域ID列表 |

#### 割草参数（mow_param）

包含全局和区域特定的割草参数：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| global_param | object | 全局割草参数（WorkParam类型） |
| regions | array | 有定制参数的区域列表 |
| enable_thorough_corner_cutting | boolean | 是否启用角落彻底切割功能 |
| high_grass_edge_trim_mode | object | 边缘割草时的高草优化模式配置 |

WorkParam 对象包含：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| mow_height | number | 割草高度（毫米） |
| mow_speed | string | 割草速度（MOW_SPEED_TYPE_LOW/MEDIUM/ADAPTIVE_HIGH） |
| edge_cutting_distance | number | 边缘割草距离（毫米） |
| main_direction_angle_config | object | 主方向角度配置 |
| mow_spacing | number | 割草间距（毫米） |
| blade_disk_speed | string | 刀盘转速（BLADE_DISK_SPEED_TYPE_LOW/MEDIUM/HIGH） |

#### 作业信息（clean_info）

当前作业状态信息：

| 字段名 | 类型 | 描述 |
| ------ | ---- | ---- |
| mode | string | 作业模式（MAP_CLEAN_INFO_MODE_GLOBAL/SELECT_REGION/DRAW_REGION/MOVE_TO_TARGET_POINT） |
| select_region | object | 选区作业信息（仅mode为SELECT_REGION时有效） |
| draw_region | object | 划区作业信息（仅mode为DRAW_REGION时有效） |
| move_to_target_point | object | 移动到目标点信息（仅mode为MOVE_TO_TARGET_POINT时有效） |

select_region 对象包含：
- region_id: 选中的子区域ID数组

draw_region 对象包含：
- regions: 划区作业的区域列表（Polygon数组）

move_to_target_point 对象包含：
- target_point: 目标点位置

#### JSON 格式示例

##### 完整示例

```json
{
  "id": 1,
  "name": "我的草坪",
  "total_area": 5005,
  "map_state": "MAP_STATE_COMPLETE",
  "regions": [
    {
      "id": 1,
      "name": "前院",
      "sub_regions": [
        {
          "id": 101,
          "name": "前院-左侧",
          "is_selected_for_mow": true,
          "selected_for_mow_order": 1,
          "adjacent_sub_regions_id": [102]
        },
        {
          "id": 102,
          "name": "前院-右侧",
          "is_selected_for_mow": true,
          "selected_for_mow_order": 2,
          "adjacent_sub_regions_id": [101]
        }
      ]
    },
    {
      "id": 2,
      "name": "后院",
      "sub_regions": [
        {
          "id": 201,
          "name": "后院-主区域",
          "is_selected_for_mow": false,
          "selected_for_mow_order": 0,
          "adjacent_sub_regions_id": []
        }
      ]
    }
  ],
  "mow_param": {
    "global_param": {
      "mow_height": 30,
      "mow_speed": "MOW_SPEED_TYPE_MEDIUM",
      "edge_cutting_distance": 100,
      "mow_spacing": 150,
      "blade_disk_speed": "BLADE_DISK_SPEED_TYPE_HIGH",
      "main_direction_angle_config": {
        "mode": "MAIN_DIRECTION_MODE_SINGLE",
        "single_mode_config": {
          "angle": 0
        },
        "current_angle": 0
      }
    },
    "regions": [
      {
        "id": 101,
        "region_param": {
          "mow_height": 25,
          "mow_speed": "MOW_SPEED_TYPE_ADAPTIVE_HIGH",
          "edge_cutting_distance": 80,
          "mow_spacing": 120,
          "blade_disk_speed": "BLADE_DISK_SPEED_TYPE_HIGH"
        }
      }
    ],
    "enable_thorough_corner_cutting": true,
    "high_grass_edge_trim_mode": {
      "mode": "HIGH_GRASS_EDGE_TRIM_STANDARD"
    }
  },
  "clean_info": {
    "mode": "MAP_CLEAN_INFO_MODE_SELECT_REGION",
    "select_region": {
      "region_id": [101, 102]
    }
  }
}
```

##### 简化示例（地图不完整时）

```json
{
  "id": 2,
  "name": "未命名地图",
  "total_area": 0,
  "map_state": "MAP_STATE_INCOMPLETE",
  "regions": []
}
```

### 设备型号

> **版本要求**：需要设备端HA兼容性版本号 ≥ 2

设备型号通过 MQTT 主题 `model/name` 发布设备的商业型号名称：

- **发布时机**：设备启动时发布一次
- **消息类型**：使用 QoS 1 和 retained 标志
- **数据格式**：纯文本字符串，如 "TerraMow S1200"
- **用途**：Home Assistant 集成使用此信息显示设备型号
