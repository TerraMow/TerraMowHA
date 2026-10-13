"""校验集成的多语言文案结构保持同步。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TRANSLATIONS_DIR = (
    Path(__file__).parents[1] / "custom_components" / "terramow" / "translations"
)
PLACEHOLDER_PATTERN = re.compile(r"\{[^}]+\}|%[a-zA-Z]")
EXPECTED_LOCALES = set(
    "cs da de en es fi fr hr hu it lt nl nn pl sk sl sv zh-CN zh-Hans".split()
)


def _leaf_values(value: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    """返回嵌套文案对象中的叶子值，便于比较键集合和占位符。"""
    if isinstance(value, dict):
        result: dict[tuple[str, ...], str] = {}
        for key, child in value.items():
            result.update(_leaf_values(child, (*path, key)))
        return result
    if isinstance(value, str):
        return {path: value}
    raise AssertionError(f"Unexpected translation value at {'.'.join(path)}")


def test_all_translation_files_match_english_keys_and_placeholders() -> None:
    """所有语言必须覆盖同一组文案键，并保留格式化占位符。"""
    english = json.loads((TRANSLATIONS_DIR / "en.json").read_text())
    english_values = _leaf_values(english)
    translation_files = sorted(TRANSLATIONS_DIR.glob("*.json"))
    assert EXPECTED_LOCALES == {path.stem for path in translation_files}

    for translation_file in translation_files:
        values = _leaf_values(json.loads(translation_file.read_text()))
        assert set(values) == set(english_values), translation_file.name
        assert all(value.strip() for value in values.values()), translation_file.name
        for path, english_value in english_values.items():
            assert set(PLACEHOLDER_PATTERN.findall(values[path])) == set(
                PLACEHOLDER_PATTERN.findall(english_value)
            ), f"{translation_file.name}: {'.'.join(path)}"


def test_english_entity_terms_match_translation_source() -> None:
    """英文实体源文案与英文翻译必须保持同一套术语。"""
    strings = json.loads((TRANSLATIONS_DIR.parent / "strings.json").read_text())
    english = json.loads((TRANSLATIONS_DIR / "en.json").read_text())

    source_terms = _leaf_values(strings["entity"])
    english_terms = _leaf_values(english["entity"])
    for path, value in source_terms.items():
        assert english_terms[path] == value, ".".join(path)
