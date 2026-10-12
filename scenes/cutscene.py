"""全屏过场演出场景 (剧情动画).

在 DialogueScene 的"底部对话框"之上补一层**电影化演出**:
  · **全屏**: 上下黑边 (letterbox) + 压暗背景; 背景优先用**进入剧情前的地图画面**
    (原版过场也是在场景里播的, 这样用的是真实资源而不是凭空造背景图);
  · **立绘入场**: 当前页的原版立绘 (帧号来自剧本 `<$CODE:帧号>`, 见 core.script_text)
    居中站定, 换人时带"滑入 + 淡入"(smoothstep 缓动);
  · **淡入淡出**: 入场淡入, 最后一句播完淡出后才切回地图;
  · **逐句切 BGM**: 每页的 `<BGMnn>` (见 core.bgm_table) 不同就换曲, 同曲不重复播;
  · 逐字揭示 (打字机), 第一次按键补全本句, 再按翻页。

⚠ 背景说明: 剧本里的 `<CSnn>` (17 种取值) **没有对应的 CG 资源** (origin 下的 .avi
是片头/厂商 logo/staff 动画, 不是过场背景), 所以不伪造背景图 —— 用地图画面压暗代替。
"""
from __future__ import annotations

import pygame

from core import npc_sprites
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.unit_render import AnimationState

TYPE_CPS = 45           # 逐字揭示速度 (字符/秒)
FADE_MS = 260           # 淡入 / 淡出时长
ENTER_MS = 300          # 立绘入场时长
BOX_H = 150             # 底部文本框高度
CAST_SCALE = 2.2        # 立绘放大倍数 (电影感)
LETTERBOX = 0.08        # 上下黑边占屏高比例


class CutsceneScene(Scene):
    """全屏过场演出. 接口与 DialogueScene 兼容 (可直接替换)."""

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None = None,
                 messages: list[dict] | None = None, title: str = "过场",
                 on_close=None, backdrop: pygame.Surface | None = None,
                 audio=None) -> None:
        super().__init__(surface)
        self.return_scene = return_scene
        self.msgs = messages or []
        self.title = title
        self.on_close = on_close
        self.backdrop = backdrop
        self.audio = audio
        self.font = load_chinese_font(22)
        self.name_font = load_chinese_font(26)
        self.small = load_chinese_font(16)
        self.idx = 0
        self._reveal = 0.0
        self._fade = 0.0          # 0=全黑 1=清晰
        self._enter = 1.0         # 立绘入场进度 (首页直接站定)
        self._closing = False
        self._anim = AnimationState()
        self._bgm_played: int | None = None
        # 每页"生效 BGM": 逐页切换后延续 (剧本 <BGMnn> 语义). 段内首个非空的 BGM 作种子,
        # 故即便第 0 页本页无曲, 过场一开场也切到该段正确的原版曲子.
        first_nonempty = next((m.get("bgm") for m in self.msgs
                              if m.get("bgm") is not None), None)
        cur = first_nonempty
        self._page_bgms: list[int | None] = []
        for m in self.msgs:
            b = m.get("bgm")
            if b is not None:
                cur = b
            self._page_bgms.append(cur)
        self._apply_page_bgm()

    # ------- 数据 -------
    def _cur(self) -> dict:
        return self.msgs[self.idx] if self.msgs else {}

    def _cur_text(self) -> str:
        return self._cur().get("text") or ""

    def _cur_portraits(self) -> list[int]:
        return list(self._cur().get("portraits") or [])

    # ------- 更新 -------
    def update(self, dt_ms: int) -> None:
        if self._closing:
            self._fade = max(0.0, self._fade - dt_ms / FADE_MS)
            if self._fade <= 0.0:
                self._exit()
            return
        if self._fade < 1.0:
            self._fade = min(1.0, self._fade + dt_ms / FADE_MS)
        self._anim.tick(dt_ms, moving=False)
        full = self._cur_text()
        if self._reveal < len(full):
            self._reveal = min(len(full), self._reveal + TYPE_CPS * dt_ms / 1000.0)
        if self._enter < 1.0:
            self._enter = min(1.0, self._enter + dt_ms / ENTER_MS)

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE,
                             pygame.K_RIGHT, pygame.K_DOWN):
                if self._reveal < len(self._cur_text()):
                    self._reveal = float(len(self._cur_text()))   # 先补全
                    return True
                if self.idx >= len(self.msgs) - 1:
                    self._closing = True                          # 播完 → 淡出
                else:
                    self._goto(self.idx + 1)
            elif event.key in (pygame.K_LEFT, pygame.K_UP):
                self._goto(max(0, self.idx - 1))
            elif event.key in (pygame.K_ESCAPE, pygame.K_x):
                self._closing = True
        return True

    def _goto(self, i: int) -> None:
        prev = self._cur_portraits()
        self.idx = i
        self._reveal = 0.0
        # 换人 → 重新播入场动画; 同一组立绘保持站定
        self._enter = 0.0 if self._cur_portraits() != prev else 1.0
        self._apply_page_bgm()

    def _apply_page_bgm(self) -> None:
        """逐句切 BGM: 该页生效曲与当前曲不同才换 (避免重复起播)."""
        n = self._page_bgms[self.idx] if self.idx < len(self._page_bgms) else None
        if n is None or n == self._bgm_played or self.audio is None:
            return
        try:
            from core.bgm_table import bgm_file
            wav = bgm_file(n)
            if wav:
                self.audio.play_bgm(wav)
                self._bgm_played = n
        except Exception:
            pass

    def _exit(self) -> None:
        cb = self.on_close
        self.next_scene = self.return_scene if self.return_scene is not None else None
        if self.return_scene is None:
            self.next_scene = None
        if cb is not None:
            cb()

    # ------- 渲染 -------
    def _wrap(self, text: str, font: pygame.font.Font, max_w: int) -> list[str]:
        lines, cur = [], ""
        for ch in text:
            if ch == "\n":
                lines.append(cur)
                cur = ""
                continue
            if font.size(cur + ch)[0] > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines

    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        # --- 背景: 地图快照压暗 (原版过场在场景里播); 无快照则深渐变 ---
        if self.backdrop is not None:
            try:
                self.surface.blit(self.backdrop, (0, 0))
            except Exception:
                self.surface.fill((10, 8, 22))
            dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
            dim.fill((8, 6, 20, 205))
            self.surface.blit(dim, (0, 0))
        else:
            self.surface.fill((10, 8, 22))
            grad = pygame.Surface((sw, sh), pygame.SRCALPHA)
            pygame.draw.rect(grad, (30, 24, 60, 120), (0, 0, sw, sh // 2))
            self.surface.blit(grad, (0, 0))

        box_h = BOX_H
        box_top = sh - box_h
        self._draw_cast(sw, box_top)

        # --- 文本框 ---
        overlay = pygame.Surface((sw, box_h), pygame.SRCALPHA)
        overlay.fill((6, 4, 16, 225))
        self.surface.blit(overlay, (0, box_top))
        pygame.draw.line(self.surface, (150, 120, 220), (0, box_top), (sw, box_top), 2)

        # 说话人 (纯数字是剧本段号, 不是人名 → 不显示)
        sp = self._cur().get("speaker")
        if sp and not str(sp).strip().isdigit():
            self.surface.blit(self.name_font.render(str(sp), True, (255, 214, 96)),
                              (36, box_top + 14))

        # --- 逐字揭示 ---
        lines = self._wrap(self._cur_text(), self.font, sw - 72)[:4]
        y = box_top + 50
        rem = int(self._reveal)
        for ln in lines:
            if rem <= 0:
                break
            self.surface.blit(self.font.render(ln[:rem], True, (232, 228, 240)), (36, y))
            rem -= len(ln)
            y += 30

        # 进度 / 提示
        self.surface.blit(
            self.small.render(f"{self.idx + 1}/{len(self.msgs)}", True, (140, 132, 170)),
            (sw - 80, box_top + 16))
        hint = self.small.render("Enter/空格 继续    ESC 跳过", True, (140, 132, 170))
        self.surface.blit(hint, (sw - hint.get_width() - 24, sh - 28))
        if self._reveal >= len(self._cur_text()) and self.idx < len(self.msgs) - 1:
            tx, ty = sw - 46, sh - 54
            pygame.draw.polygon(self.surface, (255, 214, 96),
                                [(tx - 7, ty), (tx + 7, ty), (tx, ty + 9)])

        # --- 黑边 + 淡入淡出 ---
        bar = int(sh * LETTERBOX)
        pygame.draw.rect(self.surface, (0, 0, 0), (0, 0, sw, bar))
        pygame.draw.rect(self.surface, (0, 0, 0), (0, sh - bar, sw, bar))
        if self._fade < 1.0:
            ov = pygame.Surface((sw, sh))
            ov.fill((0, 0, 0))
            ov.set_alpha(int((1.0 - self._fade) * 255))
            self.surface.blit(ov, (0, 0))

    def _draw_cast(self, sw: int, box_top: int) -> None:
        """当前页的原版立绘: 居中站定, 换人带滑入 + 淡入."""
        frames = self._cur_portraits()
        if not frames or not npc_sprites.available():
            return
        surfs = []
        for f in frames:
            try:
                s = npc_sprites.surface_for(f, direction=1)
            except Exception:
                s = None
            if s is None:
                continue
            w, h = s.get_size()
            size = (int(w * CAST_SCALE), int(h * CAST_SCALE))
            surfs.append(_scaled(s, size))
        if not surfs:
            return
        gap = 26
        total = sum(s.get_width() for s in surfs) + gap * (len(surfs) - 1)
        x = (sw - total) // 2
        t = self._enter
        ease = t * t * (3 - 2 * t)                 # smoothstep
        for s in surfs:
            img = s.copy()
            img.set_alpha(int(ease * 255))
            self.surface.blit(
                img, (x + int((1 - ease) * 90), box_top - s.get_height() + 12))
            x += s.get_width() + gap


def _scaled(s: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    """放大立绘. pcx 载入的是 8 位调色板 surface, smoothscale 只吃 24/32 位;
    且未建显示窗口时 convert_alpha() 会失败 —— 故多级兜底, 不能只靠 try/except."""
    if s.get_bitsize() >= 24:
        return pygame.transform.smoothscale(s, size)
    for conv in (lambda: s.convert_alpha(), lambda: s.convert(32)):
        try:
            t = conv()
            if t.get_bitsize() >= 24:
                return pygame.transform.smoothscale(t, size)
        except Exception:
            continue
    return pygame.transform.scale(s, size)      # 最近邻, 任意色深都能用
