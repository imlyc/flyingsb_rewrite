"""命中特效渲染 — 直接读 anim_engine entity (kind='hit_effect') 的状态.

每个 effect 是一个独立 entity, 由 combat._spawn_effect_entity 创建, 跑标准 FM op 字节码
(= 原版 FUN_004d0c90 blood_spawn 同套路). 渲染不需要时基, 只读 entity.frame_idx +
entity.x/y (16.16 fixed 世界像素).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.fm_frames import FM_FRAMES
from core.raw_attack_seqs import atlas_resource
from core.sprites.base import load_shadow
from core.sprites.loaders import get_fm_surface

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def effect_drawn(e) -> bool:
    """画面上的特效实体: kind='hit_effect' 且在播 seq / 投射物 / 飘字, 并带可见位 0x40 —
    exe 战斗绘制循环 FUN_004c8184 `if (flags & 0x40) FUN_004b3663(i)`: 飘字落定后 / 碎冰后半程每 tick XOR 0x40 = 闪烁,
    清 0x40 = 隐去 (冰柱/冰龙本体). 投射物 (think_fn 物理驱动) 飞行期没 seq 在播但带 0x40, 也要画."""
    return (e.user_data.get('kind') == 'hit_effect'
            and bool(e.is_playing() or e.user_data.get('projectile') or e.user_data.get('float'))
            and bool(e.flags & 0x40))


def draw_effect_shadow(scene: "BattleScene", ent, cam_x: int, cam_y: int) -> None:
    """角色型特效 (分身) 的落地影子 → 接地 (否则看起来浮空). 原版影子项键恒 0 = 全部最先画."""
    if ent.user_data.get('shadow'):
        sh = load_shadow()
        r = sh.get_rect(center=((ent.x >> 16) - cam_x, (ent.y >> 16) - cam_y))
        scene.surface.blit(sh, r)


def draw_effect(scene: "BattleScene", ent, cam_x: int, cam_y: int) -> None:
    """按实体当前 atlas_slot + frame_idx 画一个特效 (不含影子; 由 scene 按 core.battle.draw_queue 与单位统一排序后调).
    支持 mid-seq atlas 切换 (技能 extra fx 中段换 atlas): 每帧从 entity.atlas_slot 反查 atlas_key, 不缓存."""
    # ps_ 网格 sheet (分身下落用 ps_CSON102 站姿, 不在 fm atlas 系统): 按 (cols, fw, fh, anchor) 切格
    ps = ent.user_data.get('ps_sheet')
    if ps is not None:
        try:
            sheet = get_fm_surface(ps)
        except FileNotFoundError:
            return
        cols, fw, fh, ax, ay = ent.user_data['ps_grid']
        fi = ent.frame_idx
        col, row = fi % cols, fi // cols
        sub = sheet.subsurface(pygame.Rect(col * fw, row * fh, fw, fh))
        sx = (ent.x >> 16) - cam_x - ax
        sy = (ent.y >> 16) + (ent.z >> 16) - cam_y - ay
        scene.surface.blit(sub, (sx, sy))
        return
    slot_lo = ent.atlas_slot & 0xffff
    atlas_key = atlas_resource(slot_lo)
    if atlas_key is None:
        return
    frames = FM_FRAMES.get(atlas_key)
    if frames is None or not (0 <= ent.frame_idx < len(frames)):
        return
    try:
        atlas_surf = get_fm_surface("fm_" + atlas_key.upper())
    except FileNotFoundError:
        return
    fx, fy, fw, fh, ax, ay = frames[ent.frame_idx]
    sub = atlas_surf.subsurface(pygame.Rect(fx, fy, fw, fh))
    if ent.user_data.get('flip_x'):          # 水平翻转 (祥云朝向): 镜像图 + 镜像锚点
        sub = pygame.transform.flip(sub, True, False)
        ax = fw - ax
    # jx / jy: exe 实体 +0x20 / +0x24 绘制偏移 (16.16, 不进排序键; 鬧鐘抖动)
    sx = ((ent.x + ent.user_data.get('jx', 0)) >> 16) - cam_x - ax
    # z 表示离地面高度 (< 0 = 上空): 加到 screen y 上让飞行物显示在 world_y 上方.
    sy = ((ent.y + ent.user_data.get('jy', 0)) >> 16) + (ent.z >> 16) - cam_y - ay
    scene.surface.blit(sub, (sx, sy))
