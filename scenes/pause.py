"""暂停菜单 / 存档读档界面 (ESC 打开; 原版窗口样式).

  menu  继续游戏 / 保存存档 / 读取存档 / 返回标题
  save  3 个存档槽 (Enter 覆盖写入, 显示 地点/金钱/时间)
  load  3 个存档槽 (Enter 读取并重建世界场景) + (可选)原版全剧情存档

素材: `assets/ui/WHDLGBOX.png` 九宫格窗口 + `assets/ui/WHARROW.png` 光标, 与背包/对话框一致.
"""

from __future__ import annotations

import pygame

from core import game_save, ui_cursor, ui_window
from scenes.base import Scene
from scenes.menu import load_chinese_font

PANEL = pygame.Rect(230, 118, 340, 320)
SLOT_PANEL = pygame.Rect(160, 100, 480, 340)
ROW_H = 40
SLOT_ROW_H = 62          # 存档行较高: 第一行 地点/金钱/时间, 第二行 队伍(名字+Lv)


class PauseScene(Scene):
    TEXT = (232, 228, 240)
    DIM = (150, 150, 180)
    GOLD = (255, 214, 96)
    FOCUS = (70, 56, 20)

    def __init__(self, surface: pygame.Surface, world, audio, mode: str = "menu",
                 include_original: bool = False) -> None:
        super().__init__(surface)
        self.world = world                  # WorldMapScene; 标题读档时为 None
        self.audio = audio
        self.mode = mode                    # menu | save | load
        self.include_original = include_original
        self.cursor = 0
        self.msg = ""
        self.font = load_chinese_font(24)
        self.small = load_chinese_font(17)
        self.big = load_chinese_font(30)
        self._backdrop = None
        if world is not None:
            try:
                self._backdrop = world._capture_backdrop()
            except Exception:
                self._backdrop = None
        if self.mode == "menu" and self.world is None:
            self.mode = "load"

    # ------- 菜单项 -------
    def _items(self) -> list[str]:
        if self.mode == "menu":
            return ["继续游戏", "背包物品", "保存存档", "读取存档", "返回标题"]
        return []                            # 存档/读档走槽位列表

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.KEYDOWN:
            return True
        if event.key in (pygame.K_ESCAPE, pygame.K_x):
            if self.mode == "menu":
                self.next_scene = self.world        # 继续游戏
            elif self.world is not None:
                self.mode = "menu"
                self.cursor = 0
            else:
                from scenes.menu import TitleScene
                self.next_scene = TitleScene(self.surface, self.audio)
            return True
        if self.mode == "menu":
            return self._handle_menu(event)
        return self._handle_slots(event)

    def _handle_menu(self, event: pygame.event.Event) -> bool:
        items = self._items()
        if event.key in (pygame.K_UP, pygame.K_w):
            self.cursor = (self.cursor - 1) % len(items)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.cursor = (self.cursor + 1) % len(items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            act = items[self.cursor]
            if act == "继续游戏":
                self.next_scene = self.world
            elif act == "背包物品":
                if self.world is None:
                    self.msg = "标题界面无法打开背包"
                else:
                    from scenes.inventory import InventoryScene
                    self.next_scene = InventoryScene(self.surface, self.world,
                                                     self.audio, self.world.save)
            elif act == "保存存档":
                if self.world is None:
                    self.msg = "标题界面无法保存"
                else:
                    self.mode = "save"
                    self.cursor = 0
            elif act == "读取存档":
                self.mode = "load"
                self.cursor = 0
            elif act == "返回标题":
                from scenes.menu import TitleScene
                self.next_scene = TitleScene(self.surface, self.audio)
        return True

    def _slot_count(self) -> int:
        n = game_save.SLOT_COUNT + (1 if (self.include_original and self._has_original()) else 0)
        return n

    def _has_original(self) -> bool:
        try:
            from scenes.menu import DEFAULT_SAVE
            return DEFAULT_SAVE.exists()
        except Exception:
            return False

    def _handle_slots(self, event: pygame.event.Event) -> bool:
        n = self._slot_count()
        if event.key in (pygame.K_UP, pygame.K_w):
            self.cursor = (self.cursor - 1) % n
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.cursor = (self.cursor + 1) % n
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.cursor >= game_save.SLOT_COUNT:
                self._load_original()
            elif self.mode == "save":
                self._do_save(self.cursor)
            else:
                self._do_load(self.cursor)
        return True

    # ------- 存 / 读 -------
    def _do_save(self, slot: int) -> None:
        if self.world is None:
            return
        w = self.world
        game_save.save_game(w.save, w.story.state, w.location_base,
                            w.player_x, w.player_y, slot)
        self.msg = f"已保存到 存档{slot + 1}"
        print(f"[存档] slot{slot + 1}  {w.location_base} ({w.player_x},{w.player_y})")

    def _do_load(self, slot: int) -> None:
        data = game_save.load_game(slot)
        if data is None:
            self.msg = "空存档"
            return
        self.next_scene = self._build_world(data)
        print(f"[读档] slot{slot + 1}  {data.base} ({data.x},{data.y})")

    def _load_original(self) -> None:
        from core.save_manager import load_save
        from scenes.menu import DEFAULT_SAVE
        try:
            save = load_save(DEFAULT_SAVE)
        except Exception as e:
            self.msg = f"原版存档读取失败"
            print(f"[读档] 原版存档失败: {e}")
            return
        from core import game_save as gs
        data = gs.LoadedGame(save=save, base="TFI0___P", x=0, y=0, done=set(), flags=set())
        self.next_scene = self._build_world(data)

    def _build_world(self, data: game_save.LoadedGame):
        from scenes.world_map.scene import WorldMapScene
        sc = WorldMapScene(self.surface, self.audio, save=data.save)
        # 就地改集合 (场景的 npc_layer 持有同一引用), 不能整体替换
        sc.story.state.done.clear()
        sc.story.state.done.update(data.done)
        sc.story.state.flags.clear()
        sc.story.state.flags.update(data.flags)
        if data.x or data.y:
            sc.enter_location(data.base, spawn=(data.x, data.y), auto_beat=False)
        else:
            sc.enter_location(data.base, auto_beat=False)
        return sc

    # ------- 渲染 -------
    def _panel(self, rect: pygame.Rect, big: bool = False) -> None:
        win = ui_window.window("brown")
        if win is not None:
            win.draw(self.surface, rect)
            inner = pygame.Surface((rect.w - 18, rect.h - 18), pygame.SRCALPHA)
            inner.fill((8, 6, 20, 130))
            self.surface.blit(inner, (rect.x + 9, rect.y + 9))
        else:
            pygame.draw.rect(self.surface, (26, 22, 42), rect)
            pygame.draw.rect(self.surface, (150, 120, 220), rect, 2)

    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        if self._backdrop is not None:
            self.surface.blit(self._backdrop, (0, 0))
            veil = pygame.Surface((sw, sh), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 110))
            self.surface.blit(veil, (0, 0))
        else:
            self.surface.fill((12, 12, 30))

        if self.mode == "menu":
            self._draw_menu()
        else:
            self._draw_slots()

    def _draw_menu(self) -> None:
        self._panel(PANEL)
        self.surface.blit(self.big.render("暂 停", True, self.GOLD),
                          (PANEL.x + 26, PANEL.y + 16))
        cur = ui_cursor.arrow("right")
        y = PANEL.y + 76
        for i, name in enumerate(self._items()):
            sel = i == self.cursor
            if sel:
                pygame.draw.rect(self.surface, self.FOCUS,
                                 (PANEL.x + 18, y - 4, PANEL.w - 36, ROW_H - 6))
                if cur is not None:
                    self.surface.blit(cur, (PANEL.x + 24, y + 2))
                else:
                    self.surface.blit(self.font.render("▶", True, self.GOLD), (PANEL.x + 26, y))
            self.surface.blit(
                self.font.render(name, True, (255, 255, 255) if sel else self.TEXT),
                (PANEL.x + 56, y))
            y += ROW_H
        if self.msg:
            self.surface.blit(self.small.render(self.msg, True, self.GOLD),
                              (PANEL.x + 24, PANEL.bottom - 34))

    def _draw_slots(self) -> None:
        title = "保存存档" if self.mode == "save" else "读取存档"
        self._panel(SLOT_PANEL)
        self.surface.blit(self.big.render(title, True, self.GOLD),
                          (SLOT_PANEL.x + 26, SLOT_PANEL.y + 14))
        cur = ui_cursor.arrow("right")
        y = SLOT_PANEL.y + 70
        for i in range(self._slot_count()):
            sel = i == self.cursor
            row = pygame.Rect(SLOT_PANEL.x + 16, y - 4, SLOT_PANEL.w - 32, SLOT_ROW_H - 6)
            if sel:
                pygame.draw.rect(self.surface, self.FOCUS, row)
                if cur is not None:
                    self.surface.blit(cur, (SLOT_PANEL.x + 22, y + 4))
            info_d = None
            if i >= game_save.SLOT_COUNT:
                label, info, money, date = "原版存档", "光盘全剧情 Save1.dat", "", ""
                members = []
            else:
                info_d = game_save.slot_summary(i)
                label = f"存档 {i + 1}"
                members = []
                if info_d:
                    info = str(info_d["place"])
                    money = f"{info_d['money']} 金"
                    stamp = str(info_d.get("saved_at") or "")
                    date = stamp[5:16] if len(stamp) >= 16 else stamp   # MM-DD HH:MM
                    members = info_d.get("party_info") or []
                else:
                    info, money, date = "— 空 —", "", ""
            self.surface.blit(
                self.font.render(label, True, (255, 255, 255) if sel else self.TEXT),
                (SLOT_PANEL.x + 52, y))
            self.surface.blit(self.small.render(info, True,
                                                self.TEXT if info_d and i < game_save.SLOT_COUNT
                                                else self.DIM),
                              (SLOT_PANEL.x + 152, y + 4))
            if money:
                self.surface.blit(self.small.render(money, True, self.GOLD),
                                  (SLOT_PANEL.x + 252, y + 4))
            if date:
                t = self.small.render(date, True, self.DIM)
                self.surface.blit(t, (SLOT_PANEL.right - t.get_width() - 20, y + 4))
            # 第二行: 队伍 (名字 + Lv)
            if members:
                x = SLOT_PANEL.x + 52
                for nm, lv in members[:5]:
                    chip = f"{nm} Lv{lv}"
                    t = self.small.render(chip, True, self.TEXT if sel else self.DIM)
                    self.surface.blit(t, (x, y + 24))
                    x += t.get_width() + 16
            y += SLOT_ROW_H
        hint = "Enter 确认   ESC 返回"
        if self.msg:
            hint = self.msg + "   " + hint
        self.surface.blit(self.small.render(hint, True, self.GOLD),
                          (SLOT_PANEL.x + 26, SLOT_PANEL.bottom - 30))
