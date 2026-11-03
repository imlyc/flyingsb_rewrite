"""战斗行动菜单 = 原版菜单系统: 十字窗口 0xf (FUN_00434eff) → 道具列表 (窗口 4) / 特殊能力 (窗口 5), 竞技场里跑通."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402


@pytest.fixture
def arena_scene():
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    from core.audio_manager import AudioManager
    from scenes.arena.battle_scene import ArenaBattleScene
    import scenes.arena.roster as R
    sc = ArenaBattleScene(surf, AudioManager(), player_names=["孙悟空"],
                          enemy_names=[R.ENEMY_ROSTER[0]], return_scene=None)
    if hasattr(sc, "on_enter"):
        sc.on_enter()
    for e in sc.battle.enemies:                 # 我方是 40 级真值: 别让最弱的敌人在轮到玩家前就被反击打死
        e.hp = e.max_hp = 99999
    return sc


def _step(sc, n=40):
    for _ in range(n):
        sc.update(33)
        sc.draw()


def _until_player_turn(sc, limit=3000):
    """敌人初始行动值随机 (exe 摆阵 rand%20), 可能先手: 推进到玩家回合."""
    from core.battle.data import Phase
    for _ in range(limit):
        if sc.battle.current.is_player and sc.battle.phase == Phase.PLAYER_MOVE:
            break
        sc.update(33)
        sc.draw()
    _step(sc)


def _key(sc, k, n=40):
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    sc.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
    _step(sc, n)


def _cross(sc):
    from scenes.team_info import W_CROSS
    return sc._menu.wins.get(W_CROSS) if sc._menu is not None else None


def test_cross_opens_from_screen_frame_and_hides_ranges(arena_scene):
    """Esc: 光标当前 = 画面框, 缩到单位头顶; 图标 7 tick 转出到半径 32; 菜单开着不画移动范围 (exe 0x7e2ddc)."""
    from scenes.team_info import SCREEN_H, SCREEN_W
    sc = arena_scene
    _until_player_turn(sc)
    u = sc.battle.current
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="", scancode=0))
    sc._menu.step()                                  # state 1
    w = _cross(sc)
    cx, cy = w.cx, w.cy
    assert sc._menu.cursor.cur[0] >> 16 == 1 and sc._menu.cursor.cur[2] >> 16 == SCREEN_W - 1
    assert sc._menu.cursor.dst == [(cx - 1) << 16, (cy - 1) << 16, (cx + 1) << 16, (cy + 1) << 16]
    for _ in range(6):
        sc._menu.step()
        assert w.state == 10
    sc._menu.step()
    assert w.state == 0x14 and w.rx == 0x20 and w.angle == 0
    from scenes.battle.battle_menu import cross_center
    assert (cx, cy) == cross_center(sc, u)
    blits = []
    real = sc.surface
    sc.surface = type("S", (), {"blit": lambda self, *a, **k: blits.append(a)})()
    try:
        sc._draw_overlays(int(sc._cam_x), int(sc._cam_y))
    finally:
        sc.surface = real
    assert not blits                                 # 移动范围 / 攻击范围都不画


def test_cancel_returns_to_move(arena_scene):
    from core.battle.data import Phase
    sc = arena_scene
    _until_player_turn(sc)
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_ESCAPE)
    assert sc._menu is None and sc.battle.phase == Phase.PLAYER_MOVE


def test_end_turn_is_two_step(arena_scene):
    """↓ 只选中 END (光标框到 END); 其它方向键退选中; 再 ↓ 才结束回合."""
    sc = arena_scene
    _until_player_turn(sc)
    u = sc.battle.current
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_DOWN)
    w = _cross(sc)
    assert w.armed == 1 and sc._menu.cursor.dst[1] >> 16 == w.cy - 0x12 + 0x20
    _key(sc, pygame.K_UP)                            # 退选中, 不进特殊能力
    assert w.armed == 0 and _cross(sc) is w and w.state == 0x14
    _key(sc, pygame.K_DOWN)
    _key(sc, pygame.K_DOWN)
    assert sc._menu is None
    for _ in range(300):
        if sc.battle.current is not u:
            break
        sc.update(33)
    assert sc.battle.current is not u


def test_arena_item_menu_opens_and_uses_sandbox_item(arena_scene):
    sc = arena_scene
    _until_player_turn(sc)
    assert sc.battle.current.is_player
    _key(sc, pygame.K_ESCAPE)
    assert _cross(sc) is not None
    _key(sc, pygame.K_LEFT)                 # 道具: 光标到道具图标框, 图标转入 → 原版「战斗用道具」窗口
    from scenes.team_info import W_DESC, W_LIST
    assert _cross(sc) is None
    lst = sc._menu.wins[W_LIST]
    assert lst.title == "　战斗用道具" and W_DESC in sc._menu.wins
    assert [it for it, _ in lst.entries] == sorted(i for i, _ in sc.inventory.consumables())
    items = sc.inventory.consumables()
    assert items
    u = sc.battle.current
    u.hp = 1
    from core.battle.data import Phase
    _key(sc, pygame.K_RETURN)               # 选第一个消耗品 → 道具瞄准 (自己 + 面前一格, 光标默认自己)
    assert sc._menu is None
    assert sc.battle.phase == Phase.PLAYER_AIM and sc.battle.aim_cursor == (u.x, u.y)
    _key(sc, pygame.K_RETURN)               # 确认: 当场结算, 扣背包
    assert u.hp > 1
    assert sum(c for _, c in sc.inventory.consumables()) == sum(c for _, c in items) - 1
    for _ in range(600):                    # 演出 (起手 → 图标 → 光点 → 白字) 跑完后结束该角色回合
        if sc.battle.current is not u:
            break
        sc.update(33)
    assert sc.battle.current is not u


def test_item_menu_without_inventory_shows_empty(arena_scene):
    sc = arena_scene
    sc.inventory = None                     # 模拟没有道具栏的宿主
    _until_player_turn(sc)
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_LEFT)
    assert sc._menu is not None and sc._menu.wins
    _key(sc, pygame.K_RETURN)               # 无物可用, 不崩
    _key(sc, pygame.K_ESCAPE)               # 收起 → 重开十字窗口
    assert _cross(sc) is not None


def test_item_submenu_left_key_does_not_walk(arena_scene, monkeypatch):
    """ESC → ← 打开道具窗口时, 按住的 ← 不能让角色走动 (回归)."""
    sc = arena_scene
    _until_player_turn(sc)
    u = sc.battle.current
    pos = (u.x, u.y)
    _key(sc, pygame.K_ESCAPE)
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT, mod=0, unicode="", scancode=0))
    _step(sc, 10)
    assert sc._menu is not None
    held = {pygame.K_LEFT}
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: type("K", (), {"__getitem__": lambda s, k: k in held})())
    _step(sc, 60)                                  # 按住 ← 一阵
    assert (u.x, u.y) == pos and u.facing is not None


def test_item_list_cursor_remembered_and_cancel_reopens_cross(arena_scene):
    """exe 0x7b8f20: 战斗道具列表光标全局记忆; Esc 收起后重开十字窗口 0xf."""
    sc = arena_scene
    _until_player_turn(sc)
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_LEFT)
    from scenes.team_info import W_LIST
    _key(sc, pygame.K_DOWN)
    assert sc._menu.wins[W_LIST].cursor == 1
    _key(sc, pygame.K_ESCAPE)
    assert W_LIST not in sc._menu.wins and _cross(sc) is not None
    _key(sc, pygame.K_LEFT)
    assert sc._menu.wins[W_LIST].cursor == 1


def test_skill_window_battle_mode(arena_scene):
    """↑: 窗口 5 mode 0xf; 灰的技能 Enter 无效; Esc 重开十字; 亮的技能 Enter → 技能瞄准."""
    from core.battle import energy
    from core.battle.data import Phase
    from scenes.team_info import W_SKILL
    sc = arena_scene
    _until_player_turn(sc)
    u = sc.battle.current
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_UP)
    sw = sc._menu.wins[W_SKILL]
    assert _cross(sc) is None and sw.mode == 0xF
    assert sw.skills[:len(u.known_skills)] == list(u.known_skills)
    assert sw.enabled == [s >= 0 and energy.can_cast(u, s) for s in sw.skills]
    _key(sc, pygame.K_ESCAPE)
    assert W_SKILL not in sc._menu.wins and _cross(sc) is not None
    u.sg = 16
    u.mp = u.max_mp
    _key(sc, pygame.K_UP)
    sw = sc._menu.wins[W_SKILL]
    assert sw.enabled[sw.row]
    _key(sc, pygame.K_RETURN)
    assert sc._menu is None and sc.battle.phase in (Phase.PLAYER_AIM, Phase.PLAYER_MOVE)


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    from core import game_settings
    monkeypatch.setattr(game_settings, "_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(game_settings, "_values", None)
    return game_settings


def test_battle_settings_window(arena_scene, temp_settings):
    """→: 窗口 0x10 战斗环境设定; ↓↓← 攻击技术 看不到 (写设定); 音效 ←10; Esc 重开十字."""
    from scenes.team_info import W_OPT
    G = temp_settings
    sc = arena_scene
    _until_player_turn(sc)
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_RIGHT)
    w = sc._menu.wins[W_OPT]
    assert _cross(sc) is None and (w.cx, w.cy) == (400, 300)
    _key(sc, pygame.K_DOWN)
    _key(sc, pygame.K_DOWN)
    assert w.row == 2 and G.get("battle_enemy_skill") == 1
    _key(sc, pygame.K_LEFT)
    assert G.get("battle_enemy_skill") == 0
    import json
    assert json.loads(G._PATH.read_text(encoding="utf-8"))["battle_enemy_skill"] == 0
    for _ in range(3):
        _key(sc, pygame.K_DOWN)
    assert w.row == 4
    _key(sc, pygame.K_LEFT)
    assert G.get("volume_soundeffect") == 90
    _key(sc, pygame.K_ESCAPE)
    assert W_OPT not in sc._menu.wins and _cross(sc) is not None


def test_player_status_off_slides_bar_out(arena_scene, temp_settings):
    sc = arena_scene
    _until_player_turn(sc)
    assert sc._status_bar_h == 80
    temp_settings.set("battle_player_status", 0)
    _step(sc, 30)
    assert sc._status_bar_h == 0


def test_enemy_status_panel(arena_scene, temp_settings):
    """敌军状态: 面板 56×32 贴在 (实体 x - 16, y - 23 - h), 高度每 tick 2px; 关掉收起; 隐藏属性敌人显示 "?"."""
    from scenes.battle import enemy_panel
    sc = arena_scene
    _until_player_turn(sc)
    assert sc._enemy_panel_h == 32
    e = sc.battle.enemies[0]
    assert e._panel_anchor is not None
    x, y = e._panel_anchor = (200, 200)                  # 摆阵随机, 锚点可能在画面外: 固定到画面内
    sc.surface.fill((0, 0, 0))
    enemy_panel.draw(sc, [e])
    m = pygame.mask.from_threshold(sc.surface, (0, 0, 0), (1, 1, 1, 255))
    m.invert()
    box = m.get_bounding_rects()[0].unionall(m.get_bounding_rects())
    assert box.left >= x - 16 and box.right <= x + 40 and box.top >= y - 55 and box.bottom <= y - 23
    e.type_flags |= 0x20
    assert enemy_panel.cell(e) is enemy_panel.cell(sc.battle.enemies[0])     # 只看 "?", 与数值无关
    temp_settings.set("battle_enemy_status", 0)
    _step(sc, 4)
    assert 0 < sc._enemy_panel_h < 32
    _step(sc, 30)
    assert sc._enemy_panel_h == 0


def test_enemy_move_banner_before_action(temp_settings):
    """攻击技术 看得到: 敌人出招前横幅 1 + 15 + 8 + 15 tick, 销毁后下一 tick 才出招 (一桶水 #42 会走过来猛撞)."""
    from core.battle.data import Phase
    from core.audio_manager import AudioManager
    from scenes.arena.battle_scene import ArenaBattleScene
    temp_settings.set("battle_enemy_skill", 1)
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    sc = ArenaBattleScene(surf, AudioManager(), player_names=["孙悟空"], enemy_names=["#42"], return_scene=None)
    sc.on_enter()
    for p in sc.battle.players:
        p.hp = p.max_hp = 999999
    seen = []
    for _ in range(4000):
        if sc.battle.current.is_player and sc.battle.phase == Phase.PLAYER_MOVE:
            sc.battle.player_end_turn()
        sc.update(30)
        sc.draw()
        t = sc._technique
        if t is not None:
            seen.append(t)
            assert not sc.battle.current.is_attacking
        elif seen:
            break
    assert seen and seen[-1].done
    assert sum(1 for _ in seen) >= 39
