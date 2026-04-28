"""TerraMow 地图摄像头实体。

将 ha_map_v1 / ha_path_v1 / pose 渲染为带 HUD 的 PNG 地图。
"""

from __future__ import annotations

import io
import logging
import math
import time
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, TerraMowBasicData

_LOGGER = logging.getLogger(__name__)

# 输出画布
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024

# 布局
OUTER_MARGIN = 40
MAP_RECT = (40, 40, 984, 728)
SUMMARY_RECT = (40, 760, 984, 928)
MAP_PADDING = 24
MAP_RADIUS = 28
CARD_RADIUS = 24

# 颜色定义
COLOR_APP_BG = (237, 240, 244, 255)
COLOR_MAP_BG = (244, 244, 246, 255)
COLOR_CARD_BG = (255, 255, 255, 255)
COLOR_CARD_BORDER = (223, 227, 233, 255)
COLOR_SHADOW = (205, 212, 223, 90)
COLOR_TEXT = (38, 38, 38, 255)
COLOR_TEXT_SUBTLE = (102, 110, 122, 255)
COLOR_TEXT_MUTED = (149, 156, 166, 255)
COLOR_TEXT_WHITE = (255, 255, 255, 255)

COLOR_MAP_DEFAULT_FILL = (220, 224, 232, 255)
COLOR_MAP_DEFAULT_OUTLINE = (198, 199, 204, 255)
COLOR_CHANNEL = (255, 196, 0, 255)
COLOR_CHANNEL_SOFT = (255, 247, 219, 160)
COLOR_RESTRICTED_FILL = (255, 120, 70, 26)
COLOR_RESTRICTED_OUTLINE = (255, 120, 70, 255)
COLOR_PASS_THROUGH_FILL = (255, 162, 49, 36)
COLOR_PASS_THROUGH_OUTLINE = (255, 162, 49, 255)
COLOR_REQUIRED_FILL = (68, 117, 235, 32)
COLOR_REQUIRED_OUTLINE = (68, 117, 235, 255)
COLOR_DRAW_REGION_FILL = (68, 117, 235, 20)
COLOR_DRAW_REGION_OUTLINE = (68, 117, 235, 220)
COLOR_OBSTACLE_FILL = (98, 102, 109, 160)
COLOR_OBSTACLE_OUTLINE = (65, 69, 77, 255)
COLOR_EDGE_LINE = (176, 181, 190, 220)
COLOR_PATH_OTHER = (132, 138, 146, 255)
COLOR_PATH_CLEANING = (68, 117, 235, 255)
COLOR_PATH_RETURN = (255, 162, 49, 255)
COLOR_PATH_MAPPING = (255, 196, 0, 255)
COLOR_PATH_MANUAL = (122, 136, 180, 255)
COLOR_PATH_HISTORY = (48, 220, 187, 88)
COLOR_PATH_HISTORY_GLOW = (48, 220, 187, 52)
COLOR_PATH_CURRENT = (18, 191, 143, 132)
COLOR_PATH_CURRENT_GLOW = (18, 191, 143, 78)
COLOR_ORIGIN = (38, 38, 38, 180)

COLOR_ROBOT_BODY = (46, 46, 47, 255)
COLOR_ROBOT_TOP = (208, 211, 214, 255)
COLOR_ROBOT_DETAIL = (169, 174, 179, 255)
COLOR_ROBOT_DIR = (38, 38, 38, 255)

COLOR_STATION_BODY = (45, 45, 45, 255)
COLOR_STATION_TOP = (237, 239, 240, 255)
COLOR_STATION_LED = (51, 255, 92, 255)
COLOR_STATION_BORDER = (190, 194, 197, 255)

COLOR_BADGE_RED = (169, 37, 43, 255)
COLOR_BADGE_BLUE = (68, 117, 235, 255)
COLOR_BADGE_ORANGE = (255, 120, 70, 255)
COLOR_BADGE_GRAY = (108, 114, 124, 255)

COLOR_PLACEHOLDER_BG = (200, 200, 200, 255)
COLOR_HATCH = (255, 120, 70, 88)
BATTERY_STATUS_DP = 108

PATH_POINT_COLORS = {
    "PATH_POINT_TYPE_CLEANING": COLOR_PATH_CLEANING,
    "PATH_POINT_TYPE_RETURN": COLOR_PATH_RETURN,
    "PATH_POINT_TYPE_RESUME": COLOR_PATH_CLEANING,
    "PATH_POINT_TYPE_MOVE": COLOR_PATH_OTHER,
    "PATH_POINT_TYPE_MAPPING": COLOR_PATH_MAPPING,
    "PATH_POINT_TYPE_CROSS_BOUDARY": COLOR_CHANNEL,
    "PATH_POINT_TYPE_SEMI_AUTO_MANUAL_MAPPING": COLOR_PATH_MANUAL,
}

HANDLED_MAP_FIELDS = {
    "id",
    "name",
    "width",
    "height",
    "resolution",
    "origin",
    "has_station",
    "station_pose",
    "regions",
    "obstacles",
    "forbidden_zones",
    "virtual_walls",
    "physical_forbidden_zones",
    "cross_boundary_markers",
    "total_area",
    "map_state",
    "cross_boundary_tunnels",
    "trapped_points",
    "has_bird_view",
    "bird_view_index",
    "clean_info",
    "mow_param",
    "has_backup",
    "required_zones",
    "file_size",
    "virtual_cross_boundary_tunnels",
    "type",
    "pass_through_zones",
    "backup_info_list",
    "map_view_rotate_angle",
    "maintenance_points",
    "is_boundary_locked",
    "enable_advanced_edge_cutting",
    "is_able_to_run_build_map",
}
HANDLED_PATH_FIELDS = {"id", "map_id", "type", "points"}


@lru_cache(maxsize=32)
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载字体。"""
    candidates = [
        (
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ),
        (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for regular_path, bold_path in candidates:
        font_path = bold_path if bold else regular_path
        try:
            return ImageFont.truetype(font_path, size=size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


class CoordinateTransformer:
    """地图坐标 (mm) → 画布像素坐标转换器。"""

    def __init__(
        self,
        points: list[tuple[float, float]],
        rect: tuple[int, int, int, int],
        padding: int = MAP_PADDING,
    ) -> None:
        self.left, self.top, self.right, self.bottom = rect
        self.padding = padding
        self._usable_width = max(1.0, float(self.right - self.left - 2 * padding))
        self._usable_height = max(1.0, float(self.bottom - self.top - 2 * padding))
        self._scale = 1.0
        self._offset_x = float(self.left + padding)
        self._offset_y = float(self.top + padding)

        if not points:
            return

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        range_x = max(1.0, max_x - min_x)
        range_y = max(1.0, max_y - min_y)
        self._scale = min(self._usable_width / range_x, self._usable_height / range_y)
        content_w = range_x * self._scale
        content_h = range_y * self._scale
        self._offset_x = (
            self.left
            + padding
            + (self._usable_width - content_w) / 2
            - min_x * self._scale
        )
        self._offset_y = (
            self.top
            + padding
            + (self._usable_height - content_h) / 2
            - min_y * self._scale
        )

    def to_pixel(self, x: float, y: float) -> tuple[int, int]:
        """转换地图坐标到像素坐标（仅做缩放和平移）。"""
        px = int(round(x * self._scale + self._offset_x))
        py = int(round(y * self._scale + self._offset_y))
        return px, py

    def to_pixels(self, points: list[tuple[float, float]]) -> list[tuple[int, int]]:
        """批量转换坐标。"""
        return [self.to_pixel(point[0], point[1]) for point in points]


def _coerce_float(value: Any) -> float | None:
    """尽量把输入转换为浮点数。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    """尽量把输入转换为整数。"""
    number = _coerce_float(value)
    if number is None:
        return None
    return int(number)


def _point_tuple(obj: Any) -> tuple[float, float] | None:
    """从对象提取 Point。"""
    if not isinstance(obj, dict):
        return None
    x = _coerce_float(obj.get("x"))
    y = _coerce_float(obj.get("y"))
    if x is None or y is None:
        return None
    return (x, y)


def _pose_tuple(obj: Any) -> dict[str, float] | None:
    """从对象提取 Pose。"""
    point = _point_tuple(obj)
    if point is None:
        return None
    theta = _coerce_float(obj.get("theta"))
    yaw = _coerce_float(obj.get("yaw"))
    return {
        "x": point[0],
        "y": point[1],
        "theta": theta if theta is not None else yaw,
    }


def _polygon_points(polygon: dict | None) -> list[tuple[float, float]]:
    """从 Polygon 对象提取点列表。"""
    if not isinstance(polygon, dict):
        return []
    raw = polygon.get("points")
    if not isinstance(raw, list):
        return []
    points: list[tuple[float, float]] = []
    for item in raw:
        point = _point_tuple(item)
        if point is not None:
            points.append(point)
    return points


def _line_points(line: Any) -> list[tuple[float, float]]:
    """从 Line 或任意线性结构提取点列表。"""
    if isinstance(line, dict):
        direct = _polygon_points(line)
        if len(direct) >= 2:
            return direct
        candidates: list[tuple[float, float]] = []
        for key in (
            "start",
            "end",
            "start_point",
            "end_point",
            "point1",
            "point2",
            "from",
            "to",
        ):
            point = _point_tuple(line.get(key))
            if point is not None:
                candidates.append(point)
        if len(candidates) >= 2:
            return candidates
    return _collect_recursive_points(line, limit=8)


def _collect_recursive_points(data: Any, limit: int = 64) -> list[tuple[float, float]]:
    """递归收集任意对象中的点位。"""
    points: list[tuple[float, float]] = []
    stack = [data]
    while stack and len(points) < limit:
        item = stack.pop()
        point = _point_tuple(item)
        if point is not None:
            points.append(point)
        if isinstance(item, dict):
            for value in item.values():
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(item, (list, tuple)):
            for value in item:
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
    return _dedupe_points(points)


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """按坐标去重。"""
    seen: set[tuple[int, int]] = set()
    result: list[tuple[float, float]] = []
    for point in points:
        key = (int(round(point[0] * 1000)), int(round(point[1] * 1000)))
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    return result


def _ellipse_points(ellipse: Any, segments: int = 36) -> list[tuple[float, float]]:
    """把 Ellipse 近似成多边形点集。"""
    if not isinstance(ellipse, dict):
        return []

    center = _point_tuple(ellipse.get("center"))
    if center is None:
        center = _point_tuple(ellipse)
    if center is None:
        points = _collect_recursive_points(ellipse, limit=8)
        center = points[0] if points else None
    if center is None:
        return []

    radius_x = _coerce_float(ellipse.get("radius_x"))
    radius_y = _coerce_float(ellipse.get("radius_y"))
    if radius_x is None:
        radius_x = _coerce_float(ellipse.get("rx"))
    if radius_y is None:
        radius_y = _coerce_float(ellipse.get("ry"))
    if radius_x is None:
        width = _coerce_float(ellipse.get("width"))
        if width is not None:
            radius_x = width / 2
    if radius_y is None:
        height = _coerce_float(ellipse.get("height"))
        if height is not None:
            radius_y = height / 2
    if radius_x is None:
        radius_x = _coerce_float(ellipse.get("major_radius"))
    if radius_y is None:
        radius_y = _coerce_float(ellipse.get("minor_radius"))
    if radius_x is None:
        radius_x = _coerce_float(ellipse.get("a"))
    if radius_y is None:
        radius_y = _coerce_float(ellipse.get("b"))
    if radius_x is None and radius_y is not None:
        radius_x = radius_y
    if radius_y is None and radius_x is not None:
        radius_y = radius_x
    if radius_x is None or radius_y is None or radius_x <= 0 or radius_y <= 0:
        return []

    rotation = _coerce_float(ellipse.get("rotation"))
    if rotation is None:
        rotation = _coerce_float(ellipse.get("angle"))
    if rotation is None:
        rotation = _coerce_float(ellipse.get("theta"))
        if rotation is not None and abs(rotation) > math.pi * 4:
            rotation = rotation / 1000.0
            rotation = math.degrees(rotation)
    rotation_rad = math.radians(rotation or 0.0)
    cos_a = math.cos(rotation_rad)
    sin_a = math.sin(rotation_rad)

    result: list[tuple[float, float]] = []
    cx, cy = center
    for index in range(segments):
        angle = 2 * math.pi * index / segments
        local_x = radius_x * math.cos(angle)
        local_y = radius_y * math.sin(angle)
        point_x = cx + local_x * cos_a - local_y * sin_a
        point_y = cy + local_x * sin_a + local_y * cos_a
        result.append((point_x, point_y))
    return result


def _extract_polygons(item: Any) -> list[list[tuple[float, float]]]:
    """从对象提取多边形列表。"""
    polygons: list[list[tuple[float, float]]] = []
    if not isinstance(item, dict):
        return polygons

    direct = _polygon_points(item)
    if len(direct) >= 3:
        polygons.append(direct)

    for key in ("boundary", "polygon"):
        points = _polygon_points(item.get(key))
        if len(points) >= 3:
            polygons.append(points)

    ellipse = item.get("ellipse")
    ellipse_points = _ellipse_points(ellipse)
    if len(ellipse_points) >= 3:
        polygons.append(ellipse_points)

    return polygons


def _extract_polylines(item: Any) -> list[list[tuple[float, float]]]:
    """从对象提取折线列表。"""
    polylines: list[list[tuple[float, float]]] = []
    if not isinstance(item, dict):
        return polylines
    for key in ("line", "polyline", "center_line"):
        points = _line_points(item.get(key))
        if len(points) >= 2:
            polylines.append(points)
    if not polylines:
        direct = _line_points(item)
        if len(direct) >= 2:
            polylines.append(direct)
    return polylines


def _feature_points(item: Any) -> list[tuple[float, float]]:
    """提取一个空间对象的所有点。"""
    points: list[tuple[float, float]] = []
    for polygon in _extract_polygons(item):
        points.extend(polygon)
    for polyline in _extract_polylines(item):
        points.extend(polyline)
    point = _point_tuple(item)
    if point is not None:
        points.append(point)
    pose = _pose_tuple(item)
    if pose is not None:
        points.append((pose["x"], pose["y"]))
    return _dedupe_points(points)


def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """计算简单中心点。"""
    if not points:
        return None
    x = sum(point[0] for point in points) / len(points)
    y = sum(point[1] for point in points) / len(points)
    return (x, y)


def _extract_marker_points(items: list[Any]) -> list[tuple[float, float]]:
    """从一组对象提取中心点。"""
    markers: list[tuple[float, float]] = []
    for item in items:
        points = _feature_points(item)
        if points:
            marker = _polygon_centroid(points)
            if marker is not None:
                markers.append(marker)
    return _dedupe_points(markers)


def _extract_path_points(path_data: dict) -> list[dict[str, Any]]:
    """从 ha_path_v1 提取 PathPoint 列表。"""
    raw = path_data.get("points")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        position = _point_tuple(item.get("position"))
        if position is None:
            continue
        result.append(
            {
                "x": position[0],
                "y": position[1],
                "type": item.get("type", ""),
            }
        )
    return result


def _path_map_id(path_data: dict[str, Any]) -> int | None:
    """提取路径对应的地图 ID。"""
    if not isinstance(path_data, dict):
        return None
    return _coerce_int(path_data.get("map_id"))


def _path_point_key(point: dict[str, Any]) -> tuple[int, int, str]:
    """生成路径点去重键。"""
    return (
        int(round(point["x"] * 1000)),
        int(round(point["y"] * 1000)),
        str(point.get("type", "")),
    )


def _merge_path_points(
    history_points: list[dict[str, Any]],
    current_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按“历史路径在前，当前路径在后”的方式拼接路径点。"""
    if not history_points:
        return list(current_points)
    if not current_points:
        return list(history_points)
    if _path_point_key(history_points[-1]) == _path_point_key(current_points[0]):
        return [*history_points, *current_points[1:]]
    return [*history_points, *current_points]


def _filter_cleaning_path_points(path_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留割草路径点。"""
    return [point for point in path_points if point.get("type") == "PATH_POINT_TYPE_CLEANING"]


def _pixel_distance(point_a: tuple[int, int], point_b: tuple[int, int]) -> float:
    """计算两个像素点之间的距离。"""
    return math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])


def _point_line_distance(
    point: tuple[int, int],
    line_start: tuple[int, int],
    line_end: tuple[int, int],
) -> float:
    """计算点到线段的垂直距离。"""
    x0, y0 = point
    x1, y1 = line_start
    x2, y2 = line_end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x0 - x1, y0 - y1)
    return abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def _rdp_simplify_pixels(points: list[tuple[int, int]], epsilon: float) -> list[tuple[int, int]]:
    """用 RDP 算法简化像素折线。"""
    if len(points) <= 2:
        return list(points)
    max_distance = 0.0
    max_index = 0
    start = points[0]
    end = points[-1]
    for index in range(1, len(points) - 1):
        distance = _point_line_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            max_index = index
    if max_distance <= epsilon:
        return [start, end]
    left = _rdp_simplify_pixels(points[: max_index + 1], epsilon)
    right = _rdp_simplify_pixels(points[max_index:], epsilon)
    return left[:-1] + right


def _simplify_path_pixels(
    pixels: list[tuple[int, int]],
    epsilon: float,
    min_segment: float,
) -> list[tuple[int, int]]:
    """对路径像素做显示层简化。"""
    if len(pixels) <= 2:
        return list(pixels)

    deduped = [pixels[0]]
    for point in pixels[1:]:
        if point != deduped[-1]:
            deduped.append(point)
    if len(deduped) <= 2:
        return deduped

    simplified = _rdp_simplify_pixels(deduped, epsilon)
    if len(simplified) <= 2:
        return simplified

    filtered = [simplified[0]]
    for point in simplified[1:-1]:
        if _pixel_distance(filtered[-1], point) >= min_segment:
            filtered.append(point)
    if simplified[-1] != filtered[-1]:
        filtered.append(simplified[-1])
    return filtered


def _extract_map_extent(map_data: dict[str, Any]) -> list[tuple[float, float]]:
    """根据 width/height/resolution/origin 推导地图外框。"""
    width = _coerce_float(map_data.get("width"))
    height = _coerce_float(map_data.get("height"))
    resolution = _coerce_float(map_data.get("resolution"))
    origin = _point_tuple(map_data.get("origin"))
    if width is None or height is None or resolution is None or origin is None:
        return []
    origin_x, origin_y = origin
    max_x = origin_x + width * resolution
    max_y = origin_y + height * resolution
    return [
        (origin_x, origin_y),
        (max_x, origin_y),
        (max_x, max_y),
        (origin_x, max_y),
    ]


def _extract_all_map_points(map_data: dict) -> list[tuple[float, float]]:
    """收集地图中的所有已知坐标点。"""
    points: list[tuple[float, float]] = []
    points.extend(_extract_map_extent(map_data))

    for region in map_data.get("regions", []):
        points.extend(_feature_points(region))
        for sub_region in region.get("sub_regions", []):
            points.extend(_feature_points(sub_region))
            for inner in sub_region.get("inner_boundarys", []):
                points.extend(_polygon_points(inner))
        for obstacle in region.get("obstacles", []):
            points.extend(_feature_points(obstacle))

    for key in (
        "forbidden_zones",
        "physical_forbidden_zones",
        "required_zones",
        "pass_through_zones",
        "obstacles",
    ):
        for item in map_data.get(key, []):
            points.extend(_feature_points(item))

    for key in ("virtual_walls", "cross_boundary_tunnels", "virtual_cross_boundary_tunnels"):
        for item in map_data.get(key, []):
            points.extend(_feature_points(item))

    for key in ("cross_boundary_markers", "trapped_points", "maintenance_points"):
        points.extend(_extract_marker_points(map_data.get(key, [])))

    station_pose = _pose_tuple(map_data.get("station_pose"))
    if station_pose is not None:
        points.append((station_pose["x"], station_pose["y"]))

    clean_info = map_data.get("clean_info", {})
    if isinstance(clean_info, dict):
        draw_region = clean_info.get("draw_region", {})
        if isinstance(draw_region, dict):
            for polygon in draw_region.get("regions", []):
                points.extend(_polygon_points(polygon))
        move_info = clean_info.get("move_to_target_point", {})
        if isinstance(move_info, dict):
            target_point = _point_tuple(move_info.get("target_point"))
            if target_point is not None:
                points.append(target_point)

    return _dedupe_points(points)


def _enum_label(value: Any) -> str:
    """把枚举字符串转换成更短的可读文本。"""
    if not isinstance(value, str) or not value:
        return "-"
    replacements = {
        "MAP_CLEAN_INFO_MODE_": "",
        "MAP_STATE_": "",
        "NAVIGATION_PATH_TYPE_": "",
        "PATH_POINT_TYPE_": "",
        "MAP_TYPE_": "",
        "HIGH_GRASS_EDGE_TRIM_": "",
        "MOW_SPEED_TYPE_": "",
        "BLADE_DISK_SPEED_TYPE_": "",
        "MAIN_DIRECTION_MODE_": "",
    }
    text = value
    for prefix, replacement in replacements.items():
        if text.startswith(prefix):
            text = replacement + text[len(prefix):]
            break
    return text.replace("_", " ").title()


def _truncate(text: str, max_length: int) -> str:
    """截断字符串。"""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def _format_area(total_area_tenths: Any) -> str:
    """格式化面积。"""
    area = _coerce_float(total_area_tenths)
    if area is None:
        return "-"
    return f"{area / 10:.1f}㎡"


def _format_file_size(value: Any) -> str:
    """格式化文件大小。"""
    size = _coerce_float(value)
    if size is None:
        return "-"
    units = ["B", "KB", "MB", "GB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)}{units[index]}"
    return f"{size:.1f}{units[index]}"


def _format_point(point: tuple[float, float] | None) -> str:
    """格式化点位。"""
    if point is None:
        return "-"
    return f"{int(round(point[0]))}, {int(round(point[1]))}"


def _format_size(map_data: dict[str, Any]) -> str:
    """格式化尺寸信息。"""
    width = _coerce_int(map_data.get("width"))
    height = _coerce_int(map_data.get("height"))
    resolution = _coerce_int(map_data.get("resolution"))
    if width is None or height is None or resolution is None:
        return "-"
    return f"{width}×{height} @ {resolution}mm"


def _coerce_angle_radians(value: Any, milli_radian: bool = False) -> float | None:
    """把角度转换成弧度。"""
    number = _coerce_float(value)
    if number is None:
        return None
    if milli_radian:
        return number / 1000.0
    return number


def _normalize_angle_radians(value: float) -> float:
    """把弧度归一化到 [-pi, pi)。"""
    return math.atan2(math.sin(value), math.cos(value))


def _render_placeholder(text: str = "Waiting for map data...") -> bytes:
    """生成占位图。"""
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), COLOR_PLACEHOLDER_BG[:3])
    draw = ImageDraw.Draw(image)
    title_font = _load_font(28, bold=True)
    text_font = _load_font(18)
    title = "TerraMow Map"
    title_box = draw.textbbox((0, 0), title, font=title_font)
    text_box = draw.textbbox((0, 0), text, font=text_font)
    title_w = title_box[2] - title_box[0]
    title_h = title_box[3] - title_box[1]
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    center_x = IMAGE_WIDTH / 2
    center_y = IMAGE_HEIGHT / 2
    draw.text(
        (center_x - title_w / 2, center_y - title_h - 8),
        title,
        fill=COLOR_TEXT,
        font=title_font,
    )
    draw.text(
        (center_x - text_w / 2, center_y + 8),
        text,
        fill=COLOR_TEXT_SUBTLE,
        font=text_font,
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TerraMowMapCamera(Camera):
    """地图摄像头实体。"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:map"

    def __init__(
        self,
        basic_data: TerraMowBasicData,
        hass: HomeAssistant,
        *,
        clean_mode: bool = False,
    ) -> None:
        super().__init__()
        self.basic_data = basic_data
        self.host = basic_data.host
        self.hass = hass
        self._clean_mode = clean_mode
        self._attr_translation_key = "map_camera_clean" if clean_mode else "map_camera"
        self._map_rect: tuple[int, int, int, int] = (
            (0, 0, IMAGE_WIDTH, IMAGE_HEIGHT) if clean_mode else MAP_RECT
        )

        self._map_data: dict[str, Any] = {}
        self._path_data: dict[str, Any] = {}
        self._history_path_data: dict[str, Any] = {}
        self._pose: dict[str, Any] = {}

        self._static_image: Image.Image | None = None
        self._transformer: CoordinateTransformer | None = None
        self._cached_png: bytes | None = None
        self._last_pose_state_update = 0.0
        self._render_metadata: dict[str, Any] = {}
        self._map_data_logged = False
        self._path_data_logged = False
        self._history_path_data_logged = False

        lawn_mower = basic_data.lawn_mower
        if lawn_mower:
            lawn_mower.register_map_callback(self._on_map_info)
            lawn_mower.register_path_callback(self._on_path_data)
            lawn_mower.register_history_path_callback(self._on_history_path_data)
            lawn_mower.register_pose_callback(self._on_pose)
            lawn_mower.register_callback(BATTERY_STATUS_DP, self._on_battery_status)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={("TerraMowLawnMower", self.basic_data.host)},
            name="TerraMow",
            manufacturer="TerraMow",
            model=self.basic_data.lawn_mower.device_model,
        )

    @property
    def unique_id(self) -> str:
        suffix = "map_camera_clean" if self._clean_mode else "map_camera"
        return f"lawn_mower.terramow@{self.host}.{suffix}"

    @property
    def available(self) -> bool:
        return self.basic_data.lawn_mower is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回渲染元信息。"""
        attributes = dict(self._render_metadata)
        robot_state = self._get_display_robot_state()
        rendered_layers = list(attributes.get("rendered_layers", []))
        if robot_state["display_pose"] is not None and "robot" not in rendered_layers:
            rendered_layers.append("robot")
        attributes["rendered_layers"] = rendered_layers
        attributes["robot_pose_source"] = robot_state["source"]
        attributes["live_pose_valid"] = robot_state["live_pose_valid"]
        attributes["battery_connected"] = robot_state["battery_connected"]
        if robot_state["display_pose"] is not None:
            attributes["display_pose"] = robot_state["display_pose"]
        if self._pose:
            attributes["current_pose"] = {
                "x": self._pose.get("x"),
                "y": self._pose.get("y"),
                "yaw": self._pose.get("yaw"),
                "timestamp_ms": self._pose.get("timestamp_ms"),
                "frame": self._pose.get("frame"),
            }
        return attributes

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(self._render_final_image)

    async def _on_map_info(self, map_info: dict[str, Any]) -> None:
        """地图信息更新回调。"""
        lawn_mower = self.basic_data.lawn_mower
        if lawn_mower:
            self._map_data = lawn_mower.map_data or {}
        if not self._map_data_logged and self._map_data:
            _LOGGER.debug("ha_map_v1 top-level keys: %s", list(self._map_data.keys()))
            self._map_data_logged = True
        await self.hass.async_add_executor_job(self._rebuild_static_image)
        self._cached_png = None
        self.async_write_ha_state()

    async def _on_path_data(self, path_data: dict[str, Any]) -> None:
        """路径数据更新回调。"""
        self._path_data = path_data
        if not self._path_data_logged and path_data:
            _LOGGER.debug(
                "ha_path_v1 top-level keys: %s",
                list(path_data.keys()) if isinstance(path_data, dict) else type(path_data),
            )
            self._path_data_logged = True
        await self.hass.async_add_executor_job(self._rebuild_static_image)
        self._cached_png = None
        self.async_write_ha_state()

    async def _on_history_path_data(self, path_data: dict[str, Any]) -> None:
        """历史路径数据更新回调。"""
        self._history_path_data = path_data
        if not self._history_path_data_logged and path_data:
            _LOGGER.debug(
                "ha_path_v1 history top-level keys: %s",
                list(path_data.keys()) if isinstance(path_data, dict) else type(path_data),
            )
            self._history_path_data_logged = True
        await self.hass.async_add_executor_job(self._rebuild_static_image)
        self._cached_png = None
        self.async_write_ha_state()

    async def _on_pose(self, pose: dict[str, Any]) -> None:
        """姿态更新回调。"""
        self._pose = pose
        self._cached_png = None
        now = time.monotonic()
        if now - self._last_pose_state_update >= 2.0:
            self._last_pose_state_update = now
            self.async_write_ha_state()

    async def _on_battery_status(self, _payload: str) -> None:
        """电池状态更新后清理机器人图层缓存。"""
        self._cached_png = None
        self.async_write_ha_state()

    def _get_battery_connected(self) -> bool | None:
        """读取当前是否已连接充电器。"""
        lawn_mower = self.basic_data.lawn_mower
        if lawn_mower is None:
            return None
        battery_status = lawn_mower.battery_status
        if not isinstance(battery_status, dict):
            return None
        connected = battery_status.get("charger_connected")
        if connected is None:
            return None
        return bool(connected)

    def _get_live_robot_pose(self) -> dict[str, Any] | None:
        """解析实时 pose，并标记是否为全 0 无效姿态。"""
        if not isinstance(self._pose, dict) or not self._pose:
            return None
        x = _coerce_float(self._pose.get("x"))
        y = _coerce_float(self._pose.get("y"))
        raw_yaw = _coerce_float(self._pose.get("yaw"))
        if x is None or y is None:
            return None
        return {
            "x": x,
            "y": y,
            "yaw": raw_yaw,
            "is_zero": raw_yaw is not None and x == 0.0 and y == 0.0 and raw_yaw == 0.0,
        }

    def _get_display_robot_state(self) -> dict[str, Any]:
        """决定地图上最终显示的机器人姿态。"""
        battery_connected = self._get_battery_connected()
        live_pose = self._get_live_robot_pose()
        if live_pose is not None and not live_pose["is_zero"]:
            return {
                "source": "live_pose",
                "live_pose_valid": True,
                "battery_connected": battery_connected,
                "display_pose": {
                    "x": live_pose["x"],
                    "y": live_pose["y"],
                    "yaw": _coerce_angle_radians(live_pose["yaw"]),
                },
            }

        station_pose = _pose_tuple(self._map_data.get("station_pose"))
        if live_pose is not None and live_pose["is_zero"] and battery_connected is True and station_pose is not None:
            station_theta = _coerce_angle_radians(station_pose.get("theta"), milli_radian=True)
            robot_yaw = None
            if station_theta is not None:
                robot_yaw = _normalize_angle_radians(station_theta + math.pi)
            return {
                "source": "dock_fallback",
                "live_pose_valid": False,
                "battery_connected": battery_connected,
                "display_pose": {
                    "x": station_pose["x"],
                    "y": station_pose["y"],
                    "yaw": robot_yaw,
                },
            }

        return {
            "source": "unavailable",
            "live_pose_valid": False,
            "battery_connected": battery_connected,
            "display_pose": None,
        }

    def _build_scene(self) -> dict[str, Any]:
        """把原始协议数据整理成可绘制的场景。"""
        map_data = self._map_data if isinstance(self._map_data, dict) else {}
        path_data = self._path_data if isinstance(self._path_data, dict) else {}
        history_path_data = self._history_path_data if isinstance(self._history_path_data, dict) else {}
        clean_info = map_data.get("clean_info", {})
        mow_param = map_data.get("mow_param", {})
        current_map_id = _coerce_int(map_data.get("id"))
        raw_current_path_points = _extract_path_points(path_data)
        raw_history_path_points = _extract_path_points(history_path_data)
        current_path_points = _filter_cleaning_path_points(raw_current_path_points)
        history_path_points = _filter_cleaning_path_points(raw_history_path_points)
        current_path_map_id = _path_map_id(path_data)
        history_path_map_id = _path_map_id(history_path_data)
        target_map_id = current_map_id
        if target_map_id is None:
            if current_path_points and current_path_map_id is not None:
                target_map_id = current_path_map_id
            elif history_path_points and history_path_map_id is not None:
                target_map_id = history_path_map_id

        path_map_mismatch = False
        if target_map_id is not None and current_path_map_id is not None and current_path_map_id != target_map_id:
            current_path_points = []
            path_map_mismatch = True
        if target_map_id is not None and history_path_map_id is not None and history_path_map_id != target_map_id:
            history_path_points = []
            path_map_mismatch = True

        combined_path_points = _merge_path_points(history_path_points, current_path_points)
        display_path_data = path_data if current_path_points else history_path_data if history_path_points else path_data
        selected_ids: set[int] = set()
        if isinstance(clean_info, dict):
            select_region = clean_info.get("select_region", {})
            if isinstance(select_region, dict):
                for region_id in select_region.get("region_id", []):
                    integer = _coerce_int(region_id)
                    if integer is not None:
                        selected_ids.add(integer)

        region_param_ids: set[int] = set()
        if isinstance(mow_param, dict):
            for item in mow_param.get("regions", []):
                if not isinstance(item, dict):
                    continue
                region_id = _coerce_int(item.get("id"))
                if region_id is not None:
                    region_param_ids.add(region_id)

        scene: dict[str, Any] = {
            "rotation_deg": _coerce_float(map_data.get("map_view_rotate_angle")) or 0.0,
            "map_extent": _extract_map_extent(map_data),
            "origin": _point_tuple(map_data.get("origin")),
            "station_pose": _pose_tuple(map_data.get("station_pose")),
            "path_points": combined_path_points,
            "current_path_points": current_path_points,
            "history_path_points": history_path_points,
            "filtered_non_cleaning_point_count": {
                "current": len(raw_current_path_points) - len(current_path_points),
                "history": len(raw_history_path_points) - len(history_path_points),
            },
            "path_display_id": display_path_data.get("id"),
            "path_display_type": display_path_data.get("type"),
            "path_map_mismatch": path_map_mismatch,
            "regions": [],
            "forbidden_zones": [],
            "physical_forbidden_zones": [],
            "pass_through_zones": [],
            "required_zones": [],
            "obstacles": [],
            "virtual_walls": [],
            "cross_boundary_tunnels": [],
            "virtual_cross_boundary_tunnels": [],
            "cross_boundary_markers": _extract_marker_points(map_data.get("cross_boundary_markers", [])),
            "trapped_points": _extract_marker_points(map_data.get("trapped_points", [])),
            "maintenance_points": _extract_marker_points(map_data.get("maintenance_points", [])),
            "draw_region_polygons": [],
            "move_target_point": None,
        }

        all_points: list[tuple[float, float]] = []
        all_points.extend(scene["map_extent"])

        if scene["origin"] is not None:
            all_points.append(scene["origin"])
        if scene["station_pose"] is not None:
            all_points.append((scene["station_pose"]["x"], scene["station_pose"]["y"]))

        for region in map_data.get("regions", []):
            if not isinstance(region, dict):
                continue
            region_boundary = _polygon_points(region.get("boundary"))
            region_record = {
                "id": _coerce_int(region.get("id")),
                "name": region.get("name"),
                "boundary": region_boundary,
                "sub_regions": [],
                "edge_lines": [],
            }
            all_points.extend(region_boundary)

            for edge_segment in region.get("edge_segments", []):
                edge_line = _line_points(edge_segment)
                if len(edge_line) >= 2:
                    region_record["edge_lines"].append(edge_line)
                    all_points.extend(edge_line)

            for obstacle in region.get("obstacles", []):
                obstacle_polygons = _extract_polygons(obstacle)
                for polygon in obstacle_polygons:
                    scene["obstacles"].append(polygon)
                    all_points.extend(polygon)

            for sub_region in region.get("sub_regions", []):
                if not isinstance(sub_region, dict):
                    continue
                sub_boundary = _polygon_points(sub_region.get("boundary"))
                inner_boundaries: list[list[tuple[float, float]]] = []
                for inner in sub_region.get("inner_boundarys", []):
                    points = _polygon_points(inner)
                    if len(points) >= 3:
                        inner_boundaries.append(points)
                        all_points.extend(points)

                edge_lines: list[list[tuple[float, float]]] = []
                for key in ("edge_segments", "boudary_polyline_descriptions"):
                    for edge_segment in sub_region.get(key, []):
                        points = _line_points(edge_segment)
                        if len(points) >= 2:
                            edge_lines.append(points)
                            all_points.extend(points)

                center = _point_tuple(sub_region.get("center"))
                if center is None and sub_boundary:
                    center = _polygon_centroid(sub_boundary)
                sub_id = _coerce_int(sub_region.get("id"))
                selected = bool(sub_region.get("is_selected_for_mow")) or (
                    sub_id in selected_ids if sub_id is not None else False
                )
                region_record["sub_regions"].append(
                    {
                        "id": sub_id,
                        "name": sub_region.get("name"),
                        "boundary": sub_boundary,
                        "center": center,
                        "selected": selected,
                        "order": _coerce_int(sub_region.get("selected_for_mow_order")),
                        "has_custom_param": sub_id in region_param_ids if sub_id is not None else False,
                        "inner_boundaries": inner_boundaries,
                        "edge_lines": edge_lines,
                    }
                )
                all_points.extend(sub_boundary)
                if center is not None:
                    all_points.append(center)

            scene["regions"].append(region_record)

        for key in ("forbidden_zones", "physical_forbidden_zones", "pass_through_zones", "required_zones"):
            for item in map_data.get(key, []):
                for polygon in _extract_polygons(item):
                    scene[key].append(polygon)
                    all_points.extend(polygon)

        for obstacle in map_data.get("obstacles", []):
            for polygon in _extract_polygons(obstacle):
                scene["obstacles"].append(polygon)
                all_points.extend(polygon)

        for wall in map_data.get("virtual_walls", []):
            for line in _extract_polylines(wall):
                scene["virtual_walls"].append(line)
                all_points.extend(line)

        for key in ("cross_boundary_tunnels", "virtual_cross_boundary_tunnels"):
            for item in map_data.get(key, []):
                polygons = _extract_polygons(item)
                polylines = _extract_polylines(item)
                scene[key].append({"polygons": polygons, "polylines": polylines})
                for polygon in polygons:
                    all_points.extend(polygon)
                for polyline in polylines:
                    all_points.extend(polyline)

        if isinstance(clean_info, dict):
            draw_region = clean_info.get("draw_region", {})
            if isinstance(draw_region, dict):
                for polygon in draw_region.get("regions", []):
                    points = _polygon_points(polygon)
                    if len(points) >= 3:
                        scene["draw_region_polygons"].append(points)
                        all_points.extend(points)
            move_to_target = clean_info.get("move_to_target_point", {})
            if isinstance(move_to_target, dict):
                scene["move_target_point"] = _point_tuple(move_to_target.get("target_point"))
                if scene["move_target_point"] is not None:
                    all_points.append(scene["move_target_point"])

        for path_point in scene["path_points"]:
            all_points.append((path_point["x"], path_point["y"]))

        scene["all_points"] = _dedupe_points(all_points)
        scene["scene_counts"] = {
            "regions": len(scene["regions"]),
            "sub_regions": sum(len(region["sub_regions"]) for region in scene["regions"]),
            "forbidden_zones": len(scene["forbidden_zones"]),
            "physical_forbidden_zones": len(scene["physical_forbidden_zones"]),
            "pass_through_zones": len(scene["pass_through_zones"]),
            "required_zones": len(scene["required_zones"]),
            "obstacles": len(scene["obstacles"]),
            "virtual_walls": len(scene["virtual_walls"]),
            "cross_boundary_tunnels": len(scene["cross_boundary_tunnels"]),
            "virtual_cross_boundary_tunnels": len(scene["virtual_cross_boundary_tunnels"]),
            "cross_boundary_markers": len(scene["cross_boundary_markers"]),
            "trapped_points": len(scene["trapped_points"]),
            "maintenance_points": len(scene["maintenance_points"]),
            "path_points": len(scene["path_points"]),
            "current_path_points": len(scene["current_path_points"]),
            "history_path_points": len(scene["history_path_points"]),
            "filtered_non_cleaning_path_points": (
                scene["filtered_non_cleaning_point_count"]["current"]
                + scene["filtered_non_cleaning_point_count"]["history"]
            ),
        }
        scene["rendered_layers"] = [
            "map_extent",
            "regions",
            "sub_regions",
            "pass_through_zones",
            "required_zones",
            "forbidden_zones",
            "physical_forbidden_zones",
            "obstacles",
            "virtual_walls",
            "cross_boundary_tunnels",
            "virtual_cross_boundary_tunnels",
            "cross_boundary_markers",
            "trapped_points",
            "maintenance_points",
            "path",
            "station_pose",
            "move_target",
            "summary_hud",
        ]
        return scene

    def _build_render_metadata(self, scene: dict[str, Any]) -> dict[str, Any]:
        """构建实体 attributes。"""
        map_data = self._map_data if isinstance(self._map_data, dict) else {}
        path_data = self._path_data if isinstance(self._path_data, dict) else {}
        history_path_data = self._history_path_data if isinstance(self._history_path_data, dict) else {}
        clean_info = map_data.get("clean_info", {})
        mow_param = map_data.get("mow_param", {})
        backup_info = map_data.get("backup_info_list", [])

        if isinstance(clean_info, dict):
            clean_summary = {
                "mode": clean_info.get("mode"),
                "selected_region_count": len(
                    clean_info.get("select_region", {}).get("region_id", [])
                )
                if isinstance(clean_info.get("select_region"), dict)
                else 0,
                "draw_region_count": len(clean_info.get("draw_region", {}).get("regions", []))
                if isinstance(clean_info.get("draw_region"), dict)
                else 0,
                "has_target_point": bool(
                    isinstance(clean_info.get("move_to_target_point"), dict)
                    and clean_info["move_to_target_point"].get("target_point")
                ),
            }
        else:
            clean_summary = {}

        if isinstance(mow_param, dict):
            global_param = mow_param.get("global_param", {})
            mow_summary = {
                "region_param_count": len(mow_param.get("regions", []))
                if isinstance(mow_param.get("regions"), list)
                else 0,
                "mow_height": global_param.get("mow_height")
                if isinstance(global_param, dict)
                else None,
                "mow_speed": global_param.get("mow_speed")
                if isinstance(global_param, dict)
                else None,
                "main_direction_angle": (
                    global_param.get("main_direction_angle_config", {}).get("current_angle")
                    if isinstance(global_param, dict)
                    and isinstance(global_param.get("main_direction_angle_config"), dict)
                    else None
                ),
                "enable_thorough_corner_cutting": mow_param.get(
                    "enable_thorough_corner_cutting"
                ),
                "high_grass_edge_trim_mode": (
                    mow_param.get("high_grass_edge_trim_mode", {}).get("mode")
                    if isinstance(mow_param.get("high_grass_edge_trim_mode"), dict)
                    else None
                ),
            }
        else:
            mow_summary = {}

        if isinstance(backup_info, list):
            backup_summary = {
                "has_backup": map_data.get("has_backup", False),
                "backup_count": len(backup_info),
                "file_size": map_data.get("file_size"),
            }
        else:
            backup_summary = {}

        return {
            "present_top_level_fields": {
                "map": sorted(map_data.keys()),
                "path": {
                    "current": sorted(path_data.keys()),
                    "history": sorted(history_path_data.keys()),
                },
            },
            "scene_counts": scene.get("scene_counts", {}),
            "rendered_layers": scene.get("rendered_layers", []),
            "unrendered_fields": {
                "map": sorted(set(map_data.keys()) - HANDLED_MAP_FIELDS),
                "path": {
                    "current": sorted(set(path_data.keys()) - HANDLED_PATH_FIELDS),
                    "history": sorted(set(history_path_data.keys()) - HANDLED_PATH_FIELDS),
                },
            },
            "clean_info_summary": clean_summary,
            "mow_param_summary": mow_summary,
            "backup_summary": backup_summary,
            "path_summary": {
                "id": scene.get("path_display_id"),
                "map_id": path_data.get("map_id") if scene.get("current_path_points") else history_path_data.get("map_id"),
                "type": scene.get("path_display_type"),
                "point_count": len(scene.get("path_points", [])),
            },
            "current_path_summary": {
                "id": path_data.get("id"),
                "map_id": path_data.get("map_id"),
                "type": path_data.get("type"),
                "point_count": len(scene.get("current_path_points", [])),
            },
            "history_path_summary": {
                "id": history_path_data.get("id"),
                "map_id": history_path_data.get("map_id"),
                "type": history_path_data.get("type"),
                "point_count": len(scene.get("history_path_points", [])),
            },
            "combined_path_summary": {
                "point_count": len(scene.get("path_points", [])),
                "history_path_available": bool(history_path_data),
                "path_map_mismatch": scene.get("path_map_mismatch", False),
            },
            "filtered_non_cleaning_point_count": scene.get("filtered_non_cleaning_point_count", {}),
            "rotation_angle": scene.get("rotation_deg", 0.0),
            "map_name": map_data.get("name"),
            "map_state": map_data.get("map_state"),
        }

    def _rebuild_static_image(self) -> None:
        """重建静态图层。"""
        scene = self._build_scene()
        self._render_metadata = self._build_render_metadata(scene)

        if not self._map_data and not self._path_data and not self._history_path_data:
            self._static_image = None
            self._transformer = None
            return

        bg_color = (0, 0, 0, 0) if self._clean_mode else COLOR_APP_BG
        image = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), bg_color)
        if not self._clean_mode:
            self._draw_background(image)

        if scene["all_points"]:
            self._transformer = CoordinateTransformer(
                scene["all_points"],
                self._map_rect,
                padding=0 if self._clean_mode else MAP_PADDING,
            )
            self._draw_scene(image, scene)
        else:
            self._transformer = None
            self._draw_empty_map_card(image, scene)

        if not self._clean_mode:
            self._draw_summary_panel(image, scene)
        self._static_image = image

    def _draw_background(self, image: Image.Image) -> None:
        """绘制画布底色和卡片。"""
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rounded_rectangle(MAP_RECT, radius=MAP_RADIUS, fill=COLOR_MAP_BG, outline=COLOR_CARD_BORDER)
        draw.rounded_rectangle(
            (MAP_RECT[0], MAP_RECT[1] + 10, MAP_RECT[2], MAP_RECT[3] + 10),
            radius=MAP_RADIUS,
            fill=COLOR_SHADOW,
        )
        draw.rounded_rectangle(MAP_RECT, radius=MAP_RADIUS, fill=COLOR_MAP_BG)
        draw.rounded_rectangle(
            (SUMMARY_RECT[0], SUMMARY_RECT[1] + 10, SUMMARY_RECT[2], SUMMARY_RECT[3] + 10),
            radius=CARD_RADIUS,
            fill=COLOR_SHADOW,
        )
        draw.rounded_rectangle(SUMMARY_RECT, radius=CARD_RADIUS, fill=COLOR_CARD_BG)

    def _draw_empty_map_card(self, image: Image.Image, scene: dict[str, Any]) -> None:
        """没有空间数据时的空地图。"""
        draw = ImageDraw.Draw(image, "RGBA")
        title_font = _load_font(28, bold=True)
        body_font = _load_font(18)
        title = self._map_data.get("name") or "TerraMow Map"
        subtitle = "地图元数据已收到，但没有可绘制的空间点"
        title_box = draw.textbbox((0, 0), title, font=title_font)
        body_box = draw.textbbox((0, 0), subtitle, font=body_font)
        center_x = (self._map_rect[0] + self._map_rect[2]) / 2
        center_y = (self._map_rect[1] + self._map_rect[3]) / 2
        draw.text(
            (center_x - (title_box[2] - title_box[0]) / 2, center_y - 24),
            title,
            fill=COLOR_TEXT,
            font=title_font,
        )
        draw.text(
            (center_x - (body_box[2] - body_box[0]) / 2, center_y + 12),
            subtitle,
            fill=COLOR_TEXT_SUBTLE,
            font=body_font,
        )
        if not self._clean_mode:
            self._draw_map_chips(draw, scene)

    def _draw_scene(self, image: Image.Image, scene: dict[str, Any]) -> None:
        """绘制完整场景。"""
        draw = ImageDraw.Draw(image, "RGBA")
        transformer = self._transformer
        if transformer is None:
            return

        if scene["map_extent"]:
            pixels = transformer.to_pixels(scene["map_extent"])
            draw.polygon(
                pixels,
                fill=COLOR_MAP_DEFAULT_FILL,
                outline=COLOR_MAP_DEFAULT_OUTLINE,
            )

        for region in scene["regions"]:
            for sub_region in region["sub_regions"]:
                boundary = sub_region["boundary"]
                if len(boundary) < 3:
                    continue
                pixels = transformer.to_pixels(boundary)
                fill = COLOR_REQUIRED_FILL if sub_region["selected"] else COLOR_MAP_DEFAULT_FILL
                outline = (
                    COLOR_REQUIRED_OUTLINE if sub_region["selected"] else COLOR_MAP_DEFAULT_OUTLINE
                )
                self._draw_polygon_pixels(image, draw, pixels, fill, outline, 1)
                for inner in sub_region["inner_boundaries"]:
                    inner_pixels = transformer.to_pixels(inner)
                    draw.polygon(
                        inner_pixels,
                        fill=COLOR_MAP_BG,
                        outline=COLOR_MAP_DEFAULT_OUTLINE,
                    )
                for edge_line in sub_region["edge_lines"]:
                    self._draw_polyline(draw, transformer, edge_line, COLOR_EDGE_LINE, 2)
                center = sub_region["center"]
                if center is not None and sub_region["order"] and sub_region["order"] > 0:
                    self._draw_order_badge(draw, transformer.to_pixel(center[0], center[1]), sub_region["order"])
                if center is not None and sub_region["has_custom_param"]:
                    center_px = transformer.to_pixel(center[0], center[1])
                    draw.ellipse(
                        [center_px[0] + 12, center_px[1] - 18, center_px[0] + 22, center_px[1] - 8],
                        fill=COLOR_PASS_THROUGH_OUTLINE,
                        outline=COLOR_TEXT_WHITE,
                        width=2,
                    )

            if len(region["boundary"]) >= 3:
                pixels = transformer.to_pixels(region["boundary"])
                draw.line(pixels + [pixels[0]], fill=COLOR_MAP_DEFAULT_OUTLINE, width=2)
            for edge_line in region["edge_lines"]:
                self._draw_polyline(draw, transformer, edge_line, COLOR_EDGE_LINE, 2)

        self._draw_path(image, scene)

        for polygon in scene["required_zones"]:
            self._draw_polygon(image, draw, transformer, polygon, COLOR_REQUIRED_FILL, COLOR_REQUIRED_OUTLINE, 3)

        for polygon in scene["pass_through_zones"]:
            self._draw_polygon(
                image,
                draw,
                transformer,
                polygon,
                COLOR_PASS_THROUGH_FILL,
                COLOR_PASS_THROUGH_OUTLINE,
                3,
            )

        for polygon in scene["forbidden_zones"]:
            self._draw_polygon(
                image,
                draw,
                transformer,
                polygon,
                COLOR_RESTRICTED_FILL,
                COLOR_RESTRICTED_OUTLINE,
                3,
            )

        for polygon in scene["physical_forbidden_zones"]:
            self._draw_polygon(
                image,
                draw,
                transformer,
                polygon,
                COLOR_RESTRICTED_FILL,
                COLOR_RESTRICTED_OUTLINE,
                4,
            )
            self._apply_hatch(image, transformer.to_pixels(polygon), COLOR_HATCH, spacing=12)

        for polygon in scene["obstacles"]:
            self._draw_polygon(
                image,
                draw,
                transformer,
                polygon,
                COLOR_OBSTACLE_FILL,
                COLOR_OBSTACLE_OUTLINE,
                2,
            )

        for polygon in scene["draw_region_polygons"]:
            pixels = transformer.to_pixels(polygon)
            self._composite_polygon_fill(image, pixels, COLOR_DRAW_REGION_FILL)
            self._draw_dashed_polyline(draw, pixels + [pixels[0]], COLOR_DRAW_REGION_OUTLINE, 3, 12, 8)

        for wall in scene["virtual_walls"]:
            pixels = transformer.to_pixels(wall)
            self._draw_dashed_polyline(draw, pixels, COLOR_RESTRICTED_OUTLINE, 4, 12, 8)

        for tunnel in scene["cross_boundary_tunnels"]:
            self._draw_tunnel(image, draw, transformer, tunnel, COLOR_CHANNEL_SOFT, COLOR_CHANNEL)
        for tunnel in scene["virtual_cross_boundary_tunnels"]:
            self._draw_tunnel(image, draw, transformer, tunnel, COLOR_CHANNEL_SOFT, COLOR_CHANNEL)

        for marker in scene["cross_boundary_markers"]:
            self._draw_marker(draw, transformer.to_pixel(marker[0], marker[1]), COLOR_CHANNEL, "diamond")
        for marker in scene["trapped_points"]:
            self._draw_marker(draw, transformer.to_pixel(marker[0], marker[1]), COLOR_BADGE_ORANGE, "triangle")
        for marker in scene["maintenance_points"]:
            self._draw_marker(draw, transformer.to_pixel(marker[0], marker[1]), COLOR_BADGE_BLUE, "hex")

        if scene["move_target_point"] is not None:
            self._draw_target(draw, transformer.to_pixel(scene["move_target_point"][0], scene["move_target_point"][1]))

        if scene["station_pose"] is not None:
            self._draw_station(draw, scene["station_pose"])

        if scene["origin"] is not None:
            self._draw_origin(draw, transformer.to_pixel(scene["origin"][0], scene["origin"][1]))

        if not self._clean_mode:
            self._draw_map_chips(draw, scene)

    def _composite_draw(
        self,
        image: Image.Image,
        draw_fn: Any,
    ) -> None:
        """在透明图层上绘制后再与主图合成。"""
        overlay = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")
        draw_fn(overlay_draw)
        image.alpha_composite(overlay)

    def _composite_polygon_fill(
        self,
        image: Image.Image,
        polygon_pixels: list[tuple[int, int]],
        fill: tuple[int, int, int, int],
    ) -> None:
        """对多边形填充做真正的 alpha 合成。"""
        self._composite_draw(image, lambda overlay_draw: overlay_draw.polygon(polygon_pixels, fill=fill))

    def _draw_polygon_pixels(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        pixels: list[tuple[int, int]],
        fill: tuple[int, int, int, int],
        outline: tuple[int, int, int, int],
        width: int,
    ) -> None:
        """按像素点绘制多边形，填充单独合成，描边直接绘制。"""
        if len(pixels) < 3:
            return
        if fill[3] > 0:
            self._composite_polygon_fill(image, pixels, fill)
        draw.line(pixels + [pixels[0]], fill=outline, width=max(1, width))

    def _draw_polygon(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        transformer: CoordinateTransformer,
        polygon: list[tuple[float, float]],
        fill: tuple[int, int, int, int],
        outline: tuple[int, int, int, int],
        width: int,
    ) -> None:
        """绘制面。"""
        if len(polygon) < 3:
            return
        pixels = transformer.to_pixels(polygon)
        self._draw_polygon_pixels(image, draw, pixels, fill, outline, width)

    def _draw_polyline(
        self,
        draw: ImageDraw.ImageDraw,
        transformer: CoordinateTransformer,
        polyline: list[tuple[float, float]],
        color: tuple[int, int, int, int],
        width: int,
    ) -> None:
        """绘制折线。"""
        if len(polyline) < 2:
            return
        draw.line(transformer.to_pixels(polyline), fill=color, width=width)

    def _draw_dashed_polyline(
        self,
        draw: ImageDraw.ImageDraw,
        points: list[tuple[int, int]],
        color: tuple[int, int, int, int],
        width: int,
        dash: int,
        gap: int,
    ) -> None:
        """绘制虚线。"""
        if len(points) < 2:
            return
        for start, end in zip(points, points[1:]):
            x1, y1 = start
            x2, y2 = end
            dx = x2 - x1
            dy = y2 - y1
            distance = math.hypot(dx, dy)
            if distance == 0:
                continue
            step_x = dx / distance
            step_y = dy / distance
            position = 0.0
            while position < distance:
                dash_end = min(distance, position + dash)
                draw.line(
                    (
                        x1 + step_x * position,
                        y1 + step_y * position,
                        x1 + step_x * dash_end,
                        y1 + step_y * dash_end,
                    ),
                    fill=color,
                    width=width,
                )
                position += dash + gap

    def _apply_hatch(
        self,
        image: Image.Image,
        polygon_pixels: list[tuple[int, int]],
        color: tuple[int, int, int, int],
        spacing: int = 12,
    ) -> None:
        """给区域叠加斜线纹理。"""
        if len(polygon_pixels) < 3:
            return
        mask = Image.new("L", (IMAGE_WIDTH, IMAGE_HEIGHT), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(polygon_pixels, fill=255)

        overlay = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        min_x = min(point[0] for point in polygon_pixels)
        max_x = max(point[0] for point in polygon_pixels)
        min_y = min(point[1] for point in polygon_pixels)
        max_y = max(point[1] for point in polygon_pixels)

        start = min_x - (max_y - min_y) - spacing
        end = max_x + (max_y - min_y) + spacing
        for offset in range(int(start), int(end), spacing):
            overlay_draw.line(
                [(offset, max_y + spacing), (offset + (max_y - min_y) + spacing, min_y - spacing)],
                fill=color,
                width=1,
            )

        image.alpha_composite(Image.composite(overlay, Image.new("RGBA", overlay.size), mask))

    def _draw_tunnel(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        transformer: CoordinateTransformer,
        tunnel: dict[str, Any],
        fill: tuple[int, int, int, int],
        outline: tuple[int, int, int, int],
    ) -> None:
        """绘制跨区通道。"""
        for polygon in tunnel.get("polygons", []):
            self._draw_polygon(image, draw, transformer, polygon, fill, outline, 3)
        for polyline in tunnel.get("polylines", []):
            pixels = transformer.to_pixels(polyline)
            self._composite_draw(image, lambda overlay_draw: overlay_draw.line(pixels, fill=fill, width=10))
            draw.line(pixels, fill=outline, width=5)
            for point in (pixels[0], pixels[-1]):
                draw.ellipse(
                    [point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5],
                    fill=outline,
                )

    def _draw_marker(
        self,
        draw: ImageDraw.ImageDraw,
        center: tuple[int, int],
        color: tuple[int, int, int, int],
        kind: str,
    ) -> None:
        """绘制点状标记。"""
        x, y = center
        if kind == "diamond":
            points = [(x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)]
            draw.polygon(points, fill=color, outline=COLOR_TEXT_WHITE)
        elif kind == "triangle":
            points = [(x, y - 9), (x + 8, y + 7), (x - 8, y + 7)]
            draw.polygon(points, fill=color, outline=COLOR_TEXT_WHITE)
            draw.text((x - 2, y - 5), "!", fill=COLOR_TEXT_WHITE, font=_load_font(12, bold=True))
        elif kind == "hex":
            points = [
                (x - 7, y),
                (x - 3, y - 6),
                (x + 3, y - 6),
                (x + 7, y),
                (x + 3, y + 6),
                (x - 3, y + 6),
            ]
            draw.polygon(points, fill=color, outline=COLOR_TEXT_WHITE)
        else:
            draw.ellipse([x - 6, y - 6, x + 6, y + 6], fill=color)

    def _draw_order_badge(
        self,
        draw: ImageDraw.ImageDraw,
        center: tuple[int, int],
        order: int,
    ) -> None:
        """绘制顺序徽标。"""
        x, y = center
        draw.ellipse([x - 16, y - 16, x + 16, y + 16], fill=COLOR_BADGE_RED, outline=COLOR_TEXT_WHITE, width=2)
        font = _load_font(16, bold=True)
        text = str(order)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(
            (x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - 1),
            text,
            fill=COLOR_TEXT_WHITE,
            font=font,
        )

    def _draw_target(self, draw: ImageDraw.ImageDraw, center: tuple[int, int]) -> None:
        """绘制目标点。"""
        x, y = center
        draw.ellipse([x - 18, y - 18, x + 18, y + 18], outline=COLOR_BADGE_BLUE, width=3)
        draw.ellipse([x - 10, y - 10, x + 10, y + 10], outline=COLOR_BADGE_BLUE, width=2)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=COLOR_BADGE_BLUE)

    def _draw_origin(self, draw: ImageDraw.ImageDraw, center: tuple[int, int]) -> None:
        """绘制原点标记。"""
        x, y = center
        draw.line([(x - 8, y), (x + 8, y)], fill=COLOR_ORIGIN, width=2)
        draw.line([(x, y - 8), (x, y + 8)], fill=COLOR_ORIGIN, width=2)

    def _draw_path_stroke(
        self,
        draw: ImageDraw.ImageDraw,
        pixels: list[tuple[int, int]],
        inner_color: tuple[int, int, int, int],
        inner_width: int,
        glow_color: tuple[int, int, int, int],
        glow_width: int,
        dash: int | None = None,
        gap: int | None = None,
    ) -> None:
        """绘制带柔和外沿的路径。"""
        if len(pixels) < 2:
            return
        if dash is not None and gap is not None:
            self._draw_dashed_polyline(draw, pixels, glow_color, glow_width, dash, gap)
            self._draw_dashed_polyline(draw, pixels, inner_color, inner_width, dash, gap)
        else:
            draw.line(pixels, fill=glow_color, width=glow_width, joint="curve")
            draw.line(pixels, fill=inner_color, width=inner_width, joint="curve")

        glow_radius = max(1, glow_width // 2)
        inner_radius = max(1, inner_width // 2)
        for x, y in pixels:
            draw.ellipse(
                [x - glow_radius, y - glow_radius, x + glow_radius, y + glow_radius],
                fill=glow_color,
            )
            draw.ellipse(
                [x - inner_radius, y - inner_radius, x + inner_radius, y + inner_radius],
                fill=inner_color,
            )

    def _draw_path_layer(
        self,
        image: Image.Image,
        path_points: list[dict[str, Any]],
        variant: str,
    ) -> None:
        """按通道样式绘制一层路径。"""
        transformer = self._transformer
        if transformer is None or len(path_points) < 2:
            return

        if variant == "history":
            default_inner = COLOR_PATH_HISTORY
            default_glow = COLOR_PATH_HISTORY_GLOW
            default_inner_width = 10
            default_glow_width = 16
            simplify_epsilon = 1.1
            simplify_min_segment = 1.2
        else:
            default_inner = COLOR_PATH_CURRENT
            default_glow = COLOR_PATH_CURRENT_GLOW
            default_inner_width = 12
            default_glow_width = 18
            simplify_epsilon = 0.9
            simplify_min_segment = 1.0

        pixels = [transformer.to_pixel(point["x"], point["y"]) for point in path_points]
        pixels = _simplify_path_pixels(pixels, simplify_epsilon, simplify_min_segment)
        if len(pixels) < 2:
            return

        self._composite_draw(
            image,
            lambda overlay_draw: self._draw_path_stroke(
                overlay_draw,
                pixels,
                default_inner,
                default_inner_width,
                default_glow,
                default_glow_width,
            ),
        )

    def _draw_path(self, image: Image.Image, scene: dict[str, Any]) -> None:
        """按历史路径和当前路径分别绘制轨迹。"""
        self._draw_path_layer(image, scene.get("history_path_points", []), "history")
        self._draw_path_layer(image, scene.get("current_path_points", []), "current")

    def _draw_path_segment(
        self,
        draw: ImageDraw.ImageDraw,
        segment: list[dict[str, Any]],
    ) -> None:
        """保留旧接口，兼容现有引用。"""
        transformer = self._transformer
        if transformer is None or len(segment) < 2:
            return
        pixels = [transformer.to_pixel(point["x"], point["y"]) for point in segment]
        pixels = _simplify_path_pixels(pixels, 0.9, 1.0)
        if len(pixels) < 2:
            return
        self._draw_path_stroke(
            draw,
            pixels,
            COLOR_PATH_CURRENT,
            12,
            COLOR_PATH_CURRENT_GLOW,
            18,
        )

    def _draw_station(self, draw: ImageDraw.ImageDraw, pose: dict[str, float]) -> None:
        """绘制基站。"""
        transformer = self._transformer
        if transformer is None:
            return
        x, y = transformer.to_pixel(pose["x"], pose["y"])
        draw.rounded_rectangle(
            [x - 14, y - 18, x + 14, y + 18],
            radius=10,
            fill=COLOR_STATION_BODY,
        )
        draw.rounded_rectangle(
            [x - 10, y - 10, x + 10, y + 12],
            radius=8,
            fill=COLOR_STATION_TOP,
            outline=COLOR_STATION_BORDER,
            width=1,
        )
        draw.ellipse([x - 4, y - 13, x + 4, y - 5], fill=COLOR_STATION_LED)
        theta = _coerce_angle_radians(pose.get("theta"), milli_radian=True)
        if theta is not None:
            tip_x = x + int(round(20 * math.cos(theta)))
            tip_y = y + int(round(20 * math.sin(theta)))
            draw.line([(x, y), (tip_x, tip_y)], fill=COLOR_STATION_BODY, width=3)

    def _draw_robot(self, draw: ImageDraw.ImageDraw) -> None:
        """绘制实时机器人位置。"""
        transformer = self._transformer
        if transformer is None:
            return
        robot_state = self._get_display_robot_state()
        display_pose = robot_state["display_pose"]
        if display_pose is None:
            return

        x = display_pose["x"]
        y = display_pose["y"]
        px, py = transformer.to_pixel(x, y)
        draw.ellipse([px - 16, py - 20, px + 16, py + 20], fill=COLOR_ROBOT_BODY)
        draw.ellipse([px - 12, py - 15, px + 12, py + 4], fill=COLOR_ROBOT_TOP)
        draw.rectangle([px - 14, py + 5, px + 14, py + 12], fill=COLOR_ROBOT_DETAIL)

        yaw = display_pose.get("yaw")
        if yaw is not None:
            tip_x = px + int(round(24 * math.cos(yaw)))
            tip_y = py + int(round(24 * math.sin(yaw)))
            draw.line([(px, py), (tip_x, tip_y)], fill=COLOR_ROBOT_DIR, width=4)
            left_x = tip_x - int(round(6 * math.cos(yaw - math.pi / 6)))
            left_y = tip_y - int(round(6 * math.sin(yaw - math.pi / 6)))
            right_x = tip_x - int(round(6 * math.cos(yaw + math.pi / 6)))
            right_y = tip_y - int(round(6 * math.sin(yaw + math.pi / 6)))
            draw.polygon([(tip_x, tip_y), (left_x, left_y), (right_x, right_y)], fill=COLOR_ROBOT_DIR)

    def _draw_map_chips(self, draw: ImageDraw.ImageDraw, scene: dict[str, Any]) -> None:
        """绘制地图上方摘要标签。"""
        name = self._map_data.get("name") or f"Map #{self._map_data.get('id', '-')}"
        state = _enum_label(self._map_data.get("map_state"))

        left = MAP_RECT[0] + 18
        top = MAP_RECT[1] + 18
        self._draw_chip(draw, (left, top), _truncate(name, 26), COLOR_CARD_BG, COLOR_TEXT)
        badge_color = COLOR_BADGE_BLUE if "Complete" in state else COLOR_BADGE_ORANGE if state != "-" else COLOR_BADGE_GRAY
        self._draw_chip(draw, (left, top + 42), state, badge_color, COLOR_TEXT_WHITE)

    def _draw_chip(
        self,
        draw: ImageDraw.ImageDraw,
        location: tuple[int, int],
        text: str,
        fill: tuple[int, int, int, int],
        text_color: tuple[int, int, int, int],
    ) -> None:
        """绘制圆角标签。"""
        x, y = location
        width = self._chip_width(text)
        height = 32
        font = _load_font(15, bold=True)
        draw.rounded_rectangle([x, y, x + width, y + height], radius=16, fill=fill)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(
            (x + (width - (box[2] - box[0])) / 2, y + (height - (box[3] - box[1])) / 2 - 1),
            text,
            fill=text_color,
            font=font,
        )

    def _chip_width(self, text: str) -> int:
        """计算标签宽度。"""
        font = _load_font(15, bold=True)
        dummy = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy)
        box = draw.textbbox((0, 0), text, font=font)
        return int(box[2] - box[0] + 24)

    def _draw_summary_panel(self, image: Image.Image, scene: dict[str, Any]) -> None:
        """绘制底部摘要信息。"""
        draw = ImageDraw.Draw(image, "RGBA")
        left, top, right, bottom = SUMMARY_RECT
        width = right - left
        title_font = _load_font(15, bold=True)
        label_font = _load_font(13)
        value_font = _load_font(18, bold=True)
        chip_font = _load_font(13, bold=True)

        grid_top = top + 18
        grid_left = left + 22
        grid_width = width - 44
        cell_width = grid_width / 4
        cell_height = 42

        flags = []
        if self._map_data.get("has_bird_view"):
            flags.append(f"Bird {self._map_data.get('bird_view_index', 0)}")
        if self._map_data.get("enable_advanced_edge_cutting"):
            flags.append("Adv Edge")
        flags.append("Locked" if self._map_data.get("is_boundary_locked") else "Unlocked")
        flags.append("Build Map" if self._map_data.get("is_able_to_run_build_map") else "Build Off")

        backup_info = self._map_data.get("backup_info_list", [])
        backup_text = "Off"
        if self._map_data.get("has_backup") or backup_info:
            backup_text = f"{len(backup_info) if isinstance(backup_info, list) else 0} item"
        metrics = [
            ("Map", _truncate(f"#{self._map_data.get('id', '-')} · {self._map_data.get('name', '-')}", 22)),
            ("Area", _format_area(self._map_data.get("total_area"))),
            ("Mode", _truncate(_enum_label(self._map_data.get("clean_info", {}).get("mode")), 20)),
            ("Size", _truncate(_format_size(self._map_data), 24)),
            ("Origin", _format_point(_point_tuple(self._map_data.get("origin")))),
            ("Backup", _truncate(f"{backup_text} · {_format_file_size(self._map_data.get('file_size'))}", 24)),
            ("Flags", _truncate(" / ".join(flags), 24)),
        ]

        for index, (label, value) in enumerate(metrics):
            row = index // 4
            column = index % 4
            x = grid_left + column * cell_width
            y = grid_top + row * cell_height
            draw.text((x, y), label, fill=COLOR_TEXT_MUTED, font=label_font)
            draw.text((x, y + 16), value, fill=COLOR_TEXT, font=value_font)

        chip_y = bottom - 46
        chip_x = left + 22
        count_chips = [
            f"R {scene['scene_counts']['regions']}/{scene['scene_counts']['sub_regions']}",
            f"No-go {scene['scene_counts']['forbidden_zones'] + scene['scene_counts']['physical_forbidden_zones']}",
            f"Pass {scene['scene_counts']['pass_through_zones']}",
            f"Tunnel {scene['scene_counts']['cross_boundary_tunnels'] + scene['scene_counts']['virtual_cross_boundary_tunnels']}",
        ]
        for chip in count_chips:
            box = draw.textbbox((0, 0), chip, font=chip_font)
            chip_width = box[2] - box[0] + 20
            if chip_x + chip_width > right - 22:
                break
            draw.rounded_rectangle(
                [chip_x, chip_y, chip_x + chip_width, chip_y + 28],
                radius=14,
                fill=COLOR_MAP_BG,
            )
            draw.text((chip_x + 10, chip_y + 6), chip, fill=COLOR_TEXT_SUBTLE, font=chip_font)
            chip_x += chip_width + 10

        title = "Map Snapshot"
        title_box = draw.textbbox((0, 0), title, font=title_font)
        title_x = right - 22 - (title_box[2] - title_box[0])
        draw.text((title_x, top + 18), title, fill=COLOR_TEXT_SUBTLE, font=title_font)

    def _render_final_image(self) -> bytes:
        """渲染最终图像。"""
        if self._cached_png is not None:
            return self._cached_png

        if self._static_image is None:
            return _render_placeholder()

        image = self._static_image.copy()
        draw = ImageDraw.Draw(image, "RGBA")
        self._draw_robot(draw)

        buffer = io.BytesIO()
        if self._clean_mode:
            image.save(buffer, format="PNG")
        else:
            image.convert("RGB").save(buffer, format="PNG")
        result = buffer.getvalue()
        self._cached_png = result
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """初始化 camera 平台。"""
    basic_data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            TerraMowMapCamera(basic_data, hass),
            TerraMowMapCamera(basic_data, hass, clean_mode=True),
        ]
    )
