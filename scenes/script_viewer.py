"""剧本浏览器 / 剧情回放 (B).

数据源: `assets/script/script_table.json`
  由 `tools/extract_script_table.py` 从 FlyingSB.exe 提取, 是原版的
  "位置 / 角色 ID → 对白入口" 分派总表 (669 项 = 649 条对白 + 20 default)。
  剧本标记的语义与解析在 `core/script_text.py` (地图 NPC 对白共用同一套解析)。

操作:
  列表页   ↑↓ 选择   ←→ 预览翻页   `/` 搜索   Tab 只看有效对白   T 简/繁   Enter 回放   ESC 返回
  回放页   ←→ 翻页   ↑↓ 上/下一条     ESC 回列表
"""

from __future__ import annotations

import pygame

from core.script_text import (       # 解析逻辑在 core 层 (地图 NPC 对白也用它)
    Line,
    Page,
    Run,
    load_table,
    parse,
    raw_text,
)
from scenes.base import Scene
from scenes.menu import load_chinese_font

load_script_table = load_table      # 兼容旧调用名
parse_script_text = parse


def entry_summary(entry: dict, simplified: bool = True) -> str:
    """列表里显示的一行摘要."""
    if entry.get("default"):
        return "（默认串）Field Character Speaking. Default String"
    pages = parse(raw_text(entry, simplified))["pages"]
    return "".join(t for t, _ in pages[0][0]) if pages else "（空）"


class ScriptViewerScene(Scene):
    """左列表 + 右预览; Enter 进入回放."""

    BG = (14, 12, 26)
    PANEL = (26, 22, 42)
    EDGE = (150, 120, 220)
    TEXT = (230, 226, 240)
    DIM = (146, 138, 176)
    GOLD = (255, 214, 96)
    EMPH = (255, 236, 130)
    SEL_BG = (66, 52, 108)

    LIST_W = 330
    ROWS = 18

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None = None) -> None:
        super().__init__(surface)
        self.return_scene = return_scene
        self.entries = load_script_table()
        self.filtered: list[dict] = list(self.entries)
        self.cursor = 0
        self.top = 0
        self.preview_page = 0
        self.playing = False
        self.only_real = True
        self.simplified = True
        self.search = ""
        self.typing = False
        self._cache: dict[tuple, dict] = {}
        self.font = load_chinese_font(20)
        self.big = load_chinese_font(24)
        self.small = load_chinese_font(16)
        self.tiny = load_chinese_font(14)
        self._apply_filter()

    # ------- 数据 -------
    def _apply_filter(self) -> None:
        key = self.search.strip()
        self.filtered = [
            e for e in self.entries
            if (not self.only_real or not e.get("default"))
            and (not key or key == str(e.get("id"))
                 or key in (e.get("text") or "") or key in (e.get("s") or ""))
        ]
        self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))
        self.top = max(0, min(self.top, max(0, len(self.filtered) - self.ROWS)))
        self.preview_page = 0

    def _current(self) -> dict | None:
        if not self.filtered:
            return None
        return self.filtered[self.cursor]

    def _parse(self, entry: dict) -> dict:
        """解析并在 (id, 简繁) 上缓存 —— 列表每帧都要摘要, 不能重复解析."""
        if entry.get("default"):
            return {"speaker": None, "notes": [], "pages": []}
        key = (entry.get("id"), self.simplified)
        hit = self._cache.get(key)
        if hit is None:
            hit = parse_script_text(raw_text(entry, self.simplified))
            self._cache[key] = hit
        return hit

    def _summary(self, entry: dict) -> str:
        if entry.get("default"):
            return "（默认串）Field Character Speaking. Default String"
        pages = self._parse(entry)["pages"]
        return "".join(t for t, _ in pages[0][0]) if pages else "（空）"

    def _parsed(self) -> dict:
        e = self._current()
        if e is None:
            return {"speaker": None, "notes": [], "pages": []}
        return self._parse(e)

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return True
        if self.typing:
            return self._handle_typing(event)
        if event.key in (pygame.K_ESCAPE, pygame.K_x):
            if self.playing:
                self.playing = False
            else:
                self.next_scene = self.return_scene
            return True
        if event.key == pygame.K_SLASH:
            self.typing = True
            return True
        if event.key == pygame.K_TAB:
            self.only_real = not self.only_real
            self._apply_filter()
            return True
        if event.key == pygame.K_t:
            self.simplified = not self.simplified
            self._cache.clear()
            return True
        if event.key == pygame.K_RETURN and not self.playing:
            if self._parsed()["pages"]:
                self.playing = True
                self.preview_page = 0
            return True
        if event.key in (pygame.K_DOWN, pygame.K_s):
            if self.cursor + 1 < len(self.filtered):
                self.cursor += 1
                self.preview_page = 0
        elif event.key in (pygame.K_UP, pygame.K_w):
            if self.cursor > 0:
                self.cursor -= 1
                self.preview_page = 0
        elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_SPACE):
            self.preview_page += 1
            if self.preview_page >= len(self._parsed()["pages"]):
                if self.playing and self.cursor + 1 < len(self.filtered):
                    self.cursor += 1
                    self.preview_page = 0
                else:
                    self.preview_page = max(0, len(self._parsed()["pages"]) - 1)
        elif event.key in (pygame.K_LEFT, pygame.K_a):
            if self.preview_page > 0:
                self.preview_page -= 1
            elif self.playing and self.cursor > 0:
                self.cursor -= 1
                self.preview_page = max(0, len(self._parsed()["pages"]) - 1)
        self._scroll_into_view()
        return True

    def _handle_typing(self, event: pygame.event.Event) -> bool:
        if event.key == pygame.K_ESCAPE:
            self.typing = False
            self.search = ""
            self._apply_filter()
        elif event.key == pygame.K_RETURN:
            self.typing = False
        elif event.key == pygame.K_BACKSPACE:
            self.search = self.search[:-1]
            self._apply_filter()
        elif event.unicode and event.unicode.isprintable():
            self.search += event.unicode
            self._apply_filter()
        return True

    def _scroll_into_view(self) -> None:
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + self.ROWS:
            self.top = self.cursor - self.ROWS + 1

    # ------- 渲染 -------
    def _wrap_runs(self, runs: Line, max_w: int) -> list[Line]:
        """把一行(带强调片段)按像素宽度折行."""
        out: list[Line] = []
        cur: Line = []
        w = 0
        for text, emph in runs:
            piece = ""
            for ch in text:
                cw = self.font.size(ch)[0]
                if w + cw > max_w and piece:
                    if piece:
                        cur.append((piece, emph))
                    out.append(cur)
                    cur, w, piece = [], 0, ""
                piece += ch
                w += cw
            if piece:
                cur.append((piece, emph))
        if cur:
            out.append(cur)
        return out

    def _draw_page(self, box: pygame.Rect, parsed: dict, page_idx: int,
                   show_badge: bool = True) -> None:
        page = parsed["pages"][page_idx]
        y = box.y + 12
        if show_badge and parsed["speaker"]:
            name = self.big.render(parsed["speaker"], True, self.GOLD)
            self.surface.blit(name, (box.x + 16, y))
            y += 32
        for runs in page:
            for line in self._wrap_runs(runs, box.w - 32):
                x = box.x + 16
                for text, emph in line:
                    surf = self.font.render(text, True, self.EMPH if emph else self.TEXT)
                    if y + 28 > box.bottom - 24:
                        return
                    self.surface.blit(surf, (x, y))
                    x += surf.get_width()
                y += 28

    def _draw_playback(self, entry: dict, parsed: dict, npages: int) -> None:
        """回放模式: 全屏对白框 (贴近原版观感)."""
        sw, sh = self.surface.get_size()
        box = pygame.Rect(40, 56, sw - 80, sh - 116)
        pygame.draw.rect(self.surface, self.PANEL, box)
        pygame.draw.rect(self.surface, self.EDGE, box, 2)

        top = box.y + 18
        if parsed["speaker"]:
            self.surface.blit(self.big.render(parsed["speaker"], True, self.GOLD),
                              (box.x + 26, top))
            top += 38
        inner = pygame.Rect(box.x + 18, top, box.w - 36, box.bottom - top - 40)
        if parsed["pages"]:
            self._draw_page(inner, parsed, self.preview_page, show_badge=False)
        elif entry.get("default"):
            self.surface.blit(self.font.render(
                "（原版 default 分支, 无剧情对白）", True, self.DIM), (inner.x + 4, inner.y))

        foot = (f"FC ID {entry['id']}   代码 0x{entry['code']:06x}"
                f"   第 {self.preview_page + 1}/{npages} 页"
                f"   ←→ 翻页   ↑↓ 换条   ESC 回列表")
        fs = self.tiny.render(foot, True, self.DIM)
        self.surface.blit(fs, (box.right - fs.get_width() - 18, box.bottom - 26))
        if parsed["notes"]:
            self.surface.blit(self.tiny.render(
                "  ".join(parsed["notes"])[:90], True, (250, 200, 120)),
                (box.x + 26, box.bottom - 26))

    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        self.surface.fill(self.BG)
        if not self.entries:
            self.surface.blit(self.font.render(
                "未找到 assets/script/script_table.json", True, self.TEXT), (24, 24))
            self.surface.blit(self.small.render(
                "先运行: venv\\Scripts\\python -m tools.extract_script_table", True, self.DIM),
                (24, 56))
            return

        entry = self._current()
        parsed = self._parsed()
        npages = max(1, len(parsed["pages"]))
        self.preview_page = min(self.preview_page, npages - 1)

        # ---- 顶栏 ----
        head = (f"剧情回放   {self.cursor + 1}/{len(self.filtered)}"
                f"   {'[回放]' if self.playing else '[浏览]'}"
                f"   共 {len(self.entries)} 条   文本: {'简体' if self.simplified else '繁体(原版)'}")
        self.surface.blit(self.font.render(head, True, self.GOLD), (16, 10))
        hint = "↑↓ 选择  ←→ 翻页  Enter 回放  / 搜索  Tab 筛选  T 简/繁  ESC 返回"
        hs = self.tiny.render(hint, True, self.DIM)
        if not self.playing:
            self.surface.blit(hs, (sw - hs.get_width() - 16, 15))

        if self.playing:
            self._draw_playback(entry, parsed, npages)
            return

        # ---- 左列表 ----
        lst = pygame.Rect(16, 44, self.LIST_W, sh - 60)
        pygame.draw.rect(self.surface, self.PANEL, lst)
        pygame.draw.rect(self.surface, self.EDGE, lst, 1)
        for k in range(self.ROWS):
            i = self.top + k
            if i >= len(self.filtered):
                break
            e = self.filtered[i]
            row_y = lst.y + 6 + k * 26
            if i == self.cursor:
                pygame.draw.rect(self.surface, self.SEL_BG,
                                 pygame.Rect(lst.x + 3, row_y - 2, lst.w - 6, 25))
            color = self.TEXT if i == self.cursor else self.DIM
            label = f"{e['id']:>4d}  {self._summary(e)[:13]}"
            self.surface.blit(self.font.render(label, True, color), (lst.x + 8, row_y))

        # ---- 右预览 ----
        rp = pygame.Rect(lst.right + 12, 44, sw - lst.right - 28, sh - 60)
        pygame.draw.rect(self.surface, self.PANEL, rp)
        pygame.draw.rect(self.surface, self.EDGE, rp, 1)

        meta = (f"FC ID {entry['id']}   代码 0x{entry['code']:06x}"
                f"   对话框 {npages}   第 {self.preview_page + 1}/{npages} 页   Enter 回放")
        self.surface.blit(self.small.render(meta, True, self.GOLD), (rp.x + 12, rp.y + 8))

        box = pygame.Rect(rp.x + 12, rp.y + 40, rp.w - 24, rp.h - 78)
        pygame.draw.rect(self.surface, (10, 8, 22), box)
        pygame.draw.rect(self.surface, self.EDGE, box, 1)
        if parsed["pages"]:
            self._draw_page(box, parsed, self.preview_page)
        elif entry.get("default"):
            self.surface.blit(self.tiny.render(
                "原版 default 分支（无剧情对白）", True, self.DIM), (box.x + 16, box.y + 12))

        if parsed["notes"]:
            self.surface.blit(self.tiny.render(
                "  ".join(parsed["notes"])[:120], True, (250, 200, 120)),
                (rp.x + 12, rp.bottom - 26))

        if self.typing:
            pygame.draw.rect(self.surface, (60, 46, 96),
                             pygame.Rect(16, sh - 26, sw - 32, 22))
            self.surface.blit(self.small.render(
                f"搜索: {self.search}_   (Enter 确定 / ESC 清除)", True, self.TEXT), (20, sh - 25))
        elif self.search:
            self.surface.blit(self.tiny.render(
                f"筛选: {self.search}", True, self.DIM), (16, sh - 22))
