"""五行山剧情角色 (事件 NPC) 回归测试: 按剧情 flag 显隐、可被撞到对话.

原版五行山 (.mfo) 只有峰间传送门、没有 pcpos 村民。core.event_npcs 只摆放
**有独立模型的常驻角色**: 蒙面人、被压的孙悟空。

⚠ 云妮 / 仙杜莉 这两个精灵在**原版只在过场剧情动画与对白里出现**, 没有独立的
NPC 模型 (用户校正), 因此**不作为地图 NPC** —— 她们的演出走 c3 节点的过场原文
(带 `<$CODE:帧号>` 原版立绘, 见 tests/test_cutscene_portraits.py)。
同理, 孙悟空被救出后即入队, 不再站在地图上。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from core import event_npcs
from core.event_npcs import EVENT_NPCS, events_for
from scenes.world_map.npcs import NpcLayer


def test_events_for_flag_filtering():
    # 还没触发蒙面人剧情 → 五行山无人
    assert events_for("TOH0_00P", set()) == []
    # 蒙面人已现身 → 蒙面人 + 被压的悟空
    ev = events_for("TOH0_00P", {"MASKED_DONE"})
    names = [e["name"] for e in ev]
    assert "蒙面人" in names
    assert sum(1 for n in names if n == "孙悟空") == 1
    assert any("青石" in e["line"] for e in ev), "应有被压在青石下的悟空"
    # 悟空救出后: 被压版消失 (他已入队, 不再站地图)。
    # 云妮/仙杜莉 无独立 NPC 模型 (原版只出现在过场动画), 地图上不应出现。
    ev2 = events_for("TOH0_00P", {"MASKED_DONE", "WUKONG_JOINED"})
    assert [e["name"] for e in ev2] == ["蒙面人"]
    assert not any("青石" in e["line"] for e in ev2)
    assert "云妮" not in [e["name"] for e in ev2]
    assert "仙杜莉" not in [e["name"] for e in ev2]


def _layer(flags: set) -> NpcLayer:
    return NpcLayer("TOH0_00P", active_flags=flags,
                    events=EVENT_NPCS.get("TOH0_00P", ()))


def test_layer_at_and_blocks():
    layer = _layer({"MASKED_DONE"})
    n = layer.at(20, 10)
    assert n is not None and n.get("_evt")
    assert "青石" in n["line"]
    assert layer.blocks(20, 10) is True, "剧情角色应挡路 (撞上去说话)"
    assert layer.at(14, 5) is not None          # 蒙面人
    # 无 flag 的坐标不应有人
    assert layer.at(0, 0) is None


def test_trapped_wukong_leaves_map_after_rescue():
    flags = {"MASKED_DONE"}
    layer = _layer(flags)
    assert "青石" in layer.at(20, 10)["line"]
    # 剧情推进 (同一 flag 集合对象就地更新) → 悟空入队离开, 该格不再有人
    flags.add("WUKONG_JOINED")
    layer.set_flags(flags)
    assert layer.at(20, 10) is None
    assert layer.at(14, 5) is not None          # 蒙面人仍在
    # 撤回 flag 能回到被压状态 (引用保持同步)
    flags.discard("WUKONG_JOINED")
    assert "青石" in layer.at(20, 10)["line"]


def test_no_sprites_npc_on_map():
    """云妮/仙杜莉 无独立 NPC 模型 → 任何 flag 下都不该出现在地图上."""
    for fl in (set(), {"MASKED_DONE"}, {"MASKED_DONE", "WUKONG_JOINED"}):
        names = [e["name"] for e in events_for("TOH0_00P", fl)]
        assert "云妮" not in names and "仙杜莉" not in names


def test_event_npc_talkable_in_scene():
    """进五行山后, 剧情角色能被撞到 -> 弹出对应台词对话."""
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene
    from scenes.dialogue import DialogueScene

    pygame.init()
    surf = pygame.Surface((800, 600))
    scene = WorldMapScene(surf, AudioManager(), save=new_game_save())
    scene.on_enter()
    # 模拟已推进到"蒙面人现身之后、悟空未救出" (且已完成序章, 避免开篇演出抢场)
    scene.story.state.flags.update({"PROLOGUE", "LEFT_VILLAGE", "MASKED_DONE"})
    scene.story.state.done.update({"intro", "c1_forest", "c3_masked"})
    assert scene.enter_location("TOH0_00P")
    npc = scene.npc_layer.at(20, 10)
    assert npc is not None and npc.get("_evt"), "五行山应有可见的剧情角色"
    scene._talk_to(npc)
    assert isinstance(scene.next_scene, DialogueScene)
    msgs = scene.next_scene.msgs
    assert any("青石" in m["text"] for m in msgs), "应播被压悟空的台词"
