"""战斗场景单位渲染 — 活/死/虚弱/受击/攻击 状态机 + 朝向小三角.

全部写成自由函数, 第一参数 scene 当 namespace 用 (拿 scene.surface / scene.battle /
scene.small / 常量等). 比 mixin 直观, 比把 200 行塞回 BattleScene 干净.

底层图元 (blit_unit / blit_shadow / pick_locomotion_frame) 仍走 scenes.unit_render —
那层是场景无关的, 跟 world_map 共用.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.sprites.atlas_classes import (
    DEFAULT_IDLE_DIRECTION_COLS,
    idle_key_from_walk_key,
    is_flying_sprite,
)
from core.sprites.base import TILE_W, TILE_H, facing_to_direction
from core.sprites.loaders import get_character_sprite, get_idle_sprite
from scenes.unit_render import blit_shadow, blit_unit, pick_locomotion_frame

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def draw_units(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    """主单位渲染. Y-排序 + 视椎裁剪 + (shadow + sprite) blit.

    分支:
      blink-off    敌人闪烁消失的 off 半周期, 整个单位不画
      dead corpse  死亡动画 (fall + corpse), 玩家永久, 敌人闪烁掉
      dying pose   HP=0 + 数字 flash 未到, 显示虚弱半蹲
      attacking    fm 逐帧 BBox + anchor (per-character 路径 + enemy global atlas 路径)
      reaction     ps_*06 row 2/3/4 + 像素位移
      idle/walk    通用 locomotion (含 weakened ping-pong + flying flap)
    """
    # Y-排序: render_y 大的 (屏幕下方) 后画 → 在前. 同 y 时把当前行动单位放最后, 防被遮.
    # 死单位: 玩家永远显示 (尸体可被复活), 敌人完成闪烁后跳过 (= 视觉消失但仍在 list).
    def _should_render(u):
        if u.alive: return True
        if u.is_player: return True   # 留尸
        return u.death_anim_time_ms < scene.ENEMY_DEATH_TOTAL_MS
    units = sorted(
        (u for u in scene.battle.all_units if _should_render(u)),
        key=lambda u: (u.render_y, u is scene.battle.current),
    )
    for u in units:
        rect = scene._unit_rect(u, cam_x, cam_y)
        cx, cy = rect.centerx, rect.centery
        # 视椎裁剪 (大致)
        if rect.right < 0 or rect.left > scene.surface.get_width():
            continue
        if rect.bottom < 0 or rect.top > scene.surface.get_height():
            continue
        # 敌人尸体闪烁阶段: blink-off 那帧整个单位 (shadow + 尸体) 都不画.
        if dead_blink_off(scene, u):
            continue
        # 孙悟空召唤隐身阶段: caster 完全不画 (神兽攻击时孙悟空已翻跟头消失).
        if getattr(u, 'cast_hidden', False):
            continue
        # 影子: 活/死单位都画, 跟随单位一起出现/消失 (敌人 blink 期跟着闪).
        blit_shadow(scene.surface, scene._shadow_surf, cx, cy)
        # 死亡分支 (settle_pending 时抑制: AOE 延迟结算, 保持站立直到统一释放)
        if not u.alive and not u.settle_pending:
            if u.death_anim_time_ms >= 0:
                draw_dead_unit(scene, u, cx, cy)
            else:
                draw_dying_pose(scene, u, cx, cy)
            # 原版: 敌人死亡闪烁时 HP/MP 与尸体门控在同一可见位 → 一起闪烁.
            # dead_blink_off 已在 blink-off 帧 continue 跳过整个单位, 故这里照画即同步闪.
            _draw_enemy_hp_mp(scene, u, cx, cy)
            continue
        # 主体: 有 sprite_key 的用真实 atlas, 否则保留色块
        r = rect.inflate(-8, -8)
        if u.sprite_key:
            _draw_live_sprite(scene, u, cx, cy)
        else:
            color = u.color if not u.has_acted else tuple(c // 2 for c in u.color)
            pygame.draw.rect(scene.surface, color, r)
            pygame.draw.rect(scene.surface, (0, 0, 0), r, 2)
        if u is scene.battle.current:
            pygame.draw.rect(scene.surface, scene.HIGHLIGHT, rect.inflate(-2, -2), 2)
            # 朝向小三角 (黄)
            draw_facing_arrow(scene, u, rect)
        # HP / MP 持久标签: 仅敌人显示 (己方状态后续移到屏幕顶部 HUD).
        _draw_enemy_hp_mp(scene, u, cx, cy)


def _draw_enemy_hp_mp(scene: "BattleScene", u, cx: int, cy: int) -> None:
    """敌人头顶 HP/MP 标签 (己方在屏幕顶部 HUD). 活/死单位都画 — 死亡时随尸体一起闪烁
    (原版: HP/MP 与精灵门控同一可见位).
    字号 ≈ float text (sbtlfont 14px); 用普通像素字 scene.small (13). 居中堆叠在头顶.
    颜色: HP 绿(健康) / 黄(虚弱 <40% 或已死) / MP 蓝. 显示用 display_hp/display_weakened
    (受击后滞后到结算 = 数字闪烁时才掉血变色)."""
    if u.is_player:
        return
    weakened = u.display_weakened or u.display_hp <= 0
    hp_color = scene.HP_WEAKENED_COLOR if weakened else scene.HP_NUM_COLOR
    label_cx = cx + 8        # 中间偏右
    mp = scene.small.render(str(u.mp), True, scene.MP_NUM_COLOR)
    mp_rect = mp.get_rect(midbottom=(label_cx, cy - 25))
    scene.surface.blit(mp, mp_rect)
    hp = scene.small.render(str(u.display_hp), True, hp_color)
    scene.surface.blit(hp, hp.get_rect(midbottom=(label_cx, mp_rect.top - 1)))


def _draw_live_sprite(scene: "BattleScene", u, cx: int, cy: int) -> None:
    """活单位的 sprite 主体 (reaction / attacking / locomotion 三选一)."""
    cs = get_character_sprite(u.sprite_key)
    react_off = (0, 0)
    anchor: tuple[int, int] | None = None    # (feet_x, feet_y) within frame; None=用默认 bottom-center
    frame: pygame.Surface
    # 孙悟空召唤翻跟头: cast_flip_frame 非 None → 显示 ps_CSON105 第 N 帧 (覆盖一切, 方向无关).
    if getattr(u, 'cast_flip_frame', None) is not None:
        from core.sprites.loaders import get_somersault_frame, SOMERSAULT_ANCHOR
        try:
            frame = get_somersault_frame(u.cast_flip_frame)
            blit_unit(scene.surface, frame, SOMERSAULT_ANCHOR,
                      tile_center_x=cx, tile_center_y=cy)
            return
        except (FileNotFoundError, ValueError):
            pass  # 加载失败退回正常 render
    # reaction 序列优先级最高: 用脚本指定的 atlas-06 帧 + 像素位移
    if u.reaction_seq is not None and u.reaction_frame is not None:
        try:
            idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
            col = u.reaction_frame % 4
            row = u.reaction_frame // 4
            frame = idle.sheet.frame(col, row)
            anchor = idle.feet_for_facing(u.facing)
            ox, oy = u.reaction_offset
            react_off = (int(round(ox)), int(round(oy)))
        except FileNotFoundError:
            frame = cs.frame_for_facing(u.facing, 0)
    # 攻击中: 用 fm 逐帧 BBox + anchor (从 fm_frames.py 逆向得到).
    # 状态全部从 anim_engine.Entity 读: atlas_slot, frame_idx, x/y (16.16 fixed → px).
    # 两条 render 路径:
    #   (a) Player ATK_A/B/C (atlas_slot 抽象 0/1/5): 走 per-character attack_fm_atlas() lookup
    #       + phase-based sub-frame 插值 (cols > n 的角色用)
    #   (b) Enemy ENEMY_* (atlas_slot 是全局 idx, e.g. 192=ccrow_g0): 走 atlas_resource() 反查,
    #       frame_idx 直接当 atlas 内索引 (敌方 seq 不需要 phase 数学)
    elif u.is_attacking:
        frame, anchor = _resolve_attack_frame(scene, u, cs)
    else:
        # 通用 locomotion: 走路 / 待机 / (HP<40%) 虚弱, 用共享 picker
        flying = is_flying_sprite(u.sprite_key)
        try:
            idle_sprite = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
        except FileNotFoundError:
            idle_sprite = None
        weakened_sprite = None
        # 虚弱姿态跟 display_hp 一起在"落定"时切换 (原版: HP 与虚弱都读真实表, 提交时一起变,
        # 早于数字闪烁). display_weakened 基于 display_hp → 受击后滞后到落定才虚弱.
        if u.display_weakened:
            from core.sprites.atlas_classes import weakened_key_from_walk_key
            from core.sprites.loaders import get_weakened_sprite
            try:
                weakened_sprite = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
            except FileNotFoundError:
                pass    # 该角色无 ps_*04 atlas, 退回普通 walk/idle
        frame, anchor = pick_locomotion_frame(
            cs, idle_sprite, u.facing, u.anim,
            walk_period_ms=scene.WALK_FRAME_PERIOD_MS,
            idle_period_ms=scene.IDLE_FRAME_PERIOD_MS,
            flying=flying,
            weakened_sprite=weakened_sprite,
        )
    # 攻击中不要变半透明 (会让玩家误以为已结束行动)
    alpha = 140 if (u.has_acted and not u.is_attacking) else None
    # 攻击位移: entity.x/y 是 16.16 fixed point → 右移 16 拿像素.
    # 若当前在 MOVE 等待期 (move_total_ticks > 0), 从 move_start_x lerp 到 entity.x,
    # 进度 = (move_total - ticks_remaining + sub_t) / move_total, 平滑滑动.
    ax = ay = 0
    if u.is_attacking:
        ent = u.entity
        move_total = ent.user_data.get('_move_total_ticks', 0)
        if move_total > 0 and ent.ticks > 0:
            from core.attack_seq import ATTACK_TICK_MS as _ATM
            sub_t = scene._eng_acc_ms / _ATM
            progress = max(0.0, min(1.0, (move_total - ent.ticks + sub_t) / move_total))
            sx = ent.user_data.get('_move_start_x', ent.x)
            sy = ent.user_data.get('_move_start_y', ent.y)
            ax = int(sx + (ent.x - sx) * progress) >> 16
            ay = int(sy + (ent.y - sy) * progress) >> 16
        else:
            ax = ent.x >> 16
            ay = ent.y >> 16
    if anchor is None:
        # 兜底: bottom-center 当 anchor (frame 底中心)
        fw, fh = frame.get_size()
        anchor = (fw // 2, fh)
    blit_unit(
        scene.surface, frame, anchor,
        tile_center_x=cx, tile_center_y=cy,
        offset_x=react_off[0] + int(round(ax)),
        offset_y=react_off[1] + int(round(ay)),
        alpha=alpha,
    )


def _resolve_attack_frame(scene: "BattleScene", u, cs):
    """根据 entity.atlas_slot/frame_idx 选 fm 帧 + 计算 sub-frame 插值.
    返回 (frame_surface, anchor). 找不到对应 fm 资源时退到 ps_*06 row 2 (出招前倾)."""
    from core.character_sprites import attack_fm_atlas, attack_total_frames
    from core.attack_seq import frames_per_dir, ATTACK_TICK_MS
    from core.sprites.loaders import get_fm_surface
    from core.fm_frames import FM_FRAMES, cols_in_atlas
    from core.raw_attack_seqs import atlas_resource

    fm_data = None
    fm_name = None
    ent = u.entity
    slot_lo = ent.atlas_slot & 0xffff
    fm_frame_idx = ent.frame_idx if slot_lo != 0 or ent.frame_idx != 0 else None
    # 路径选择: 抽象槽 {0,1,5} (= ATK_A/B/C 普攻, 走 per-character atlas remap), 其余都是
    # 真实全局 atlas idx (技能 seq + 敌人 + 三藏 SAM_ATK_B). 注意 csam_g0=7 < 8 也是真实 atlas,
    # 旧的 ">=8" 阈值会把它误判成 per-character → 生命之火 (atlas 7) 方向/sprite 全错.
    is_global_atlas = slot_lo not in (0, 1, 5)
    if is_global_atlas and fm_frame_idx is not None:
        atlas_key = atlas_resource(slot_lo)
        if atlas_key:
            fm_name = "fm_" + atlas_key.upper()
            atlas_frames = FM_FRAMES.get(atlas_key)
            if atlas_frames and 0 <= fm_frame_idx < len(atlas_frames):
                fm_data = atlas_frames[fm_frame_idx]
    elif fm_frame_idx is not None:
        # per-character 路径
        fm_name = attack_fm_atlas(u.name)
        if fm_name:
            atlas_key = fm_name.lower().removeprefix("fm_")
            atlas_frames = FM_FRAMES.get(atlas_key)
            if atlas_frames:
                n = frames_per_dir(u.name)
                cols = cols_in_atlas(atlas_key)
                override = attack_total_frames(u.name)
                total = override if override is not None else (cols // n) * n
                phase = fm_frame_idx % n
                base = total // n
                remainder = total - base * n
                phase_size = max(1, base + (1 if phase < remainder else 0))
                phase_start = base * phase + min(phase, remainder)
                sub_frame = 0
                if phase_size > 1:
                    fm_total = ent.user_data.get('_fm_total_ticks', 0)
                    if fm_total > 0:
                        sub_t = scene._eng_acc_ms / ATTACK_TICK_MS
                        elapsed = (fm_total - ent.ticks) + sub_t
                        progress = max(0.0, min(0.999, elapsed / fm_total))
                        sub_frame = int(progress * phase_size)
                list_idx = (fm_frame_idx // n) * cols + phase_start + sub_frame
                if 0 <= list_idx < len(atlas_frames):
                    fm_data = atlas_frames[list_idx]
    if fm_data is not None:
        try:
            fx, fy, fw, fh, anc_x, anc_y = fm_data
            surf = get_fm_surface(fm_name)
            frame = surf.subsurface(pygame.Rect(fx, fy, fw, fh))
            return frame, (anc_x, anc_y)
        except (FileNotFoundError, ValueError):
            pass
    # fallback: ps_*06 row 2 (出招前倾姿态)
    try:
        idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
        col = DEFAULT_IDLE_DIRECTION_COLS[facing_to_direction(u.facing)]
        frame = idle.sheet.frame(col, 2)
        anchor = idle.feet_for_facing(u.facing)
        return frame, anchor
    except (FileNotFoundError, IndexError):
        return cs.frame_for_facing(u.facing, 0), None


def draw_dying_pose(scene: "BattleScene", u, cx: int, cy: int) -> None:
    """濒死过渡: HP=0 + reaction 已结束 + 死亡动画未启动 (= 等数字 flash) 时显示虚弱半蹲.
    防止从站立姿势直接进死亡动画 (= 不"站起来再倒下"). anchor 复用 walk feet."""
    if not u.sprite_key:
        return
    from core.sprites.atlas_classes import weakened_key_from_walk_key
    from core.sprites.loaders import get_weakened_sprite
    try:
        weak = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
        walk = get_character_sprite(u.sprite_key)
    except FileNotFoundError:
        return
    frame = weak.frame_for_facing(u.facing, 0)   # col 1 半蹲 (跟正常 weakened 同首帧, 不 ping-pong)
    anchor = walk.feet_for_facing(u.facing)
    blit_unit(scene.surface, frame, anchor,
              tile_center_x=cx, tile_center_y=cy)


def dead_blink_off(scene: "BattleScene", u) -> bool:
    """敌人 fall 后进入闪烁消失阶段, 这一帧是否处于 'off' 半周期 (整个单位含 shadow 都不画)."""
    if u.alive or u.is_player or u.death_anim_time_ms < 0:
        return False
    t_post_fall = u.death_anim_time_ms - scene.DEATH_FALL_TOTAL_MS
    if t_post_fall < 0:
        return False
    return (t_post_fall // scene.ENEMY_DEATH_FLASH_PERIOD_MS) % 2 == 1


def draw_dead_unit(scene: "BattleScene", u, cx: int, cy: int) -> None:
    """死亡渲染: ps_*04 row 4 两帧 fall (800ms/帧 = 0x14 ticks 来自 exe), 玩家永久躺尸,
    敌人 hold 后闪烁消失 (闪烁的 off 帧由 dead_blink_off 拦在调用前)."""
    if not u.sprite_key:
        return
    from core.sprites.atlas_classes import weakened_key_from_walk_key
    from core.sprites.loaders import get_weakened_sprite
    try:
        weak = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
    except FileNotFoundError:
        return
    t = max(0, u.death_anim_time_ms)
    # fall: 0/1 两帧, 每帧 800ms; 之后永久 hold frame 1 (= 躺平 corpse)
    if t < scene.DEATH_FALL_TOTAL_MS:
        frame_idx = t // scene.DEATH_FRAME_MS
    else:
        frame_idx = 1
    frame = weak.death_frame(int(frame_idx))
    # 用 corpse 的 body 中心当 anchor (= 让躺尸居中填 tile, 不再贴 tile 中线上半部)
    anchor = weak.death_anchor(int(frame_idx))
    blit_unit(scene.surface, frame, anchor,
              tile_center_x=cx, tile_center_y=cy)


def draw_facing_arrow(scene: "BattleScene", u, tile_rect: pygame.Rect) -> None:
    """在 tile 边框对应朝向的边上画一个小黄三角."""
    cx, cy = tile_rect.centerx, tile_rect.centery
    dx, dy = u.facing
    # 三角顶点贴 tile 边沿 (-2 留缝). 横向用 TILE_W/2, 纵向用 TILE_H/2.
    tip_x = cx + dx * (TILE_W // 2 - 2)
    tip_y = cy + dy * (TILE_H // 2 - 2)
    tip = (tip_x, tip_y)
    if dx != 0:  # 左/右
        base1 = (tip[0] - dx * 6, tip[1] - 5)
        base2 = (tip[0] - dx * 6, tip[1] + 5)
    else:        # 上/下
        base1 = (tip[0] - 5, tip[1] - dy * 6)
        base2 = (tip[0] + 5, tip[1] - dy * 6)
    pygame.draw.polygon(scene.surface, scene.HIGHLIGHT, [tip, base1, base2])
