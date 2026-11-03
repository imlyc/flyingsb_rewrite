"""战斗场景输入处理.

公开入口:
  handle_event(scene, event) -> bool       一次性事件 (KEYDOWN / QUIT)
  poll_player_hold(scene, dt_ms) -> None   每帧轮询方向键长按
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.battle.data import Phase
from scenes.battle import update as update_mod

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def handle_event(scene: "BattleScene", event: pygame.event.Event) -> bool:
    if event.type == pygame.QUIT:
        return False
    if scene._menu is not None:                      # 原版菜单系统 (十字 / 道具 / 特殊能力): 键全归它
        scene._menu.handle_event(event)
        return True
    if event.type != pygame.KEYDOWN:
        return True
    if scene.battle.phase in (Phase.VICTORY, Phase.DEFEAT):
        if update_mod.death_animations_pending(scene):
            return True   # 死亡动画跑完再接 banner 的输入
        _advance_end_screen(scene)
        return True
    if scene.battle.phase == Phase.ENEMY_TURN:
        return True
    # 攻击 / 受击 / 飘字 / 死亡动画 任一在播放 → 都不接键
    if update_mod.units_animating(scene):
        return True

    # PLAYER_AIM: 方向键 cursor 在 pattern 内游走 / shift+方向 转 facing / Enter 确认 / ESC 取消.
    if scene.battle.phase == Phase.PLAYER_AIM:
        _handle_aim_key(scene, event.key, event.mod)
        return True

    # 方向键不再走 KEYDOWN (改为 update 里轮询长按), 避免按一下就瞬移领先动画.
    # 但需要这一刻清掉输入门 — 否则战斗中换单位 / 返回地图时长按状态会被误读为"续按".
    if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                     pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s):
        if scene._input_gated:
            scene._input_gated = False
        return True

    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        # PLAYER_MOVE Enter: 进入 AIM 阶段 (不立即攻击)
        scene.battle.enter_attack_aim()
    elif event.key == pygame.K_ESCAPE:
        scene.open_menu()
    elif event.key == pygame.K_x:
        scene.battle.cancel_to_move()
    return True


def _handle_aim_key(scene: "BattleScene", key: int, mod: int) -> None:
    """PLAYER_AIM 阶段:
       方向键 = cursor 在 pattern 内移动 (单格普攻 pattern 只有 1 格 → 不动).
       Shift+方向键 = 转 facing, pattern 跟着旋转 (= 远程攻击转向).
       Enter = 确认攻击 cursor 上的敌人 / Esc-X = 取消.
    """
    DIR = {
        pygame.K_LEFT: (-1, 0), pygame.K_a: (-1, 0),
        pygame.K_RIGHT: (1, 0), pygame.K_d: (1, 0),
        pygame.K_UP: (0, -1), pygame.K_w: (0, -1),
        pygame.K_DOWN: (0, 1), pygame.K_s: (0, 1),
    }
    if key in DIR:
        dx, dy = DIR[key]
        if mod & pygame.KMOD_SHIFT:
            scene.battle.aim_turn_facing(dx, dy)
        else:
            scene.battle.aim_move_cursor(dx, dy)
        return
    if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        if not scene.battle.confirm_attack_aim():
            scene.battle._log(f"{scene.battle.current.name} 目标格无可作用的对象")
        elif scene.battle.last_item_used is not None:      # 道具确认: 扣背包
            if scene.inventory is not None:
                scene.inventory.remove(scene.battle.last_item_used, 1)
            scene.battle.last_item_used = None
        return
    if key in (pygame.K_ESCAPE, pygame.K_x):
        scene.battle.cancel_attack_aim()
        scene._input_gated = True
        return


def _advance_end_screen(scene: "BattleScene") -> None:
    """胜利后逐个翻升级框, 然后返回地图. 失败时直接返回.

    在返回地图前先通知 return_scene 本场战斗的胜负 (若它实现了
    ``_on_story_battle_end`` 钩子) —— 供剧情战斗在胜利后才入队/置进度。
    """
    won = scene.battle.phase == Phase.VICTORY
    from core.battle import settlement
    rs_save = getattr(scene.return_scene, 'save', None)
    settlement.write_back(scene.battle, rs_save)  # HP/MP/SG/行动值 回角色, 金钱/掉落进存档 (exe 角色表跨战斗保留)
    rs = scene.return_scene
    if hasattr(rs, "_on_story_battle_end"):
        try:
            rs._on_story_battle_end(won)
        except Exception:
            pass
    scene.next_scene = rs


def poll_player_hold(scene: "BattleScene", dt_ms: int) -> None:
    """PLAYER_MOVE 阶段方向键处理. 复刻原版语义:
    - 朝向不一致, 按键边沿: 仅转身, 不前进
    - 朝向一致, 按键边沿: 立即走一步
    - 持续按住同一方向 < WALK_HOLD_DELAY_MS: 不动 (tap 不会自动走)
    - 持续按住 ≥ WALK_HOLD_DELAY_MS: 开始连走
    """
    # 当前单位换了 (上一回合结束) → 锁输入门 + 清持有状态
    if scene.battle.current is not scene._last_current:
        scene._last_current = scene.battle.current
        scene._input_gated = True
        scene._hold.reset()
    if scene.battle.phase != Phase.PLAYER_MOVE or scene._menu is not None:   # 菜单开着: 方向键是选菜单, 不能走
        return
    u = scene.battle.current
    if not u.is_player:
        return
    # 攻击 / 受击 / 任何动画 (包含飘字 / 死亡) 期间禁止新输入.
    if update_mod.units_animating(scene):
        return
    # 还在向逻辑位置插值, 不接受新输入 (避免叠加多步领先渲染)
    if abs(u.render_x - u.x) > scene.ANIM_EPSILON or abs(u.render_y - u.y) > scene.ANIM_EPSILON:
        return
    if scene._input_gated:
        return
    keys = pygame.key.get_pressed()
    dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
    dy = (keys[pygame.K_DOWN]  or keys[pygame.K_s]) - (keys[pygame.K_UP]   or keys[pygame.K_w])
    if dx == 0 and dy == 0:
        scene._hold.reset()
        return
    if dx != 0:
        dy = 0
    new_dir = (dx, dy)
    edge = scene._hold.tick(new_dir, dt_ms)

    if new_dir != u.facing:
        # 朝向不一致: 边沿时转身 (即生效, 不插过渡帧), 不前进
        if edge:
            u.facing = new_dir
        return

    # 朝向已对齐: 是否走一步
    if not scene._hold.should_walk(edge, scene.WALK_HOLD_DELAY_MS):
        return
    scene.battle.player_step(dx, dy)     # 走格动画由运动状态机接手 (update._tick_unit_positions)
