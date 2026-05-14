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

    # 菜单 / 二级 / 各种过渡 / 关闭动画 期间: 走菜单键路由, 不让方向键漏给角色移动
    if (scene._menu_open or scene._submenu is not None
            or scene._menu_transition_t is not None
            or scene._menu_close_t is not None
            or scene._menu_dismiss_t is not None):
        _handle_menu_key(scene, event.key)
        return True

    # 方向键不再走 KEYDOWN (改为 update 里轮询长按), 避免按一下就瞬移领先动画.
    # 但需要这一刻清掉输入门 — 否则战斗中换单位 / 返回地图时长按状态会被误读为"续按".
    if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                     pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s):
        if scene._input_gated:
            scene._input_gated = False
        return True

    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        scene.battle.player_attack_facing()
    elif event.key == pygame.K_ESCAPE:
        scene._menu_open = True
        scene._menu_anim_t = 0   # 打开动画起点 (update tick 会推进)
    elif event.key == pygame.K_x:
        scene.battle.cancel_to_move()
    return True


def _handle_menu_key(scene: "BattleScene", key: int) -> None:
    """十字菜单: 上=技能, 左=道具, 右=设置, 下=回合结束.
    ESC 一级关闭; 二级 (skill 列表) 按 ESC 回退到一级.
    """
    from core.sprites.loaders import (
        SMENU_END, SMENU_ITEM, SMENU_SETTINGS, SMENU_SKILL,
    )

    # 打开动画 / 过渡动画 / 反向关闭 / 一级关闭动画 期间不接键
    if (scene._menu_anim_t is not None
            or scene._menu_transition_t is not None
            or scene._menu_close_t is not None
            or scene._menu_dismiss_t is not None):
        return

    # 二级菜单: 只处理 ESC 回退 → 触发反向动画 (二级缩小 → 一级 open anim)
    if scene._submenu is not None:
        if key in (pygame.K_ESCAPE, pygame.K_x):
            scene._menu_close_t = 0
        return

    # 一级菜单 — 全部通过 dismiss 动画收掉
    if key in (pygame.K_ESCAPE, pygame.K_x):
        # ESC: 白点直接消失 (target=None), icons 转出
        scene._menu_dismiss_t = 0
        scene._menu_dismiss_target = None
        scene._menu_dismiss_action = None
        return
    if key in (pygame.K_UP, pygame.K_w):
        # 技能 → L1→L2 过渡动画 (含 phase A 同样的白框动画)
        scene._menu_transition_t = 0
        scene._menu_transition_target = SMENU_SKILL
    elif key in (pygame.K_LEFT, pygame.K_a):
        # 道具 → 走 dismiss 动画 (含白框移到 item icon), 暂无实际效果
        scene._menu_dismiss_t = 0
        scene._menu_dismiss_target = SMENU_ITEM
        scene._menu_dismiss_action = None
    elif key in (pygame.K_RIGHT, pygame.K_d):
        # 设置 → 同上, 暂无实际效果
        scene._menu_dismiss_t = 0
        scene._menu_dismiss_target = SMENU_SETTINGS
        scene._menu_dismiss_action = None
    elif key in (pygame.K_DOWN, pygame.K_s):
        # 回合结束 → dismiss 动画完成后执行
        scene._menu_dismiss_t = 0
        scene._menu_dismiss_target = SMENU_END
        scene._menu_dismiss_action = 'end_turn'


def _advance_end_screen(scene: "BattleScene") -> None:
    """胜利后逐个翻升级框, 然后返回地图. 失败时直接返回."""
    if scene.battle.phase == Phase.DEFEAT:
        scene.next_scene = scene.return_scene
        return
    # 第一次按键: 跳过胜利 banner
    if not scene._victory_acknowledged:
        scene._victory_acknowledged = True
        scene._levelup_idx = 0
        if not scene.battle.level_ups:
            scene.next_scene = scene.return_scene
        return
    # 后续按键: 逐个翻升级框
    scene._levelup_idx += 1
    if scene._levelup_idx >= len(scene.battle.level_ups):
        scene.next_scene = scene.return_scene


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
    if (scene.battle.phase != Phase.PLAYER_MOVE
            or scene._menu_open
            or scene._submenu is not None
            or scene._menu_transition_t is not None
            or scene._menu_close_t is not None
            or scene._menu_dismiss_t is not None):
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
    if scene.battle.player_step(dx, dy) and (u.x, u.y) != (int(round(u.render_x)), int(round(u.render_y))):
        if u.anim.anim_time_ms <= 0:
            u.anim.anim_time_ms = 1
        u.anim.idle_time_ms = 0
