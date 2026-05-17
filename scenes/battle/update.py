"""战斗场景每帧更新逻辑.

主入口 tick(scene, dt_ms) 由 BattleScene.update() 调用. 含:
  - 单位 render_x/y 朝逻辑位置插值 (走路 lerp + 路径节点 facing 切换)
  - 玩家长按方向键 → 连续移动 (走 input.poll_player_hold)
  - 伤害事件 → 飘字 spawn + 旧飘字 demote
  - reaction_seq 推进 (受击/闪避脚本)
  - 死亡动画计时门控
  - anim_engine tick 累积
  - 回合切换 + 镜头 lerp + 敌方回合启动 + BGM 切换
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.battle.data import Phase
from core.sprites.base import TILE_W, TILE_H
from scenes.battle import input as input_mod
from scenes.battle.float_text import FloatText

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def tick(scene: "BattleScene", dt_ms: int) -> None:
    now = pygame.time.get_ticks()

    _tick_unit_positions(scene, dt_ms)
    input_mod.poll_player_hold(scene, dt_ms)
    _ingest_damage_events(scene, now)
    _tick_reactions(scene, dt_ms)
    _tick_death_animations(scene, now, dt_ms)
    _tick_anim_engine(scene, dt_ms)

    if not units_animating(scene):
        scene.battle.advance_turn_when_ready()

    _tick_camera(scene)
    _tick_phase_transitions(scene, now)
    _tick_menu_anim(scene, dt_ms)


def _tick_menu_anim(scene: "BattleScene", dt_ms: int) -> None:
    """菜单动画推进:
       - _menu_anim_t: 一级菜单打开 (白方框收缩 + 4 icon 旋转放大)
       - _menu_transition_t: 一级 → 二级 过渡 (3 phase)
    """
    if scene._menu_anim_t is not None:
        scene._menu_anim_t += dt_ms
        if scene._menu_anim_t >= scene.MENU_ANIM_TOTAL_MS:
            scene._menu_anim_t = None

    if scene._menu_transition_t is not None:
        scene._menu_transition_t += dt_ms
        # phase B 开始: 提升 _submenu 状态让二级菜单 panel 开始 draw
        if scene._menu_transition_t >= scene.MENU_TRANSITION_A_MS and scene._submenu is None:
            scene._submenu = 'skill'
        if scene._menu_transition_t >= scene.MENU_TRANSITION_TOTAL_MS:
            scene._menu_transition_t = None
            scene._menu_open = False    # 一级菜单收掉, 只剩二级

    if scene._menu_close_t is not None:
        scene._menu_close_t += dt_ms
        if scene._menu_close_t >= scene.MENU_CLOSE_MS:
            scene._menu_close_t = None
            scene._submenu = None
            scene._menu_open = True
            # 接着播一级 open 动画 (跟 ESC 触发的相同)
            scene._menu_anim_t = 0

    if scene._menu_dismiss_t is not None:
        scene._menu_dismiss_t += dt_ms
        if scene._menu_dismiss_t >= scene.MENU_DISMISS_MS:
            scene._menu_dismiss_t = None
            scene._menu_open = False
            scene._input_gated = True
            action = scene._menu_dismiss_action
            scene._menu_dismiss_target = None
            scene._menu_dismiss_action = None
            if action == 'end_turn':
                scene.battle.player_end_turn()


def _tick_unit_positions(scene: "BattleScene", dt_ms: int) -> None:
    """单位渲染坐标按速度向当前路径节点插值. 沿格逐步走, 防止两轴并行 lerp 出 45° 飞行."""
    step = scene.UNIT_TILES_PER_SEC * dt_ms / 1000.0
    for unit in scene.battle.all_units:
        if not unit.alive:
            continue
        # 当前 lerp 目标: 路径头节点 / 否则 unit 逻辑位置
        if unit.move_path:
            tgt_x, tgt_y = unit.move_path[0]
        else:
            tgt_x, tgt_y = unit.x, unit.y
        moving = False
        for axis_name, target in (("x", tgt_x), ("y", tgt_y)):
            rattr = f"render_{axis_name}"
            rval = getattr(unit, rattr)
            delta = target - rval
            if abs(delta) <= step:
                if rval != float(target):
                    setattr(unit, rattr, float(target))
            else:
                setattr(unit, rattr, rval + (step if delta > 0 else -step))
                moving = True
        # 到达当前节点 → 弹出, 切换 facing 到下一段方向
        if (unit.move_path
                and abs(unit.render_x - unit.move_path[0][0]) < scene.ANIM_EPSILON
                and abs(unit.render_y - unit.move_path[0][1]) < scene.ANIM_EPSILON):
            arrived = unit.move_path.pop(0)
            if unit.move_path:
                nxt = unit.move_path[0]
                ddx = nxt[0] - arrived[0]
                ddy = nxt[1] - arrived[1]
                if abs(ddx) >= abs(ddy) and ddx != 0:
                    unit.facing = (1 if ddx > 0 else -1, 0)
                elif ddy != 0:
                    unit.facing = (0, 1 if ddy > 0 else -1)
            else:
                # 路径跑完: 还原 AI 设的攻击朝向 (否则 facing 留在最后一段移动方向)
                if unit.post_move_facing is not None:
                    unit.facing = unit.post_move_facing
                    unit.post_move_facing = None
        # 行走帧时间 / 待机帧时间互补累加 (静止 = 走帧重置, 移动 = 待机帧重置)
        unit.anim.tick(dt_ms, moving=moving)


def _ingest_damage_events(scene: "BattleScene", now: int) -> None:
    """把 battle 的伤害事件转飘字, 立即 spawn (跟攻击动画 IMPACT 同步).
    多段攻击: 每次 IMPACT 都 spawn, 但同位置先前的标记为非 final → 立即消失,
    让最后一发占位 (= 最后一发才走完整 rise + hold + flash 生命周期)."""
    for ev in scene.battle.damage_events:
        wx = ev.x * TILE_W + TILE_W // 2
        wy = ev.y * TILE_H + TILE_H // 2 - 10
        # 同位置先前的 float 全部 demote (instant remove), 只留新一发
        scene._floats = [f for f in scene._floats
                         if abs(f.world_x - wx) > 4 or abs(f.world_y - wy) > 4]
        scene._floats.append(FloatText(ev.damage, ev.remaining_hp, wx, wy, now, miss=ev.miss))
    scene.battle.damage_events.clear()
    scene._floats = [f for f in scene._floats if f.alive(now)]


def _tick_reactions(scene: "BattleScene", dt_ms: int) -> None:
    """推进 reaction 序列 (受击 / 闪避). 结束后还原朝向 (阵亡保持面向攻击者)."""
    for unit in scene.battle.all_units:
        if unit.reaction_seq is not None:
            advance_reaction(unit, dt_ms)


def _tick_death_animations(scene: "BattleScene", now: int, dt_ms: int) -> None:
    """死亡动画计时: HP=0 + reaction 已结束 + 该 unit 的最近一发伤害数字进入 flash 阶段
    → 启动死亡 tick. 跟原版"死亡动画在数字闪烁时触发"对齐."""
    for unit in scene.battle.all_units:
        if unit.hp > 0 or unit.reaction_seq is not None:
            continue
        if unit.death_anim_time_ms < 0:
            # 找该 unit 的最近一发伤害数字, 看是否进 flash
            ready = False
            for f in scene._floats:
                if (abs(f.world_x - (unit.x * TILE_W + TILE_W // 2)) <= TILE_W
                        and f.flash_started_at(now)):
                    ready = True; break
            if ready or not scene._floats:    # 没数字也立即开 (配置缺失兜底)
                unit.death_anim_time_ms = 0
        else:
            unit.death_anim_time_ms += dt_ms


def _tick_anim_engine(scene: "BattleScene", dt_ms: int) -> None:
    """推进 anim_engine: 累积 ms, 每满 ATTACK_TICK_MS (40ms) 调一次 engine.tick().
    tick 内部会跑所有 attacking entity 的 seq, 触发 SIGNAL/move/frame_change 事件."""
    from core.attack_seq import ATTACK_TICK_MS
    scene._eng_acc_ms += dt_ms
    while scene._eng_acc_ms >= ATTACK_TICK_MS:
        scene._eng_acc_ms -= ATTACK_TICK_MS
        scene.battle.engine.tick()


def _tick_camera(scene: "BattleScene") -> None:
    """镜头 lerp 跟随当前单位 (用 render 值, 让镜头也跟着平滑跑)."""
    u = scene.battle.current
    target_x, target_y = scene._compute_camera_offset(
        int(round(u.render_x)), int(round(u.render_y)))
    scene._cam_x += (target_x - scene._cam_x) * scene.CAMERA_LERP
    scene._cam_y += (target_y - scene._cam_y) * scene.CAMERA_LERP


def _tick_phase_transitions(scene: "BattleScene", now: int) -> None:
    """ENEMY_TURN 时序:
       (a) AI 待执行 (_enemy_ai_pending=True): 暂停 ENEMY_PRE_MOVE_PAUSE_MS 显示移动范围,
           然后调 run_pending_enemy_ai 触发 AI (= 移动开始).
       (b) AI 执行后, 单位移动 + 等动画走完 + ENEMY_TURN_DELAY_MS 显示攻击/伤害范围,
           最后 post_enemy_turn 触发攻击.
       VICTORY/DEFEAT: 死亡动画跑完后切 BGM (banner 由 draw 处理).
    """
    if scene.battle.phase == Phase.ENEMY_TURN:
        # (a) Pre-move 暂停: AI 还没跑, 给玩家看移动范围
        if scene.battle._enemy_ai_pending:
            if scene._enemy_pre_move_started_at is None:
                scene._enemy_pre_move_started_at = now
            if now - scene._enemy_pre_move_started_at >= scene.ENEMY_PRE_MOVE_PAUSE_MS:
                scene._enemy_pre_move_started_at = None
                scene.battle.run_pending_enemy_ai()
            return
        # (b) Pre-attack 暂停 (= 原有逻辑)
        if units_animating(scene):
            scene._enemy_turn_started_at = None  # 还在走, 重置计时
        else:
            if scene._enemy_turn_started_at is None:
                scene._enemy_turn_started_at = now
            if now - scene._enemy_turn_started_at >= scene.ENEMY_TURN_DELAY_MS:
                scene._enemy_turn_started_at = None
                scene.battle.post_enemy_turn()
    elif (scene.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
          and not scene._battle_over_signaled
          and not death_animations_pending(scene)):
        scene._battle_over_signaled = True
        wav = "Victory.wav" if scene.battle.phase == Phase.VICTORY else "Gameover.wav"
        try:
            scene.audio.play_bgm(wav, loops=0)
        except FileNotFoundError:
            pass


def death_animations_pending(scene: "BattleScene") -> bool:
    """有任何死单位还在跑死亡动画 (= 拖延 victory banner / 接 banner 输入 的判据)."""
    for u in scene.battle.all_units:
        if u.alive:
            continue
        t = u.death_anim_time_ms
        if t < 0:
            return True
        if not u.is_player and t < scene.ENEMY_DEATH_TOTAL_MS:
            return True
        if u.is_player and t < scene.DEATH_FALL_TOTAL_MS:
            return True
    return False


def units_animating(scene: "BattleScene") -> bool:
    """是否有任何单位还在播放动画. 用于回合切换 + 玩家输入门控.
    伤害数字: 只要 flash 开始就算"动画完成" (= 当前角色回合可结束); 没死的目标 flash
    阶段允许下家行动. 死亡动画: 完整跑完才放行 (= 死亡时序晚于 flash 时, 等死亡完).
    """
    now = pygame.time.get_ticks()
    # 飘字 gating: 任何一个还没进 flash 阶段 = 还在动
    for f in scene._floats:
        if not f.flash_started_at(now):
            return True
    for u in scene.battle.all_units:
        if u.hp <= 0:
            # 死亡动画跑完才放行
            if u.death_anim_time_ms < 0:
                return True
            if not u.is_player and u.death_anim_time_ms < scene.ENEMY_DEATH_TOTAL_MS:
                return True
            if u.is_player and u.death_anim_time_ms < scene.DEATH_FALL_TOTAL_MS:
                return True
            continue
        if (abs(u.render_x - u.x) > scene.ANIM_EPSILON
                or abs(u.render_y - u.y) > scene.ANIM_EPSILON):
            return True
        if u.is_attacking or u.reaction_seq is not None:
            return True
    return False


def advance_reaction(u, dt_ms: int) -> None:
    """逐步执行 reaction_seq.py 里的脚本: SET_FRAME / MOVE / END."""
    from core.reaction_seq import REACTION_TICK_MS
    u.reaction_step_elapsed_ms += dt_ms
    seq = u.reaction_seq
    while u.reaction_step_idx < len(seq):
        step = seq[u.reaction_step_idx]
        if step[0] == 'frame':
            u.reaction_frame = step[1]
            u.reaction_step_idx += 1
            u.reaction_step_elapsed_ms = 0
            u.reaction_step_start_off = u.reaction_offset
            continue
        # ('move', dx, dy, ticks)
        _, dx, dy, ticks = step
        duration = ticks * REACTION_TICK_MS
        sx, sy = u.reaction_step_start_off
        if duration <= 0:
            # 瞬间位移 (例如最终归位)
            u.reaction_offset = (sx + dx, sy + dy)
            u.reaction_step_idx += 1
            u.reaction_step_start_off = u.reaction_offset
            u.reaction_step_elapsed_ms = 0
            continue
        if u.reaction_step_elapsed_ms >= duration:
            u.reaction_offset = (sx + dx, sy + dy)
            u.reaction_step_idx += 1
            u.reaction_step_start_off = u.reaction_offset
            u.reaction_step_elapsed_ms -= duration
            continue
        # 中段线性插值
        t = u.reaction_step_elapsed_ms / duration
        u.reaction_offset = (sx + dx * t, sy + dy * t)
        return
    # 序列完成
    u.reaction_seq = None
    u.reaction_frame = None
    u.reaction_offset = (0.0, 0.0)
    if u.alive and u.reaction_saved_facing is not None:
        u.facing = u.reaction_saved_facing
    u.reaction_saved_facing = None
