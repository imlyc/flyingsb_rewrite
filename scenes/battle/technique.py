"""敌招名横幅 — 战斗设定「攻击技术 看得到」(exe 0x7b88e4): 敌人出招前 FUN_004d0291 开实体 FUN_004cfde0,
FUN_004cb62d 等它销毁后的下一 tick 才真正开始出招.

FUN_004cfde0: 640×64 面, 上行敌人名 (8, 0x10) / 下行招式名 (8, 0x30), 字体类型 0xe; 招式名颜色对 4 (蓝, 招式 flags & 0x800000
= 0 的法术类), 否则 0 (白); 敌人名颜色对 0. 宽 = 字节数 (Big5 全角 2) × 17. 中心 = 画面框中心.
横向偏移 16.16: 起 -450, 速度 60, state 10 每 tick 速度 -4 再加到偏移, 速度 0 停 (偏移 -30); state 0x14 停 8 tick;
state 0x1e 每 tick 速度 +4 再加到偏移, 速度 > 59 销毁 (该 tick 不画). 上行画在 (中心 + 偏移 - 宽/2, 中心 y - 32),
下行 (中心 - 偏移 - 宽/2, 中心 y): 两行从两侧相向滑入, 停住, 再相背滑出.
"""
from __future__ import annotations

import pygame

from scenes.battle.status_bar import PAIR_MP, PAIR_NORMAL, draw_text

FP = 0x10000


def _bytes(text: str) -> int:
    return sum(1 if ord(c) < 0x80 else 2 for c in text)


class TechniqueBanner:
    def __init__(self, enemy_name: str, move_name: str, magic: bool) -> None:
        self.enemy = enemy_name
        self.move = move_name
        self.move_pair = PAIR_MP if magic else PAIR_NORMAL
        self.w1 = _bytes(enemy_name) * 0x11
        self.w2 = _bytes(move_name) * 0x11
        self.off = -450 * FP
        self.v = 0x3C * FP
        self.a = 4 * FP
        self.hold = 0
        self.state = 10                        # state 1 (建面 + 初值) 在构造里
        self.visible = False
        self.done = False

    def tick(self) -> None:
        if self.state == 10:
            self.v -= self.a
            self.off += self.v
            if self.v == 0:
                self.state = 0x14
                self.hold = 0
            self.visible = True
        elif self.state == 0x14:
            self.hold += 1
            if self.hold == 8:
                self.state = 0x1E
            self.visible = True
        elif self.state == 0x1E:
            self.v += self.a
            self.off += self.v
            if self.v > 0x3BFFFF:
                self.done = True
                self.visible = False
                self.state = 0
                return
            self.visible = True

    def draw(self, surf: pygame.Surface, view: tuple[int, int, int, int]) -> None:
        if not self.visible:
            return
        l, t, r, b = view
        cx, cy = l + (r - l) // 2, t + (b - t) // 2
        o = self.off // FP if self.off >= 0 else -((-self.off) // FP)       # 16.16 向零取整
        line = pygame.Surface((max(1, self.w1), 32), pygame.SRCALPHA)
        draw_text(line, 8, 0x10, self.enemy, PAIR_NORMAL, big=True)
        surf.blit(line, (cx + o - self.w1 // 2, cy - 0x20))
        line = pygame.Surface((max(1, self.w2), 32), pygame.SRCALPHA)
        draw_text(line, 8, 0x10, self.move, self.move_pair, big=True)
        surf.blit(line, (cx - o - self.w2 // 2, cy))


def banner_for(battle) -> TechniqueBanner | None:
    """当前敌人这一手的横幅 (exe FUN_004cb39e 只对敌招 0x7da1f4 != -1); 设定关 / 不出招 → None."""
    from core import game_settings
    from core.bosan_skills import mine_at
    from core.enemy_moves import move
    if not game_settings.get("battle_enemy_skill"):
        return None
    u = battle.current
    if u is None or u.is_player:
        return None
    if mine_at(battle, u):
        mid = 247                                # 站在地雷上: 本回合改为引爆 (招式 247)
    else:
        tgt = battle._pending_enemy_attack
        if tgt is None or not tgt.alive or battle._pending_enemy_skill is not None:
            return None
        mid = battle._pending_enemy_move
        if mid is None and u.enemy_moves:
            mid = u.enemy_moves[0]
    m = move(mid) if mid is not None else None
    if m is None:
        return None
    return TechniqueBanner(u.name, m.name, not (m.flags & 0x800000))
