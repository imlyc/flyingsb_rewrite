"""从世界地图触发战斗: 组队 / 地牢检测 / 摆阵 / 启动 BattleScene.

自由函数, 第一参数 scene (WorldMapScene 实例) 当 namespace.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from core.battle.data import BattleMap, BattleUnit
from core.battle.setup import make_enemy, unit_from_character
from core.battle.tactics import TacticsBattle
from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
from core.character_sprites import sprite_resource
from scenes.world_map.terrain import MAP_H, MAP_W, TILES, TerrainType

if TYPE_CHECKING:
    from scenes.world_map.scene import WorldMapScene


RANDOM_BATTLE_EVERY = 3
RANDOM_BATTLE_CHANCE = 0.00
PARTY_SIZE = 2


def build_party(scene: "WorldMapScene") -> list[BattleUnit]:
    if scene.save is not None:
        chars: list[BattleUnit] = []
        for slot in PLAYABLE_SLOTS:
            ch = scene.save.characters.get(slot)
            if ch is None or ch.MaxHP <= 0:
                continue
            chars.append(unit_from_character(CHARACTER_NAMES[slot], ch))
            if len(chars) >= PARTY_SIZE:
                break
        if chars:
            return chars
    # 无存档时的默认队伍
    return [
        BattleUnit(name="孙悟空", level=1, max_hp=30, hp=30, max_mp=10, mp=10, sg=20,
                   attack=22, defence=12, agile=50, move=4, is_player=True,
                   color=(120, 200, 230),
                   sprite_key=sprite_resource("孙悟空")),
        BattleUnit(name="蒙面人", level=1, max_hp=30, hp=30, max_mp=15, mp=15, sg=18,
                   attack=24, defence=11, agile=40, move=4, is_player=True,
                   color=(160, 160, 200),
                   sprite_key=sprite_resource("蒙面人")),
    ]


def maybe_trigger_battle(scene: "WorldMapScene") -> None:
    # 走到地牢: 两个地牢分别对应不同敌人组
    if TILES[scene.grid[scene.player_y][scene.player_x]].terrain == TerrainType.DUNGEON:
        pos = (scene.player_x, scene.player_y)
        if pos == (5, 18):
            start_battle(scene, [make_enemy("乌鸦怪"), make_enemy("乌鸦怪")])
        else:  # (15, 8)
            start_battle(scene, [make_enemy("黄色怪"), make_enemy("骷髅")])
        return
    # 每 N 步骰: 随机战斗
    if scene.steps % RANDOM_BATTLE_EVERY == 0 and scene.rng.random() < RANDOM_BATTLE_CHANCE:
        template = scene.rng.choice(["骷髅", "乌鸦怪"])
        count = scene.rng.randint(1, 2)
        enemies = [make_enemy(template) for _ in range(count)]
        start_battle(scene, enemies)


def _make_battle_map_from_world(scene: "WorldMapScene") -> BattleMap:
    """把整张世界地图当战场: 不可通行 (水/山) → 障碍物."""
    bm = BattleMap(MAP_W, MAP_H)
    for y in range(MAP_H):
        for x in range(MAP_W):
            if not TILES[scene.grid[y][x]].passable:
                bm.obstacles.add((x, y))
    return bm


def _scatter_positions(
    scene: "WorldMapScene",
    center: tuple[int, int], count: int, ring_min: int, ring_max: int,
    avoid: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """在 center 周围 ring_min..ring_max 步范围内挑 count 个空格."""
    cx, cy = center
    cands = []
    for r in range(ring_min, ring_max + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dx) + abs(dy) != r:
                    continue
                p = (cx + dx, cy + dy)
                if not (0 <= p[0] < MAP_W and 0 <= p[1] < MAP_H):
                    continue
                if not TILES[scene.grid[p[1]][p[0]]].passable:
                    continue
                if p in avoid:
                    continue
                cands.append(p)
    scene.rng.shuffle(cands)
    out: list[tuple[int, int]] = []
    for p in cands:
        if p in out:
            continue
        out.append(p)
        if len(out) >= count:
            break
    return out


def start_battle(scene: "WorldMapScene", enemies: list[BattleUnit]) -> None:
    from scenes.battle import BattleScene
    party = build_party(scene)
    battle_map = _make_battle_map_from_world(scene)
    center = (scene.player_x, scene.player_y)

    # 玩家方在中心 + 周围 1-2 圈
    used: set[tuple[int, int]] = set()
    player_positions: list[tuple[int, int]] = [center]
    used.add(center)
    if len(party) > 1:
        extras = _scatter_positions(scene, center, len(party) - 1, 1, 2, used)
        for p in extras:
            used.add(p)
            player_positions.append(p)
        # 不够就硬塞 center (重叠); 一般 4 人队伍在 1-2 圈足够
        while len(player_positions) < len(party):
            player_positions.append(center)

    # 敌人在外圈 4-7 步
    enemy_positions = _scatter_positions(scene, center, len(enemies), 4, 7, used)
    # 不够就再放宽
    if len(enemy_positions) < len(enemies):
        more = _scatter_positions(scene, center, len(enemies), 8, 12, used | set(enemy_positions))
        enemy_positions.extend(more)
    while len(enemy_positions) < len(enemies):
        # 兜底: 找任意空格
        for y in range(MAP_H):
            for x in range(MAP_W):
                if (x, y) not in used and TILES[scene.grid[y][x]].passable:
                    enemy_positions.append((x, y))
                    used.add((x, y))
                    if len(enemy_positions) >= len(enemies):
                        break
            if len(enemy_positions) >= len(enemies):
                break
        break  # 防止死循环

    battle = TacticsBattle(
        party, enemies,
        battle_map=battle_map,
        rng=scene.rng,
        player_positions=player_positions,
        enemy_positions=enemy_positions,
    )
    scene.next_scene = BattleScene(
        scene.surface, scene.audio, battle,
        world_map=scene, return_scene=scene,
    )
