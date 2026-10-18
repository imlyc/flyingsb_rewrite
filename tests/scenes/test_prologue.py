"""序章演出: 分场景数据 + 导演流程 (无头)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path

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


needs_events = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "assets" / "script" / "events.json").exists(),
                                  reason="缺 assets/script/events.json (先跑 tools.extract_event_scripts)")


@needs_events
def test_director_plays_event0_then_esc_returns():
    """新序章 = 跑原版事件脚本: 第 0 事件在天界 (地图 469) 摆出樂神/孫悟空, 出气泡; ESC 跳过回世界图."""
    from scenes.prologue import PrologueScene
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    ret = _Return(surf)
    closed = []
    pro = PrologueScene(surf, return_scene=ret, on_close=lambda: closed.append(1))
    pro.on_enter()
    pro.step()                                         # 第一帧: 92.00 / e0 切到天界
    assert pro.map_row is not None and pro.map_row["id"] == 469 and pro.map is not None
    saw_bubble = False
    for _ in range(600):
        pro.step()
        pro.draw()
        saw_bubble = saw_bubble or any(d.visible() and d.cur_page().lines for d in pro.bubbles)
    assert {9, 1} <= {fc for fc, a in pro.actors.items() if a.visible}, "樂神(fc9)/孫悟空(fc1) 应在场"
    assert saw_bubble, "600 tick 内应有气泡出字"
    assert pro.next_scene is None
    pro.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert pro.next_scene is ret and closed == [1]


@needs_events
def test_director_runs_whole_prologue_headless():
    """整条链 ev0→ev9 无头跑完: 换 7 张图, 自动回到世界图 (不按键, 气泡按事件模式自动翻页)."""
    from scenes.prologue import PrologueScene
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    ret = _Return(surf)
    pro = PrologueScene(surf, return_scene=ret)
    pro.on_enter()
    n = 0
    while not pro.done and n < 40000:
        pro.step()
        n += 1
        if n % 500 == 0:
            pro.draw()
    assert pro.done and pro.next_scene is ret
    assert pro.runner.history[-1] == 9 and n < 40000
    assert [m for m in pro.runner.history] == [0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]
