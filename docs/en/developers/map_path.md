# Map and Path Capabilities

This document describes the map and path interfaces currently supported by the TerraMow Home Assistant integration, including integration flow, main data structures, and client-side handling recommendations.

The document is centered on interface usage and the information developers need when integrating or rendering map and path capabilities. It does not cover device-side implementation details.

<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Capability Overview](#capability-overview)
- [Version Requirement](#version-requirement)
- [Integration Flow](#integration-flow)
- [MQTT Metadata](#mqtt-metadata)
- [HTTP Body Retrieval](#http-body-retrieval)
- [Map Body](#map-body)
- [Path Body](#path-body)
- [Client Handling Recommendations](#client-handling-recommendations)
- [Backward Compatibility](#backward-compatibility)

<!-- /code_chunk_output -->

## Capability Overview

The current map-related capabilities are exposed through three input channels:

| Capability | MQTT Topic | HTTP Path | Schema | Description |
|------------|------------|-----------|--------|-------------|
| Current map | `map/current/meta` | `/ha/map/current.json.gz` | `ha_map_v1` | Current map body |
| Current path | `path/current/meta` | `/ha/path/current.json.gz` | `ha_path_v1` | Current realtime path |
| History path | `path/history/meta` | `/ha/path/history.json.gz` | `ha_path_v1` | History path |

These three channels follow the same "MQTT metadata notification + HTTP body retrieval" model:

- MQTT notifies clients that a new payload is available
- HTTP transports the actual map or path body
- Current path and history path share the same schema, and are distinguished by topic and path

This document does not cover the following capabilities:

- `pose/current`
- `model/name`
- `data_point/*`

## Version Requirement

Map and path capabilities require device-side `home_assistant` compatibility version `>= 3`.

If the compatibility version reported by the device is below this requirement, clients should treat map and path capabilities as unavailable and provide a clear compatibility message instead of assuming normal availability.

## Integration Flow

The recommended integration flow is:

1. Subscribe to `map/current/meta`, `path/current/meta`, and `path/history/meta`
2. After receiving MQTT metadata, read `seq`, `http_port`, `http_path`, `schema`, and `token`
3. When `seq` changes, send an HTTP request to `http://<device_ip>:<http_port><http_path>`
4. Include `Authorization: Bearer <token>` in the request headers
5. Decompress the response body according to `Content-Encoding: gzip`
6. Parse the body according to `schema`:
   - `ha_map_v1` for the map body
   - `ha_path_v1` for path bodies

Accordingly, MQTT mainly serves as a change notification channel, while map and path bodies should be fetched through the corresponding HTTP endpoints.

## MQTT Metadata

Map and path metadata are currently encoded as JSON with the following field semantics:

| Field | Type | Description |
|------|------|-------------|
| `type` | string | Fixed to `map` for maps and `path` for paths |
| `seq` | uint64 | Device-side incremental sequence number used to detect updates |
| `timestamp_ms` | uint64 | Metadata generation timestamp in milliseconds |
| `http_port` | int | HTTP service port |
| `http_path` | string | HTTP path for retrieving the body |
| `content_type` | string | Fixed to `application/json` |
| `content_encoding` | string | Fixed to `gzip` |
| `schema` | string | Fixed to `ha_map_v1` for maps and `ha_path_v1` for paths |
| `token` | string | HTTP Bearer Token |

Notes:

- These MQTT topics currently use retained messages, so newly connected clients can typically obtain the latest metadata immediately
- Current path and history path use different channels, but both use the `ha_path_v1` schema
- The distinction between current path and history path depends on the MQTT topic and HTTP path, not on a schema name change

Example:

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

## HTTP Body Retrieval

HTTP body requests follow these rules:

- The request header must include `Authorization: Bearer <token>`
- On success, the response always includes:
  - `Content-Type: application/json`
  - `Content-Encoding: gzip`
  - `Cache-Control: no-cache`

Common status codes:

| Status Code | Meaning |
|-------------|---------|
| `401` | Invalid token or missing authorization |
| `404` | No map or path body is currently available |
| `500` | The device failed to generate the response body |

## Map Body

`ha_map_v1` is the current map body and is used to carry map, region, forbidden area, tunnel, and job-context information in a single JSON object.

### Main capabilities exposed by the map body

| Capability Group | Representative Fields | Usage |
|------------------|-----------------------|-------|
| Basic map information | `id`, `name`, `width`, `height`, `resolution`, `origin` | Establish the map coordinate system and show basic metadata |
| Station and view information | `has_station`, `station_pose`, `has_bird_view`, `bird_view_index`, `map_view_rotate_angle` | Render the charging station and display map view state |
| Region structure | `regions`, `sub_regions` | Render main regions, sub-regions, and selected areas |
| Obstacles and restricted areas | `obstacles`, `forbidden_zones`, `virtual_walls`, `physical_forbidden_zones` | Render obstacles, forbidden areas, and virtual walls |
| Tunnels and auxiliary areas | `cross_boundary_tunnels`, `virtual_cross_boundary_tunnels`, `pass_through_zones`, `required_zones` | Render cross-boundary tunnels, pass-through zones, and required zones |
| Markers and maintenance points | `cross_boundary_markers`, `trapped_points`, `maintenance_points` | Render auxiliary markers or exceptional points |
| Map state and job context | `map_state`, `total_area`, `clean_info`, `mow_param`, `type` | Display map state, current job mode, and mowing parameters |
| Backup and boundary state | `has_backup`, `backup_info_list`, `is_boundary_locked`, `enable_advanced_edge_cutting`, `is_able_to_run_build_map` | Display map management and boundary-related state |

### Common geometry objects

Common spatial objects in the map body include:

- `Point`: a point, typically containing `x` and `y`
- `Pose`: a pose, typically containing `x`, `y`, and `theta`
- `Polygon`: a polygon
- `Line`: a line segment or polyline
- `Ellipse`: an ellipse

### Usage notes

- Field names use `snake_case`
- Enum values are string enum names such as `MAP_STATE_COMPLETE`
- 64-bit integers may appear as strings, such as `file_size`
- Some nested objects or arrays may be absent and should be treated as optional
- Additional fields not listed in this document may appear in the JSON; clients should ignore unknown fields instead of treating them as parsing errors

### Rendering notes

- `map_view_rotate_angle` is better treated as map view state or a configuration value
- Under the current capability model, receivers typically do not need to rotate the map geometry again based on this field
- The map body itself does not contain the realtime robot pose; if realtime robot position is needed, combine it with `pose/current`

Example map body:

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

## Path Body

`ha_path_v1` is used for both current path and history path. The body structure is identical for both channels, and the semantic distinction depends on the MQTT topic and HTTP path.

### Top-level fields

| Field | Type | Description |
|------|------|-------------|
| `id` | int32 | Path ID |
| `map_id` | int32 | Map ID associated with the path |
| `type` | string | Path type enum name |
| `end_pose` | object | End pose of the path |
| `points` | array | Path point list |

### Path point structure

Each path point currently contains:

| Field | Type | Description |
|------|------|-------------|
| `position` | object | Point position, of type `Point` |
| `type` | string | Path point type enum name |

Common values for `points[].type` include:

- `PATH_POINT_TYPE_CLEANING`
- `PATH_POINT_TYPE_RETURN`
- `PATH_POINT_TYPE_RESUME`
- `PATH_POINT_TYPE_CROSS_BOUDARY`
- `PATH_POINT_TYPE_MOVE`
- `PATH_POINT_TYPE_MAPPING`
- `PATH_POINT_TYPE_SEMI_AUTO_MANUAL_MAPPING`

### Usage notes

- Both current path and history path are read from `points`
- Not every path point type needs to be rendered
- If the client only needs to show mowing tracks, `PATH_POINT_TYPE_CLEANING` is usually the primary type to use
- `end_pose` may be useful for path semantics, but many map views do not need to render it separately

Example path body:

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

## Client Handling Recommendations

To keep map rendering stable, clients can handle the data as follows:

### Path organization

- Cache current path and history path separately
- Do not let history path overwrite current path, and do not let current path overwrite history path
- Render history path first, then append the tail of the current path
- If the last point of the history path duplicates the first point of the current path, the client can deduplicate them

### Fallback strategy

- If an older device does not provide `path/history/meta`, fall back to showing only the current path
- If `path/current` is temporarily empty but `path/history` has content, the history path can still be rendered
- If the path `map_id` does not match the current map, it is recommended not to overlay it directly

### Parsing strategy

- Ignore unknown fields to preserve forward compatibility
- Treat missing objects or arrays as empty or optional values
- Do not depend on field order

These interfaces should be integrated as an extensible capability set rather than with rigid parsing logic that is overly sensitive to field additions or omissions.

## Backward Compatibility

Historically, `map/current/info` was used to publish map content directly over MQTT. This entry point can still be treated as a compatibility path, but it is not the currently recommended formal entry point for map capabilities.

For new integrations, frontends, or third-party consumers, the following formal entry points are recommended:

- `map/current/meta`
- `path/current/meta`
- `path/history/meta`

The main benefits of using these formal entry points are:

- Large map bodies are retrieved over HTTP, which is more suitable for map-class data
- Current path and history path are clearly separated semantically
- Clients can remain compatible more easily as capabilities evolve
