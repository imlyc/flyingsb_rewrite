"""前三章全流程回归 (新交互): 开篇演出自动 → 五指村/五行山 剧情靠"面对 NPC 按空格"推进.

序章/第1章小森林为"无地点约束"开篇节点 (自动串播); 之后的第2/3章节点改由对话触发。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from core.audio_manager import AudioManager
from core.save_manager import new_game_save
from scenes.world_map.scene import WorldMapScene
from scenes.world_map.atlas import WorldAtlasScene


@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((640, 480))
    yield


def _run_story(scene: WorldMapScene) -> None:
    """模拟主循环, 把 scene 上排队的剧情场景逐个演完 (对话结算 / 战斗判胜)."""
    cur = scene
    guard = 0
    while cur.next_scene is not None and guard < 500:
        guard += 1
        nxt = cur.next_scene
        cur.next_scene = None
        cur.on_exit()
        nxt.on_enter()
        cur = nxt
        cn = type(cur).__name__
        if cn in ("DialogueScene", "CutsceneScene"):
            cur._exit()                       # 读完 -> on_close -> _after_beat
        elif cn == "PrologueScene":
            cur._finish()                     # 原版序章演出: 相当于 ESC 跳过 -> on_close -> _after_beat
        elif cn == "BattleScene":
            scene._on_story_battle_end(True)  # 判胜 -> 结算
            cur.next_scene = scene


def _any_talk_npc(sc: WorldMapScene):
    for src in (sc.npc_layer._extra, sc.npc_layer._events, sc.npc_layer.npcs):
        for n in src:
            if n.get("_talk") and not n.get("shop"):
                return n
    return None


def _advance_by_talk(sc: WorldMapScene, limit: int = 12) -> int:
    """在本图反复"找可对话 NPC 说话"推进剧情节点, 返回推进的节点数."""
    n = 0
    for _ in range(limit):
        if sc.story.beat_for_location(sc.location_base) is None:
            break
        npc = _any_talk_npc(sc)
        assert npc is not None, f"{sc.location_base} 无可对话 NPC 推进剧情"
        sc._talk_to(npc)
        _run_story(sc)
        n += 1
    return n


def test_chapters_1_to_3_full_flow(_pygame):
    save = new_game_save()
    sc = WorldMapScene(pygame.Surface((640, 480)), AudioManager(), save)
    sc.on_enter()

    # 开篇: 序章 + 第1章小森林 (无地点约束, 自动串播)
    sc.enter_location("TBB0___P")
    _run_story(sc)
    assert {"intro", "c1_forest"} <= sc.story.state.done

    # 出村(南) -> 五指村: 剧情靠与村民对话推进
    sc.player_x, sc.player_y = 11, 12
    sc.subpx = sc.subpy = 0.0
    sc._check_transition()
    assert sc.location_base == "TFI0___P"
    assert sc.next_scene is None                     # 进图不自动弹剧情
    assert _advance_by_talk(sc) >= 5                 # 抵达→打听→炸弹→嗜酒老人→五行山线索
    assert {"c2_arrive", "c2_ask", "c2_bomb", "c2_drunk", "c2_learn"} <= sc.story.state.done
    assert "LEFT_VILLAGE" in sc.story.state.flags

    # 五指村南口 -> 选地点大地图 -> 五行山
    sc.player_x, sc.player_y = 13, 39
    sc.subpx = sc.subpy = 0.0
    sc._check_transition()
    atlas = sc.next_scene
    assert isinstance(atlas, WorldAtlasScene)
    idx = next(i for i in atlas._vis if atlas._locs[i]["id"] == 30)   # 五行山南边
    atlas.cursor = atlas._vis.index(idx)
    atlas._enter()
    assert sc.location_base == "TOH0_00P"
    assert _advance_by_talk(sc) >= 3                  # 蒙面人(战斗)→收悟空→精灵
    assert {"c3_masked", "c3_wukong", "c3_sprites"} <= sc.story.state.done
    assert "WUKONG_JOINED" in sc.story.state.flags
    assert "蒙面人" in sc.story.party and "孙悟空" in sc.story.party
