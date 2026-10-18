"""主循环场景切换 (main.switch_scene) 回归测试.

⚠ 历史 bug: 切换时若把**新**场景的 next_scene 也清掉, 会吞掉"构造期就挂好的待切场景":
   · 新游戏 → enter_location 自动弹出序章对白 → 被清 → 序章不自动播, PROLOGUE 不置位
     (玩家只能按 G 补播, 且流程看着像"漏了开头");
   · 走进店铺地图 → 自动开店 → 被清 → 进店不开店。
故 switch_scene 只清旧场景指针。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from core.audio_manager import AudioManager
from main import switch_scene
from scenes.dialogue import DialogueScene
from scenes.menu import TitleScene
from scenes.world_map.scene import WorldMapScene


def test_switch_keeps_pending_scene_of_new_scene():
    """切到新场景时, 新场景预挂的 next_scene 必须保留."""
    pygame.init()
    surface = pygame.Surface((800, 600))

    class Old:
        def __init__(self):
            self.next_scene = None
            self.exited = False

        def on_exit(self):
            self.exited = True

    class New:
        def __init__(self):
            self.next_scene = object()      # 预挂的待切场景 (如序章对白)
            self.entered = False

        def on_enter(self):
            self.entered = True

    old, new = Old(), New()
    old.next_scene = new
    got = switch_scene(old)
    assert got is new
    assert old.next_scene is None           # 旧场景指针已清 (防回跳)
    assert old.exited and new.entered
    assert new.next_scene is not None       # ⚠ 新场景预挂的**不能**被清


def test_new_game_auto_plays_prologue():
    """标题 → 新游戏: 序章自动弹出; 播完 PROLOGUE 置位, 回到五指村."""
    pygame.init()
    surface = pygame.Surface((800, 600))
    title = TitleScene(surface, AudioManager())
    title.on_enter()
    assert title.next_scene is None

    title._action_new_game()
    assert isinstance(title.next_scene, WorldMapScene)

    # 主循环采纳世界地图 (其 enter_location 已预挂序章对白)
    world = switch_scene(title)
    assert isinstance(world, WorldMapScene)
    from scenes.prologue import PrologueScene
    assert isinstance(world.next_scene, (DialogueScene, PrologueScene)), "序章应自动弹出"

    # 播完序章 (原版序章演出 = 导演 + 若干场底部对白, 逐场按空格翻完)
    key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k)
    scene = world
    for _ in range(40):
        scene = switch_scene(scene)
        if isinstance(scene, WorldMapScene):
            break
        if isinstance(scene, PrologueScene):
            scene.update(60)                    # 原版事件脚本序章: 跑几帧后 ESC 跳过
            scene.handle_event(key(pygame.K_ESCAPE))
        elif isinstance(scene, DialogueScene):
            for _ in range(6):
                scene.update(16)
                scene.handle_event(key(pygame.K_SPACE))
                if scene.next_scene is not None:
                    break
            if scene.next_scene is None:
                scene._exit()
        assert scene.next_scene is not None
    world2 = scene
    assert isinstance(world2, WorldMapScene)
    assert "PROLOGUE" in world2.story.state.flags, "序章播完应置 PROLOGUE"
