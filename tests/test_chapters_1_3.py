"""前三章 (序章→五指村→五行山收悟空) 可玩性回归测试.

锁定两个历史阻断:
  · 阻断 A: battle_launch.make_story_enemy 依赖 ENEMY_TEMPLATES (曾漏 import, 剧情战 NameError)
  · 阻断 B: 新游戏金钱不足导致 c2_drunk(300G) 永远付不起 → 五行山剧情软锁
并模拟"按 G 推进 + 剧情战胜利"把链路一路推到 SPRITES (收悟空).
"""

from __future__ import annotations

from scenes.world_map.battle_launch import make_story_enemy

from core.save_manager import new_game_save
from core.story import Director


def test_make_story_enemy_known_templates():
    # 第三章蒙面人救援战的敌人 (曾因漏 import ENEMY_TEMPLATES 直接 NameError)
    for name in ("乌鸦怪", "黄色怪", "贼", "骷髅"):
        u = make_story_enemy(name)
        assert u is not None, f"{name} 造敌失败"
        assert u.max_hp > 0


def test_make_story_enemy_boss_fallback():
    # 不在模板里的 Boss 名也能兜底造出 (3 章后大量 Boss)
    u = make_story_enemy("那印")
    assert u is not None and u.max_hp > 0


def _advance(d: Director, save) -> bool:
    """模拟一次"推进当前节点" (纯对白=直接完成; 剧情战=模拟胜利结算)."""
    b = d.current()
    if b is None:
        return False
    if not d.apply_presave(b, save):
        return False  # 钱不够等
    d.apply_postbattle(b, save)
    return True


def test_new_game_has_enough_gold_for_drunk():
    save = new_game_save()
    assert save.money >= 300, "新游戏金钱需 >=300 以支付 c2 嗜酒老人"


def test_chapters_1_to_3_reachable():
    """从序章一路推进到收孙悟空 (SPRITES), 全程不卡死、不抛异常."""
    save = new_game_save()
    d = Director(save=save)
    assert d.current().id == "intro"

    guard = 0
    while "SPRITES" not in d.state.flags:
        # 先确认序章已放掉
        if d.current() is None:
            break
        ok = _advance(d, save)
        assert ok, f"推进中断于 {d.current() and d.current().id}"
        guard += 1
        assert guard < 50, "推进步数异常偏多, 疑似死循环"

    assert "SPRITES" in d.state.flags
    assert "WUKONG_JOINED" in d.state.flags
    assert "孙悟空" in d.state.party
    assert "蒙面人" in d.state.party
    # c2_drunk 的 300G 已扣 (800 -> 500)
    assert save.money == 800 - 300
