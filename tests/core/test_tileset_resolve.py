"""Tileset 配对回归.

背景: mapset.dll 里 **只有 192 个 PCX 却有 487 张 MAP**, 同"页"(名字前 5 字符)的图共用一张
图集; 且部分 .map 头部声明的尺寸 `u[8]/u[9]` 是**脏数据** (如 TFI0_04P 写 16x21, 实际只用到
瓦片号 ≤255)。若按尺寸匹配就会配到毫不相干的图集 —— 曾把雅士兰的 TAS0_01P 配给五指村的屋子,
整个地板变成盘子/碗。见 core/real_map.py `_resolve_tileset`。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pathlib import Path

import pygame
import pytest

from core import real_map as realm


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((64, 64))
    yield


def test_wuzhi_house_tileset_is_same_page(_pygame):
    """五指村各屋必须用同页图集 (曾经 TFI0_04P 被配成雅士兰的 TAS0_01P → 地板全是盘子)."""
    for base in ["TFI0___P"] + [f"TFI0_0{i}P" for i in range(7)]:
        m = realm.load(base)
        assert m.ts_name[:5] == base[:5], f"{base} 配到了跨页图集 {m.ts_name}"
        # 且容量要够画完本图用到的最大瓦片号 (否则会有空洞)
        assert m.ts_cols * m.ts_rows >= max(m.grid) + 1, f"{base} 图集容量不足"


def test_tileset_geometry_is_dirty_header_proof(_pygame):
    """格子几何必须按**图集实际尺寸**算.

    ⚠ 地图头部 u[8]/u[9] 常是脏数据 (TFI0_04P 写 16x21, 实际图集 TFI0_00P 是 16x16)。
    若按声明算: cell_h = 768 // 21 = 36 (应为 48) → 每格取错源矩形 → **整图花屏**
    (曾表现为"屋内地板铺满盘子/横条纹")。所以 cell 必须恒为 64x48。
    """
    from core.sprites.base import TILE_W, TILE_H
    for base in ["TFI0_04P", "TFI0___P", "TAS0___P", "TAL0_00P", "T_LOC0_P"]:
        m = realm.load(base)
        assert (m.cell_w, m.cell_h) == (TILE_W, TILE_H), \
            f"{base} 格子尺寸 {m.cell_w}x{m.cell_h} != {TILE_W}x{TILE_H} (头部脏尺寸未纠正)"
        tw, th = m.tileset.get_size()
        assert (m.ts_cols, m.ts_rows) == (tw // TILE_W, th // TILE_H)


def test_all_maps_load_and_almost_all_covered(_pygame):
    """全游戏地图都要能加载; 图集容量不足的只能是少数已知边角.

    已知边角 (~13 张, 与本次修复无关, 是资源/解析层面的历史问题):
      · TJP0_01P / TTD1___P: .map 尾部有额外数据 (120+2wh 恒等式不成立) → 网格被读错;
      · 其余 (THG0___P / TMO1___P / TMY0_00P ...): 地图声明的图集比提取出的 .pcx 大
        (如声明 20x18 而 PCX 只有 20x8) → 尾部瓦片号越界, 渲染会留空洞 (已确认 PCX 头部
        与 pygame 读取一致, 非读取问题)。
    """
    maps = sorted(Path(realm.MAPS_DIR).glob("*.map")) if hasattr(realm, "MAPS_DIR") else []
    if not maps:
        pytest.skip("没有地图资源")
    insufficient = []
    for p in maps:
        m = realm.load(p.stem)                       # 不应抛异常
        if max(m.grid) + 1 > m.ts_cols * m.ts_rows:
            insufficient.append(p.stem)
    assert len(insufficient) <= 16, f"太多图配错图集: {insufficient}"
