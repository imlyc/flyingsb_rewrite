"""幻想西游记物品数据库.

数据源: origin/mod/flyingsb/Data/item.txt (mod 编辑器 FlyingSB Editor.exe 用的原始表,
GB18030 繁体, t2s 转简体).

ID 约定: engine_id = file_line - 1 (mod 文件 1-indexed 列出, 但游戏内部 ID 0-indexed).
锚点验证:
  Save1.dat 孙悟空 Hand=128 → '如意双截棍'  ✓
  cheat asyourwish → 如意棒 = ID 199  ✓
  cheat gundamisgundam → 光剑 = ID 200  ✓

分类边界:
  HAT        0-64    (65 项)
  CLOTHES    65-120  (56 项)
  WEAPON     121-200 (80 项)
  ACCESSORY  201-298 (98 项)
  CONSUMABLE 299-355 (56 项; ID 354 在 mod 表里空缺)

技能 (skill) 段见 core/skills.py.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path

UNSET = 0xFFFFFFFF


class ItemCategory(Enum):
    HAT = "帽子"
    CLOTHES = "衣服"
    WEAPON = "武器"
    ACCESSORY = "首饰"
    CONSUMABLE = "消耗品"


def _category_for(item_id: int) -> ItemCategory:
    if item_id <= 64:
        return ItemCategory.HAT
    if item_id <= 120:
        return ItemCategory.CLOTHES
    if item_id <= 200:
        return ItemCategory.WEAPON
    if item_id <= 298:
        return ItemCategory.ACCESSORY
    return ItemCategory.CONSUMABLE


_RAW_ITEMS: dict[int, str] = {
    0: '普通帽子', 1: '草帽', 2: '圆锥帽子', 3: '皮帽子', 4: '魔法头巾',
    5: '使者帽子', 6: '银头带', 7: '金头带', 8: '钻石头带', 9: '皮帽',
    10: '风的头巾', 11: '黑暗头巾', 12: '强力头巾', 13: '羽毛帽子', 14: '高僧帽子',
    15: '铜头盔', 16: '铁盔', 17: '钢盔', 18: '银盔', 19: '金头盔',
    20: '绝世头盔', 21: '歪头帽', 22: '头盔', 23: '头盔', 24: '头盔',
    25: '头盔', 26: '头盔', 27: '头盔', 28: '头盔', 29: '头盔',
    30: '头盔', 31: '头盔', 32: '头盔', 33: '头盔', 34: '头盔',
    35: '流行的头巾', 36: '风之头巾', 37: '彩虹头巾', 38: '明王之冠', 39: '草刚之冠',
    40: '身后光', 41: '光亮的军盔', 42: '超合金头盔', 43: '背德头盔', 44: '红头巾',
    45: '轮字头巾', 46: '三重底层锅子', 47: '强力头巾', 48: '黑面具', 49: '虎面具',
    50: '暗黑面具', 51: '火炎头盔', 52: '特制的皮帽', 53: '路当的面包帽', 54: '单登的头巾',
    55: '巴合的假发', 56: '罗宾汉的羽毛', 57: '狙击手帽子', 58: '猫头鹰之眼', 59: '绿扁帽',
    60: '海盗头盔', 61: '将军头盔', 62: '刺眼的领带', 63: '仙女头叉', 64: '女神头饰',

    65: '薄衣', 66: '机械长鞋', 67: '黑帽衣', 68: '魔法袍', 69: '钻石袍',
    70: '大地袍', 71: '无拉袍', 72: '长裙', 73: '红裙', 74: '女神裙',
    75: '冰护心镜', 76: '雷电护心镜', 77: '水晶服装', 78: '天使披肩', 79: '美拉州护心镜',
    80: '陶瓷战甲', 81: '白金战甲', 82: '青铜战甲', 83: '铁战甲', 84: '银战甲',
    85: '金战甲', 86: '绝世战甲', 87: '青蛙服', 88: '防弹背心', 89: '金丝汗衫',
    90: '力量之衫', 91: '热血汗衫', 92: '公主裙', 93: '天使裙', 94: '巴起里的裙子',
    95: '高僧服装', 96: '罗汉服装', 97: '任得罗的战袍', 98: '超合金背心', 99: '特殊军服',
    100: '背德的背心', 101: '赤披肩', 102: '原厂披肩', 103: '蝙辐侠披肩', 104: '底乌个奈斯的蓑衣',
    105: '圣战甲', 106: '死者服装', 107: '特拉路战甲', 108: '龙战甲', 109: '摇滚音乐外套',
    110: '鳄鱼外套', 111: '龙皮外套', 112: '特殊皮战衣', 113: '狙击手护心镜', 114: '杀手护心镜',
    115: '魔鬼司令外套', 116: '恐布份子外套', 117: '战神外套', 118: '女神韵律服', 119: '调整型盔甲',
    120: '半透明盔甲',

    121: '空手', 122: '铁拳', 123: '铁手套', 124: '双截棍', 125: '魔双截棍',
    126: '魔风双截棍', 127: '金钢双截棍', 128: '如意双截棍', 129: '软刀', 130: '硬刀',
    131: '风剑', 132: '路罗之剑', 133: '闪刀', 134: '水晶刀', 135: '轮小刀',
    136: '音速剑', 137: '空手', 138: '木鱼', 139: '铁手套', 140: '铁木鱼',
    141: '无敌指甲', 142: '紫青手', 143: '金刚木鱼', 144: '万佛归一', 145: '火箭砲',
    146: '强力机关砲', 147: '虎砲', 148: '龙砲', 149: '风火箭砲', 150: '原子火箭砲',
    151: '自动火箭砲', 152: '手提火箭砲', 153: '黄槌子', 154: '重槌子', 155: '碰碰槌',
    156: '红色槌子', 157: '银槌子', 158: '金槌子', 159: '霸者斧头', 160: '连续槌子',
    161: '长剑', 162: '莫亚刀', 163: '鱼肠剑', 164: '修罗剑', 165: '丧节刃',
    166: '阎罗刀', 167: '太极剑', 168: '普通吉他', 169: '铁吉他', 170: '钢吉他',
    171: '铝吉他', 172: '巨型吉他', 173: '大声翁吉他', 174: '乂吉他', 175: '名人吉他',
    176: '小箭', 177: '箭', 178: '长箭', 179: '古箭', 180: '王箭',
    181: '彩虹箭', 182: '魔法箭', 183: '破无之箭', 184: '步枪', 185: '螺旋枪',
    186: '水晶枪', 187: '飞翼枪', 188: '魔力枪', 189: '雷射枪', 190: '粒子枪',
    191: '雷光枪', 192: '棍棒', 193: '光之棍', 194: '冰之棍', 195: '雷棍',
    196: '暴风棒', 197: '丝棒', 198: '魔棒', 199: '如意棒', 200: '光剑',

    201: '鳄皮腰带', 202: '强力手套', 203: '绝世手镯', 204: '狂牛之角', 205: '耳环',
    206: '黑暗之珠', 207: '贤人之戒', 208: '魔法师头饰', 209: '盗贼之脚环', 210: '大盗凉鞋',
    211: '路旁池的长靴', 212: '山神长靴', 213: '君子剑', 214: '小短刀', 215: '短刀',
    216: '老兵勋章', 217: '手套', 218: '冠军腰带', 219: '保护膝盖带', 220: '防御戒指',
    221: '爷爷腹带', 222: '佛珠', 223: '符咒', 224: '幸运钟', 225: '黄金苹果',
    226: '星形发簪', 227: '急性袜子', 228: '停止手表', 229: '乌伏之表', 230: '精灵',
    231: '新品种之证明', 232: '皮盾', 233: '小盾', 234: '黄铜盾', 235: '铁盾',
    236: '大盾', 237: '银盾', 238: '金盾', 239: '火盾', 240: '冰盾',
    241: '雷盾', 242: '绝世盾', 243: '水晶盾', 244: '血盾', 245: '钻石盾',
    246: '勇者之盾', 247: '火炎盾', 248: '英雄盾', 249: '光盾', 250: '脱皮盾',
    251: '脱皮盾', 252: '不幸盾', 253: '雷神盾', 254: '恶魔之盾', 255: '飞龙盾',
    256: '力盾', 257: '光盾', 258: '蛇血', 259: '苏醒笛子', 260: '多嘴牙齿',
    261: '有氧舞蹈', 262: '集中精神之头带', 263: '护目镜', 264: '红宝石之炼', 265: '蓝宝石之炼',
    266: '古玉之炼', 267: '珍珠之炼', 268: '钻石之炼', 269: '绿宝石之炼', 270: '珊瑚之炼',
    271: '奇迹之炼', 272: '护肩带', 273: '护胸带', 274: '护膝带', 275: '铜铁袖套',
    276: '金牌', 277: '保护纹章', 278: '银戒指', 279: '十字架', 280: '狼牙炼',
    281: '钢宝炼', 282: '陨石', 283: '纯金十字架', 284: '象牙炼', 285: '钛袖套',
    286: '英雄纹章', 287: '巨人链子', 288: '月光带', 289: '阳光带', 290: '空气盾',
    291: '音波盾', 292: '磁波之力', 293: '能量盾', 294: '岩浆防御', 295: '力量防御',
    296: '五彩窗帘', 297: '变身套', 298: '完全变身套',

    299: '恢复药', 300: '良药', 301: '优药', 302: '药草', 303: '良药',
    304: '优药', 305: '仙桃', 306: '天桃', 307: '魔法的白粉', 308: '强力针灸',
    309: '烟雾弹', 310: '解毒剂', 311: '闹钟', 312: '法式亲吻', 313: '肌肉恢复膏',
    314: '兴奋剂', 315: '双光', 316: '梦梦777', 317: '万灵丹', 318: '强力药丸',
    319: 'DHA药丸', 320: '雪药丸', 321: '幸运药丸', 322: '鼬鼠内衣', 323: '空保温瓶',
    324: '满的保温瓶', 325: '火大的丝巾', 326: '坏的手表', 327: '超级滑板', 328: '混乱笛子',
    329: '黄色炸药', 330: '线锯', 331: '时温超合金', 332: '高品质润滑油', 333: '斧头',
    334: '木材', 335: '坏掉的斧头', 336: '桥梁设计图', 337: '穿孔器', 338: '抓鸟机',
    339: '钥匙', 340: '钥匙', 341: '铲子', 342: '能量药丸', 343: '船票',
    344: '红宝石', 345: '钥匙', 346: '万年雪之精气', 347: '精灵粉', 348: '眼罩',
    349: '时温之信', 350: '仓库钥匙', 351: '山寨仓库钥匙', 352: '水晶', 353: '钥匙',
    # 354 在 mod 表里空行 (引擎未用 ID)
    355: '疆尸之炼',
}


# 公开数据: id -> (name, category)
ITEMS: dict[int, tuple[str, ItemCategory]] = {
    i: (name, _category_for(i)) for i, name in _RAW_ITEMS.items()
}


def get_item_name(item_id: int) -> str:
    """装备槽 / 道具 ID -> 中文名. UNSET (-1) -> '无'."""
    if item_id == UNSET or item_id < 0:
        return "无"
    entry = ITEMS.get(item_id)
    return entry[0] if entry else f"未知#{item_id}"


def get_item_category(item_id: int) -> ItemCategory | None:
    entry = ITEMS.get(item_id)
    return entry[1] if entry else None


assert len(ITEMS) == 355, f"Expected 355 items, got {len(ITEMS)}"


# ---------------------------------------------------------------------------
# 原版真实数值 (来源: FlyingSB.exe 物品表 VA 0x6954D4, 步长 76; 见 tools/extract_item_table.py)
#
# 字段语义已由反汇编证实 (装备应用函数 0x4334b0..0x4335a8):
#   item[+0x20/24/28/2c/30/34] = 力量/智慧/敏捷/攻击/防御/幸运 加成, 加到角色对应属性上.
#   item[+0x18] = 装备槽位掩码 (0=不可装备)
#   item[+0x1c] = 效果类型: 5=纯装备 / 6=属性药丸 / 10=状态·特殊 / 14=HP·MP回复 / 0=关键道具
#   item[+0x20] (type=14) = 回复量 (10000=全回复); item[+0x44] = 描述
# 数据落在 assets/items_table.json (由 tools.extract_item_table 生成).
# 缺数据时回退到旧的分类占位数值, 保证无资源环境 (CI/单测) 仍可跑.
# ---------------------------------------------------------------------------
_TABLE_PATH = Path(__file__).resolve().parent.parent / "assets" / "items_table.json"
_table_cache: dict | None = None


def _table() -> dict:
    global _table_cache
    if _table_cache is None:
        try:
            _table_cache = json.loads(
                _TABLE_PATH.read_text(encoding="utf-8")).get("items", {})
        except Exception:
            _table_cache = {}
    return _table_cache


def item_table_entry(item_id: int) -> dict | None:
    """原版物品记录 (含价格/属性/效果/描述). 缺 assets 时为 None."""
    return _table().get(str(item_id))


def item_slot_mask(item_id: int) -> int:
    """装备槽位掩码 (0 = 不可装备)."""
    e = item_table_entry(item_id)
    return int(e.get("slot", 0)) if e else 0


def is_equippable(item_id: int) -> bool:
    return item_slot_mask(item_id) != 0


def item_effect_type(item_id: int) -> int:
    """效果类型: 5 装备 / 6 属性药丸 / 10 状态 / 14 HP·MP 回复 / 0 关键道具."""
    e = item_table_entry(item_id)
    return int(e.get("type", 0)) if e else 0


def item_desc(item_id: int) -> str:
    """原版物品描述 (简体). 缺数据返回 ''."""
    e = item_table_entry(item_id)
    return str(e.get("desc", "")) if e else ""


def item_combat_bonus(item_id: int) -> dict[str, int]:
    """装备的真实属性加成: {"pow","wis","agi","atk","def","luk"}.

    数值直接取自原版物品表 (已由反汇编确认字段归属). 不可装备物品返回 {}.
    缺 assets 时回退旧占位 (分类常量).
    """
    e = item_table_entry(item_id)
    if e is None:                                  # 无资源回退
        cat = get_item_category(item_id)
        if cat is ItemCategory.WEAPON:
            return {"atk": 6}
        if cat is ItemCategory.CLOTHES:
            return {"def": 5, "hp": 10}
        if cat is ItemCategory.HAT:
            return {"def": 2}
        if cat is ItemCategory.ACCESSORY:
            return {"hp": 5, "mp": 5}
        return {}
    if not e.get("slot"):
        return {}
    return {k: int(v) for k, v in (e.get("stats") or {}).items() if v}


def item_effect(item_id: int) -> tuple[int, int]:
    """可用道具效果: 返回 (hp_restore, mp_restore). 全回复用 9999 表示. 非回复品 (0, 0).

    原版 type=14 的回复品, 回复量取自描述文本 (玩家可见的权威值: 如 "HP回復300"),
    全回复 (描述含 "完全回復" 或值 >= 10000) 记 9999.
    """
    e = item_table_entry(item_id)
    if e is None:                                  # 无资源回退
        cat = get_item_category(item_id)
        if cat is not ItemCategory.CONSUMABLE:
            return (0, 0)
        hp = 30 if item_id in (299, 300, 301) else 0
        mp = 60 if item_id in (302, 303, 304) else 0
        if item_id in (305, 306, 307):
            hp = mp = 9999
        return (hp, mp)
    if item_effect_type(item_id) != 14:
        return (0, 0)
    desc = str(e.get("desc", ""))
    val = int(e.get("val", 0) or 0)
    full = ("完全" in desc) or ("全回" in desc) or val >= 10000
    m = re.search(r"(\d+)", desc)
    amount = 9999 if full else (int(m.group(1)) if m else val)
    hp = amount if "HP" in desc else 0
    mp = amount if "MP" in desc else 0
    if not hp and not mp:                          # 描述未标 → 按 hp 兜底
        hp = amount
    return (hp, mp)
