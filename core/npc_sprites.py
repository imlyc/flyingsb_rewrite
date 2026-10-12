"""地图角色 (Field Character) 精灵 —— 从原版角色表取真精灵.

逆向结论 (tools/_a 探针, 已逐项验证):
  · **角色表**在 exe 里: `0x1b01a9` 起 133 条 + `0x1bd9c9` 起 20 条, 每条 416 字节,
    内容是 ase_ps.dll 的图集资源名 (如 `CSON000.PCX`), 中间夹一条全零空记录;
  · 游戏按**表顺序**把这些图集拼成一个"虚拟大图集", 帧号是全局的 ——
    剧本 `<SON:NNNN>` 与 `.mfo` `jmp` 的 `c0/c1/o0/o1` 都在这个编号空间里;
  · 每帧 64x96, 图集 `ps_CJAH000` (384x384) = 6x4 帧,
    **行 = 朝向 (0 背面 / 1 正面 / 2 左侧 / 3 右侧), 列 = 动画帧**。
  · 例: 五指村 `TAS0___P` 角色 c0=292/332/372 → 落在 `CJAH000/CJAH100/CJAH300`
    区间内, 渲染出来是连贯的人形角色。

对外 API:
  available()                 角色表是否可用
  atlas_for(frame)            全局帧号 → (图集资源名, 图集内帧号)
  surface_for(frame, direction)  该帧号所属图集 + 指定朝向的第 0 帧 (站立像)
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

import pygame

from core.sprites.base import load_image

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"
SPRITES = ROOT / "assets" / "sprites"

FRAME_W, FRAME_H = 64, 96
TABLE_1 = (0x1B01A9, 133)        # (文件偏移, 条数)
TABLE_2 = (0x1BD9C9, 20)
STRIDE = 416


def _read_table() -> list[str]:
    """按表顺序返回图集资源名 (空记录跳过)."""
    if not EXE.exists():
        return []
    raw = EXE.read_bytes()
    names: list[str] = []
    for base, count in (TABLE_1, TABLE_2):
        for i in range(count):
            o = base + i * STRIDE
            if o + STRIDE > len(raw):
                break
            e = raw.find(b"\x00", o)
            nm = raw[o:(e if 0 < e < o + 32 else o + 32)].decode("latin1").strip()
            if nm.lower().endswith(".pcx"):
                nm = nm[:-4]
            if nm:
                names.append(nm)
    return names


@lru_cache(maxsize=1)
def _index() -> list[tuple[int, int, str, int, int]]:
    """[(起始帧, 结束帧, 资源名, 列数, 行数)] 按表顺序."""
    out = []
    cum = 0
    for nm in _read_table():
        p = SPRITES / f"ps_{nm}.pcx"
        if not p.exists():
            continue
        try:
            w, h = pygame.image.load(str(p)).get_size()
        except Exception:
            continue
        cols, rows = w // FRAME_W, h // FRAME_H
        if cols < 1 or rows < 1:
            continue
        n = cols * rows
        out.append((cum, cum + n, nm, cols, rows))
        cum += n
    return out


def available() -> bool:
    return bool(_index())


def atlas_for(frame: int) -> tuple[str, int, int, int] | None:
    """全局帧号 → (资源名, 图集内帧号, 列数, 行数); 越界返回 None."""
    for s, e, nm, cols, rows in _index():
        if s <= frame < e:
            return nm, frame - s, cols, rows
    return None


_surface_cache: dict[tuple[str, int, int], pygame.Surface] = {}


def surface_for(frame: int, direction: int = 1,
                anim: int = 0) -> pygame.Surface | None:
    """该帧号所属图集 + (朝向, 动画帧) 的子表面; 失败返回 None.

    direction: 0 背面 / 1 正面 / 2 左侧 / 3 右侧 (与图集行号一致)
    """
    hit = atlas_for(frame)
    if hit is None:
        return None
    nm, local, cols, rows = hit
    d = max(0, min(rows - 1, direction))
    c = (local % cols + anim) % cols
    key = (nm, d, c)
    surf = _surface_cache.get(key)
    if surf is None:
        path = SPRITES / f"ps_{nm}.pcx"
        try:
            # AUTO 色键 (采样左上角) —— 与 core.sprites.loaders 的角色图集一致
            atlas = load_image(path)
            surf = atlas.subsurface(pygame.Rect(c * FRAME_W, d * FRAME_H,
                                                FRAME_W, FRAME_H)).copy()
        except Exception:
            return None
        _surface_cache[key] = surf
    return surf
