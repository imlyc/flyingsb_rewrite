"""竞技场战斗阶段.

BattleScene 子类: 用竞技场专用地图, 双方随机摆阵, arena_mode (无经验结算),
战斗结束返回设置场景. 战斗中按 '/' 调出控制台 (当前功能: 增加新敌人 / 设置当前角色 HP).
"""

from __future__ import annotations

import random

import pygame

from core import real_map as realm
from core.audio_manager import AudioManager
from core.battle.tactics import TacticsBattle
from scenes.base import Scene
from scenes.battle import BattleScene
from scenes.arena.roster import ENEMY_ROSTER, build_enemy_unit, build_player_unit
from scenes.arena.terrain import ArenaTerrain


def _random_positions(
    terrain: ArenaTerrain, rng: random.Random, count: int,
    x_lo: int, x_hi: int, used: set[tuple[int, int]],
    y_lo: int | None = None, y_hi: int | None = None,
) -> list[tuple[int, int]]:
    """在 x∈[x_lo,x_hi], y∈[y_lo,y_hi] 的空格里随机挑 count 个互不重叠的位置.
    y 范围默认整张内部 (1..h-2)."""
    y0 = 1 if y_lo is None else y_lo
    y1 = (terrain.h - 2) if y_hi is None else y_hi
    cands = [
        (x, y)
        for x in range(x_lo, x_hi + 1)
        for y in range(y0, y1 + 1)
        if terrain.passable(x, y) and (x, y) not in used
    ]
    rng.shuffle(cands)
    out: list[tuple[int, int]] = []
    for p in cands:
        out.append(p)
        used.add(p)
        if len(out) >= count:
            break
    return out


class ArenaBattleScene(BattleScene):
    CONSOLE_BG = (12, 14, 22, 235)
    CONSOLE_BORDER = (120, 200, 240)
    CONSOLE_TEXT = (220, 220, 235)
    CONSOLE_FOCUS = (255, 230, 110)

    def __init__(
        self,
        surface: pygame.Surface,
        audio: AudioManager,
        player_names: list[str],
        enemy_names: list[str],
        return_scene: Scene,
    ) -> None:
        rng = random.Random()
        terrain = self._make_terrain()
        battle_map = terrain.build_battle_map()

        players = [build_player_unit(n) for n in player_names]
        enemies = [build_enemy_unit(n) for n in enemy_names]

        # 敌我双方位置随机, 不分左右. 优先居中内缩区域 (远离围墙 + 开局都在视野内),
        # 数量太多排不下时再回退到全内部补齐.
        used: set[tuple[int, int]] = set()
        total = len(players) + len(enemies)
        mx = max(2, terrain.w // 5)               # 左右各内缩 ~1/5
        my = max(2, terrain.h // 5)
        allpos = _random_positions(terrain, rng, total,
                                   mx, terrain.w - 1 - mx, used,
                                   my, terrain.h - 1 - my)
        if len(allpos) < total:                   # 居中区不够 → 全内部补
            allpos += _random_positions(terrain, rng, total - len(allpos),
                                        1, terrain.w - 2, used)
        ppos = allpos[:len(players)]
        epos = allpos[len(players):]

        battle = TacticsBattle(
            players, enemies,
            battle_map=battle_map, rng=rng,
            player_positions=ppos, enemy_positions=epos,
            arena_mode=True,
        )
        super().__init__(surface, audio, battle, world_map=terrain, return_scene=return_scene)

        self._terrain = terrain
        # 沙盒道具栏 (不存档): 让竞技场也能测道具菜单/回复流程
        from core.inventory import Inventory
        self.inventory = Inventory({299: 3, 300: 2, 302: 3, 305: 1})   # 恢复药/良药/药草/仙桃
        # 控制台
        self._console_open = False
        self._console_level = 0       # 0=顶层命令 / 1=选敌人 / 2=改当前角色 HP
        self._hp_input = ""           # level 2 的输入值 (字符串, 空 = 未输入)
        self._console_idx = 0
        self._console_font = self.font
        self._console_small = self.small

    @staticmethod
    def _make_terrain():
        if realm.maps_available() and realm.is_available(realm.DEFAULT_ARENA_MAP):
            try:
                return realm.load(realm.DEFAULT_ARENA_MAP)
            except Exception as e:
                print("arena real map failed:", e)
        return ArenaTerrain()

    # 顶层命令: (标签, 类型)
    _CONSOLE_TOP = [("增加敌人 ▸", "add_enemy"), ("设置当前角色 HP ▸", "set_hp"), ("退出战斗", "quit_battle"),
                    ("关闭控制台", "close")]

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if self._console_open:
                self._console_key(event.key)
                return True
            if event.key == pygame.K_SLASH:
                self._console_open = True
                self._console_level = 0
                self._console_idx = 0
                return True
        return super().handle_event(event)

    def _console_key(self, key: int) -> None:
        if key == pygame.K_SLASH:
            self._console_open = False
            return
        if self._console_level == 2:
            self._hp_key(key)
            return
        items = self._CONSOLE_TOP if self._console_level == 0 else ENEMY_ROSTER
        if key in (pygame.K_UP, pygame.K_w):
            self._console_idx = (self._console_idx - 1) % len(items)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self._console_idx = (self._console_idx + 1) % len(items)
        elif key == pygame.K_ESCAPE:
            if self._console_level == 1:
                self._console_level = 0
                self._console_idx = 0
            else:
                self._console_open = False
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self._console_exec()

    def _console_exec(self) -> None:
        if self._console_level == 0:
            kind = self._CONSOLE_TOP[self._console_idx][1]
            if kind == "add_enemy":
                self._console_level = 1
                self._console_idx = 0
            elif kind == "set_hp":
                self._console_level = 2
                self._hp_input = str(self.battle.current.hp)
            elif kind == "quit_battle":
                self._console_open = False
                self.next_scene = self.return_scene   # 直接返回设置场景
            elif kind == "close":
                self._console_open = False
        else:
            name = ENEMY_ROSTER[self._console_idx]
            self._add_enemy(name)

    # ------- 设置当前角色 HP -------
    _DIGIT_KEYS = {getattr(pygame, f"K_{i}"): str(i) for i in range(10)}
    _DIGIT_KEYS.update({getattr(pygame, f"K_KP{i}"): str(i) for i in range(10)})

    def _hp_value(self) -> int:
        return int(self._hp_input) if self._hp_input else 0

    def _hp_key(self, key: int) -> None:
        u = self.battle.current
        if key == pygame.K_ESCAPE:
            self._console_level = 0
            self._console_idx = 1
        elif key in self._DIGIT_KEYS:
            if len(self._hp_input) < 6:
                self._hp_input = (self._hp_input + self._DIGIT_KEYS[key]).lstrip("0") or "0"
        elif key == pygame.K_BACKSPACE:
            self._hp_input = self._hp_input[:-1]
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            step = {pygame.K_LEFT: -1, pygame.K_RIGHT: 1, pygame.K_UP: 10, pygame.K_DOWN: -10}[key]
            self._hp_input = str(max(1, min(u.max_hp, self._hp_value() + step)))
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._set_current_hp(self._hp_value())
            self._console_open = False

    def _set_current_hp(self, value: int) -> None:
        """直接改当前行动角色 HP, 夹在 1..max_hp (0 会让行动中的角色死在自己回合里, 卡住回合流程)."""
        u = self.battle.current
        v = max(1, min(u.max_hp, value))
        u.hp = v
        u.shown_hp_override = None      # 显示值立即同步 (不走受击提交)
        self.battle.refresh_status_snapshot()   # 调试控制台: 状态栏也立即同步
        self.battle._log(f"[控制台] {u.name} HP → {v}/{u.max_hp}")

    def _add_enemy(self, name: str) -> None:
        tile = self._random_free_tile()
        if tile is None:
            self.battle._log("[控制台] 没有空格可放置新敌人")
            return
        e = build_enemy_unit(name)
        e.x, e.y = tile
        e.snap_render()
        self.battle.enemies.append(e)
        self.battle._log(f"[控制台] 新敌人「{name}」加入战场 @{tile} (下回合行动)")

    def _random_free_tile(self) -> tuple[int, int] | None:
        t = self._terrain
        cands = [
            (x, y)
            for x in range(1, t.w - 1)
            for y in range(1, t.h - 1)
            if t.passable(x, y) and self.battle.q.occupant(x, y) is None
        ]
        if not cands:
            return None
        return self.battle.rng.choice(cands)

    # ------- 更新 (控制台开启时冻结战斗) -------
    def update(self, dt_ms: int) -> None:
        if self._console_open:
            return
        super().update(dt_ms)

    # ------- 渲染 -------
    def draw(self) -> None:
        super().draw()
        if self._console_open:
            self._draw_console()

    def _draw_console(self) -> None:
        sw, sh = self.surface.get_size()
        panel = pygame.Rect(0, 0, 360, 280)
        panel.center = (sw // 2, sh // 2)
        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill(self.CONSOLE_BG)
        self.surface.blit(overlay, panel.topleft)
        pygame.draw.rect(self.surface, self.CONSOLE_BORDER, panel, 2)

        title = self._console_font.render("/ 战斗控制台", True, self.CONSOLE_BORDER)
        self.surface.blit(title, (panel.x + 16, panel.y + 12))

        if self._console_level == 2:
            self._draw_hp_editor(panel)
            return
        items = (self._CONSOLE_TOP if self._console_level == 0
                 else [(n, None) for n in ENEMY_ROSTER])
        sub = "选择命令" if self._console_level == 0 else "选择要加入的敌人"
        st = self._console_small.render(sub, True, self.CONSOLE_TEXT)
        self.surface.blit(st, (panel.x + 16, panel.y + 42))

        y = panel.y + 70
        for i, it in enumerate(items):
            label = it[0] if isinstance(it, tuple) else it
            focused = (i == self._console_idx)
            color = self.CONSOLE_FOCUS if focused else self.CONSOLE_TEXT
            prefix = "▶ " if focused else "  "
            txt = self._console_font.render(prefix + label, True, color)
            self.surface.blit(txt, (panel.x + 24, y))
            y += 30

        hint = self._console_small.render(
            "↑↓ 选择   回车 确认   ESC 返回/关闭   / 关闭",
            True, (170, 170, 190))
        self.surface.blit(hint, (panel.x + 16, panel.bottom - 26))

    def _draw_hp_editor(self, panel: pygame.Rect) -> None:
        u = self.battle.current
        st = self._console_small.render(f"当前角色: {u.name}   现 HP {u.hp}/{u.max_hp}", True, self.CONSOLE_TEXT)
        self.surface.blit(st, (panel.x + 16, panel.y + 42))
        shown = self._hp_input or "_"
        txt = self._console_font.render(f"▶ 新 HP: {shown} / {u.max_hp}", True, self.CONSOLE_FOCUS)
        self.surface.blit(txt, (panel.x + 24, panel.y + 90))
        note = self._console_small.render("范围 1..上限 (超出自动夹紧)", True, (170, 170, 190))
        self.surface.blit(note, (panel.x + 24, panel.y + 130))
        hint = self._console_small.render(
            "数字输入  ←→ ±1  ↑↓ ±10  回车 生效  ESC 返回", True, (170, 170, 190))
        self.surface.blit(hint, (panel.x + 16, panel.bottom - 26))
