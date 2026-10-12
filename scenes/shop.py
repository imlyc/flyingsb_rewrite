"""城镇商店 / 旅馆 —— **原版界面** (assets/ui/SPAN04.png 面板).

原版商店面板 (SPAN04, 512x368) 自带: 顶部 購買/販賣/離開 三档、左侧商品列表、
右侧「持有」栏与队伍头像列、底部「總價 / 持有金額」、下方说明框 (本模块在其上叠字).

功能:
  · 購買: 列出 core.items 里该类别的道具 (价格/可售性来自原版物品表 core.prices)
  · 販賣: 列出背包里可回收的道具 (原版卖价)
  · 離開: 退出
  · 旅馆 (INN): 住宿恢复全队 (原版真实价)
←/→(或 Tab) 换档, ↑↓ 选择, Enter 执行, ESC/X 离开.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from core.items import ItemCategory, _category_for, get_item_name, item_desc, _RAW_ITEMS
from core.prices import INN_PRICE, buy_price, sell_price, has_price_table, is_available
from core import item_icons
from core import authored_npcs as _A
from scenes.base import Scene
from scenes.menu import load_chinese_font

ROOT = Path(__file__).resolve().parent.parent
SPAN04 = ROOT / "assets" / "ui" / "SPAN04.png"

# 店铺地图 base → (店名, 分类 or None=旅馆/酒馆/客栈). 数据见 core/authored_npcs.SHOPS_RAW
_CAT_BY_KIND: dict[str, ItemCategory | None] = {
    "ITEM": ItemCategory.CONSUMABLE,
    "WEP": ItemCategory.WEAPON,
    "ARMOR": ItemCategory.CLOTHES,
    "ACC": ItemCategory.ACCESSORY,
    "INN": None,
    "PUB": None,
}
SHOPS: dict[str, tuple[str, ItemCategory | None]] = {
    base: (name, _CAT_BY_KIND.get(kind))
    for base, (name, kind) in _A.SHOPS_RAW.items()
}

# 原版面板内的版面坐标 (相对 SPAN04 左上角)
TAB_CURSOR = (32, 110, 182)                   # 購買/販賣/離開 三个档位标签下方的光标 x
LIST_XY = (16, 36)                            # 商品列表起始
ROW_H = 26
ROWS = 7
LIST_RIGHT = 336                              # 价格右对齐 x
TOTAL_VAL = (80, 236)                         # 總價 数值
GOLD_VAL = (286, 236)                         # 持有金額 数值
DESC_XY = (18, 338)                           # 说明文字 (下方框)
LOG_XY = (18, 250)                            # 操作反馈 (總價 条下方的空条)
PORTRAIT_RECT = (444, 20, 68, 244)            # 右侧队伍头像栏 (盖掉面板烘焙的死头像)
PANEL_BG = (28, 29, 65)                       # 面板底色 (盖图用)

_panel_cache: pygame.Surface | None = None


def _panel() -> pygame.Surface | None:
    global _panel_cache
    if _panel_cache is None:
        if not SPAN04.exists():
            return None
        img = pygame.image.load(str(SPAN04))
        try:
            img = img.convert()
        except pygame.error:
            pass
        _panel_cache = img
    return _panel_cache


class ShopScene(Scene):
    BG = (10, 10, 34)
    TAB_ON = (120, 226, 255)
    TAB_OFF = (96, 116, 156)
    TEXT = (226, 230, 244)
    DIM = (140, 150, 180)
    GOLD = (255, 214, 96)
    FOCUS_BG = (34, 40, 96)

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None,
                 base: str, save=None) -> None:
        super().__init__(surface)
        self.return_scene = return_scene
        self.save = save
        self.base = base
        title, cat = SHOPS.get(base, ("商店", None))
        self.title = title
        self.kind = "inn" if cat is None else "shop"
        self.cat = cat
        if cat is not None:
            self.buy_items = sorted(i for i in _RAW_ITEMS
                                    if _category_for(i) == cat and is_available(i))
        else:
            self.buy_items = []
        self.tab = 0                      # 0 购买 / 1 贩卖 / 2 离开
        self.cursor = 0
        self.top = 0
        self.log: list[str] = []
        self.font = load_chinese_font(18)
        self.big = load_chinese_font(24)
        self.small = load_chinese_font(15)
        self._panel = _panel()
        self._faces: dict[str, pygame.Surface | None] = {}
        sw, sh = surface.get_size()
        pw, ph = (self._panel.get_size() if self._panel else (512, 368))
        self.px = (sw - pw) // 2
        self.py = (sh - ph) // 2

    # ------- 数据 -------
    @property
    def money(self) -> int:
        return self.save.money if self.save is not None else 0

    def _sell_list(self) -> list[tuple[int, int]]:
        if self.save is None or getattr(self.save, "inventory", None) is None:
            return []
        out = []
        for iid, cnt in self.save.inventory.sorted():
            if sell_price(iid) is not None:
                out.append((iid, cnt))
        return out

    def _rows(self) -> int:
        """当前档位列表行数."""
        if self.kind == "inn":
            return 1
        if self.tab == 1:
            return len(self._sell_list())
        return len(self.buy_items)

    def _clamp(self) -> None:
        n = self._rows()
        self.cursor = max(0, min(self.cursor, max(0, n - 1)))
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + ROWS:
            self.top = self.cursor - ROWS + 1

    # ------- 动作 -------
    def _buy(self) -> None:
        if not self.buy_items:
            return
        iid = self.buy_items[self.cursor]
        price = buy_price(iid)
        if price is None:
            msg = f"{get_item_name(iid)} 是非卖品"
        elif self.save is None:
            msg = "(无存档, 无法结算)"
        elif self.save.money < price:
            msg = "金钱不足"
        else:
            self.save.money -= price
            self.save.inventory.add(iid, 1)
            msg = f"购入 {get_item_name(iid)}  -{price}"
        self.log.append(msg)
        del self.log[:-3]

    def _sell(self) -> None:
        rows = self._sell_list()
        if not rows or self.save is None:
            return
        iid, _cnt = rows[self.cursor]
        price = sell_price(iid)
        if price is None or not self.save.inventory.remove(iid, 1):
            return
        self.save.money += price
        self.log.append(f"卖出 {get_item_name(iid)}  +{price}")
        del self.log[:-3]
        self._clamp()

    def _rest(self) -> None:
        if self.save is None:
            self.log.append("(无存档, 无法住宿)")
        elif self.save.money < INN_PRICE:
            self.log.append("金钱不足")
        else:
            self.save.money -= INN_PRICE
            n = 0
            for ch in self.save.characters.values():
                if ch is None or ch.MaxHP <= 0:
                    continue
                ch.CurrentHP, ch.CurrentMP = ch.MaxHP, ch.MaxMP
                n += 1
            self.log.append(f"住宿完毕, 全员恢复 ({n} 人)  -{INN_PRICE}")
        del self.log[:-3]

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return True
        if event.key in (pygame.K_ESCAPE, pygame.K_x):
            self.next_scene = self.return_scene
            return True
        if self.kind != "inn":                        # 换档
            if event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_TAB):
                self.tab = (self.tab + 1) % 3
                self.cursor = self.top = 0
                return True
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self.tab = (self.tab - 1) % 3
                self.cursor = self.top = 0
                return True
        if self.tab == 2 and self.kind != "inn":      # 離開
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.next_scene = self.return_scene
            return True
        n = self._rows()
        if event.key in (pygame.K_DOWN, pygame.K_s) and n:
            self.cursor = min(n - 1, self.cursor + 1)
        elif event.key in (pygame.K_UP, pygame.K_w) and n:
            self.cursor = max(0, self.cursor - 1)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.kind == "inn":
                self._rest()
            elif self.tab == 0:
                self._buy()
            elif self.tab == 1:
                self._sell()
        self._clamp()
        return True

    # ------- 渲染 -------
    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        self.surface.fill(self.BG)
        if self._panel is None:                        # 缺素材 → 简易兜底
            self._draw_fallback(sw, sh)
            return
        self.surface.blit(self._panel, (self.px, self.py))
        ox, oy = self.px, self.py
        # 档位标签是面板自带的 (購買/販賣/離開), 只在当前档位下方画一个原版风格光标
        if self.kind != "inn":
            cx = TAB_CURSOR[self.tab]
            pygame.draw.polygon(self.surface, self.GOLD,
                                [(ox + cx, oy + 30), (ox + cx + 12, oy + 30),
                                 (ox + cx + 6, oy + 38)])
        # 列表
        lsx, lsy = ox + LIST_XY[0], oy + LIST_XY[1]
        if self.kind == "inn":
            self.surface.blit(self.font.render(
                f"住宿一晚 {INN_PRICE} 金，恢复全员 HP/MP", True, self.TEXT),
                (lsx, lsy + 8))
            sel_id, sel_price = None, INN_PRICE
        elif self.tab == 1:
            self._draw_sell(lsx, lsy)
            rows = self._sell_list()
            sel_id = rows[self.cursor][0] if rows else None
            sel_price = sell_price(sel_id) if sel_id is not None else None
        else:
            self._draw_buy(lsx, lsy)
            sel_id = self.buy_items[self.cursor] if self.buy_items else None
            sel_price = buy_price(sel_id) if sel_id is not None else None
        # 總價 / 持有金額
        self.surface.blit(self.font.render(
            str(sel_price or 0), True, self.GOLD), (ox + TOTAL_VAL[0], oy + TOTAL_VAL[1]))
        self.surface.blit(self.font.render(
            str(self.money), True, self.GOLD), (ox + GOLD_VAL[0], oy + GOLD_VAL[1]))
        self._draw_party(ox, oy)
        # 操作反馈 (總價 条下方空条)
        ly = oy + LOG_XY[1]
        for line in self.log[-2:]:
            self.surface.blit(self.small.render(line, True, self.GOLD), (ox + LOG_XY[0], ly))
            ly += 18
        # 说明框 (下方框)
        if sel_id is not None:
            desc = item_desc(sel_id) or get_item_name(sel_id)
            self.surface.blit(self.small.render(desc[:36], True, self.TEXT),
                              (ox + DESC_XY[0], oy + DESC_XY[1]))

    def _draw_buy(self, lsx: int, lsy: int) -> None:
        for k in range(ROWS):
            i = self.top + k
            if i >= len(self.buy_items):
                break
            iid = self.buy_items[i]
            y = lsy + k * ROW_H
            if i == self.cursor:
                pygame.draw.rect(self.surface, self.FOCUS_BG, (lsx - 6, y - 2, 330, 24))
                self.surface.blit(self.small.render("▶", True, self.GOLD), (lsx - 16, y + 2))
            col = (255, 255, 255) if i == self.cursor else self.TEXT
            iw = item_icons.draw(self.surface, iid, lsx, y + 1)
            self.surface.blit(self.font.render(get_item_name(iid), True, col), (lsx + iw + 6, y))
            pr = buy_price(iid)
            p = self.small.render(f"{pr} 金" if pr else "非卖品", True, self.GOLD)
            self.surface.blit(p, (lsx + LIST_RIGHT - p.get_width(), y + 3))

    def _draw_sell(self, lsx: int, lsy: int) -> None:
        rows = self._sell_list()
        if not rows:
            self.surface.blit(self.font.render("(没有可卖的东西)", True, self.TEXT),
                              (lsx, lsy + 8))
            return
        for k in range(ROWS):
            i = self.top + k
            if i >= len(rows):
                break
            iid, cnt = rows[i]
            y = lsy + k * ROW_H
            if i == self.cursor:
                pygame.draw.rect(self.surface, self.FOCUS_BG, (lsx - 6, y - 2, 330, 24))
                self.surface.blit(self.small.render("▶", True, self.GOLD), (lsx - 16, y + 2))
            col = (255, 255, 255) if i == self.cursor else self.TEXT
            iw = item_icons.draw(self.surface, iid, lsx, y + 1)
            self.surface.blit(self.font.render(f"{get_item_name(iid)} ×{cnt}", True, col),
                              (lsx + iw + 6, y))
            pr = sell_price(iid)
            p = self.small.render(f"{pr} 金" if pr else "不可卖", True, self.GOLD)
            self.surface.blit(p, (lsx + LIST_RIGHT - p.get_width(), y + 3))

    def _party_names(self) -> list[str]:
        if self.save is None:
            return []
        try:
            from core import party as party_mod
            return party_mod.active_party(self.save)
        except Exception:
            return []

    def _face(self, name: str):
        """角色 → 小头像 (取立姿精灵头部/上身, 缩到 26x26). 见 core.portraits."""
        if name in self._faces:
            return self._faces[name]
        from core import portraits
        surf = portraits.head_face(name, 26)
        self._faces[name] = surf
        return surf

    def _draw_party(self, ox: int, oy: int) -> None:
        """右侧队伍头像栏: 面板自带的是烘死的固定头像 → 盖掉, 画当前队伍真精灵."""
        x, y, w, h = PORTRAIT_RECT
        pygame.draw.rect(self.surface, PANEL_BG, (ox + x, oy + y, w, h))
        names = self._party_names()[:8]
        if not names:
            return
        slot_h = max(26, min(30, h // len(names)))
        for i, name in enumerate(names):
            face = self._face(name)
            if face is None:
                continue
            self.surface.blit(face, (ox + x + 8, oy + y + 4 + i * slot_h))

    def _draw_fallback(self, sw: int, sh: int) -> None:
        self.surface.blit(self.big.render(self.title, True, self.GOLD), (24, 20))
        self.surface.blit(self.small.render(
            "缺 assets/ui/SPAN04.png (先跑 tools.extract_dll)", True, self.TEXT), (24, 60))
