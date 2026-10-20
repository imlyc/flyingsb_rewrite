"""全屏过场演出场景 (scenes/cutscene.py) 回归测试."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from scenes.cutscene import CutsceneScene
from scenes.dialogue import DialogueScene
from scenes.world_map.scene import WorldMapScene


def _msg(text="测试台词", portraits=None, bgm=None, speaker=None):
    return {"scene": "P", "speaker": speaker, "text": text,
            "tags": [], "cmds": [], "portraits": portraits or [], "bgm": bgm}


def _scene(msgs, **kw):
    pygame.init()
    return CutsceneScene(pygame.Surface((640, 480)), messages=msgs, **kw)


def test_fade_in_then_stable():
    cs = _scene([_msg()])
    assert cs._fade == 0.0
    cs.update(300)
    assert cs._fade == 1.0        # 淡入完成
    cs.update(300)
    assert cs._fade == 1.0        # 不会继续涨


def test_typewriter_and_page_advance():
    # 用长句, 免得两次 update 就把字出完 (update 每次都会推进揭示)
    cs = _scene([_msg("一" * 200), _msg("二" * 200)])
    cs.update(300)                 # 淡入 (同时推进约 13 字)
    cs.update(1000)                # 再推进约 45 字
    assert 50 <= cs._reveal <= 65
    _press = lambda: cs.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    _press()                       # 补全本句
    assert cs._reveal == 200 and cs.idx == 0
    _press()                       # 翻页
    assert cs.idx == 1 and cs._reveal == 0.0


def test_closing_fades_out_then_calls_on_close():
    done = []
    cs = _scene([_msg()], on_close=lambda: done.append(1))
    cs.update(300)
    cs.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    cs.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    assert cs._closing is True
    cs.update(300)                 # 淡出结束
    assert done == [1]


def test_portrait_entrance_replays_only_when_cast_changes():
    msgs = [_msg(portraits=[3026]), _msg(portraits=[3026]), _msg(portraits=[1706])]
    cs = _scene(msgs)
    cs.update(300)
    assert cs._enter == 1.0        # 首页直接站定
    cs._goto(1)
    assert cs._enter == 1.0        # 同一组立绘 → 不重播入场
    cs._goto(2)
    assert cs._enter == 0.0        # 换人 → 重播入场动画


def test_per_line_bgm_switches_only_on_change():
    played = []

    class A:
        def play_bgm(self, name, loops=-1):
            played.append(name)

        def play_sfx_id(self, *a, **k):
            pass

    msgs = [_msg(bgm=15), _msg(bgm=15), _msg(bgm=28)]
    cs = _scene(msgs, audio=A())
    cs.update(300)
    assert played == ["MONSTER.WAV"]      # 首页起播
    cs._goto(1)
    assert played == ["MONSTER.WAV"]      # 同曲不重复起播
    cs._goto(2)
    assert played == ["MONSTER.WAV", "VILL3.WAV"]


def test_draw_with_and_without_backdrop():
    bak = pygame.Surface((640, 480))
    bak.fill((30, 40, 60))
    for backdrop in (None, bak):
        msgs = [_msg(portraits=[3026], bgm=15)]
        cs = _scene(msgs, backdrop=backdrop)
        cs.update(300)
        cs.draw()                          # 不应抛异常


def test_world_map_uses_cutscene_for_portrait_beats():
    """带原版立绘的剧情节点 → 全屏过场; 纯文字 → 底部对话框."""
    from core.audio_manager import AudioManager
    from core.save_manager import new_game_save
    from core.story import BEATS

    pygame.init()
    sc = WorldMapScene(pygame.Surface((640, 480)), AudioManager(), save=new_game_save())
    sc.on_enter()
    sc.enter_location("TOH0_00P")
    sc.next_scene = None
    sc.story.state.flags.update({"LEFT_VILLAGE", "MASKED_DONE", "BOMB"})

    b = next(x for x in BEATS if x.id == "c3_wukong")
    msgs = b.messages()
    assert sc._is_cutscene(msgs), "第3章过场应带立绘 → 判为过场"
    sc._launch_beat(b)
    assert isinstance(sc.next_scene, CutsceneScene)
    assert sc.next_scene.backdrop is not None   # 用地图画面作背景

    # 序章: 有 exe 序章数据 → 原版分场景演出 (PrologueScene); 否则纯文字 → 底部对话框
    from core import prologue
    from scenes.prologue import PrologueScene
    intro = next(x for x in BEATS if x.id == "intro")
    sc.next_scene = None
    sc._launch_beat(intro)
    assert isinstance(sc.next_scene, PrologueScene if prologue.available() else DialogueScene)
