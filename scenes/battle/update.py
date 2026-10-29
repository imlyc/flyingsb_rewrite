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
from core.battle.locomotion import WALK_TICKS, motion_tick, tick_pose
from core.attack_seq import ATTACK_TICK_MS
from core.sprites.base import TILE_W, TILE_H
from scenes.battle import input as input_mod
from core.battle.float_digits import floats_animating

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def tick(scene: "BattleScene", dt_ms: int) -> None:
    now = pygame.time.get_ticks()

    _tick_unit_positions(scene, dt_ms)
    input_mod.poll_player_hold(scene, dt_ms)
    _ingest_damage_events(scene, now)
    _tick_reactions(scene, dt_ms)            # 受击反应结束 → commit HP (原版 case0xb 在反应后提交)
    _tick_damage_signals(scene, now)         # 飘字闪烁信号 → 触发死亡动画 (原版数字闪烁驱动)
    _tick_death_animations(scene, now, dt_ms)
    _tick_anim_engine(scene, dt_ms)

    if not units_animating(scene):
        scene.battle.advance_turn_when_ready()
        scene._anim_block_since = None
    else:
        _watchdog_animating(scene, now)

    _tick_camera(scene)
    _tick_phase_transitions(scene, now)
    _tick_menu_anim(scene, dt_ms)


def _watchdog_animating(scene: "BattleScene", now: int) -> None:
    """卡死诊断: units_animating 连续阻塞 >15s (远超任何正常演出) → 终端打印阻塞原因.
    每个阻塞事件只打一次 (打完 since 前移 60s 防刷屏). 排查'演出完但不能操作'类问题."""
    since = getattr(scene, '_anim_block_since', None)
    if since is None:
        scene._anim_block_since = now
        return
    if now - since < 15000:
        return
    scene._anim_block_since = now + 60000       # 下一轮 60s 后才再报
    print(f"[watchdog] units_animating 已阻塞 >15s, phase={scene.battle.phase.name}, 阻塞原因:")
    if floats_animating(scene.battle):
        print(f"  - 飘字未落定: float_pending={scene.battle.float_pending}")
    for u in scene.battle.all_units:
        if u.hp <= 0 and (u.death_anim_time_ms < 0
                          or (not u.is_player and u.death_anim_time_ms < scene.ENEMY_DEATH_TOTAL_MS)
                          or (u.is_player and u.death_anim_time_ms < scene.DEATH_FALL_TOTAL_MS)):
            print(f"  - {u.name} 死亡动画未完: death_anim={u.death_anim_time_ms}"
                  f" settle={u.settle_pending} batch={u.settle_batch} react={u.reaction_seq is not None}")
        elif u.hp > 0:
            if (abs(u.render_x - u.x) > scene.ANIM_EPSILON
                    or abs(u.render_y - u.y) > scene.ANIM_EPSILON):
                print(f"  - {u.name} render lerp 未到位: render=({u.render_x:.2f},{u.render_y:.2f})"
                      f" 逻辑=({u.x},{u.y}) path={u.move_path}")
            if u.is_attacking:
                ent = u.entity
                print(f"  - {u.name} is_attacking: atlas={ent.atlas_slot:#x} frame={ent.frame_idx}"
                      f" ticks={ent.ticks} seq_len={len(ent.seq)} offset={ent.offset}")
            if u.reaction_seq is not None:
                print(f"  - {u.name} reaction 未结束: step={u.reaction_step_idx}/{len(u.reaction_seq)}")
    for e in scene.battle.engine.entities:
        if e.user_data.get('projectile') and e.state_code != 20:
            print(f"  - projectile ent id={e.id} state={e.state_code}"
                  f" think={getattr(e.think_fn, '__name__', None)} kind={e.user_data.get('kind')}"
                  f" ud_keys={list(e.user_data.keys())[:10]}")


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
            scene._skill_cursor = 0    # 进 L2 总从首项起
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


LOCO_TICK_MS = ATTACK_TICK_MS       # 战斗 1 tick (与引擎同)
WALK_STEP = 1.0 / WALK_TICKS        # 每 tick 1/4 格


def _tick_unit_positions(scene: "BattleScene", dt_ms: int) -> None:
    """单位走格 = 原版运动状态机 (core.battle.locomotion): 每 LOCO_TICK_MS 一 tick, 状态 2 每 tick 走 1/4 格
    (4 tick 一格), 到格那一 tick phase 翻转; 姿态 (走路/待机/虚弱帧) 也在 tick 里算 (exe 姿态函数每 tick 推进计数).
    沿路径节点逐格走, 防止两轴并行插值出 45° 飞行."""
    scene._loco_acc = getattr(scene, "_loco_acc", 0) + dt_ms
    while scene._loco_acc >= LOCO_TICK_MS:
        scene._loco_acc -= LOCO_TICK_MS
        scene._loco_tick = getattr(scene, "_loco_tick", 0) + 1
        for unit in scene.battle.all_units:
            # settle_pending: 逻辑已死但视觉仍站立 (大金刚延迟结算) → 仍推进待机/呼吸动画, 防静止.
            if not unit.alive and not unit.settle_pending:
                continue
            _loco_step(unit, scene._loco_tick)
    for unit in scene.battle.all_units:
        if not unit.alive and not unit.settle_pending:
            continue
        # 行走 / 待机时间 (施法姿等仍按 ms 计)
        unit.anim.tick(dt_ms, moving=unit.loco.state == 2)


def _loco_step(unit, global_tick: int) -> None:
    # 当前目标: 路径头节点 / 否则 unit 逻辑位置
    if unit.move_path:
        tgt_x, tgt_y = unit.move_path[0]
    else:
        tgt_x, tgt_y = unit.x, unit.y
    walking = unit.render_x != float(tgt_x) or unit.render_y != float(tgt_y)
    unit.loco_prev = None
    if motion_tick(unit.loco, walking):
        unit.loco_prev = (unit.render_x, unit.render_y)
        for rattr, target in (("render_x", tgt_x), ("render_y", tgt_y)):
            rval = getattr(unit, rattr)
            delta = target - rval
            if delta:
                setattr(unit, rattr, float(target) if abs(delta) <= WALK_STEP else rval + (WALK_STEP if delta > 0 else -WALK_STEP))
    # 到达当前节点 → 弹出, 切换 facing 到下一段方向
    if (unit.move_path
            and unit.render_x == float(unit.move_path[0][0])
            and unit.render_y == float(unit.move_path[0][1])):
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
    unit.loco_pose = tick_pose(unit, global_tick)


def _ingest_damage_events(scene: "BattleScene", now: int) -> None:
    """飘字数字实体已在 core (combat.push_damage_event → float_digits) 随伤害当场生成; 这里只清事件队列."""
    scene.battle.damage_events.clear()


def _tick_reactions(scene: "BattleScene", dt_ms: int) -> None:
    """推进 reaction 序列 (受击 / 闪避). 受击反应**结束**时 commit HP (原版: 动作动画结束/反应后
    把工作缓冲提交回真实表 = 显示值; 早于数字闪烁). 存活 → 显示同步真实 hp + 虚弱; 死亡 → 保留旧值."""
    for unit in scene.battle.all_units:
        if unit.reaction_seq is None:
            continue
        advance_reaction(unit, dt_ms)
        if unit.reaction_seq is None and not unit.settle_batch:   # 刚结束 (非大金刚批量)
            unit.commit_hp()


def _on_damage_flash(scene: "BattleScene", unit) -> None:
    """伤害数字"闪烁"信号 handler: 放行死亡/虚弱视觉, 致死单位启动死亡动画
    (原版: 死亡动画在数字闪烁时触发). 大金刚 settle_batch 由批量处理, 跳过."""
    if unit.settle_batch:
        return
    unit.release_death_visual()
    if not unit.alive and unit.reaction_seq is None and unit.death_anim_time_ms < 0:
        unit.death_anim_time_ms = 0


def _tick_damage_signals(scene: "BattleScene", now: int) -> None:
    """飘字数字实体自驱的信号 (core.battle.float_digits → battle.float_events): 首位数字进闪烁 → 触发死亡."""
    evs = getattr(scene.battle, 'float_events', None)
    if not evs:
        return
    for kind, unit in evs:
        if kind == 'flash' and unit is not None:
            _on_damage_flash(scene, unit)
    evs.clear()


def _tick_death_animations(scene: "BattleScene", now: int, dt_ms: int) -> None:
    """死亡动画计时累加 (启动主路径 = _on_damage_flash 闪烁信号). 兜底: 视觉已放行
    (settle_pending 已清) 且反应结束但死亡未启动 (如反应罕见地晚于闪烁) → 补启动."""
    for unit in scene.battle.all_units:
        if unit.hp > 0:
            continue
        if (unit.death_anim_time_ms < 0 and not unit.settle_pending
                and not unit.settle_batch and unit.reaction_seq is None):
            unit.death_anim_time_ms = 0
        if unit.death_anim_time_ms >= 0:
            unit.death_anim_time_ms += dt_ms


def _tick_anim_engine(scene: "BattleScene", dt_ms: int) -> None:
    """推进 anim_engine: 累积 ms, 每满 ATTACK_TICK_MS (40ms) 调一次 engine.tick().
    tick 内部会跑所有 attacking entity 的 seq, 触发 SIGNAL/move/frame_change 事件."""
    from core.attack_seq import ATTACK_TICK_MS
    scene._eng_acc_ms += dt_ms
    while scene._eng_acc_ms >= ATTACK_TICK_MS:
        scene._eng_acc_ms -= ATTACK_TICK_MS
        scene.battle.engine.tick()
        _tick_flicker(scene.battle)
        from scenes.battle import status_bar
        status_bar.tick(scene)                   # 状态栏滑入/滑出 (exe FUN_004cf1ed, 每 tick 4px)


def _tick_flicker(battle) -> None:
    """紫河变身闪烁 31t (core.normal_attack.FLICKER_MASK)."""
    from core.normal_attack import FLICKER_TICKS
    for u in battle.all_units:
        fl = u.flicker
        if fl:
            fl['t'] += 1
            if fl['t'] >= FLICKER_TICKS:
                u.flicker = None
                battle.refresh_status_snapshot(working=False)   # exe 0xd/0xe 闪完 FUN_004a4e42(0)


def _tick_camera(scene: "BattleScene") -> None:
    """镜头 lerp 跟随当前单位 (用 render 值, 让镜头也跟着平滑跑)."""
    u = scene.battle.current
    target_x, target_y = scene._compute_camera_offset(
        int(round(u.render_x)), int(round(u.render_y)))
    scene._cam_x += (target_x - scene._cam_x) * scene.CAMERA_LERP
    scene._cam_y += (target_y - scene._cam_y) * scene.CAMERA_LERP
    # 发布可见屏幕中心 (世界 px) 给满屏特效 (超亂舞) 当框中心
    sw, sh = scene.surface.get_size()
    scene.battle.view_center_world = (int(scene._cam_x) + sw // 2,
                                      int(scene._cam_y) + sh // 2)


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
            if (any(u.flicker for u in scene.battle.all_units)    # 紫河变身闪烁中: 敌人等闪完再开始
                    or getattr(scene.battle, 'toxic_active', False)):   # 中毒演出 (core.battle.toxic) 演完再开始
                scene._enemy_pre_move_started_at = None
                return
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
    # 飘字 gating: 末位数字还没落定 (exe dispatcher 等 -20 的同一判据)
    if floats_animating(scene.battle):
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
        if u.flicker:                            # 紫河变身闪烁: exe 状态机停在 0xd/0xe 31t, 下一个单位等闪完
            return True
    # 投射物 entity (= 技能 B 类的飞行物) 还在 → 还在动
    for e in scene.battle.engine.entities:
        if e.user_data.get('projectile') and e.state_code != 20:    # 20 = PROJ_STATE_DONE
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
