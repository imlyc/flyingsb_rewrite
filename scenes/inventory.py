"""背包 / 装备界面 (原版样式: WHDLGBOX 窗口 + SITEM 道具图标 + WHARROW 光标).

从世界地图按 I (或 E) 进入. 操作:
  ↑/↓   选择物品
  Enter  消耗品→当场使用(回血/回蓝); 装备→进入"选角色装备"
  装备模式下 ←/→ 选角色, Enter 装备(旧装备退回背包), Esc 取消
  Esc    返回世界地图

背包数据在 SaveData.inventory (core.inventory); 装备写入对应角色的
Head/Body/Hand/Accessories 槽. 数值/描述取自原版 exe 物品表 (见 core.items + assets/items_table.json).
"""

from __future__ import annotations

import pygame

from core import item_icons, portraits, ui_cursor, ui_window
from core.character import UNSET
from core.inventory import Inventory
from core.items import (
    ItemCategory, get_item_category, get_item_name,
    item_combat_bonus, item_desc, item_effect,
)
from core.party import NAME_TO_SLOT, active_party
from scenes.menu import load_chinese_font

_CAT_LABEL = {
    ItemCategory.HAT: "帽子",
    ItemCategory.CLOTHES: "衣服",
    ItemCategory.WEAPON: "武器",
    ItemCategory.ACCESSORY: "首饰",
    ItemCategory.CONSUMABLE: "消耗",
}

_STAT_LABEL = {"pow": "力量", "wis": "智慧", "agi": "敏捷",
               "atk": "攻击", "def": "防御", "luk": "幸运"}

FULL = 9999

# 版面 (窗口矩形)
LIST_RECT = (16, 16, 372, 500)
DETAIL_RECT = (400, 16, 384, 330)
EQUIP_RECT = (400, 356, 384, 160)
ROW_H = 28
ROWS = 14


def _detail_lines(item_id: int) -> list[str]:
    """选中物品的详情: 描述 + 属性加成 / 回复量."""
    lines: list[str] = []
    desc = item_desc(item_id)
    if desc:
        lines.append(desc)
    bon = item_combat_bonus(item_id)
    if bon:
        lines.append("  ".join(
            f"{_STAT_LABEL.get(k, k)}{v:+d}" for k, v in bon.items()))
    hp, mp = item_effect(item_id)
    if hp:
        lines.append("HP回复 " + ("全满" if hp >= FULL else str(hp)))
    if mp:
        lines.append("MP回复 " + ("全满" if mp >= FULL else str(mp)))
    return lines


def _slot_field(cat: ItemCategory) -> str | None:
    return {
        ItemCategory.HAT: "Head",
        ItemCategory.CLOTHES: "Body",
        ItemCategory.WEAPON: "Hand",
        ItemCategory.ACCESSORY: "Accessories1",
    }.get(cat)


class InventoryScene:
    """背包 + 装备界面 (原版窗口样式)."""

    BG = (10, 10, 30)
    TEXT = (232, 228, 240)
    DIM = (150, 150, 180)
    GOLD = (255, 214, 96)

    def __init__(self, surface: pygame.Surface, parent, audio, save) -> None:
        self.surface = surface
        self.parent = parent
        self.audio = audio
        self.save = save
        self.next_scene = None

        self.font = load_chinese_font(20)
        self.title_font = load_chinese_font(26)
        self.small = load_chinese_font(16)

        self.mode = "list"          # "list" | "equip"
        self.sel = 0                # 当前选中的背包物品下标
        self.top = 0
        self.target = 0             # 装备模式下选中的队伍成员下标
        self.toast = ""
        self.toast_t = 0.0
        self._refresh_items()

    # ------- 数据 -------
    # ------- 生命周期 (主循环切场景会调, 缺了会 AttributeError → 按 I 直接崩) -------
    def on_enter(self) -> None:
        self._refresh_items()

    def on_exit(self) -> None:
        pass

    def _refresh_items(self) -> None:
        self.items = self.save.inventory.sorted()   # [(id, count), ...]
        if self.sel >= len(self.items):
            self.sel = max(0, len(self.items) - 1)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + ROWS:
            self.top = self.sel - ROWS + 1

    def _party_slots(self) -> list[int]:
        return [NAME_TO_SLOT[n] for n in active_party(self.save)
                if NAME_TO_SLOT.get(n) is not None]

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return True
        if event.key == pygame.K_ESCAPE:
            if self.mode == "equip":
                self.mode = "list"
                return True
            self.next_scene = self.parent          # 返回世界地图
            return True

        if self.mode == "list":
            return self._handle_list(event)
        return self._handle_equip(event)

    def _handle_list(self, event: pygame.event.Event) -> bool:
        if not self.items:
            return True
        if event.key in (pygame.K_UP, pygame.K_w):
            self.sel = (self.sel - 1) % len(self.items)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.sel = (self.sel + 1) % len(self.items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            item_id, _ = self.items[self.sel]
            cat = get_item_category(item_id)
            if cat is ItemCategory.CONSUMABLE:
                self._use_field(item_id)
            else:
                self.mode = "equip"
                self.target = 0
        self._refresh_items()
        return True

    def _handle_equip(self, event: pygame.event.Event) -> bool:
        slots = self._party_slots()
        if not slots:
            self.mode = "list"
            return True
        if event.key in (pygame.K_LEFT, pygame.K_a):
            self.target = (self.target - 1) % len(slots)
        elif event.key in (pygame.K_RIGHT, pygame.K_d):
            self.target = (self.target + 1) % len(slots)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            item_id, _ = self.items[self.sel]
            self._equip(item_id, slots[self.target])
            self.mode = "list"
            self._refresh_items()
        return True

    # ------- 动作 -------
    def _use_field(self, item_id: int) -> None:
        hp, mp = item_effect(item_id)
        if not (hp or mp):
            self._say(f"{get_item_name(item_id)} 无法在野外使用")
            return
        slots = self._party_slots()
        if not slots:
            return
        slot = slots[0]
        ch = self.save.characters[slot]
        before_hp, before_mp = ch.CurrentHP, ch.CurrentMP
        ch.CurrentHP = min(ch.MaxHP, ch.CurrentHP + hp)
        ch.CurrentMP = min(ch.MaxMP, ch.CurrentMP + mp)
        gained_hp, gained_mp = ch.CurrentHP - before_hp, ch.CurrentMP - before_mp
        self.save.inventory.remove(item_id, 1)
        self._refresh_items()
        name = active_party(self.save)[0]
        bits = []
        if gained_hp:
            bits.append(f"+{gained_hp} HP")
        if gained_mp:
            bits.append(f"+{gained_mp} MP")
        self._say(f"{name} 使用 {get_item_name(item_id)} {(' '.join(bits)).strip()}")

    def _equip(self, item_id: int, slot: int) -> None:
        ch = self.save.characters[slot]
        cat = get_item_category(item_id)
        field = _slot_field(cat)
        if field is None:
            return
        prev = getattr(ch, field)
        setattr(ch, field, item_id)
        self.save.inventory.remove(item_id, 1)
        if prev not in (UNSET, 0xFFFFFFFF) and prev != 0:
            self.save.inventory.add(prev, 1)
        names = active_party(self.save)
        name = names[self.target] if self.target < len(names) else "?"
        self._say(f"{name} 装备 {get_item_name(item_id)}")

    def _say(self, msg: str) -> None:
        self.toast = msg
        self.toast_t = 2.0

    # ------- 更新 / 渲染 -------
    def update(self, dt_ms: int) -> None:
        if self.toast_t > 0:
            self.toast_t -= dt_ms / 1000.0
            if self.toast_t <= 0:
                self.toast = ""

    def _window(self, rect: pygame.Rect) -> bool:
        """画一个原版窗口, 返回是否用了真素材."""
        win = ui_window.window("brown")
        if win is not None:
            win.draw(self.surface, rect)
            # 原版窗口内是暗底 (面板纹理偏亮, 叠一层半透明黑让字跳出来)
            inner = pygame.Surface((rect.w - 18, rect.h - 18), pygame.SRCALPHA)
            inner.fill((8, 6, 20, 120))
            self.surface.blit(inner, (rect.x + 9, rect.y + 9))
            return True
        pygame.draw.rect(self.surface, (30, 24, 48), rect)
        pygame.draw.rect(self.surface, (150, 120, 220), rect, 2)
        return False

    def draw(self) -> None:
        self.surface.fill(self.BG)
        self._draw_list(pygame.Rect(*LIST_RECT))
        self._draw_detail(pygame.Rect(*DETAIL_RECT))
        self._draw_equip(pygame.Rect(*EQUIP_RECT))
        if self.toast:
            t = self.font.render(self.toast, True, self.GOLD)
            self.surface.blit(t, (LIST_RECT[0] + 20, LIST_RECT[1] + LIST_RECT[3] + 8))

    def _draw_list(self, box: pygame.Rect) -> None:
        self._window(box)
        self.surface.blit(self.title_font.render("背 包", True, self.GOLD),
                          (box.x + 18, box.y + 12))
        cur = ui_cursor.arrow("right")
        y0 = box.y + 54
        if not self.items:
            self.surface.blit(self.font.render("背包为空", True, self.TEXT),
                              (box.x + 20, y0))
            return
        for k in range(ROWS):
            i = self.top + k
            if i >= len(self.items):
                break
            item_id, count = self.items[i]
            y = y0 + k * ROW_H
            sel = (i == self.sel)
            if sel and cur is not None:
                self.surface.blit(cur, (box.x + 10, y + 3))
            elif sel:
                self.surface.blit(self.small.render("▶", True, self.GOLD), (box.x + 12, y + 4))
            iw = item_icons.draw(self.surface, item_id, box.x + 30, y + 2)
            col = (255, 255, 255) if sel else self.TEXT
            self.surface.blit(self.font.render(get_item_name(item_id), True, col),
                              (box.x + 30 + iw + 8, y))
            cnt = self.small.render(f"×{count}", True, self.GOLD)
            self.surface.blit(cnt, (box.right - cnt.get_width() - 16, y + 5))
        # 上下有更多
        tip = self.small.render(
            f"{self.top + 1}-{min(len(self.items), self.top + ROWS)}/{len(self.items)}"
            "   ↑↓ 选择  Enter 使用/装备  Esc 返回", True, self.DIM)
        self.surface.blit(tip, (box.x + 18, box.bottom - 26))

    def _draw_detail(self, box: pygame.Rect) -> None:
        self._window(box)
        if not self.items:
            return
        item_id, _ = self.items[self.sel]
        cat = get_item_category(item_id)
        self.surface.blit(self.title_font.render(get_item_name(item_id), True, self.GOLD),
                          (box.x + 18, box.y + 12))
        tag = self.small.render(_CAT_LABEL.get(cat, ""), True, self.DIM)
        self.surface.blit(tag, (box.right - tag.get_width() - 18, box.y + 18))
        item_icons.draw(self.surface, item_id, box.x + 20, box.y + 48)
        dy = box.y + 52
        for line in _detail_lines(item_id)[:8]:
            self.surface.blit(self.font.render(line, True, self.TEXT), (box.x + 52, dy))
            dy += 26

    def _draw_equip(self, box: pygame.Rect) -> None:
        self._window(box)
        names = active_party(self.save)
        slots = self._party_slots()
        self.surface.blit(self.small.render("队伍 / 装备", True, self.GOLD),
                          (box.x + 18, box.y + 8))
        y = box.y + 34
        for i, slot in enumerate(slots):
            ch = self.save.characters[slot]
            sel = (self.mode == "equip" and i == self.target)
            face = portraits.head_face(names[i], 22) if i < len(names) else None
            row = pygame.Rect(box.x + 12, y - 2, box.width - 24, 26)
            if sel:
                pygame.draw.rect(self.surface, (60, 50, 20), row)
                self.surface.blit(self.small.render("▶", True, self.GOLD), (box.x + 16, y + 3))
            if face is not None:
                self.surface.blit(face, (box.x + 30, y + 1))
            nm = self.small.render(f"{names[i]}", True,
                                   (255, 255, 255) if sel else self.TEXT)
            self.surface.blit(nm, (box.x + 58, y + 3))
            if ch.MaxHP > 0:
                hp = self.small.render(f"HP {max(0, ch.CurrentHP)}/{ch.MaxHP}", True, (200, 230, 200))
                self.surface.blit(hp, (box.right - hp.get_width() - 14, y + 3))
            y += 28
            if y > box.bottom - 24:
                break
