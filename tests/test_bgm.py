"""原版 BGM 编号表回归测试.

表来源: exe 文件偏移 0x1464c4, 步长 4, 定长 58 项指针表
(tools/find_bgm_table.py 扫描定位, tools/extract_bgm_table.py 提取 → assets/bgm_table.json)

⚠ 反向提醒: 剧本里的 `<$NAME>` (无冒号, 如 <$MIRO>/<$SONA>) 是**角色代号**,
不是 BGM; 拿它前缀匹配 WAV 会得出 'P'→PAO.WAV 这类错误映射, 见 core/bgm_table 注释。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from core.bgm_table import bgm_file, count
from core.story import BEATS


def test_bgm_table_decoded():
    assert count() >= 50, "BGM 表未生成 (跑 tools.extract_bgm_table)"


def test_known_bgm_values():
    """剧本里出现过的 <BGMnn> 取值 → 曲名 (与场景对照交叉验证)."""
    assert bgm_file(2) == "MIRO.WAV"        # 梦境 (美娜主题)
    assert bgm_file(15) == "MONSTER.WAV"    # 五行山 · 妖怪出没
    assert bgm_file(28) == "VILL3.WAV"      # 石油村 · 村长家 (村庄曲)
    assert bgm_file(53) == "SLEEP.WAV"      # 刘震之死


def test_out_of_range_is_none():
    assert bgm_file(999) is None
    assert bgm_file(None) is None


def test_chapter3_cutscene_uses_original_bgm():
    """第3章过场带 <BGMnn>, 且能解析出曲名."""
    b = next(b for b in BEATS if b.id == "c3_wukong")
    msgs = b.messages()
    nums = {m.get("bgm") for m in msgs if m.get("bgm") is not None}
    assert nums, "第3章过场应带 <BGMnn>"
    assert all(bgm_file(n) for n in nums)


def test_launching_beat_switches_bgm():
    """播过场时按 <BGMnn> 切到原版曲子."""
    from core.save_manager import new_game_save
    from scenes.world_map.scene import WorldMapScene

    played: list[str] = []

    class FakeAudio:
        def play_bgm(self, name, loops=-1):
            played.append(name)

        def play_sfx_id(self, *a, **k):
            pass

    pygame.init()
    sc = WorldMapScene(pygame.Surface((800, 600)), FakeAudio(), save=new_game_save())
    sc.on_enter()
    sc.enter_location("TOH0_00P")
    sc.next_scene = None
    sc.story.state.flags.update({"LEFT_VILLAGE", "MASKED_DONE", "BOMB"})
    b = next(b for b in BEATS if b.id == "c3_wukong")
    played.clear()
    sc._launch_beat(b)
    assert "MONSTER.WAV" in played, f"过场未切到原版曲子: {played}"
