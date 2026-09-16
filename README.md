# 幻想西游记 重制版

用 Python + Pygame 重制 1990 年代的 Windows 战棋 RPG《幻想西游记》。

战斗系统、技能演出、音效时序等均通过对原版 `FlyingSB.exe` 的逆向工程逐帧还原
（动画字节码、伤害结算时序、AOE 范围表、音效映射等都取自 exe 真值）。

> **版权说明**：本仓库**只包含重制代码，不含任何原版游戏资源**（图像 / 音频 / 地图 /
> 存档）。运行游戏需要你自备原版游戏拷贝，资源由脚本从你自己的拷贝中提取。
> 原游戏版权归原开发商所有。

## 环境要求

- Python 3.12+（开发环境 3.14）
- 原版《幻想西游记》游戏目录（含 `ase_fm.dll`、`ase_ps.dll`、`mapset.dll`、
  `pcxset.dll`、`se_event.dll`、`wav_eft.dll` 及 `Data/` BGM 目录）

## 跑起来

### 1. 安装依赖

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. 放置原版游戏

默认路径为仓库**上一级**的 `origin/flyingsb`：

```
你的工作目录/
├── origin/flyingsb/    # 原版游戏 (自备)
└── rewrite/            # 本仓库
```

放在别处也行，用环境变量指定：

```sh
export FLYINGSB_ORIGIN=/path/to/flyingsb
```

### 3. 提取资源

从原版 6 个 DLL 里把 sprite / 地图 / UI / 音效批量 dump 到 `assets/`：

```sh
venv/bin/python -m tools.extract_dll
```

### 4. 链接 BGM

BGM 直接使用原版 `Data/` 目录下的 WAV（不复制）：

```sh
ln -s "$FLYINGSB_ORIGIN/Data" assets/audio     # 未设环境变量则用 ../origin/flyingsb/Data
```

（Windows 无符号链接权限时，把 `Data/` 里的 `.wav` 复制到 `assets/audio/` 也可。）

### 5. 启动

```sh
venv/bin/python main.py
```

标题菜单：**竞技场**（选人 → 沙盒战斗，推荐入口）/ 新游戏 / 读取存档 / 退出。

读取存档默认找原版目录里的全剧情存档，路径可用 `FLYINGSB_SAVE` 环境变量覆盖：

```sh
export FLYINGSB_SAVE=/path/to/Save1.dat
```

## 操作

| 按键 | 作用 |
|---|---|
| 方向键 / WASD | 移动光标、走格、菜单选择 |
| Enter / Space | 确认、攻击、进入瞄准 |
| ESC | 打开战斗菜单（技能 / 道具 / 回合结束）、取消 |
| X | 取消 / 回退 |
| Shift + 方向键 | 瞄准阶段转朝向（攻击范围随朝向旋转） |
| `/` | 竞技场战斗内控制台（加敌人、退出战斗等） |

## 测试

```sh
venv/bin/python -m pytest tests/ -q
```

测试不依赖原版资源（缺资源的用例会自动 skip）。

## 目录结构

```
core/       战斗引擎、动画字节码引擎、技能演出、存档解析、音效表
scenes/     标题 / 世界地图 / 战斗 / 竞技场 场景
tools/      资源提取 (extract_dll) 等工具
tests/      pytest 单元测试
assets/     提取产物 (不入库, 由 tools/extract_dll 生成)
```
