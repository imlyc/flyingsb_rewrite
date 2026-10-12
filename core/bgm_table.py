"""原版 BGM 编号表: 剧本 `<BGMnn>` 里的 nn → Data/*.WAV 曲名.

来源: exe 文件偏移 **0x1464c4**, 步长 4, 定长 58 项的指针表
(由 tools/find_bgm_table.py 变步长扫描定位, tools/extract_bgm_table.py 提取).
结构: 0..13 是角色主题曲 (PUSAN/SON5/MIRO/SAMJANG/JUPAL/SAOJUNG/MASK/SONATA/
PAO/JAHA/AMAZONA/OKRANG), 14..57 是场景曲 (FAIRY/WORLD1/VILL1-4/MOUNTAIN/
DUNGEON/FOREST/DESERT/TEMPLE/...)。

交叉验证 (剧本里出现过的取值与场景吻合):
  BGM2  → MIRO.WAV     梦境 (美娜主题)
  BGM15 → MONSTER.WAV  五行山 · 妖怪出没
  BGM28 → VILL3.WAV    石油村 · 村长家 (村庄曲)
  BGM53 → SLEEP.WAV    刘震之死

⚠ 别用 `<$NAME>` 去猜 BGM: 那是**角色代号** (如 <$MIRO>/<$SONA>), 前缀匹配 WAV
  会得出 'P'→PAO.WAV 这类错误映射。
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "assets" / "bgm_table.json"


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    if not TABLE.exists():
        return {}
    try:
        return json.loads(TABLE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def bgm_file(n: int | str | None) -> str | None:
    """<BGMnn> 的编号 → 曲名 (assets/audio 下的文件名); 没有则 None."""
    if n is None:
        return None
    try:
        return _table().get(str(int(n)))
    except (TypeError, ValueError):
        return None


def count() -> int:
    return len(_table())
