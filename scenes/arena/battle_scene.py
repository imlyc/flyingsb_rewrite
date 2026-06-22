"""竞技场战斗阶段.

BattleScene 子类: 用竞技场专用地图, 双方随机摆阵, arena_mode (无经验结算),
战斗结束返回设置场景. 战斗中按 '/' 调出控制台 (当前功能: 增加新敌人).
"""

from __future__ import annotations

import random

import pygame

from core.audio_manager import AudioManager
from core.battle.tactics import TacticsBattle
from scenes.base import Scene
from scenes.battle import BattleScene
from scenes.arena.roster import ENEMY_ROSTER, build_enemy_unit, build_player_unit
from scenes.arena.terrain import ArenaTerrain


def _random_positions(
    terrain: ArenaTerrain, rng: random.Random, count: int,
    x_lo: int, x_hi: int, used: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """在 x∈[x_lo,x_hi], y∈内部 的空格里随机挑 count 个互不重叠的位置."""
    cands = [
        (x, y)
        for x in range(x_lo, x_hi + 1)
        for y in range(1, terrain.h - 1)
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
        terrain = ArenaTerrain()
        battle_map = terrain.build_battle_map()

        players = [build_player_unit(n) for n in player_names]
        enemies = [build_enemy_unit(n) for n in enemy_names]

        used: set[tuple[int, int]] = set()
        mid = terrain.w // 2
        ppos = _random_positions(terrain, rng, len(players), 1, mid - 1, used)
        epos = _random_positions(terrain, rng, len(enemies), mid, terrain.w - 2, used)
        # 兜底: 哪侧没排满, 从全图剩余空格补
        if len(ppos) < len(players):
            ppos += _random_positions(terrain, rng, len(players) - len(ppos),
                                      1, terrain.w - 2, used)
        if len(epos) < len(enemies):
            epos += _random_positions(terrain, rng, len(enemies) - len(epos),
                                      1, terrain.w - 2, used)

        battle = TacticsBattle(
            players, enemies,
            battle_map=battle_map, rng=rng,
            player_positions=ppos, enemy_positions=epos,
            arena_mode=True,
        )
        super().__init__(surface, audio, battle, world_map=terrain, return_scene=return_scene)

        self._terrain = terrain
        # 控制台
        self._console_open = False
        self._console_level = 0       # 0=顶层命令 / 1=选敌人
        self._console_idx = 0
        self._console_font = self.font
        self._console_small = self.small

    # 顶层命令: (标签, 类型)
    _CONSOLE_TOP = [("增加敌人 ▸", "add_enemy"), ("关闭控制台", "close")]

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
            elif kind == "close":
                self._console_open = False
        else:
            name = ENEMY_ROSTER[self._console_idx]
            self._add_enemy(name)

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
