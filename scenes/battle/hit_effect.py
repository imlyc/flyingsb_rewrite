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


def draw_hit_effects(scene: "BattleScene", cam_x: int, cam_y: int, behind: bool = False) -> None:
    """扫 engine.entities 找 kind='hit_effect' 的实体, 按当前 atlas_slot + frame_idx 画.
    支持 mid-seq atlas 切换 (= 技能 extra fx 中段从一个 atlas 换到另一个), 每帧从
    entity.atlas_slot 反查 atlas_key, 不缓存.
    投射物 (think_fn 物理驱动) 在飞行期没 seq running, 但 visible flag (0x40) 为 1, 也要画.

    绘制顺序: 按 user_data['draw_order'] 升序 (默认 0), 同序保持 spawn 顺序. 神兽本体
    (draw_order 高) 最后画 = 在冰锥等粒子之上 (e.g. 青龙盖在冰锥上).

    behind=True: 只画标了 'behind_units' 的 (= 敌人身后的分身, 在 draw_units 之前调);
    behind=False: 画其余的 (默认, draw_units 之后调).
    """
    # 收集可见的 hit_effect, 稳定按 draw_order 排序 (高的后画 = 上层)
    ents = [e for e in scene.battle.engine.entities
            if e.user_data.get('kind') == 'hit_effect'
            and (e.is_playing() or e.user_data.get('projectile'))
            and bool(e.user_data.get('behind_units')) == behind]
    ents.sort(key=lambda e: e.user_data.get('draw_order', 0))
    for ent in ents:
        # 角色型特效 (分身) 加落地影子 → 接地 (否则看起来浮空)
        if ent.user_data.get('shadow'):
            sh = load_shadow()
            r = sh.get_rect(center=((ent.x >> 16) - cam_x, (ent.y >> 16) - cam_y))
            scene.surface.blit(sh, r)
        # ps_ 网格 sheet (分身下落用 ps_CSON102 站姿, 不在 fm atlas 系统): 按 (cols, fw, fh, anchor) 切格
        ps = ent.user_data.get('ps_sheet')
        if ps is not None:
            try:
                sheet = get_fm_surface(ps)
            except FileNotFoundError:
                continue
            cols, fw, fh, ax, ay = ent.user_data['ps_grid']
            fi = ent.frame_idx
            col, row = fi % cols, fi // cols
            sub = sheet.subsurface(pygame.Rect(col * fw, row * fh, fw, fh))
            sx = (ent.x >> 16) - cam_x - ax
            sy = (ent.y >> 16) + (ent.z >> 16) - cam_y - ay
            scene.surface.blit(sub, (sx, sy))
            continue
        slot_lo = ent.atlas_slot & 0xffff
        atlas_key = atlas_resource(slot_lo)
        if atlas_key is None:
            continue
        frames = FM_FRAMES.get(atlas_key)
        if frames is None or not (0 <= ent.frame_idx < len(frames)):
            continue
        try:
            atlas_surf = get_fm_surface("fm_" + atlas_key.upper())
        except FileNotFoundError:
            continue
        fx, fy, fw, fh, ax, ay = frames[ent.frame_idx]
        sub = atlas_surf.subsurface(pygame.Rect(fx, fy, fw, fh))
        if ent.user_data.get('flip_x'):          # 水平翻转 (祥云朝向): 镜像图 + 镜像锚点
            sub = pygame.transform.flip(sub, True, False)
            ax = fw - ax
        sx = (ent.x >> 16) - cam_x - ax
        # z 表示离地面高度 (< 0 = 上空): 加到 screen y 上让飞行物显示在 world_y 上方.
        sy = (ent.y >> 16) + (ent.z >> 16) - cam_y - ay
        scene.surface.blit(sub, (sx, sy))
