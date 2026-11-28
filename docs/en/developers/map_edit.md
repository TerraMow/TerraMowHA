# Map editing protocol

DP120 carries map editing requests and replies. This document covers thorough
corner cutting and the high-grass edge trim mode. Both settings belong to a
specific map and are stored under that map's `mow_param` object.

<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Firmware capabilities](#firmware-capabilities)
- [Transport and request fields](#transport-and-request-fields)
- [Thorough corner cutting](#thorough-corner-cutting)
- [High-grass edge trim mode](#high-grass-edge-trim-mode)
- [Replies and state verification](#replies-and-state-verification)

<!-- /code_chunk_output -->

## Firmware capabilities

The relevant capability versions are reported by DP127:

| Field | Version | Interface |
| --- | --- | --- |
| `module.thorough_corner_cutting` | 0 | Unsupported |
| `module.thorough_corner_cutting` | 1 | Legacy global setting in DP150 |
| `module.thorough_corner_cutting` | 2+ | Map-level setting through DP120 |
| `module.high_grass_edge_trim` | 0 | Unsupported |
| `module.high_grass_edge_trim` | 1 | Legacy boolean setting in DP150 |
| `module.high_grass_edge_trim` | 2 | Legacy three-mode setting in DP150 |
| `module.high_grass_edge_trim` | 3+ | Map-level three-mode setting through DP120 |

These are feature compatibility versions, not firmware release numbers. The
current MP510 9.9.0 firmware maintenance line already uses the map-level
interfaces described here. Use the reported feature versions to distinguish
interfaces when supporting older firmware.

The device-side HA compatibility version used for reading maps is a separate
capability. See [Map and Path Capabilities](./map_path.md) for the HA v3+ map
body interface and the developer guide's
[legacy map topic](../developers.md#map-information) for HA v2.

DP155 does not contain either setting. On firmware using map-level settings,
the old DP150 `enable_high_grass_edge_trim` boolean can still be stored and
reported, but it does not update the map's three-mode setting. An echo of that
legacy value is not confirmation that the current map was changed.

## Transport and request fields

Subscribe to `data_point/120/robot` before publishing requests to
`data_point/120/app`. Both payloads use protobuf JSON and the snake_case field
names shown below.

| Field | Type | Meaning |
| --- | --- | --- |
| `seq` | uint32 | Request identifier echoed in the reply; use a distinct nonzero value for each new request |
| `map_id` | int32 | ID of the map being edited |
| `command` | Enum | Map editing command name |
| Matching parameter object | Object | The command-specific field listed below |

Take `map_id` from the target map's `id`, not from a region ID. The examples use
map ID `1`; replace it with the actual ID. When editing the current map, capture
its ID with the settings being displayed so a map change does not redirect an
outstanding request or its result to a different map.

Each request contains exactly the parameter object for its command. The named
object is a top-level field alongside `seq`, `map_id` and `command`; there is no
additional `param` wrapper.

| Operation | `command` | Numeric value | Parameter field |
| --- | --- | --- | --- |
| Set thorough corner cutting | `MAP_EDIT_COMMAND_SET_THOROUGH_CORNER_CUTTING` | 51 | `set_thorough_corner_cutting_param` |
| Set high-grass edge trim mode | `MAP_EDIT_COMMAND_SET_HIGH_GRASS_EDGE_TRIM_MODE` | 52 | `set_high_grass_edge_trim_mode_param` |

## Thorough corner cutting

`set_thorough_corner_cutting_param.enable_thorough_corner_cutting` is a boolean.
Send `true` to enable the feature for the selected map:

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

Send `false` to disable it, using a new request identifier:

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

Read the resulting value from `mow_param.enable_thorough_corner_cutting` in the
target map.

## High-grass edge trim mode

Set the nested field
`set_high_grass_edge_trim_mode_param.high_grass_edge_trim_mode.mode` to one of:

| Enum name | Numeric value | Meaning |
| --- | --- | --- |
| `HIGH_GRASS_EDGE_TRIM_DISABLED` | 0 | Disable high-grass optimization |
| `HIGH_GRASS_EDGE_TRIM_STANDARD` | 1 | Standard high-grass optimization |
| `HIGH_GRASS_EDGE_TRIM_ENHANCED` | 2 | Enhanced high-grass optimization |

For example, select enhanced mode:

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

Use the same structure with `HIGH_GRASS_EDGE_TRIM_DISABLED` or
`HIGH_GRASS_EDGE_TRIM_STANDARD` for the other modes. Read the resulting value
from `mow_param.high_grass_edge_trim_mode.mode` in the target map.

## Replies and state verification

Match a reply on `data_point/120/robot` to the request's `seq`. Ignore retained
replies and replies for other requests. The map edit reply reports its result
in `code`, not the `ret` field used by some other commands. A valid protobuf
JSON reply may omit `code` when it is zero; a missing or invalid `seq` must not
be interpreted as success.

For example, a successful reply to request `1003` is:

```json
{
  "seq": 1003,
  "code": 0
}
```

| `code` | Meaning |
| --- | --- |
| 0 | Success |
| 201 | Invalid command parameter |
| 202 | Invalid map parameter; the client's map data may be out of sync |
| 203 | Map data could not be sent |

Code `203` does not prove that the setting was left unchanged: the edit may
already have been applied before map delivery failed. Obtain fresh map state
and check the value before deciding whether to retry. Other nonzero codes,
timeouts and MQTT disconnections do not confirm a successful edit.

The reply contains no copy of the setting. MQTT publish acknowledgement only
confirms transport. Verify the value in a fresh snapshot of the same map using
the [map body interface](./map_path.md#map-body), or the legacy
`map/current/info` topic when applicable. A relevant excerpt is:

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

Keep each verification associated with its target map ID. When the current map
changes, display that map's settings; do not use a different map's snapshot to
confirm an earlier edit.
