"""完整地图与纯地图相机共用图层和动态位置的回归测试。"""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from PIL import Image, ImageChops, ImageDraw
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramow import TerraMowBasicData
from custom_components.terramow.camera import (
    COLOR_MAP_BG,
    COLOR_PASS_THROUGH_FILL,
    COLOR_PHYSICAL_RESTRICTED_FILL,
    COLOR_REQUIRED_FILL,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    MAP_RECT,
    MARKER_MAX_SIZE_PX,
    MARKER_SIZE,
    PATH_SMOOTH_MAX_POINTS,
    CoordinateTransformer,
    TerraMowCleanMapCamera,
    TerraMowMapCamera,
    _load_marker_image,
    _marker_display_size,
    _smooth_path_pixels,
    _split_path_segments,
    async_setup_entry,
)
from custom_components.terramow.const import DOMAIN
from custom_components.terramow.lawn_mower import TerraMowLawnMowerEntity


def _square(left: int, top: int, right: int, bottom: int) -> dict:
    """构造闭合区域供图层颜色测试使用。"""
    return {
        "boundary": {
            "points": [
                {"x": left, "y": top},
                {"x": right, "y": top},
                {"x": right, "y": bottom},
                {"x": left, "y": bottom},
            ]
        }
    }


def test_path_smoothing_rounds_turn_without_moving_control_points() -> None:
    """急转弯变为连续弧线，原始定位点和两端保持原位。"""
    pixels = [(0, 0), (50, 0), (70, 20), (50, 40), (50, 60)]
    smoothed = _smooth_path_pixels(pixels)

    assert smoothed[0] == pixels[0]
    assert smoothed[-1] == pixels[-1]
    assert all(point in smoothed for point in pixels)
    assert any(x > 50 and 0 < y < 20 for x, y in smoothed)
    assert len(smoothed) > len(pixels)


def test_path_smoothing_leaves_large_gaps_straight() -> None:
    """分段采样不能为跨区间隔补出虚假的弯曲轨迹。"""
    pixels = [
        (0, 0),
        (20, 0),
        (30, 10),
        (40, 20),
        (220, 20),
        (240, 20),
        (250, 30),
        (260, 40),
    ]
    smoothed = _smooth_path_pixels(pixels)

    assert ((40, 20), (220, 20)) in zip(smoothed, smoothed[1:], strict=False)
    assert _smooth_path_pixels(pixels[:3]) == pixels[:3]


def test_path_smoothing_limits_dense_output() -> None:
    """长轨迹限制插值点数，避免地图刷新耗时随路径失控。"""
    pixels = [(index * 10, index % 7) for index in range(3500)]
    smoothed = _smooth_path_pixels(pixels)

    assert smoothed[0] == pixels[0]
    assert smoothed[-1] == pixels[-1]
    assert len(smoothed) <= PATH_SMOOTH_MAX_POINTS + 1


@pytest.mark.parametrize(("dash", "gap"), [(None, None), (9, 5)])
def test_dense_path_keeps_same_center_strength_as_sparse_path(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
    dash: int | None,
    gap: int | None,
) -> None:
    """密集采样点的外沿不能覆盖已绘制的路径内层。"""
    map_camera, _ = cameras
    inner = (174, 229, 185, 140)
    glow = (174, 229, 185, 50)

    def center_pixel(points: list[tuple[int, int]]) -> tuple[int, ...]:
        overlay = Image.new("RGBA", (101, 101), (0, 0, 0, 0))
        map_camera._draw_path_stroke(
            ImageDraw.Draw(overlay, "RGBA"),
            points,
            inner,
            10,
            glow,
            16,
            dash=dash,
            gap=gap,
        )
        background = Image.new("RGBA", overlay.size, (240, 240, 240, 255))
        background.alpha_composite(overlay)
        assert overlay.getpixel((50, 50)) == inner
        return background.getpixel((50, 50))

    sparse = center_pixel([(20, 50), (80, 50)])
    dense = center_pixel([(x, 50) for x in range(20, 81, 3)])
    assert dense == sparse


def test_history_segments_share_one_alpha_layer(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """重叠段不重复加深，邻段的外沿也不能冲淡已绘制的内层。"""
    map_camera, _ = cameras
    transformer = MagicMock()
    transformer.to_pixel.side_effect = lambda x, y: (int(x), int(y))
    map_camera._transformer = transformer

    def clean(y: int) -> list[dict]:
        return [
            {"x": 20, "y": y, "type": "PATH_POINT_TYPE_CLEANING"},
            {"x": 80, "y": y, "type": "PATH_POINT_TYPE_CLEANING"},
        ]

    def render(points: list[dict]) -> Image.Image:
        image = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), COLOR_MAP_BG)
        map_camera._draw_path_layer(image, points, "history")
        return image

    first = clean(50)
    resume = {"x": 90, "y": 90, "type": "PATH_POINT_TYPE_RESUME"}
    single = render(first)
    overlapping = render([*first, resume, *clean(50)])
    nearby = render([*first, resume, *clean(56)])

    assert (
        ImageChops.difference(
            single.convert("RGB"), overlapping.convert("RGB")
        ).getbbox()
        is None
    )
    assert nearby.getpixel((50, 50)) == single.getpixel((50, 50))


def test_path_segments_keep_transitions_but_break_at_resume() -> None:
    """普通类型切换承接上一点，恢复点两侧不产生连接。"""
    points = [
        {"x": 10, "y": 20, "type": "PATH_POINT_TYPE_CLEANING"},
        {"x": 20, "y": 20, "type": "PATH_POINT_TYPE_CLEANING"},
        {"x": 30, "y": 40, "type": "PATH_POINT_TYPE_MOVE"},
        {"x": 40, "y": 40, "type": "PATH_POINT_TYPE_MOVE"},
        {"x": 50, "y": 20, "type": "PATH_POINT_TYPE_CLEANING"},
        {"x": 60, "y": 20, "type": "PATH_POINT_TYPE_RESUME"},
        {"x": 70, "y": 20, "type": "PATH_POINT_TYPE_CLEANING"},
    ]

    segments = _split_path_segments(points)

    assert [kind for kind, _ in segments] == [
        "PATH_POINT_TYPE_CLEANING",
        "PATH_POINT_TYPE_MOVE",
        "PATH_POINT_TYPE_CLEANING",
        "PATH_POINT_TYPE_RESUME",
        "PATH_POINT_TYPE_CLEANING",
    ]
    assert segments[1][1] == points[1:4]
    assert segments[2][1] == points[3:5]
    assert segments[3][1] == [points[5]]
    assert segments[4][1] == [points[6]]


@pytest.fixture
def cameras(hass: HomeAssistant) -> tuple[TerraMowMapCamera, TerraMowCleanMapCamera]:
    """两台相机共享一个内存中的地图数据源。"""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.69", ""), hass)
    map_camera = TerraMowMapCamera(mower.basic_data, hass)
    clean_camera = TerraMowCleanMapCamera(mower.basic_data, hass, map_camera)
    return map_camera, clean_camera


async def test_camera_platform_adds_both_variants(hass: HomeAssistant) -> None:
    """第二个相机有独立实体 ID，但不重复注册地图回调。"""
    mower = TerraMowLawnMowerEntity(TerraMowBasicData("192.0.2.70", ""), hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: mower.host, CONF_PASSWORD: ""}
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mower.basic_data
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    assert [type(entity) for entity in entities] == [
        TerraMowMapCamera,
        TerraMowCleanMapCamera,
    ]
    assert len({entity.unique_id for entity in entities}) == 2
    assert len(mower.map_callbacks) == 1
    assert len(mower.path_callbacks) == 1
    assert len(mower.pose_callbacks) == 1


async def test_removed_clean_camera_stops_receiving_updates(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """禁用纯地图实体后，原相机继续刷新但不触发旧实体。"""
    map_camera, clean_camera = cameras
    writes = 0

    @callback
    def write() -> None:
        nonlocal writes
        writes += 1

    map_camera.async_write_ha_state = callback(MagicMock())
    clean_camera.entity_id = "camera.test_clean_map"
    clean_camera.async_write_ha_state = write
    await clean_camera.async_added_to_hass()

    map_camera._notify_image_updated()
    assert writes == 1
    await clean_camera.async_remove(force_remove=True)
    map_camera._notify_image_updated()
    assert writes == 1


def test_clean_map_excludes_panels_but_keeps_map_and_robot(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """纯地图保留区域和机器人，同时裁掉面板、卡片和地图角标。"""
    map_camera, _ = cameras
    points = [
        {"x": 0, "y": 0},
        {"x": 100, "y": 0},
        {"x": 100, "y": 100},
        {"x": 0, "y": 100},
    ]
    map_camera._map_data = {
        "id": 1,
        "name": "Garden",
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "regions": [
            {
                "id": 1,
                "boundary": {"points": points},
                "sub_regions": [{"id": 1, "boundary": {"points": points}}],
            }
        ],
    }
    map_camera._rebuild_static_image()

    full = Image.open(io.BytesIO(map_camera._render_final_image())).convert("RGB")
    clean = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    assert full.size == (IMAGE_WIDTH, IMAGE_HEIGHT)
    assert clean.size == (MAP_RECT[2] - MAP_RECT[0], MAP_RECT[3] - MAP_RECT[1])
    assert clean.getpixel((0, 0)) == COLOR_MAP_BG[:3]
    assert clean.getpixel((clean.width // 2, clean.height // 2)) != COLOR_MAP_BG[:3]
    assert ImageChops.difference(full.crop(MAP_RECT), clean).getbbox() is not None

    before = clean.copy()
    map_camera._pose = {"x": 60, "y": 60, "yaw": 0}
    map_camera._notify_image_updated(write_state=False)
    after = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    assert ImageChops.difference(before, after).getbbox() is not None


def test_clean_map_distinguishes_zones_paths_and_tunnels(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """主要区域、割草路径和跨界通道在同一地图上仍可辨认。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "required_zones": [_square(10, 10, 30, 30)],
        "pass_through_zones": [_square(40, 10, 60, 30)],
        "forbidden_zones": [_square(70, 10, 90, 30)],
        "physical_forbidden_zones": [_square(10, 50, 30, 70)],
        "cross_boundary_tunnels": [
            {"line": {"points": [{"x": 40, "y": 90}, {"x": 60, "y": 90}]}}
        ],
    }
    map_camera._path_data = {
        "map_id": 1,
        "points": [
            {"position": {"x": 40, "y": 60}, "type": "PATH_POINT_TYPE_CLEANING"},
            {"position": {"x": 60, "y": 60}, "type": "PATH_POINT_TYPE_CLEANING"},
        ],
    }
    map_camera._rebuild_static_image()
    image = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        px, py = transformer.to_pixel(x, y)
        return image.getpixel((px - MAP_RECT[0], py - MAP_RECT[1]))

    base = pixel(5, 5)
    required = pixel(20, 20)
    passing = pixel(50, 20)
    forbidden = pixel(80, 20)
    physical = pixel(20, 60)
    path = pixel(50, 60)
    tunnel = pixel(50, 90)
    assert COLOR_REQUIRED_FILL[3] == 77
    assert COLOR_PASS_THROUGH_FILL[3] == 102
    assert COLOR_PHYSICAL_RESTRICTED_FILL[3] == 77
    assert required[2] > required[0]
    assert passing[0] > passing[2]
    assert forbidden[0] > forbidden[2]
    assert physical != passing
    assert path[1] > path[0]
    assert tunnel != base


def test_restricted_zones_and_obstacles_use_solid_boundaries(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """两类禁区共用半透明填充与细实线，障碍物保留底色留白。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "regions": [
            {
                "id": 1,
                "boundary": _square(5, 5, 95, 35)["boundary"],
                "sub_regions": [
                    {"id": 1, "boundary": _square(5, 5, 95, 35)["boundary"]}
                ],
            }
        ],
        "forbidden_zones": [_square(10, 10, 30, 30)],
        "physical_forbidden_zones": [_square(40, 10, 60, 30)],
        "obstacles": [_square(70, 10, 90, 30)],
    }
    map_camera._rebuild_static_image()
    image = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        px, py = transformer.to_pixel(x, y)
        return image.getpixel((px - MAP_RECT[0], py - MAP_RECT[1]))

    background = Image.new("RGBA", (1, 1), (223, 224, 230, 255))
    overlay = Image.new("RGBA", (1, 1), (255, 102, 63, 77))
    expected_fill = Image.alpha_composite(background, overlay).getpixel((0, 0))[:3]
    for left in (10, 40):
        assert pixel(left + 10, 20) == expected_fill
        left_px, top_px = transformer.to_pixel(left, 10)
        _, bottom_px = transformer.to_pixel(left, 30)
        x = left_px - MAP_RECT[0]
        assert all(
            image.getpixel((x, y - MAP_RECT[1])) == (255, 120, 70)
            for y in range(top_px + 3, bottom_px - 3)
        )
        assert pixel(left + 5, 15) == pixel(left + 15, 25) == expected_fill

    assert pixel(80, 20) == COLOR_MAP_BG[:3]
    assert pixel(70, 20) == (198, 199, 204)
    assert pixel(50, 50) == COLOR_MAP_BG[:3]


def test_selected_subregion_keeps_default_surface_color(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """选中分区只靠顺序徽标区分，不给整片区域叠色。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "regions": [
            {
                "id": 1,
                "boundary": _square(10, 40, 90, 90)["boundary"],
                "sub_regions": [
                    {
                        "id": 1,
                        "is_selected_for_mow": True,
                        "selected_for_mow_order": 1,
                        "boundary": _square(10, 40, 45, 90)["boundary"],
                    },
                    {"id": 2, "boundary": _square(55, 40, 90, 90)["boundary"]},
                ],
            }
        ],
    }
    map_camera._rebuild_static_image()
    image = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None
    for x in (20, 70):
        px, py = transformer.to_pixel(x, 60)
        assert image.getpixel((px - MAP_RECT[0], py - MAP_RECT[1])) == (223, 224, 230)
    outside_x, outside_y = transformer.to_pixel(50, 20)
    assert (
        image.getpixel((outside_x - MAP_RECT[0], outside_y - MAP_RECT[1]))
        == COLOR_MAP_BG[:3]
    )


@pytest.mark.parametrize(
    ("steps", "gap_point", "hidden_point", "visible_point"),
    [
        (
            [
                (10, 20, "CLEANING"),
                (20, 20, "CLEANING"),
                (21, 21, "MOVE"),
                (20, 70, "MOVE"),
                (80, 70, "MOVE"),
                (79, 21, "MOVE"),
                (80, 20, "CLEANING"),
                (90, 20, "CLEANING"),
            ],
            (50, 20),
            (50, 70),
            (15, 20),
        ),
        (
            [
                (10, 20, "CLEANING"),
                (20, 20, "CLEANING"),
                (80, 20, "RESUME"),
                (90, 20, "CLEANING"),
                (95, 20, "CLEANING"),
            ],
            (85, 20),
            (80, 20),
            (92, 20),
        ),
    ],
)
def test_clean_map_does_not_bridge_path_type_gaps(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
    steps: list[tuple[int, int, str]],
    gap_point: tuple[int, int],
    hidden_point: tuple[int, int],
    visible_point: tuple[int, int],
) -> None:
    """绕行和恢复间隔不应被画成横穿地图的割草直线。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
    }
    map_camera._rebuild_static_image()
    baseline = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    map_camera._path_data = {
        "map_id": 1,
        "points": [
            {"position": {"x": x, "y": y}, "type": f"PATH_POINT_TYPE_{kind}"}
            for x, y, kind in steps
        ],
    }
    map_camera._rebuild_static_image()
    map_camera._notify_image_updated(write_state=False)
    rendered = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None
    scene = map_camera._build_scene()
    assert len(scene["current_path_points"]) == len(steps)
    assert scene["filtered_non_cleaning_point_count"]["current"] == sum(
        kind != "CLEANING" for _, _, kind in steps
    )

    def pixel(image: Image.Image, point: tuple[int, int]) -> tuple[int, int, int]:
        x, y = transformer.to_pixel(*point)
        return image.getpixel((x - MAP_RECT[0], y - MAP_RECT[1]))

    assert pixel(rendered, gap_point) == pixel(baseline, gap_point)
    assert pixel(rendered, hidden_point) == pixel(baseline, hidden_point)
    assert pixel(rendered, visible_point) != pixel(baseline, visible_point)


def test_path_map_fallback_uses_dataset_with_cleaning_points(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """地图 ID 缺失时，只有转移点的当前路径不能挤掉可绘制的历史路径。"""
    map_camera, _ = cameras
    map_camera._path_data = {
        "map_id": 2,
        "points": [
            {"position": {"x": 10, "y": 10}, "type": "PATH_POINT_TYPE_MOVE"},
        ],
    }
    map_camera._history_path_data = {
        "map_id": 1,
        "points": [
            {"position": {"x": 20, "y": 20}, "type": "PATH_POINT_TYPE_CLEANING"},
            {"position": {"x": 30, "y": 20}, "type": "PATH_POINT_TYPE_CLEANING"},
        ],
    }

    scene = map_camera._build_scene()

    assert scene["current_path_points"] == []
    assert len(scene["history_path_points"]) == 2
    assert scene["path_map_mismatch"] is True
    assert scene["filtered_non_cleaning_point_count"] == {"current": 1, "history": 0}


@pytest.mark.parametrize("path_layer", ["current", "history"])
@pytest.mark.parametrize("hidden_type", ["MOVE", "RETURN", "RESUME"])
def test_hidden_path_points_do_not_change_map_viewport(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
    path_layer: str,
    hidden_type: str,
) -> None:
    """地图外的隐藏路径仅用于分段，不应缩小或移动两种地图画面。"""
    map_camera, _ = cameras
    boundary = _square(0, 0, 20_000, 20_000)["boundary"]
    map_camera._map_data = {
        "id": 1,
        "width": 20_000,
        "height": 20_000,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "regions": [
            {
                "id": 1,
                "boundary": boundary,
                "sub_regions": [{"id": 1, "boundary": boundary}],
            }
        ],
    }
    path = {
        "map_id": 1,
        "points": [
            {
                "position": {"x": x, "y": 10_000},
                "type": "PATH_POINT_TYPE_CLEANING",
            }
            for x in (5_000, 15_000)
        ],
    }
    if path_layer == "current":
        map_camera._path_data = path
    else:
        map_camera._history_path_data = path
    map_camera._rebuild_static_image()
    before_clean = Image.open(io.BytesIO(map_camera._render_clean_image())).convert(
        "RGB"
    )
    before_full = Image.open(io.BytesIO(map_camera._render_final_image())).convert(
        "RGB"
    )
    transformer = map_camera._transformer
    assert transformer is not None
    expected_corners = [
        transformer.to_pixel(*point) for point in ((0, 0), (20_000, 20_000))
    ]

    path["points"].append(
        {
            "position": {"x": 100_000, "y": 100_000},
            "type": f"PATH_POINT_TYPE_{hidden_type}",
        }
    )
    map_camera._rebuild_static_image()
    map_camera._notify_image_updated(write_state=False)
    transformer = map_camera._transformer
    assert transformer is not None
    assert [
        transformer.to_pixel(*point) for point in ((0, 0), (20_000, 20_000))
    ] == expected_corners
    after_clean = Image.open(io.BytesIO(map_camera._render_clean_image())).convert(
        "RGB"
    )
    after_full = Image.open(io.BytesIO(map_camera._render_final_image())).convert("RGB")
    assert ImageChops.difference(before_clean, after_clean).getbbox() is None
    assert (
        ImageChops.difference(
            before_full.crop(MAP_RECT), after_full.crop(MAP_RECT)
        ).getbbox()
        is None
    )


def test_region_order_badge_stays_above_cleaning_path(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """割草轨迹经过区域中心时，编号仍保持可读。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "regions": [
            {
                "id": 1,
                "boundary": _square(10, 10, 90, 90)["boundary"],
                "sub_regions": [
                    {
                        "id": 1,
                        "boundary": _square(10, 10, 90, 90)["boundary"],
                        "center": {"x": 50, "y": 50},
                        "selected_for_mow_order": 1,
                    }
                ],
            }
        ],
    }
    map_camera._path_data = {
        "map_id": 1,
        "points": [
            {"position": {"x": 20, "y": 50}, "type": "PATH_POINT_TYPE_CLEANING"},
            {"position": {"x": 80, "y": 50}, "type": "PATH_POINT_TYPE_CLEANING"},
        ],
    }
    map_camera._rebuild_static_image()
    image = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None
    center_x, center_y = transformer.to_pixel(50, 50)
    red, green, blue = image.getpixel(
        (center_x - MAP_RECT[0] - 10, center_y - MAP_RECT[1])
    )
    assert red > green + 80 and red > blue + 80


def test_coordinate_origin_is_not_drawn_as_a_map_marker(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """坐标原点仅用于定位，不应被误认成地图上的作业起点。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
    }
    map_camera._rebuild_static_image()
    image = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")
    transformer = map_camera._transformer
    assert transformer is not None
    origin_x, origin_y = transformer.to_pixel(0, 0)
    origin_x -= MAP_RECT[0]
    origin_y -= MAP_RECT[1]

    nearby_pixels = (
        image.getpixel((x, y))
        for x in range(max(0, origin_x - 12), min(image.width, origin_x + 13))
        for y in range(max(0, origin_y - 20), min(image.height, origin_y + 6))
    )
    assert all(min(pixel) > 130 for pixel in nearby_pixels)


def test_map_marker_assets_keep_transparency_and_status_colors() -> None:
    """打包图标保留透明背景和可区分的设备状态颜色。"""
    icons = [
        _load_marker_image("mower.png"),
        _load_marker_image("station_charging.png"),
        _load_marker_image("station_idle.png"),
    ]
    for icon in icons:
        assert icon.size == MARKER_SIZE
        assert icon.getpixel((0, 0))[3] == 0
    assert any(
        red > green + 60 and red > blue + 60 and alpha > 200
        for _, (red, green, blue, alpha) in (
            _load_marker_image("mower.png").getcolors(MARKER_SIZE[0] * MARKER_SIZE[1])
            or []
        )
    )
    assert any(
        green > red + 60 and green > blue + 60 and alpha > 200
        for _, (red, green, blue, alpha) in (
            _load_marker_image("station_charging.png").getcolors(
                MARKER_SIZE[0] * MARKER_SIZE[1]
            )
            or []
        )
    )


@pytest.mark.parametrize(
    ("extent_mm", "expected_px"),
    [(20_000, 24), (5_000, 77), (100, MARKER_MAX_SIZE_PX)],
)
def test_map_marker_size_tracks_scale_with_bounds(
    extent_mm: int, expected_px: int
) -> None:
    """正常地图按实际尺寸缩放，极小地图限制图标过度放大。"""
    transformer = CoordinateTransformer([(0, 0), (extent_mm, extent_mm)], MAP_RECT)
    size = _marker_display_size(transformer)

    assert size == (expected_px, expected_px)
    for name in ("mower.png", "station_charging.png", "station_idle.png"):
        assert _load_marker_image(name, size).size == size


def test_station_marker_changes_with_charger_status(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """充电状态变化时，两张相机都应换用对应的基站图标。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "station_pose": {"x": 50, "y": 50, "theta": 0},
    }
    map_camera._rebuild_static_image()
    mower = map_camera.basic_data.lawn_mower
    assert mower is not None
    mower._battery_status = {"charger_connected": False}
    idle_full = Image.open(io.BytesIO(map_camera._render_final_image())).convert("RGB")
    idle_clean = Image.open(io.BytesIO(map_camera._render_clean_image())).convert("RGB")

    mower._battery_status = {"charger_connected": True}
    map_camera._notify_image_updated(write_state=False)
    charging_full = Image.open(io.BytesIO(map_camera._render_final_image())).convert(
        "RGB"
    )
    charging_clean = Image.open(io.BytesIO(map_camera._render_clean_image())).convert(
        "RGB"
    )
    assert ImageChops.difference(idle_full, charging_full).getbbox() is not None
    assert ImageChops.difference(idle_clean, charging_clean).getbbox() is not None


def test_station_without_heading_still_renders(
    cameras: tuple[TerraMowMapCamera, TerraMowCleanMapCamera],
) -> None:
    """缺少基站方向角时仍能生成地图画面。"""
    map_camera, _ = cameras
    map_camera._map_data = {
        "id": 1,
        "width": 100,
        "height": 100,
        "resolution": 1,
        "origin": {"x": 0, "y": 0},
        "station_pose": {"x": 50, "y": 50},
    }
    map_camera._rebuild_static_image()
    rendered = Image.open(io.BytesIO(map_camera._render_clean_image()))
    assert rendered.size == (MAP_RECT[2] - MAP_RECT[0], MAP_RECT[3] - MAP_RECT[1])


@pytest.mark.parametrize(
    "file_name",
    [
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/zh-Hans.json",
        "translations/zh-CN.json",
    ],
)
def test_clean_camera_has_translation(file_name: str) -> None:
    """纯地图实体在所有语言中都有名称。"""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "terramow"
    data = json.loads((root / file_name).read_text(encoding="utf-8"))
    assert data["entity"]["camera"]["clean_map_camera"]["name"]
