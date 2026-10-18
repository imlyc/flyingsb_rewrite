"""WorldMapScene + Director 的剧情闭环集成测试 (无头, dummy display)."""

from __future__ import annotations

import pytest

from core import story as story_mod
from core.save_manager import new_game_save
from scenes.dialogue import DialogueScene
from scenes.world_map.scene import WorldMapScene

# 剧情演出的承载场景: 带原版立绘的过场走全屏 CutsceneScene, 纯文字对白走 DialogueScene.
# 这里测的是"节点接线", 不该绑死某个场景类。
_STORY_SCENES = (DialogueScene,)

try:                                    # CutsceneScene 总是可导入, 保留兜底写法
    from scenes.cutscene import CutsceneScene
    _STORY_SCENES = (DialogueScene, CutsceneScene)
except Exception:                       # pragma: no cover
    pass

pytestmark = pytest.mark.skipif(
    not story_mod.main_story(),
    reason="assets/script/messages.json 未生成 (先跑 tools.extract_script)")


class _Audio:
    def play_bgm(self, *a, **k): pass
    def stop_bgm(self, *a, **k): pass
    def play_sfx_id(self, *a, **k): pass


def _make_scene(pygame_inited):
    return WorldMapScene(pygame_inited, _Audio(), save=new_game_save())


def test_launch_dialogue_beat_opens_dialogue(pygame_inited):
    """对白型节点: 走到/触发后打开 DialogueScene, 播完即完成节点."""
    sc = _make_scene(pygame_inited)
    beat = sc.story.current()            # 序章 intro (enter=())
    assert beat is not None
    sc._launch_beat(beat)
    from scenes.prologue import PrologueScene
    assert isinstance(sc.next_scene, (DialogueScene, PrologueScene))   # 有序章数据时走原版序章演出
    sc.next_scene.on_close()             # 模拟对白播完
    assert beat.id in sc.story.state.done


def test_battle_beat_wired_and_win_recruits(pygame_inited):
    """战斗型节点: 打开对白, 胜利回调后标记完成并入队 (蒙面人)."""
    sc = _make_scene(pygame_inited)
    sc.story.state.flags.add("LEFT_VILLAGE")      # 解锁第3章蒙面人节点
    beat = sc.story.beat_for_location("TOH0_00P")
    assert beat is not None and beat.id == "c3_masked"
    sc._launch_beat(beat)
    # 战斗节点先播对白/过场, 关闭时接战斗 (on_close 已挂接)
    assert isinstance(sc.next_scene, _STORY_SCENES)
    assert sc.next_scene.on_close is not None
    # 模拟: 对白关闭 -> 进入战斗 -> 战斗胜利回调
    sc._post_battle_beat = beat
    sc._on_story_battle_end(True)
    assert beat.id in sc.story.state.done
    assert "蒙面人" in sc.story.party


def test_battle_loss_keeps_beat_pending(pygame_inited):
    """战斗失败: 节点不完成, 仍可重试."""
    sc = _make_scene(pygame_inited)
    sc.story.state.flags.add("LEFT_VILLAGE")
    beat = sc.story.beat_for_location("TOH0_00P")
    sc._post_battle_beat = beat
    sc._on_story_battle_end(False)
    assert beat.id not in sc.story.state.done
    assert sc.story.current() is not None   # 仍可继续推进
