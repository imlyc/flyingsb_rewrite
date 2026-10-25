"""战斗状态栏 — 照 exe FUN_004ce480 (绘制) / FUN_004cf1ed (滑入滑出) 逆向 (2026-10-25,
reverse_engineering/mp_sg_funcs.txt + hud_helpers.txt + font_init.txt, 原版 cnc-ddraw 原生截图核对).

画在战斗画面框左上角, 每个队员一栏 128px 宽, 整条 80px 高, 无底板 (文字直接压在地图上):
  名字 (8, 10)             字体 4        Lv%3d (80, 10)    字体 10
  "HP:     /%4d" 最大值 (8, 30) 白       当前值 "%4d" (40, 30) 按比例着色
  "MP:     /%4d" 最大值 (8, 50) 白       当前值 (40, 50) 蓝      — MaxMP < 1 时改画 "SG" 标签
  SG 槽 (40, 42): SMENU.pcx y32-47 空槽 / y48-63 满槽, 宽按 exe 槽宽表 (5 格 × 16px, 沙悟净 2 格)
  状态图标行 y=62: SMENU.pcx y64/y80 的 16×16 图标, 每种状态固定 x 位置
y 是文字**垂直中线** (DrawText DT_VCENTER, 框 y-32..y+32). 字体 = 新細明體 16px (LOGFONT 表 0x5407d8 #4/#10,
weight 500), 半角 8px 等宽; 文字先按描边模板 (0x53c7a4 #0: 6 个偏移) 画描边色, 再画主色.
颜色 = PALETTEINDEX 对 (0x53ca48), 取战斗调色板实值. 原版 Wine 下数字重叠是字体替换导致字宽不同, 这里按 Windows 等宽排.
滑入: 战斗进行中每 tick 可见高度 +4 (0→80, 露出的是底部, 从上往下滑出), 结束时 -4 滑回.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene

COL_W, BAR_H = 128, 80
SLIDE_STEP = 4
# (主色, 描边色): exe 0x53ca48 的 PALETTEINDEX 对, 战斗调色板实值 (原生截图读出)
PAIR_NORMAL = ((255, 255, 255), (35, 35, 35))      # 0xff / 0xfd
PAIR_DEAD = ((0, 0, 0), (71, 71, 71))              # 0xfe / 0xfc
PAIR_LOW = ((255, 106, 33), (196, 0, 0))           # 2 / 3     HP ≤ 1/4
PAIR_GOOD = ((43, 166, 0), (0, 41, 0))             # 5 / 6     HP > 1/2
PAIR_MP = ((77, 133, 255), (0, 33, 156))           # 8 / 9
PAIR_MID = ((255, 255, 51), (153, 129, 118))       # 0xde / 0x91  HP > 1/4
OUTLINE = ((-1, -1), (-1, 0), (0, -1), (0, 1), (1, 0), (1, 1))   # 描边模板 #0 (16px 字体)
# 状态图标: (状态位, 备选位 or None, SMENU 源 (x, y), 栏内 x). 备选位只在主位没有时画 (exe if/else).
STATUS_ICONS = (
    (0x100, None, (0, 64), 0),       # 中毒
    (0x200, None, (16, 64), 16),     # 睡眠
    (0x400, None, (32, 64), 32),     # 沉默
    (0x800, None, (48, 64), 48),     # 痲痺
    (0x1000, 0x2000, (64, 64), 64),  # 咀咒 (否则 幸運進行曲 0x2000 → (80,64))
    (0x8000, 0x4000, (112, 64), 80), # 返荷杖 (否则 斗轉星移 0x4000 → (96,64))
    (0x10000, None, (0, 80), 96),    # 強力森巴
    (0x20000, None, (16, 80), 112),  # 強力防禦
)
ALT_SRC = {0x2000: (80, 64), 0x4000: (96, 64)}

_fonts: dict = {}
_smenu: pygame.Surface | None = None
_glyph_cache: dict = {}


# 新細明體 16px 的字形: 半角大写/数字约 9px 高、全角约 12px 高 (原生截图量); 系统字体按字形高度挑字号
FONT_SIZE_ASCII, FONT_SIZE_CJK = 12, 14
BAR_Y_OFFSET = 8          # FUN_004cf1ed 贴在画面框 (左, 上+8)


def _get_font(cjk: bool) -> pygame.font.Font:
    size = FONT_SIZE_CJK if cjk else FONT_SIZE_ASCII
    f = _fonts.get(size)
    if f is None:
        from scenes.menu import load_chinese_font
        f = _fonts[size] = load_chinese_font(size)
    return f


def _get_smenu() -> pygame.Surface:
    global _smenu
    if _smenu is None:
        from core.sprites.base import UI_DIR
        s = pygame.image.load(str(UI_DIR / "SMENU.png"))
        try:
            s = s.convert()
        except pygame.error:
            pass
        s.set_colorkey((0, 0, 0))
        _smenu = s
    return _smenu


def _glyph(ch: str, color) -> pygame.Surface:
    key = (ch, color)
    g = _glyph_cache.get(key)
    if g is None:
        g = _get_font(ord(ch) >= 0x80).render(ch, False, color)
        _glyph_cache[key] = g
    return g


def _text_width(text: str) -> int:
    return sum(8 if ord(c) < 0x80 else 16 for c in text)


def draw_text(surf: pygame.Surface, x: int, cy: int, text: str, pair) -> None:
    """FUN_0041db29: 新細明體 16px 等宽 (半角 8 / 全角 16), y = 垂直中线; 先描边后主色."""
    fg, sh = pair

    def put(ox: int, oy: int, color) -> None:
        cx = x + ox
        for c in text:
            w = 8 if ord(c) < 0x80 else 16
            if c != ' ':
                g = _glyph(c, color)
                surf.blit(g, (cx + (w - g.get_width()) // 2, cy + oy - g.get_height() // 2))
            cx += w
    for dx, dy in OUTLINE:
        put(dx, dy, sh)
    put(0, 0, fg)


def hp_pair(hp: int, max_hp: int):
    if hp > max_hp // 2:
        return PAIR_GOOD
    if hp > max_hp // 4:
        return PAIR_MID
    if hp < 1:
        return PAIR_DEAD
    return PAIR_LOW


def render_bar(rows) -> pygame.Surface:
    """整条状态栏 (len(rows) × 128 × 80, 透明底). rows = energy.status_snapshot() 列表 (或 BattleUnit, 现取)."""
    from core.battle import energy
    rows = [r if isinstance(r, SimpleNamespace) else energy.status_snapshot(r) for r in rows]
    surf = pygame.Surface((max(1, len(rows)) * COL_W, BAR_H), pygame.SRCALPHA)
    smenu = _get_smenu()
    for i, u in enumerate(rows):
        x = i * COL_W
        hp = u.hp
        base = PAIR_DEAD if hp < 1 else PAIR_NORMAL
        draw_text(surf, x + 8, 10, u.name, base)          # 原版是繁体名; 重制版界面统一简体
        draw_text(surf, x + 80, 10, f"Lv{u.level:3d}", base)
        draw_text(surf, x + 8, 30, f"HP:     /{u.max_hp:4d}", base)
        draw_text(surf, x + 40, 30, f"{max(0, hp):4d}", hp_pair(hp, u.max_hp))
        if u.max_mp < 1:
            draw_text(surf, x + 8, 50, "SG", base)
        else:
            draw_text(surf, x + 8, 50, f"MP:     /{u.max_mp:4d}", base)
            draw_text(surf, x + 40, 50, f"{u.mp:4d}", PAIR_DEAD if hp < 1 else PAIR_MP)
        t = u.etype
        if t in (energy.ENERGY_SG, energy.ENERGY_SG2) and u.sg_ok:
            px_tab = energy.SG_GAUGE_PX[t]
            full_w = len(energy.SG_THRESHOLDS[t]) * 16
            px = px_tab[max(0, min(energy.SG_MAX, u.sg))]
            if full_w - px > 0:
                surf.blit(smenu, (x + 40 + px, 42), pygame.Rect(px, 32, full_w - px, 16))
            if px > 0:
                surf.blit(smenu, (x + 40, 42), pygame.Rect(0, 48, px, 16))
        bits = u.status_bits
        for bit, alt, src, ix in STATUS_ICONS:
            if bits & bit:
                s = src
            elif alt is not None and bits & alt:
                s = ALT_SRC[alt]
            else:
                continue
            surf.blit(smenu, (x + ix, 62), pygame.Rect(s[0], s[1], 16, 16))
    return surf


def tick(scene: "BattleScene") -> None:
    """FUN_004cf1ed: 战斗进行中可见高度每 tick +4 到 80; 结束 (胜负) 每 tick -4."""
    from core.battle.tactics import Phase
    h = getattr(scene, '_status_bar_h', 0)
    if scene.battle.phase in (Phase.VICTORY, Phase.DEFEAT):
        h = max(0, h - SLIDE_STEP)
    else:
        h = min(BAR_H, h + SLIDE_STEP)
    scene._status_bar_h = h


def draw(scene: "BattleScene") -> None:
    h = getattr(scene, '_status_bar_h', 0)
    if h <= 0:
        return
    snap = getattr(scene.battle, 'status_snapshot', None)
    bar = render_bar(snap if snap is not None else scene.battle.players)
    ox, oy = getattr(scene, 'battle_view_origin', (0, 0))
    scene.surface.blit(bar, (ox, oy + BAR_Y_OFFSET), pygame.Rect(0, BAR_H - h, bar.get_width(), h))
