"""战斗场景 HUD/菜单/banner/日志 渲染.

自由函数, 第一参数 scene. 不持有状态, 每次从 scene 读字体/颜色/数据.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.battle.data import BattleUnit, LevelUpReport, Phase
from core.character import UNSET
from core.sprites import TILE_W, TILE_H

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


# HUD 布局常量 (顶部双卡片)
HUD_X = 12
HUD_Y = 12
HUD_W_CUR = 280
HUD_W_NEXT = 220
LOG_H = 100


def draw_floats(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    now = pygame.time.get_ticks()
    for f in scene._floats:
        f.draw(scene.surface, scene._float_big, scene._float_small, cam_x, cam_y, now)


def draw_action_menu(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    """十字 4 选项, 围在当前单位四周 (上=攻 / 右=技 / 下=终 / 左=道)."""
    if not scene._menu_open:
        return
    u = scene.battle.current
    ucx = u.x * TILE_W - cam_x + TILE_W // 2
    ucy = u.y * TILE_H - cam_y + TILE_H // 2
    box_w, box_h = 56, 36
    offset = 48  # 距单位中心
    # 4 个框的 (label, center_x, center_y)
    boxes = [
        ("↑ 攻击", ucx, ucy - offset),
        ("→ 技能", ucx + offset + box_w // 2, ucy),
        ("↓ 结束", ucx, ucy + offset),
        ("← 道具", ucx - offset - box_w // 2, ucy),
    ]
    for label, x, y in boxes:
        rect = pygame.Rect(0, 0, box_w, box_h)
        rect.center = (x, y)
        # 半透明黑底 + 黄边
        bg = pygame.Surface(rect.size, pygame.SRCALPHA)
        bg.fill((0, 0, 0, 220))
        scene.surface.blit(bg, rect)
        pygame.draw.rect(scene.surface, scene.HIGHLIGHT, rect, 2)
        txt = scene._menu_font.render(label, True, scene.HIGHLIGHT)
        scene.surface.blit(txt, txt.get_rect(center=rect.center))


def draw_hud(scene: "BattleScene") -> None:
    draw_actor_card(scene, HUD_X, HUD_Y, HUD_W_CUR, 70, scene.battle.current,
                    label="当前行动", highlight=True)
    nxt = scene.battle.next_actor()
    if nxt is not None:
        draw_actor_card(scene, HUD_X + HUD_W_CUR + 12, HUD_Y, HUD_W_NEXT, 70, nxt,
                        label="下一行动", highlight=False)


def draw_actor_card(scene: "BattleScene", x: int, y: int, w: int, h: int,
                    u: BattleUnit, label: str, highlight: bool) -> None:
    rect = pygame.Rect(x, y, w, h)
    # 半透明底
    bg = pygame.Surface(rect.size, pygame.SRCALPHA)
    bg.fill((28, 22, 40, 220))
    scene.surface.blit(bg, rect)
    pygame.draw.rect(scene.surface,
                     scene.HIGHLIGHT if highlight else scene.PANEL_BORDER,
                     rect, 2 if highlight else 1)
    avatar = pygame.Rect(x + 6, y + 6, h - 12, h - 12)
    pygame.draw.rect(scene.surface, u.color, avatar)
    pygame.draw.rect(scene.surface, (0, 0, 0), avatar, 1)
    side = (u.name[0] if u.is_player else "敌")
    t = scene.font.render(side, True, (0, 0, 0))
    scene.surface.blit(t, t.get_rect(center=avatar.center))

    tx = avatar.right + 10
    ty = y + 4
    tag = scene.tiny.render(label, True,
                            scene.HIGHLIGHT if highlight else scene.DIM)
    scene.surface.blit(tag, (tx, ty)); ty += 14
    name_text = f"{u.name}  Lv{u.level}"
    t = scene.font.render(name_text, True, scene.TEXT)
    scene.surface.blit(t, (tx, ty)); ty += 22
    line = f"HP {u.hp}/{u.max_hp}   MP {u.mp}/{u.max_mp}"
    t = scene.small.render(line, True, scene.TEXT)
    scene.surface.blit(t, (tx, ty)); ty += 16
    draw_sg_icons(scene, tx, ty, u.sg)
    agi_text = f"敏 {u.agile}  移 {u.move}"
    t = scene.tiny.render(agi_text, True, scene.DIM)
    scene.surface.blit(t, (tx + 80, ty + 1))


def draw_sg_icons(scene: "BattleScene", x: int, y: int, sg: int, max_slots: int = 5) -> None:
    if sg == UNSET:
        t = scene.small.render("SG ∞", True, scene.HIGHLIGHT)
        scene.surface.blit(t, (x, y - 1))
        return
    label = scene.tiny.render("SG", True, scene.DIM)
    scene.surface.blit(label, (x, y))
    slot_w = 6; gap = 2; ox = x + 22
    slots = max(1, min(max_slots, max(1, sg // 5 if sg > 0 else 1)))
    filled = min(slots, max(0, sg // 2))
    for i in range(slots):
        r = pygame.Rect(ox + i * (slot_w + gap), y + 2, slot_w, 10)
        color = scene.HIGHLIGHT if i < filled else scene.DIM
        pygame.draw.rect(scene.surface, color, r)


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
