"""从世界地图触发战斗: 组队 / 地牢检测 / 摆阵 / 启动 BattleScene.

自由函数, 第一参数 scene (WorldMapScene 实例) 当 namespace.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from core.battle.data import BattleMap, BattleUnit
from core.battle.setup import (
    ENEMY_TEMPLATES, make_enemy, make_enemy_by_type, unit_from_character,
)
from core.battle.tactics import TacticsBattle
from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
from core.character_sprites import sprite_resource
from scenes.world_map.terrain import MAP_H, MAP_W, TILES, TerrainType

if TYPE_CHECKING:
    from scenes.world_map.scene import WorldMapScene


def make_story_enemy(name: str) -> "BattleUnit":
    """剧情敌人构造: 已知模板直接用, 否则按名字套模板并给 Boss 加数值.

    章节剧本里用到很多原版 Boss 名 (那印/干达休斯/玉皇大帝/魔王合体…),
    它们不在 ENEMY_TEMPLATES 里, 这里做兜底: 普通杂兵 1.6×、Boss(名含 王/帝/魔/那印/
    干达/乐神/合体/化身) 3×, 保证剧情战斗可玩且 Boss 更有压迫感。真实数值待从 exe
    敌人表校准 (core.battle.setup.make_enemy_by_type)。
    """
    if name in ENEMY_TEMPLATES:
        return make_enemy(name)
    base = ENEMY_TEMPLATES["黄色怪"]
    boss = any(k in name for k in ("王", "帝", "魔", "那印", "干达", "乐神", "合体", "化身"))
    mul = 3.0 if boss else 1.6
    lvl = base["level"] + (8 if boss else 2)
    max_hp = int(base["max_hp"] * mul)
    return BattleUnit(
        name=name, level=lvl, max_hp=max_hp, hp=max_hp,
        max_mp=0, mp=0, sg=0,
        attack=int(base["attack"] * mul), defence=int(base["defence"] * mul),
        agile=base["agile"], move=base["move"],
        exp_reward=int(base["exp_reward"] * mul),
        money_reward=int(base["money_reward"] * mul),
        is_player=False,
        color=(210, 70, 70) if boss else (160, 120, 160),
        sprite_key="CGHOU00",
    )


RANDOM_BATTLE_EVERY = 3
RANDOM_BATTLE_CHANCE = 0.00
REAL_MAP_BATTLE_CHANCE = 0.25


def battle_party_slots(scene: "WorldMapScene") -> list[int]:
    """出场队员槽位 (按队伍顺序, 最多 5 = exe 0x867e84 上限; 状态栏也按这个顺序排).
    原版存档: 0xBF8 人数 + 0xBFC 名单 (core.save_manager.party_slots); 重制版 JSON 存档: 导演记录的入队名单."""
    from core.party import NAME_TO_SLOT
    from core.save_manager import PARTY_MAX, party_slots
    save = scene.save
    slots = party_slots(save)
    if not slots:
        names = list(getattr(getattr(scene, "story", None), "party", []) or [])
        slots = [NAME_TO_SLOT[n] for n in names if n in NAME_TO_SLOT]
    if not slots:
        slots = list(PLAYABLE_SLOTS)
    out = []
    for s in slots:
        ch = save.characters.get(s)
        if ch is not None and ch.MaxHP > 0 and s not in out:
            out.append(s)
    return out[:PARTY_MAX]


def build_party(scene: "WorldMapScene") -> list[BattleUnit]:
    if scene.save is not None:
        chars = [unit_from_character(CHARACTER_NAMES[s], scene.save.characters[s])
                 for s in battle_party_slots(scene)]
        if chars:
            return chars
    # 无存档时的默认队伍 (主角美娜开局)
    from core.skills import default_skills_for
    return [
        BattleUnit(name="美娜", level=1, max_hp=40, hp=40, max_mp=20, mp=20, sg=10,
                   attack=14, defence=10, agile=40, move=4, is_player=True,
                   color=(220, 200, 120),
                   sprite_key=sprite_resource("美娜"),
                   known_skills=default_skills_for("美娜")),
        BattleUnit(name="孙悟空", level=1, max_hp=30, hp=30, max_mp=10, mp=10, sg=20,
                   attack=22, defence=12, agile=50, move=4, is_player=True,
                   color=(120, 200, 230),
                   sprite_key=sprite_resource("孙悟空"),
                   known_skills=default_skills_for("孙悟空")),
    ]


def maybe_trigger_battle(scene: "WorldMapScene") -> None:
    if getattr(scene, "real_map", None) is not None:
        _maybe_real_map_battle(scene)
        return
    # 走到地牢: 两个地牢分别对应不同敌人组
    if TILES[scene.grid[scene.player_y][scene.player_x]].terrain == TerrainType.DUNGEON:
        pos = (scene.player_x, scene.player_y)
        if pos == (5, 18):
            start_battle(scene, [make_enemy("乌鸦怪"), make_enemy("乌鸦怪")])
        else:  # (15, 8)
            start_battle(scene, [make_enemy("黄色怪"), make_enemy("骷髅"), make_enemy("贼")])
        return
    # 每 N 步骰: 随机战斗
    if scene.steps % RANDOM_BATTLE_EVERY == 0 and scene.rng.random() < RANDOM_BATTLE_CHANCE:
        template = scene.rng.choice(["骷髅", "乌鸦怪", "贼"])
        count = scene.rng.randint(1, 2)
        enemies = [make_enemy(template) for _ in range(count)]
        start_battle(scene, enemies)


def _make_battle_map_from_world(scene: "WorldMapScene") -> BattleMap:
    """把整张世界地图当战场: 不可通行 (水/山) → 障碍物."""
    if getattr(scene, "real_map", None) is not None:
        return scene.real_map.build_battle_map()
    bm = BattleMap(MAP_W, MAP_H)
    for y in range(MAP_H):
        for x in range(MAP_W):
            if not TILES[scene.grid[y][x]].passable:
                bm.obstacles.add((x, y))
    return bm


def _reachable_from(scene: "WorldMapScene", start: tuple[int, int]) -> set[tuple[int, int]]:
    """从 start 出发在可通行格上 BFS 能到达的连通区域 (防止单位被摆到孤岛/水上)."""
    from collections import deque
    if not scene.passable_at(start[0], start[1]):
        return {start}
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (x + dx, y + dy)
            if p in seen or not scene.passable_at(p[0], p[1]):
                continue
            seen.add(p)
            q.append(p)
    return seen


def _scatter_positions(
    scene: "WorldMapScene",
    center: tuple[int, int], count: int, ring_min: int, ring_max: int,
    avoid: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """在 center 周围 ring_min..ring_max 步范围内挑 count 个**连通**空格."""
    cx, cy = center
    reach = _reachable_from(scene, center)
    cands = []
    for r in range(ring_min, ring_max + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dx) + abs(dy) != r:
                    continue
                p = (cx + dx, cy + dy)
                if p not in reach:            # 必须可达 (含可通行判定)
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
        for y in range(scene._map_h()):
            for x in range(scene._map_w()):
                if (x, y) not in used and scene.passable_at(x, y):
                    enemy_positions.append((x, y))
                    used.add((x, y))
                    if len(enemy_positions) >= len(enemies):
                        break
            if len(enemy_positions) >= len(enemies):
                break
        break  # 防止死循环

    for e in enemies:                     # exe 摆阵 FUN_0049ff07 (普通阵型): 敌初始行动值 rand%20
        e.action_value = scene.rng.randrange(20)
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


def _maybe_real_map_battle(scene: "WorldMapScene") -> None:
    """real map encounter: roll every RANDOM_BATTLE_EVERY steps (城镇/房间不遇敌)."""
    from core import world_graph
    base = getattr(scene, "location_base", "")
    if not world_graph.has_encounters(base):
        return
    if scene.steps % RANDOM_BATTLE_EVERY != 0:
        return
    if scene.rng.random() >= REAL_MAP_BATTLE_CHANCE:
        return
    # 用该地图 .mfo 的 enemytype 池 + 原版敌人表真实数值
    types = world_graph.enemy_types(base)
    enemies: list[BattleUnit] = []
    if types:
        count = scene.rng.randint(1, 2)
        for et in scene.rng.sample(types, min(count, len(types))):
            u = make_enemy_by_type(int(et))
            if u is not None:
                enemies.append(u)
    if not enemies:                       # 缺数据 → 回退旧占位模板
        template = scene.rng.choice(["骷髅", "乌鸦怪", "贼"])
        enemies = [make_enemy(template) for _ in range(scene.rng.randint(1, 2))]
    start_battle(scene, enemies)


