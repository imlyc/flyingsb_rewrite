"""交互方式 + 剧情演出动画的回归测试.

1) 对话改为"走到跟前按空格", 不再是撞上去触发;
2) DialogueScene 加逐字揭示 (打字机) + 说话角色待机立绘 + 对话框入场.
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from scenes.dialogue import DialogueScene


def _scene():
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene
    pygame.init()
    surf = pygame.Surface((800, 600))
    sc = WorldMapScene(surf, AudioManager(), save=new_game_save())
    sc.on_enter()
    assert sc.enter_location("TFI0___P")
    sc.next_scene = None
    return sc


def _space(sc):
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    sc.handle_event(ev)


def _authored_npc(sc):
    """取一个手工 NPC 及其"可站立的相邻格 + 朝向" (原版 pcpos 全是门, 故用编排 NPC)."""
    for npc in sc.npc_layer._extra:
        if not npc.get("_talk"):
            continue
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            px, py = npc["x"] + dx, npc["y"] + dy
            if not sc.passable_at(px, py):
                continue
            sc.player_x, sc.player_y = px, py
            sc.facing = (-dx, -dy)
            if sc._facing_npc() is npc:
                return npc, (px, py), (-dx, -dy)
    raise AssertionError("没有可站立对话的手工 NPC")


def test_space_talks_to_facing_npc():
    sc = _scene()
    npc, (px, py), face = _authored_npc(sc)
    sc.player_x, sc.player_y = px, py
    sc.facing = face
    assert sc._facing_npc() is npc
    _space(sc)
    assert sc.next_scene is not None, "空格未触发对话"
    assert isinstance(sc.next_scene, DialogueScene)


def test_space_falls_back_to_chest_without_npc():
    sc = _scene()
    # 面朝空地 (无 NPC 无宝箱) → 空格不应崩, 也不该弹对话
    sc.player_x, sc.player_y = 2, 2
    sc.facing = (0, 1)
    assert sc._facing_npc() is None
    _space(sc)
    assert sc.next_scene is None


def test_npc_wanders_near_home():
    """手工 NPC 踱步不会离"窝"太远 (≤3 格), 也不会踩门/重叠."""
    sc = _scene()
    npc = sc.npc_layer._extra[0]
    hx, hy = npc["_home"]
    for _ in range(600):
        sc.npc_layer.tick(80, sc.passable_at)
        assert (npc["x"], npc["y"]) not in sc.npc_layer.doors
        assert abs(npc["x"] - hx) + abs(npc["y"] - hy) <= 3


def test_npc_blocks_and_walk_into_does_not_open_dialogue():
    """角色挡路 (走不进去), 但走路撞上不再自动播对白 (改按空格)."""
    sc = _scene()
    npc, (px, py), face = _authored_npc(sc)
    sc.player_x, sc.player_y = px, py
    sc.facing = face
    assert not sc.passable_at(npc["x"], npc["y"]), "NPC 应挡路"
    sc._poll_input_for_next_step(16)
    assert not isinstance(sc.next_scene, DialogueScene), "走路撞 NPC 仍自动触发了对话"


def _msgs(text):
    return [{"scene": 1, "speaker": "孙悟空", "text": text, "tags": [], "cmds": []},
            {"scene": 1, "speaker": None, "text": "第二句", "tags": [], "cmds": []}]


def test_typewriter_reveals_progressively():
    pygame.init()
    surf = pygame.Surface((800, 600))
    ds = DialogueScene(surf, messages=_msgs("一" * 100), title="t")
    assert ds._reveal == 0.0
    ds.update(1000)                      # 45 字符/秒 → 1 秒约 45 字
    assert 40 <= ds._reveal <= 50
    assert ds._reveal < 100              # 还没出完


def test_space_first_completes_then_advances():
    pygame.init()
    surf = pygame.Surface((800, 600))
    ds = DialogueScene(surf, messages=_msgs("二" * 100), title="t")
    _press = lambda: ds.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    _press()                             # 第一次: 补全本句 (不翻页)
    assert ds._reveal == 100
    assert ds.idx == 0
    _press()                             # 第二次: 翻到下一句
    assert ds.idx == 1
    assert ds._reveal == 0.0


def test_dialogue_draws_speaker_sprite_without_crash():
    """说话角色有原版精灵 → 立绘能画出来 (含待机动画取样)."""
    pygame.init()
    surf = pygame.Surface((800, 600))
    ds = DialogueScene(surf, messages=_msgs("测试一句台词"), title="t")
    unit = ds._speaker_unit("孙悟空")
    assert unit is not None, "孙悟空应有角色精灵"
    ds.update(16)
    ds.draw()                            # 不应抛异常
    # 未知说话人 (旁白/非角色名) → 不画立绘, 也不崩
    ds2 = DialogueScene(surf, messages=[{"scene": 2, "speaker": "某个村民",
                                         "text": "hi", "tags": [], "cmds": []}],
                        title="t")
    assert ds2._speaker_unit("某个村民") is None
    ds2.draw()
