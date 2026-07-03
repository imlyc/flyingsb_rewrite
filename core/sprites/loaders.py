"""资源加载入口 + 缓存. PCX 磁盘读取只发生一次.

公开:
  load_character_sprite / get_character_sprite
  get_idle_sprite / get_weakened_sprite
  get_fm_surface / get_sbtlfont_surface / sbtlfont_frame
  clear_cache
"""

from __future__ import annotations

import pygame

from core.sprites.base import (
    AUTO,
    DEFAULT_CHAR_FRAME_SIZE,
    Direction,
    SPRITES_DIR,
    SpriteSheet,
    load_image,
)
from core.sprites.atlas_classes import (
    CharacterSprite,
    DEFAULT_DIRECTION_ROWS,
    DEFAULT_IDLE_DIRECTION_COLS,
    IdleSprite,
    WEAKENED_DIRECTION_ROWS,
    WeakenedSprite,
    is_flying_sprite,
)


# ----- 角色 walk atlas -----
_CACHE: dict[str, CharacterSprite] = {}


def load_character_sprite(
    resource_name: str,
    frame_w: int = DEFAULT_CHAR_FRAME_SIZE[0],
    frame_h: int = DEFAULT_CHAR_FRAME_SIZE[1],
    direction_rows: dict[Direction, int] | None = None,
) -> CharacterSprite:
    """从 assets/sprites/<resource_name>.pcx 加载角色 atlas.

    名字通常带 'ps_' / 'fm_' 前缀, 决定色键. 例: 'ps_CAMAZ000'.
    """
    path = SPRITES_DIR / f"{resource_name}.pcx"
    if not path.exists():
        raise FileNotFoundError(path)
    surf = load_image(path, color_key=AUTO)
    sheet = SpriteSheet(surf, frame_w, frame_h)
    return CharacterSprite(
        sheet=sheet,
        direction_rows=direction_rows or DEFAULT_DIRECTION_ROWS,
    )


def get_character_sprite(resource_name: str, **kwargs) -> CharacterSprite:
    if resource_name not in _CACHE:
        cs = load_character_sprite(resource_name, **kwargs)
        if is_flying_sprite(resource_name):
            cs.walk_frames = 4   # col 4 空白, 只循环 cols 0-3
        _CACHE[resource_name] = cs
    return _CACHE[resource_name]


def clear_cache() -> None:
    _CACHE.clear()


# ----- 待机 + 虚弱 atlas -----
_IDLE_CACHE: dict[str, IdleSprite] = {}
_WEAKENED_CACHE: dict[str, WeakenedSprite] = {}


def get_idle_sprite(resource_name: str) -> IdleSprite:
    if resource_name not in _IDLE_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        surf = load_image(path, color_key=AUTO)
        sheet = SpriteSheet(surf, DEFAULT_CHAR_FRAME_SIZE[0], DEFAULT_CHAR_FRAME_SIZE[1])
        _IDLE_CACHE[resource_name] = IdleSprite(
            sheet=sheet,
            direction_cols=DEFAULT_IDLE_DIRECTION_COLS,
        )
    return _IDLE_CACHE[resource_name]


def get_weakened_sprite(resource_name: str) -> WeakenedSprite:
    if resource_name not in _WEAKENED_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        surf = load_image(path, color_key=AUTO)
        # 显式 64×96 (= DEFAULT_CHAR_FRAME_SIZE), atlas 自动算 cols×rows = 3×5
        sheet = SpriteSheet(surf, DEFAULT_CHAR_FRAME_SIZE[0], DEFAULT_CHAR_FRAME_SIZE[1])
        _WEAKENED_CACHE[resource_name] = WeakenedSprite(
            sheet=sheet,
            direction_rows=WEAKENED_DIRECTION_ROWS,
        )
    return _WEAKENED_CACHE[resource_name]


# ----- SMENU 战斗行动菜单图标 -----
# assets/ui/SMENU.png 是 128×96 = 4 列 × 3 行 × 32×32 图标. row 0 是 ESC 弹出的十字菜单
# 4 个图标 (左→右): SKILL (面孔), ITEM (宝珠), SETTINGS (OP), END (回合结束).
# 其它两行是 HUD 用 (HP/MP 数字 + 状态), 暂未用.
SMENU_ICON_SIZE = 32
SMENU_SKILL = 0
SMENU_ITEM = 1
SMENU_SETTINGS = 2
SMENU_END = 3
_smenu_atlas: pygame.Surface | None = None
_smenu_cache: dict[int, pygame.Surface] = {}


def load_smenu_icon(idx: int) -> pygame.Surface:
    """加载 SMENU.png 第 idx 个图标 (0..11, 行优先). 0-3 是 ESC 菜单的四个."""
    from core.sprites.base import UI_DIR
    global _smenu_atlas
    if _smenu_atlas is None:
        # 黑底 (0,0,0) 是透明色 — 实测每个 icon 右/下边的黑像素应该透出底层 (tile/sprite).
        _smenu_atlas = pygame.image.load(str(UI_DIR / "SMENU.png")).convert()
        _smenu_atlas.set_colorkey((0, 0, 0))
    if idx not in _smenu_cache:
        col = idx % 4
        row = idx // 4
        rect = pygame.Rect(col * SMENU_ICON_SIZE, row * SMENU_ICON_SIZE,
                           SMENU_ICON_SIZE, SMENU_ICON_SIZE)
        _smenu_cache[idx] = _smenu_atlas.subsurface(rect).copy()
    return _smenu_cache[idx]


# ----- fm_ atlas (攻击/特效) -----
# 逆向得到的真实数据: 每帧有显式 BBox (x, y, w, h) + 锚点 (ax, ay).
# fm atlas 不是均匀网格! 帧大小因姿态变化, 用逐帧 BBox 才能取出干净 sprite.
# 数据在 core/fm_frames.py (6610 帧, 334 个 atlas, 从 FlyingSB.exe 0x5bf8a8 表逆向).
_FM_SURF_CACHE: dict[str, pygame.Surface] = {}


# 个别 atlas 透明色不在左上角 (AUTO 采样 (0,0) 会取错): 显式指定. eson09 大凤凰背景=绿(0,255,0),
# 但 (0,0) 是帧 BBox 外的黑边 → AUTO 误取黑, 绿背景没抠掉 (用户: 凤凰背景还是绿色).
_FM_COLORKEY_OVERRIDE: dict[str, tuple[int, int, int]] = {
    "fm_ESON09": (0, 255, 0),
}


def get_fm_surface(resource_name: str) -> pygame.Surface:
    """加载 fm_ atlas 大图. 帧从 fm_frames.FM_FRAMES 取 BBox 子表面.
    也能加载任意 .pcx (e.g. ps_CSON105 翻跟头), 不限 fm_ 前缀."""
    if resource_name not in _FM_SURF_CACHE:
        path = SPRITES_DIR / f"{resource_name}.pcx"
        if not path.exists():
            raise FileNotFoundError(path)
        ck = _FM_COLORKEY_OVERRIDE.get(resource_name, AUTO)
        _FM_SURF_CACHE[resource_name] = load_image(path, color_key=ck)
    return _FM_SURF_CACHE[resource_name]


# (孙悟空翻跟头 ps_CSON105 (4×2 网格 64×96, 8 帧, 脚锚 32,84) 现由 units.py mode2 通用
#  ps_ 网格分支渲染 (slot 5 → ps_XXX105), 专用 get_somersault_frame loader 已删.)


# ---------- SBTLFONT 伤害/MISS 数字字体 ----------
# fm_SBTLFONT.pcx (130x56, 52 帧 unique BBox, 来自 fm_frames.SBTLFONT).
# 来源 exe FUN_004d05d8 + FUN_004d074e: 把 char (ASCII) 转 frame_idx.
#   FUN_004d074e 路径 (mass-spawn): frame_idx = char - 0x30 → 数字 '0'..'9' = frames 0..9
#   FUN_004d0488 路径 (drip-spawn): frame_idx = char - 0x23 → '0'..'9' = frames 13..22
# 我们用 drip 路径 (frames 13-22) 作为标准伤害数字, 跟用户观察一致.
# MISS: exe 用 chars 0x3a/0x3b/0x3c/0x3c (-0x23) = frames 23/24/25/25 (字母 'MISS' 在 atlas 后段)
SBTLFONT_DIGIT_BASE_FRAME = 13                         # row 1 cols 0-9 = 红色伤害数字 (跟 MISS 同行同色)
SBTLFONT_MISS_FRAMES = (23, 24, 25, 25)                # row 1 cols 10-12 = 红色 M/I/S/S
SBTLFONT_DAMAGE_BASE_FRAME = SBTLFONT_DIGIT_BASE_FRAME # 别名: 伤害数字也是红色 (= 跟 MISS 一致)
SBTLFONT_HEAL_BASE_FRAME = 0                           # row 0 cols 0-9 = 白色回血数字 (生命之火)


def get_sbtlfont_surface() -> pygame.Surface:
    return get_fm_surface("fm_SBTLFONT")


def sbtlfont_frame(frame_idx: int) -> tuple[pygame.Surface, int, int]:
    """frame_idx = sbtlfont atlas 内绝对帧号 (调用方自己算好行列, e.g. row0 白 0-9 /
    row1 红伤害 13-22 / row2 青绿 26-35). 返回 (subsurface, anchor_x, anchor_y).
    ⚠ 不再有 digit 快捷映射 — 以前 `<13 → +13` 会把 heal row-0 帧误推到红行."""
    from core.fm_frames import FM_FRAMES
    bbox_data = FM_FRAMES.get("sbtlfont")
    if not bbox_data or frame_idx >= len(bbox_data):
        raise IndexError(f"sbtlfont frame {frame_idx} out of range")
    fx, fy, fw, fh, ax, ay = bbox_data[frame_idx]
    surf = get_sbtlfont_surface().subsurface(pygame.Rect(fx, fy, fw, fh))
    return surf, ax, ay
