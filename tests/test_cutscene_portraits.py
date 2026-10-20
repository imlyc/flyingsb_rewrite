"""过场原文 + 原版立绘 回归测试.

原版立绘机制 (实证):
  · messages.json 的 P 条目**丢失**了演出标签; assets/script/scenario_full.txt
    是 exe 剧本区原文 dump, 保留 `<$CODE:帧号>` 立绘标签 (如 <$MIRO:3016>).
  · 帧号属 core.npc_sprites 的**全局编号空间** (与原版 jmp.c0 同一空间),
    可直接出图 —— 资源早已在 assets/sprites/ps_*.pcx 里。
  · tools.extract_cutscenes 把 P 条目按文本回挂到过场原文; core/story 优先播它。
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from core import npc_sprites
from core.story import BEATS, cutscenes


def _beat(bid: str):
    return next(b for b in BEATS if b.id == bid)


def test_cutscenes_mapped():
    assert len(cutscenes()) > 0, "过场原文未生成 (跑 tools.extract_cutscenes)"


def test_portrait_frames_resolve_to_images():
    """过场里出现的立绘帧号必须能真的出图."""
    assert npc_sprites.available()
    frames = []
    for b in BEATS:
        for m in b.messages():
            frames += list(m.get("portraits") or [])
    assert frames, "没有任何过场带立绘"
    bad = [f for f in frames if npc_sprites.atlas_for(f) is None]
    assert not bad, f"立绘帧号越界: {bad[:5]}"
    # 抽查真的能取到 surface
    ok = [f for f in frames[:5] if npc_sprites.surface_for(f, direction=1) is not None]
    assert len(ok) == min(5, len(frames))


def test_chapter3_beats_carry_portraits():
    """第3章过场 (蒙面人现身 / 孙悟空加入) 应带原版立绘."""
    for bid in ("c3_masked", "c3_wukong"):
        msgs = _beat(bid).messages()
        with_p = [m for m in msgs if m.get("portraits")]
        assert with_p, f"{bid} 的过场没有带立绘的对白"
        assert len(msgs) > 1, f"{bid} 应按页拆成多条对白"


def test_villager_dialogue_has_no_portrait():
    """第二章村民对白用 <$P> 槽位码, 原版本就没有立绘帧 —— 不应伪造."""
    msgs = _beat("c2_ask").messages()
    assert not [m for m in msgs if m.get("portraits")]


def test_dialogue_renders_portrait_without_crash():
    """带立绘的对白能画出来 (原版立绘优先于角色精灵)."""
    from scenes.dialogue import DialogueScene
    pygame.init()
    surf = pygame.Surface((800, 600))
    msgs = _beat("c3_masked").messages()
    hit = next(m for m in msgs if m.get("portraits"))
    ds = DialogueScene(surf, messages=[hit], title="t")
    ds.update(16)
    ds.draw()      # 不应抛异常
