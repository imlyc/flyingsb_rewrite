"""序章演出: 按 core.prologue 的分场景, 每场景 = 真实地图 + 事件脚本站位的角色 + 底部对白.

实现方式: 本场景只是"导演" —— 为每个分场景把地图和在场角色渲染成一张背景图, 交给
DialogueScene 逐页播对白 (复用对话框/头像/打字机); 对白播完回到这里, 切下一场景;
全部播完回到世界地图并回调 on_close (剧情节点结算).
BGM: 场景指定 (樂神场景 = 7 SONATA) 或地图表的地图曲.
"""
from __future__ import annotations

import pygame

from core import bgm_table, npc_sprites, prologue, real_map as realm
from core.sprites.base import TILE_H, TILE_W, load_image
from scenes.base import Scene
from scenes.dialogue import DialogueScene

FRAME_W, FRAME_H = 64, 96
ANCHOR_Y = FRAME_H - TILE_H // 2 + 12      # 与 scenes.unit_render 的脚点锚一致


def _sprite_frame(code: str, frames: list[int]) -> pygame.Surface | None:
    """在场角色的站立帧: 事件脚本给了全局帧号就用它 (如封印中的孫悟空), 否则该角色图集正面第 0 帧."""
    if frames and npc_sprites.available():
        s = npc_sprites.surface_for(frames[-1], direction=1)
        if s is not None:
            return s
    res = prologue.CODE_SPRITE.get(code)
    if not res:
        return None
    path = realm.ROOT / "assets" / "sprites" / f"{res}.png"
    if not path.exists():
        path = path.with_suffix(".pcx")
        if not path.exists():
            return None
    try:
        atlas = load_image(path)
        return atlas.subsurface(pygame.Rect(0, 1 * FRAME_H, FRAME_W, FRAME_H)).copy()
    except Exception:
        return None


def render_stage(surface_size: tuple[int, int], sc: "prologue.PrologueScene") -> pygame.Surface | None:
    """地图 + 在场角色 → 背景图 (镜头对准在场角色的中心, 不出图边)."""
    if not realm.is_available(sc.base):
        return None
    m = realm.load(sc.base)
    sw, sh = surface_size
    xs = [c["x"] for c in sc.cast] or [m.w // 2]
    ys = [c["y"] for c in sc.cast] or [m.h // 2]
    cx = (sum(xs) / len(xs) + 0.5) * TILE_W
    cy = (sum(ys) / len(ys) + 0.5) * TILE_H
    cam_x = int(max(0, min(cx - sw / 2, m.w * TILE_W - sw)))
    cam_y = int(max(0, min(cy - sh / 2, m.h * TILE_H - sh)))
    layer = sc.cast[0]["z"] if sc.cast else m.layer
    surf = pygame.Surface(surface_size)
    surf.fill((0, 0, 0))
    by_row: dict[int, list[dict]] = {}
    for c in sc.cast:
        by_row.setdefault(c["y"], []).append(c)
    y0 = max(0, cam_y // TILE_H)
    y1 = min(m.h, (cam_y + sh) // TILE_H + 1)
    for y in range(y0, y1):
        m.draw_terrain(surf, cam_x, cam_y, rows=(y, y + 1))
        for c in by_row.get(y, ()):
            spr = _sprite_frame(c["code"], c.get("frames") or [])
            if spr is None:
                continue
            px = c["x"] * TILE_W + TILE_W // 2 - FRAME_W // 2 - cam_x
            py = c["y"] * TILE_H + TILE_H // 2 - ANCHOR_Y - cam_y
            surf.blit(spr, (px, py))
        m.draw_tall(surf, cam_x, cam_y, y, layer)
    return surf


class PrologueScene(Scene):
    """序章导演. 用法: scene.next_scene = PrologueScene(surface, return_scene=world_map, audio=..., on_close=...)"""

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None = None,
                 audio=None, on_close=None) -> None:
        super().__init__(surface)
        self.return_scene = return_scene
        self.audio = audio
        self.on_close = on_close
        self.pages = prologue.load_pages()
        self.scenes = prologue.scenes()
        self.idx = -1            # 当前分场景下标 (-1 = 还没开始)
        self.done = False

    # 主循环每次切回本场景都会调 on_enter: 第一次开始第 0 场, 之后推进到下一场
    def on_enter(self) -> None:
        self._advance()

    def _advance(self) -> None:
        self.idx += 1
        if self.idx >= len(self.scenes) or not self.pages:
            self._finish()
            return
        sc = self.scenes[self.idx]
        self._play_bgm(sc)
        msgs = prologue.messages_for(sc, self.pages)
        backdrop = render_stage(self.surface.get_size(), sc)
        print(f"[序章] {self.idx + 1}/{len(self.scenes)} {sc.name} — {len(msgs)} 页")
        self.next_scene = DialogueScene(self.surface, return_scene=self, messages=msgs,
                                        title=sc.name, backdrop=backdrop)

    def _play_bgm(self, sc: "prologue.PrologueScene") -> None:
        if self.audio is None:
            return
        n = sc.bgm
        if n is None:
            row = realm.map_table().get(sc.base)
            n = row.get("bgm") if row else None
        f = bgm_table.bgm_file(n) if n is not None and n >= 0 else None
        if f:
            try:
                self.audio.play_bgm(f)
            except Exception:
                pass

    def _finish(self) -> None:
        if self.done:
            return
        self.done = True
        self.next_scene = self.return_scene
        if self.on_close is not None:
            self.on_close()

    def handle_event(self, event: pygame.event.Event) -> bool:
        return True

    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
