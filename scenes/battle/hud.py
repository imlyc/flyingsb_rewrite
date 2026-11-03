"""战斗场景 HUD/banner/日志 渲染 (行动菜单是原版菜单系统窗口, 见 scenes.battle.battle_menu).

自由函数, 第一参数 scene. 不持有状态, 每次从 scene 读字体/颜色/数据.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.battle.data import LevelUpReport, Phase

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


# HUD 布局常量 (顶部双卡片)
LOG_H = 100


def draw_hud(scene: "BattleScene") -> None:
    """原版战斗状态栏 (scenes.battle.status_bar, exe FUN_004ce480)."""
    from scenes.battle import status_bar
    status_bar.draw(scene)


def draw_log(scene: "BattleScene") -> None:
    sw, sh = scene.surface.get_size()
    rect = pygame.Rect(8, sh - LOG_H - 8, sw - 16, LOG_H)
    bg = pygame.Surface(rect.size, pygame.SRCALPHA)
    bg.fill((20, 14, 30, 210))
    scene.surface.blit(bg, rect)
    pygame.draw.rect(scene.surface, scene.PANEL_BORDER, rect, 1)
    max_lines = max(1, (LOG_H - 12) // 18)
    msgs = scene.battle.messages[-max_lines:]
    for i, m in enumerate(msgs):
        t = scene.small.render(m, True, scene.TEXT)
        scene.surface.blit(t, (rect.x + 8, rect.y + 6 + i * 18))


def draw_end_banner(scene: "BattleScene") -> None:
    if scene.battle.phase == Phase.DEFEAT:
        _draw_simple_banner(scene, "战  败", (220, 90, 90), "游戏结束", "按任意键返回地图")
        return
    # VICTORY
    if not scene._victory_acknowledged:
        sub = f"经验 +{scene.battle.exp_gained}    金钱 +{scene.battle.money_gained}"
        _draw_simple_banner(scene, "胜  利", (90, 220, 100), sub, "按任意键继续")
        return
    # 翻升级对话框
    if 0 <= scene._levelup_idx < len(scene.battle.level_ups):
        _draw_levelup_dialog(scene, scene.battle.level_ups[scene._levelup_idx])


def _draw_simple_banner(scene: "BattleScene", title: str, color: tuple, sub: str, hint: str) -> None:
    sw, sh = scene.surface.get_size()
    big = scene.big.render(title, True, color)
    rect = big.get_rect(center=(sw // 2, sh // 2 - 30))
    bg = rect.inflate(80, 40)
    pygame.draw.rect(scene.surface, (0, 0, 0), bg)
    pygame.draw.rect(scene.surface, color, bg, 3)
    scene.surface.blit(big, rect)
    sub_t = scene.font.render(sub, True, scene.TEXT)
    scene.surface.blit(sub_t, sub_t.get_rect(center=(sw // 2, rect.bottom + 20)))
    hint_t = scene.small.render(hint, True, scene.DIM)
    scene.surface.blit(hint_t, hint_t.get_rect(center=(sw // 2, rect.bottom + 46)))


def _draw_levelup_dialog(scene: "BattleScene", rep: "LevelUpReport") -> None:
    """模仿原版 f144: 「<名字> 等级 up!」+ 「提升了 HP/攻击/防御 N」."""
    sw, sh = scene.surface.get_size()
    lines = [f"{rep.name}  等级 up!  → Lv{rep.new_level}"]
    if rep.hp_inc:  lines.append(f"  提升了 HP   +{rep.hp_inc}")
    if rep.mp_inc:  lines.append(f"  提升了 MP   +{rep.mp_inc}")
    if rep.atk_inc: lines.append(f"  提升了 攻击 +{rep.atk_inc}")
    if rep.def_inc: lines.append(f"  提升了 防御 +{rep.def_inc}")

    # 估算尺寸
    title_surf = scene.font.render(lines[0], True, scene.HIGHLIGHT)
    body_surfs = [scene.font.render(l, True, scene.TEXT) for l in lines[1:]]
    line_h = 28
    w = max(title_surf.get_width(), *(s.get_width() for s in body_surfs)) + 60
    h = 24 + line_h * len(lines) + 28  # title + body + hint
    box = pygame.Rect(0, 0, w, h)
    box.center = (sw // 2, sh // 2)

    # 半透明黑底 + 黄边
    bg = pygame.Surface(box.size, pygame.SRCALPHA)
    bg.fill((0, 0, 0, 230))
    scene.surface.blit(bg, box)
    pygame.draw.rect(scene.surface, scene.HIGHLIGHT, box, 2)

    y = box.y + 14
    scene.surface.blit(title_surf, title_surf.get_rect(midtop=(box.centerx, y)))
    y += line_h + 4
    for s in body_surfs:
        scene.surface.blit(s, (box.x + 30, y))
        y += line_h
    # 翻页提示
    idx = scene._levelup_idx + 1
    total = len(scene.battle.level_ups)
    hint = scene.small.render(f"按任意键继续 ({idx}/{total})", True, scene.DIM)
    scene.surface.blit(hint, hint.get_rect(midbottom=(box.centerx, box.bottom - 6)))
