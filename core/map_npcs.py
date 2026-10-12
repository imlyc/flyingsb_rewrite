"""地图角色 / 传送点数据 (A) —— 来自原版 .mfo 的 pcpos + jmp.

数据源: `assets/map_npcs.json`（由 `tools/extract_map_npcs.py` 生成）
  {"maps": {base: {"name": 地名, "id": 位置ID,
                   "npcs": [{x, y, d, act, script, sprite, text}],
                   "doors": [{x, y, d, target}]}}}

语义（逆向结论，见 tools/extract_map_npcs.py 顶部）：
  · `script` 既是**该角色的剧本 ID**（`core.script_text` 的索引），
    也在数值上与**目标位置 ID** 共用同一套空间 —— 所以地图上的村民/守卫/神像
    都能直接取到原版对白；
  · `sprite` = [c0, o0]，原版精灵帧范围的前两个值（如 292/293、332/333），
    完整范围是 c0..c1 / o0..o1（各约 20 帧）。该图集尚未定位，故目前渲染占位图。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "assets" / "map_npcs.json"


@lru_cache(maxsize=1)
def _maps() -> dict:
    if not ASSET.exists():
        return {}
    return json.loads(ASSET.read_text(encoding="utf-8")).get("maps", {})


def available() -> bool:
    return bool(_maps())


def map_info(base: str) -> dict:
    return _maps().get(base) or {}


def npcs_for(base: str) -> list[dict]:
    """该地图上的角色列表 (可能为空)."""
    return list(map_info(base).get("npcs") or [])


def doors_for(base: str) -> list[dict]:
    """该地图上的纯传送点列表."""
    return list(map_info(base).get("doors") or [])


@lru_cache(maxsize=64)
def _npc_index(base: str) -> dict[tuple[int, int], dict]:
    return {(n["x"], n["y"]): n for n in npcs_for(base)}


def npc_at(base: str, x: int, y: int) -> dict | None:
    """该格上的角色; 没有则 None."""
    return _npc_index(base).get((x, y))


@lru_cache(maxsize=64)
def _door_index(base: str) -> dict[tuple[int, int], dict]:
    return {(d["x"], d["y"]): d for d in doors_for(base)}


def door_at(base: str, x: int, y: int) -> dict | None:
    return _door_index(base).get((x, y))


def blocked_tiles(base: str) -> set[tuple[int, int]]:
    """角色占据的格子: 不能走上去, 要走"撞"上去触发对白 (原版行为)."""
    return set(_npc_index(base))
