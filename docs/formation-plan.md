# 开局编成方案（支援卡 + 回忆）

支援卡和回忆按社区规则一起选，方案写进 `conf/formation-plan.json`。开局时程序按方案里的编成号开局，并在第 2、3 步核对编成。
不想用方案时，照旧设 `HIRO_SUPPORT_SET` / `HIRO_MEMORY_SET` 即可；两者都写了时以环境变量为准。

## 用法

1. 扫库存（实机，只读，会操作游戏翻页）：
   - 支援卡：编成页点一个空格进入「選択」列表，停在第 1 页顶部，运行 `python tools/support_inventory.py --list` → `reports/live/support-inventory.json`
   - 回忆：编成页点开任意一格回忆，停在回忆选择页，运行 `python tools/memory_inventory.py --live` → `reports/live/memory-inventory.json`
2. 出方案（离线）：

   ```bash
   python -m hiro.brain.formation_plan --idol <偶像卡 skin id> --support-set 20 --memory-set 20
   ```

   写出 `conf/formation-plan.json` 和给人看的 `reports/live/formation-plan.md`。`--main-attr` 指定默认主属性，`--fixed-main` 不比较逆练。
3. 在游戏里按报告把卡存进支援卡编成 20、メモリー編成 20（别覆盖自己常用的编成）。
4. 开局照常跑 `python tools/play_game.py --idol …`（不用再设编成号）。`hiro.kaa_env` 读到方案，并且方案里的偶像和 `--idol` 一致时：
   - 支援卡、回忆改用方案里的编成号；方案的 `memory.chosen[].timing` 区分 `start`（开局入手）、`mid`（首考后入手）与未知。只有确认 `start` 的卡在开局计为已有；其余等牌组观测或实际获得记录确认；
   - 没给 `--main-attr` 时用方案里的主属性；租借格把两页租借列表看完，每张按「加上它之后整个编成的价值」打分（`support_select.rental_scorer`，
     和选自己 5 张同一套估价），租价值最高的（没有方案时仍是「主属性、等级最高，碰到满级立刻租」）；
   - 第 2 步读 5 格支援卡和方案比，第 3 步在 KAA 选完编成后读「N/20」和方案比，再认四格回忆的技能卡小图标和方案的回忆卡比。
     对不上就抛 `FormationMismatch`，不开局，退出码 3。`HIRO_MEMORY_CARD_CHECK=warn` 回忆卡对不上只警告，`off` 不认图标（默认 `block`）。
     没有卡面素材（`AssetSource.card_art_dir()` 为空）时图标一律「认不出」，只警告。
   手动设 `HIRO_MEMORY_CARDS` 时，可设等长的 `HIRO_MEMORY_CARD_TIMINGS=start,mid,unknown,...`；未提供时机的卡不会被预先计为已有。旧方案没有 `chosen[].timing` 仍可读取，但时机视为未知。`HIRO_FORMATION_PLAN=off` 不读方案，`HIRO_FORMATION_PLAN=<路径>` 读指定文件。

## 回忆小图标认卡（`hiro.vision.memory_icons`）

第 3 步每格回忆右边有一张技能卡小图（边长 87 像素），上面叠着效果角标、「+」、费用、元気、课程数值、定制计数。

**渲染模板（推荐）**：图标的真实结构取自游戏客户端（开局准备页回忆格的技能卡图标预制件）：圆角底板 + 稀有度底色（SSR 彩虹、SR / R 渐变）
+ 卡面插画按分类遮罩裁形（主动卡六边形、精神卡圆形）+ 分类外框 + 深灰外框。`hiro.vision.card_icon_render` 按这个结构把每张卡面渲染成干净图标。
认卡时把截图图标缩到 48×48，遮掉角标可能出现的区域，剩下的像素和全部模板比 Lab 距离，按卡汇总。

启用（零件和卡面用随仓库的素材包 assets/pack/）：

```bash
python -m hiro.vision.card_icon_render build        # 生成渲染库 cache/card_icons.npz（约 2300 张，几分钟）
```

关掉了素材包时，先 `pip install UnityPy` 再 `python tools/assets/export_card_sprites.py`，从你自己的客户端导出 13 张界面精灵图。

- 「认出」= 最佳分 ≤ 20、和第二名差 ≥ 10、不是平色。离线验证（KAA 卡面）：正例 12 个（第 3 步 4 格 + 详情栏 8 个）全对，分差 ≥ 14；
  低清角标压满的一张、纯灰图、截到背景的位置落在「认不出」。
- 核对不看顺序。某格有把握地认成方案外的卡（比方案里最像的那张好 5 分以上）才拦；认不出、拿不准只记警告；四格都认不出时提示布局可能变了。
- 没有渲染库时退回旧方法：和整张卡面插画比（区分度低很多，日志里 `method` 写 `art`）；连卡面都没有时一律「认不出」，只警告。

## 选法和社区依据

支援卡（`hiro.brain.support_select`）：

- 每张卡的价值是各词条效果乘以这条路线上的实际触发次数，再加支援事件给的属性、卡和 P 点 [いおん ep02 / ep08]。事件送的卡如果会污染牌组就扣分 [ep05]。
- 编成按 4-2-0 或 4-1-1 组，SP 发生率在编成层面算 [ep08]。库存里没有租借列表时，自己的 5 张按「主属性 3 张 + 其他 2 张」选，开局再租一张主属性的卡补到 4 张。
- 主属性（`choose_main`）：三个属性各当一次主属性组编成。默认用偶像的主属性（Campus 広 定为 Da，其他偶像按成长率最高的属性），另一个属性当主属性时总价值要高出 100 以上才换，也就是「逆练」[ep02]。
- 报告里会提醒 ep08 的稳妥属性线：一属性约 2000、二属性 1400、三属性 1100。

回忆（`hiro.brain.formation.select_memories` + `hiro.state.memory_priority`）：

- 流派由偶像卡的 `examEffectType` 决定（`profile_for_idol`）：

  | 流派 | 偶像类型 | 依据 | A:B 推荐 |
  |---|---|---|---|
  | `yaruki` | ロジック やる気 | いおん14/15、もなみ、wiki、game8、もりし | 不限 |
  | `review_smile` | ロジック 好印象 | いおん10、いおん01 | 2:2 |
  | `sense_spotlight` | センス 好调 / 集中 | いおん09、いおん01 | 2:2 |
  | `anomaly_tsuyoki` | アノマリー 强气 / 全力 | いおん12、いおん01 | 1:3 |

  全力型没有专门的社区篇，暂时借用强气表，方案里会标出来。

- 评分 = 卡的社区优先度 + 这份回忆的质量（推荐定制、入手时机、强化、HIF 能力、属性词条按实际基数估价 [ep01 / ep03]）。
- A 栏放一次性压缩和过牌件，B 栏放要强化或定制的循环核心，每栏 1–3 张。越界扣 15 分，正好等于推荐配比加 8 分。
- 社区要求必须强化的卡（脚光、成長痛、エンターテイナー 等）另有强化加分，「值得刷」清单里也会列出来。
- 卡名对照：视频里的中文昵称按主数据卡面效果对到卡 ID，推断出来的写在表的 `note` 里，包括「再动刀」= シュプレヒコール、「届到你」= 輝くキミへ。

## 还没做

- 把方案自动写进游戏编成位，目前要手动存。
- 回忆租借：评分（`formation.choose_memory_rental`）早就有，但第 3 步点进回忆租借列表的画面还没取过帧，执行器没法写；已请总控实机取帧。
- 第 3 步图标位置只按一张实机帧（2026-11-04）标定；游戏改版或别的模式下布局不同时会四格都认不出（只警告，不拦），要重新标定 `STEP3_ICONS`。
- 其他流派的定制 OCR 关键词（`CUSTOM_TEXT_KEYS` 里新加的几项）还没拿实机回忆页验证。
- 支援卡的考试增益（P 道具、考试效果）还没估价 [ep05]。非 Da 主属性的路线触发次数沿用 Campus 広 的实机统计，只把课程次数挪到新的主属性上。
- 开源版的支援卡技能来自素材插件（`AssetSource.support_effects`），默认素材拿不到时只按事件收益、属性、等级比较。
