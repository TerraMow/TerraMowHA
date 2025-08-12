# TerraMow Developer Guide

This document provides development information about the TerraMow Home Assistant integration component, helping developers understand the code structure and extend functionality.


<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Communication Method](#communication-method)
- [MQTT Topics Definition](#mqtt-topics-definition)

<!-- /code_chunk_output -->

## Communication Method

Communication between TerraMow and Home Assistant is primarily through the MQTT protocol. To simplify configuration, we don't use the MQTT Broker on the Home Assistant side, but instead have built a lightweight MQTT Broker into TerraMow. This way, during setup, you only need to enter the TerraMow IP and password.

It's worth noting that TerraMow's MQTT Broker uses the default port 1883 and does not enable SSL/TLS encryption, so it's best to use it within a local network and ensure your Wifi network has appropriate encryption (WPA/WPA2).

## MQTT Topics Definition

In TerraMow, the main data protocol is defined in units of Data Points. To achieve bidirectional communication, TerraMow needs to publish the state of data points to Home Assistant via MQTT Topics, while also listening to topics published by Home Assistant to receive commands.

The topic definitions related to Data Points are as follows:

| Topic | Description |
| ------- | ------ |
| data_point/{dp_id}/robot | Direction of messages published by the robot (from robot to application) |
| data_point/{dp_id}/app | Direction of messages published to the robot (from application to robot) |

Where `{dp_id}` is the ID of the Data Point, an integer ranging from 0 to 200.

For specific Data Point definitions, please refer to [Data Point Definition](./developers/data_point.md).

## Special Topics

In addition to Data Point related topics, TerraMow also provides some special-purpose MQTT topics.

> **Version Compatibility Note**  
> The following special topic features require device-side HA compatibility version 2 or higher to function properly.  
> If your device version is below this requirement, these features will not be available.

### Special Topics Index

| Topic | MQTT Topic | Data Direction | Description | Min Version |
|-------|------------|----------------|-------------|-------------|
| [Map Information](#map-information) | map/current/info | Robot→HA | Complete map information (published only when changes occur) | HA v2+ |
| [Device Model](#device-model) | model/name | Robot→HA | Device commercial model name | HA v2+ |

### Map Information

> **Version Requirement**: Requires device-side HA compatibility version ≥ 2

Map information is published through the dedicated MQTT topic `map/current/info`, containing complete map data. The publishing strategy for this topic is as follows:

- **Message Type**: Uses QoS 1 and retained flag to ensure newly connected clients can get the latest map information
- **Data Format**: JSON format, containing map state, region information, mowing parameters, etc.

#### Data Structure Description

The map information JSON contains the following main fields:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| id | number | Unique map identifier |
| name | string | Map name |
| total_area | number | Total map area (unit: 0.1 square meters) |
| map_state | string | Map state: MAP_STATE_EMPTY (empty), MAP_STATE_INCOMPLETE (incomplete), MAP_STATE_COMPLETE (complete) |
| regions | array | Region list containing main region information |
| mow_param | object | Global mowing parameter settings |
| clean_info | object | Current job information |

#### Region Structure (regions)

Each region contains:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| id | number | Region ID |
| name | string | Region name |
| sub_regions | array | Sub-region list |

Sub-regions (sub_regions) contain:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| id | number | Sub-region ID |
| name | string | Sub-region name |
| is_selected_for_mow | boolean | Whether selected for mowing |
| selected_for_mow_order | number | Mowing order |
| adjacent_sub_regions_id | array | Adjacent sub-region ID list |

#### Mowing Parameters (mow_param)

Contains global and region-specific mowing parameters:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| global_param | object | Global mowing parameters (WorkParam type) |
| regions | array | List of regions with custom parameters |
| enable_thorough_corner_cutting | boolean | Whether to enable thorough corner cutting |
| high_grass_edge_trim_mode | object | High grass optimization mode configuration for edge trimming |

WorkParam object contains:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| mow_height | number | Mowing height (millimeters) |
| mow_speed | string | Mowing speed (MOW_SPEED_TYPE_LOW/MEDIUM/ADAPTIVE_HIGH) |
| edge_cutting_distance | number | Edge cutting distance (millimeters) |
| main_direction_angle_config | object | Main direction angle configuration |
| mow_spacing | number | Mowing spacing (millimeters) |
| blade_disk_speed | string | Blade disk speed (BLADE_DISK_SPEED_TYPE_LOW/MEDIUM/HIGH) |

#### Job Information (clean_info)

Current job status information:

| Field Name | Type | Description |
| ---------- | ---- | ----------- |
| mode | string | Job mode (MAP_CLEAN_INFO_MODE_GLOBAL/SELECT_REGION/DRAW_REGION/MOVE_TO_TARGET_POINT) |
| select_region | object | Region selection job information (only valid when mode is SELECT_REGION) |
| draw_region | object | Draw region job information (only valid when mode is DRAW_REGION) |
| move_to_target_point | object | Move to target point information (only valid when mode is MOVE_TO_TARGET_POINT) |

select_region object contains:
- region_id: Array of selected sub-region IDs

draw_region object contains:
- regions: List of regions for draw region job (Polygon array)

move_to_target_point object contains:
- target_point: Target point position

#### JSON Format Examples

##### Complete Example

```json
{
  "id": 1,
  "name": "My Lawn",
  "total_area": 5005,
  "map_state": "MAP_STATE_COMPLETE",
  "regions": [
    {
      "id": 1,
      "name": "Front Yard",
      "sub_regions": [
        {
          "id": 101,
          "name": "Front Yard - Left",
          "is_selected_for_mow": true,
          "selected_for_mow_order": 1,
          "adjacent_sub_regions_id": [102]
        },
        {
          "id": 102,
          "name": "Front Yard - Right",
          "is_selected_for_mow": true,
          "selected_for_mow_order": 2,
          "adjacent_sub_regions_id": [101]
        }
      ]
    },
    {
      "id": 2,
      "name": "Back Yard",
      "sub_regions": [
        {
          "id": 201,
          "name": "Back Yard - Main Area",
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

##### Simplified Example (when map is incomplete)

```json
{
  "id": 2,
  "name": "Unnamed Map",
  "total_area": 0,
  "map_state": "MAP_STATE_INCOMPLETE",
  "regions": []
}
```

### Device Model

> **Version Requirement**: Requires device-side HA compatibility version ≥ 2

Device model is published through MQTT topic `model/name` containing the commercial model name of the device:

- **Publishing Timing**: Published once when the device starts up
- **Message Type**: Uses QoS 1 and retained flag
- **Data Format**: Plain text string, e.g., "TerraMow S1200"
- **Purpose**: Home Assistant integration uses this information to display device model