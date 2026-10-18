"""序章演出: 分场景数据 + 导演流程 (无头)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from core import prologue
from scenes.base import Scene

needs_data = pytest.mark.skipif(not prologue.available(), reason="缺 assets/script/prologue.json (先跑 tools.extract_prologue)")


@needs_data
def test_scene_pages_cover_prologue_in_order():
    pages = prologue.load_pages()
    assert len(pages) >= 180
    scs = prologue.scenes()
    assert [s.map_id for s in scs] == [469, 470, 471, 472, 473, 474, 476]
    last = -1
    for s in scs:
        assert s.a == last + 1 and s.b >= s.a, f"{s.name} 页区间不连续"
        last = s.b
    assert scs[-1].b == len(pages) - 1, "最后一场要吃到最后一页"
    # 事件脚本真值覆盖了手摆坐标: 樂神场景两人 z=1, 大殿 5 人
    assert all(c["z"] == 1 for c in scs[0].cast)
    assert {c["code"] for c in scs[5].cast} >= {"OK", "MIRO", "DIT", "SOL", "CAP"}


@needs_data
def test_messages_have_speaker_faces():
    pages = prologue.load_pages()
    msgs = prologue.messages_for(prologue.scenes()[0], pages)
    assert msgs[0]["speaker"] == "樂神傑特" and msgs[0]["face"] == "ps_CSONA00"


class _Return(Scene):
    pass


@needs_data
def test_director_runs_all_scenes_then_returns():
    from scenes.prologue import PrologueScene
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    ret = _Return(surf)
    closed = []
    pro = PrologueScene(surf, return_scene=ret, on_close=lambda: closed.append(1))
    scene: Scene = pro
    scene.on_enter()
    played = 0
    for _ in range(50):
        nxt = scene.next_scene
        if nxt is None:
            break
        scene.next_scene = None
        scene = nxt
        scene.on_enter()
        if scene is ret:
            break
        if scene is pro:
            continue                       # 导演推进到下一场
        assert scene.msgs, "分场景对白不该为空"
        played += 1
        scene.draw()                       # 带背景图 + 对话框能画出来
        scene._exit()                      # 这一场播完
    assert scene is ret and played == 7 and closed == [1]
