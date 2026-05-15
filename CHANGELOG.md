# Clotho Project Changelog

本文件是 Clotho 的项目主记忆和阶段记录。

用途：

- 记录每个稳定阶段的目标、边界、commit 和验证结果；
- 保存 compact 后恢复上下文所需的关键决策；
- 防止重复实现已经否定或尚未审计的算法；
- 为研究复现、G-function/DFIT 分析和论文写作保留可追溯记录。

阅读约定：

- 最新阶段通常在文件末尾；
- 如果本文件与仓库源码或测试冲突，以源码和测试为准；
- 旧路径 `notes/project-state.md` 仅保留为兼容指针。

# Clotho Project State

本文件是对话压缩后的优先阅读文件。继续做 Clotho 前，先读这里，再读 `AGENTS.md` 和相关测试。

## 当前目标

Clotho 服务于“基于停泵数据的压裂缝网参数评价方法研究”。当前阶段只建立清楚、可读的数据边界，暂时不进入 G-function 公式或裂缝反演。

## 当前代码组织原则

- 少文件，先集中，后拆分。
- 不为了工程洁癖提前创建空包、registry、factory、adapter 等抽象。
- 读者是中国大陆石油工程硕士生，但解释水平按本科一年级写。
- Python 变量名用英文；中文注释解释物理含义和数据含义。
- 优先用 `numpy`、`pandas` 等现成库减少手写样板代码。

## 当前硬约束

- 不复制 `gfunc/`。
- 不复制 `wells/well4/`。
- 不新增真实井数据。
- 不实现 G-function、Carter、PKN、closure、stress-shadow 或 reporting。
- 后续进入公式前，先把数据口径、压力口径、停泵窗口和泵注时间定义讲清楚。

## 当前源码边界

当前 `src/clotho/` 只应有少量文件：

- `__init__.py`
- `__main__.py`
- `cli.py`
- `stage_data.py`

当前 `stage_data.py` 只负责：

1. 读 `stage_params.csv`；
2. 读单段施工曲线 CSV；
3. 保留井口压力；
4. 找停泵时间所在行；
5. 用真实时间差计算停泵后的 elapsed seconds；
6. 在显式调用时，把井口压力加液柱压力，得到估算井底压力。

## 压力口径

### `add_pressure`

旧库字段：

`add_pressure`

人类已明确说明：它表示液柱压力。因为压力计测的是井口压力，所以早期处理时用：

近似井底压力 = 井口压力 + 液柱压力

Clotho 当前命名：

`liquid_column_pressure_mpa`

如果需要生成近似井底压力，使用：

`estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa`

注意：

- `estimated_bottomhole_pressure_mpa` 是估算井底压力；
- 它不是井下压力计实测 BHP；
- 不要无说明地命名为 `bottomhole_pressure_mpa`；
- 若后续做更严格井底压力换算，需要补充密度、井深、井筒摩阻等信息。

## `sigma_min` 口径

旧字段 `sigma_min` 当前命名为：

`minimum_stress_prior_mpa`

含义：外部给定或人工解释得到的最小应力先验值。它不是 `stage_data.py` 从停泵曲线自动识别出来的闭合压力。

## Phase 2B：泵注时间 / window policy

当前新增的是教学版 tp/window policy，对比不同注入时间定义：

- `rate_positive_elapsed`：停泵前排量大于阈值的真实累计时间；
- `volume_over_max_sustained_rate`：注入总液量 / 最大稳定排量；
- `human_picked`：人工选定开始时间和结束时间，例如裂缝打开时间到停泵时间。

注意：

- 这一步仍然不计算 G-function；
- 不判断哪种 tp 最终正确；
- 不自动识别裂缝打开时间；
- 不自动盲选最大稳定排量；
- 目的只是让后续 G-function 计算前，先把时间尺度讲清楚。

## Phase 2C：well4 体积列与窗口策略审计

本地审计参考库 `well4` 后得到：

- `stage_volume` 在 30/30 个 stage 的停泵前都有回落或重置；
- `total_volume` 在 30/30 个 stage 的停泵前没有回落；
- 用 `total_volume` 推断，`rate / (dV/dt)` 的中位数约 60，说明 rate 更像 m³/min，而不是 m³/s；
- `rate > 0` 累计法通常偏长；
- `rate > 10` 累计法与 `total_volume / P95 正排量` 的时间尺度更接近。

当前结论：

- 不要默认用 `stage_volume` 代表总注入量；
- 体积 / 最大稳定排量法必须显式选择 `volume_column`；
- 对 well4 这类数据，`total_volume` 是更合理的累计注入量候选；
- 这仍然不是 G-function 结论，只是进入 G-function 前的数据口径审计。

## Phase 2D：最小 window-audit CLI

新增 `clotho window-audit` 命令，用于对外部井目录中的单个 stage 做窗口策略审计。

它只输出几个 tp 候选值：

- `rate_positive_elapsed_seconds`
- `volume_over_max_sustained_rate_seconds`
- 可选的 `picked_duration_seconds`

注意：

- 它不计算 G-function；
- 不做 closure；
- 不反演裂缝参数；
- 不复制真实数据；
- `volume_column` 和 `max_sustained_rate` 必须显式传入；
- 输出必须回显关键输入参数，包括 `volume_column`、`min_rate`、`max_sustained_rate`、`rate_time_unit`。否则后续审计记录无法独立解释每个 tp 候选值是如何得到的；
- 这个命令只是为了让窗口策略审计可复现。

## 下一步提醒

下一步仍不直接迁移旧库公式。优先候选是用 `clotho window-audit` 对真实/参考井少量 stage 做窗口策略审计：只比较不同 tp 选法，不反演裂缝参数。等 tp 口径稳定后，再进入 G-function formula audit。

## Phase 2E：well4 stage 1/29 window-audit 审计

使用 `clotho window-audit` 对参考库 `/tmp/gfunction-ref-audit/Gfunction-wells-current/wells/well4`
中的 stage 1 和 stage 29 做了本地窗口审计。参考数据没有复制进 Clotho 仓库。

审计条件：

- `volume_column=total_volume`
- `rate_time_unit=minute`
- 未传 `picked_start_time`，因为尚未人工确认“裂缝打开时间”
- `max_sustained_rate` 使用两个审计代理值：
  - 停泵前正排量 P95
  - 停泵前正排量最高 10% 的中位数

结果摘要：

### Stage 1

- `shut_in_time=09:42:53`
- `p95_positive_rate=19.94`
- `top10_median_rate=19.93`
- `rate > 0` 累计时间：`13659.0 s`
- `rate > 10` 累计时间：`9818.0 s`
- `total_volume / P95 正排量`：`9567.86 s`
- `rate > 0` 比体积/排量法长约 `43%`
- `rate > 10` 与体积/排量法差约 `2.6%`

### Stage 29

- `shut_in_time=13:28:05`
- `p95_positive_rate=20.06`
- `top10_median_rate=20.06`
- `rate > 0` 累计时间：`14874.0 s`
- `rate > 10` 累计时间：`10214.0 s`
- `total_volume / P95 正排量`：`9328.44 s`
- `rate > 0` 比体积/排量法长约 `59%`
- `rate > 10` 与体积/排量法差约 `9.5%`

负向检查：

- 对 well4 stage 1 使用 `volume_column=stage_volume` 会失败；
- 错误信息包含 `stage_volume` 和“回落或重置”；
- 这说明体积列安全检查生效。

当前解释：

- `rate > 0` 累计法容易把低排量、预注入、阶梯降排量或同步误差计入 tp，因此偏长；
- `rate > 10` 更接近高排量主施工窗口，但仍只是经验代理；
- `total_volume / 最大稳定排量` 更符合当前主候选 tp 口径；
- P95 正排量和 top10 median 正排量在 stage 1 与 stage 29 差异很小，说明这两段高排量平台较稳定；
- `human_picked` 仍然保留，但必须等待人工或后续清晰规则给出“裂缝打开时间”。

当前暂定策略：

- 主候选：`volume_over_max_sustained_rate`，使用 `volume_column=total_volume` 和人工确认或审计代理的最大稳定排量；
- sanity check：`rate_positive_elapsed`，建议使用 `min_rate=10` 作为高排量窗口代理；
- 对照/反例：`rate_positive_elapsed` with `min_rate=0`，因为它在 well4 stage 1 和 stage 29 上明显偏长。

注意：

- 这仍然不是 G-function 结论；
- 不代表裂缝参数反演已经验证；
- 不判断哪种 tp 在所有井段上最终正确；
- 只是进入 G-function 公式前的数据窗口口径审计。

## Phase 3B：教学版 Nolte G-time 公式

新增小文件：

```text
src/clotho/g_function.py
```

它只实现纯 G-time 数学公式：

```text
g_function_time(delta, m)
nolte_g_time(delta, m, delta0=0.0)
```

含义：

- `delta = elapsed_time / tp`，无量纲；
- `g_function_time(delta, m)` 返回中间函数 `g(Δ,m)`；
- `nolte_g_time(delta, m, delta0=0.0)` 返回归一化后的 G-time；
- `delta0` 只做平移归零。

当前实现范围：

- `m=1` 使用解析公式；
- `m=1/2` 使用解析公式；
- 其他 `0 < m <= 1` 使用 NumPy 梯形积分；
- 真实负 `delta` 会报错；
- 极小浮点误差导致的负值，例如 `-1e-13`，会按 0 处理；
- `m` 当前限制为 `0 < m <= 1`。

当前仍不实现：

- `dP/dG`;
- `G dP/dG`;
- pressure smoothing;
- closure diagnostics;
- Carter leakoff;
- PKN;
- volume balance;
- fracture inversion.

原因：

G-time 是纯时间变换，不需要压力。压力导数和闭合诊断对噪声、重采样和平滑策略非常敏感，必须后续单独审计。

## Phase 3C：G-time 与 window/tp 的本地 smoke 审计

本阶段只做本地审计，没有修改 Clotho 源码，没有修改 CLI，没有 commit 真实井数据。

审计目标：

```text
停泵后 elapsed seconds
→ delta = elapsed_seconds / tp_seconds
→ nolte_g_time(delta, m=0.8)
```

使用当前 Clotho 代码：

```python
from clotho.stage_data import elapsed_seconds_after
from clotho.stage_data import find_shut_in_index
from clotho.stage_data import read_stage_curve
from clotho.stage_data import read_stage_params
from clotho.stage_data import rate_positive_duration_seconds
from clotho.stage_data import volume_over_max_rate_duration_seconds
from clotho.g_function import nolte_g_time
```

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### Stage 1 smoke

审计条件：

```text
stage = 1
data_file = stage_data/stage_01.csv
shut_in_time = 09:42:53
volume_column = total_volume
rate_time_unit = minute
max_sustained_rate = P95 positive rate before shut-in
m = 0.8
```

本地输出：

```text
shut_in_index=13664
p95_positive_rate=19.94
top10_median_positive_rate=19.93
rate_gt0_seconds=13659
rate_gt10_seconds=9818
tp_seconds_total_volume_over_p95_rate=9567.86359077
elapsed_first8=[0. 1. 2. 3. 4. 5. 6. 7.]
delta_first8=[0.         0.00010452 0.00020903 0.00031355 0.00041807 0.00052258
 0.0006271  0.00073162]
G_first8_m_0p8=[0.         0.00024327 0.00048538 0.00072673 0.00096745 0.00120763
 0.00144734 0.00168661]
elapsed_first50_has_duplicate=False
elapsed_first50_has_backward_step=False
```

解释：

- `elapsed_seconds_after()` 给出停泵后真实秒数；
- `tp_seconds` 使用 `total_volume / P95 正排量`；
- `delta = elapsed_seconds / tp_seconds`，是无量纲；
- `nolte_g_time(delta, m=0.8)` 输出无量纲 G-time。

Stage 1 的结果与 Phase 3A/3B 的手工 sanity check 一致。

### Stage 29 smoke

审计条件：

```text
stage = 29
data_file = stage_data/stage_29.csv
shut_in_time = 13:28:05
volume_column = total_volume
rate_time_unit = minute
max_sustained_rate = P95 positive rate before shut-in
m = 0.8
```

本地输出：

```text
shut_in_index=19273
p95_positive_rate=20.06
top10_median_positive_rate=20.06
rate_gt0_seconds=14874
rate_gt10_seconds=10214
tp_seconds_total_volume_over_p95_rate=9328.444666
elapsed_first8=[0. 2. 2. 3. 4. 5. 6. 7.]
delta_first8=[0.         0.0002144  0.0002144  0.0003216  0.0004288  0.000536
 0.00064319 0.00075039]
G_first8_m_0p8=[0.         0.00049779 0.00049779 0.00074528 0.00099213 0.00123842
 0.00148421 0.00172955]
elapsed_first50_has_duplicate=True
elapsed_first50_has_backward_step=False
```

说明：

- Stage 29 停泵后前 50 个 elapsed seconds 中存在重复时间戳；
- 当前阶段只记录该数据现象；
- 不在 Phase 3C 中修复；
- 不解释成物理结论；
- 不据此做 closure 或反演。

### 负向检查

使用 `stage_volume` 作为体积列时，仍然会失败：

```text
negative_check_stage_volume=PASS
negative_check_error=体积列 'stage_volume' 在停泵前出现回落或重置
```

这说明 Phase 2C.1 的体积列边界检查仍然生效。

### 当前结论

Phase 3C 只证明：

```text
当前 stage_data.py 的停泵后 elapsed seconds
可以和当前 g_function.py 的 Nolte G-time 公式连接。
```

它不证明：

- 不证明 closure 识别正确；
- 不证明裂缝参数反演正确；
- 不证明 `total_volume / P95 正排量` 是最终唯一 tp 口径；
- 不证明 G-function 导数可直接使用；
- 不证明与微地震、广域电磁、SRV/HDS-SRV 有正相关。

当前仍然没有实现：

- `dP/dG`
- `G dP/dG`
- pressure smoothing
- closure diagnostics
- Carter leakoff
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

### 对 CLI 的暂定判断

暂时不把 G-time 输出加入 `clotho window-audit`。

原因：

- CLI 如果输出 G-time，必须明确说明使用哪一种 tp；
- 当前只是本地 smoke 审计；
- 过早加 `--g-time-m` 容易让使用者误以为 G-time 结果已经绑定了最终推荐的 tp 策略。

后续如果要加 CLI，应单独设计，例如：

```text
--g-time-m 0.8
--g-time-count 8
```

并且必须在输出中明确：

```text
g_time_tp_source = volume_over_max_sustained_rate_seconds
```

但这不是 Phase 3C.1 的任务。

## Phase 3D：window-audit 可选 G-time 预览

新增 `clotho window-audit --g-time-m` 和 `--g-time-count`。

该输出只在用户显式传入 `--g-time-m` 时出现。默认 `window-audit` 输出保持不变。

G-time 预览使用：

```text
delta = elapsed_seconds_after / volume_over_max_sustained_rate_seconds
```

其中 `volume_over_max_sustained_rate_seconds` 来自当前 CLI 已经输出的
`total_volume / max_sustained_rate` 口径。

输出字段包括：

```text
g_time_tp_source
g_time_m
g_time_count_requested
g_time_count_returned
g_time_elapsed_seconds
g_time_delta
nolte_g_time
```

本阶段仍然不实现：

- `dP/dG`
- `G dP/dG`
- pressure smoothing
- closure diagnostics
- Carter leakoff
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

Stage 29 这类重复 elapsed timestamp 只原样输出，不在本阶段重采样或修正。

## Phase 3E：压力-G-time 导数前置条件本地审计

本阶段只做本地审计，没有修改源码、测试或 CLI，没有提交真实井数据。

审计目标是回答：

```text
当前停泵后压力曲线 + 当前 G-time 序列，是否已经满足后续计算 dP/dG 的最基本数据条件？
```

本阶段没有计算：

- `dP/dG`
- `G dP/dG`
- closure
- Carter
- PKN
- volume balance
- fracture inversion

### 审计方法

使用当前 Clotho 代码：

- `elapsed_seconds_after()`
- `volume_over_max_rate_duration_seconds()`
- `nolte_g_time()`
- `add_estimated_bottomhole_pressure()`

时间尺度仍使用：

```text
tp_seconds = total_volume / P95 positive rate before shut-in
rate_time_unit = minute
m = 0.8
```

后续导数的最基本前置条件暂定为：

- G-time 必须严格递增；
- G-time 不能有 NaN 或 inf；
- 压力列不能有 NaN 或 inf；
- 停泵后样点数至少大于等于 3。

注意：

- 这里没有调用 `np.gradient(P, G)`；
- 这里只判断是否具备直接计算导数的基本条件。

### Stage 1 审计结果

本地输出摘要：

```text
stage=1
shut_in_time=09:42:53
shut_in_index=13664
post_shut_in_rows=1224
liquid_column_pressure_mpa=42.5517
p95_positive_rate=19.94
tp_seconds_total_volume_over_p95_rate=9567.86359077
```

时间和 G-time 单调性：

```text
elapsed_duplicate_step_count=3
elapsed_backward_step_count=0
elapsed_strictly_increasing=False
elapsed_nondecreasing=True

g_time_duplicate_step_count=3
g_time_backward_step_count=0
g_time_strictly_increasing=False
g_time_nondecreasing=True

elapsed_step_min=0
elapsed_step_median=1
elapsed_step_max=3
```

前 12 个样点：

```text
elapsed_first12=[ 0.  1.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11.]

delta_first12=[0.         0.00010452 0.00020903 0.00031355 0.00041807 0.00052258
 0.0006271  0.00073162 0.00083613 0.00094065 0.00104517 0.00114968]

g_time_first12=[0.         0.00024327 0.00048538 0.00072673 0.00096745 0.00120763
 0.00144734 0.00168661 0.00192548 0.00216397 0.00240211 0.00263991]
```

压力列摘要：

```text
wellhead_pressure_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 0.0, 'median': 64.18, 'max': 67.27}

estimated_bottomhole_pressure_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 42.5517, 'median': 106.7317, 'max': 109.82169999999999}

pressure_shift_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 42.55169999999999, 'median': 42.5517, 'max': 42.551700000000004}
```

导数前置条件判断：

```text
derivative_ready_strict_g_and_finite_pressure=False
derivative_blockers=G-time is not strictly increasing
derivative_was_computed=False
closure_was_computed=False
```

解释：

- Stage 1 前 12 个样点看起来严格递增；
- 但完整停泵后序列中存在 3 个重复 elapsed step；
- 因此完整 G-time 序列也存在 3 个重复 step；
- 所以 stage 1 不能直接进入 `dP/dG`。

这修正了 Phase 3C 的一个局限：

- Phase 3C 只检查了 stage 1 的前 50 个 elapsed；
- Phase 3E 检查完整 post-shut-in 序列后，发现 stage 1 后部仍存在重复 elapsed。

### Stage 29 审计结果

本地输出摘要：

```text
stage=29
shut_in_time=13:28:05
shut_in_index=19273
post_shut_in_rows=1112
liquid_column_pressure_mpa=42.7672
p95_positive_rate=20.06
tp_seconds_total_volume_over_p95_rate=9328.444666
```

时间和 G-time 单调性：

```text
elapsed_duplicate_step_count=1
elapsed_backward_step_count=0
elapsed_strictly_increasing=False
elapsed_nondecreasing=True

g_time_duplicate_step_count=1
g_time_backward_step_count=0
g_time_strictly_increasing=False
g_time_nondecreasing=True

elapsed_step_min=0
elapsed_step_median=1
elapsed_step_max=2
```

前 12 个样点：

```text
elapsed_first12=[ 0.  2.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11.]

delta_first12=[0.         0.0002144  0.0002144  0.0003216  0.0004288  0.000536
 0.00064319 0.00075039 0.00085759 0.00096479 0.00107199 0.00117919]

g_time_first12=[0.         0.00049779 0.00049779 0.00074528 0.00099213 0.00123842
 0.00148421 0.00172955 0.00197448 0.00221901 0.00246317 0.00270698]
```

压力列摘要：

```text
wellhead_pressure_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 0.0, 'median': 67.795, 'max': 84.95}

estimated_bottomhole_pressure_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 42.7672, 'median': 110.5622, 'max': 127.7172}

pressure_shift_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 42.767199999999995, 'median': 42.7672, 'max': 42.76720000000001}
```

导数前置条件判断：

```text
derivative_ready_strict_g_and_finite_pressure=False
derivative_blockers=G-time is not strictly increasing
derivative_was_computed=False
closure_was_computed=False
```

解释：

- Stage 29 停泵后早期已经出现重复 elapsed；
- 重复 elapsed 导致重复 delta；
- 重复 delta 导致重复 G-time；
- 所以 stage 29 不能直接进入 `dP/dG`。

### 压力口径解释

当前 Clotho 的压力口径仍然是：

```text
estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa
```

其中：

- `wellhead_pressure_mpa` 是原始井口压力列；
- `estimated_bottomhole_pressure_mpa` 是估算井底压力；
- `estimated_bottomhole_pressure_mpa` 不是井下压力计实测 BHP。

如果单个 stage 内液柱压力只是常数，则：

```text
P_estimated = P_wellhead + constant
```

因此：

- 常数液柱压力不改变 `dP/dG` 的形状；
- 常数液柱压力会改变 closure pressure 的绝对压力值口径。

本阶段没有计算导数，也没有计算 closure pressure。

### 额外数据质量观察

Stage 1 和 stage 29 的停泵后压力列均为有限值：

```text
nan_or_inf_count=0
```

但两段的井口压力摘要都出现：

```text
min=0.0
```

这不是 Phase 3E 的主要 blocker。当前主要 blocker 是：

```text
G-time is not strictly increasing
```

但后续如果进入压力质量审计，需要单独检查停泵后压力为 0 的行是否是传感器缺测、填充值、尾部数据截断或真实记录。

### 当前结论

Phase 3E 证明：

- 当前 well4 stage 1 和 stage 29 的完整停泵后 G-time 序列不是严格递增；
- 因此不能直接用当前序列进入 `np.gradient(P, G)` 或 closure 诊断。

当前还不能做：

- 直接计算 `dP/dG`；
- 直接计算 `G dP/dG`；
- 直接判断 closure；
- 直接反演裂缝参数。

后续如果要进入压力导数，必须先设计并审计至少一种数据处理策略，例如：

- 重复 timestamp / 重复 G-time 的处理；
- 是否按 elapsed 或 G-time 聚合重复点；
- 是否保留第一个点、最后一个点或取均值；
- 是否重采样到严格递增网格；
- 是否做平滑；
- 压力为 0 的行如何处理。

这些策略都会影响导数形状和 closure 判断，因此不能默认静默处理。

## Phase 3F：window-audit 可选 derivative-readiness 数据质量输出

新增 `clotho window-audit --derivative-readiness`。

该输出只在用户显式传入 `--derivative-readiness` 时出现，并要求同时传入 `--g-time-m`。

本阶段只检查后续直接计算 `dP/dG` 的最基本数据前置条件：

- post-shut-in 样点数是否至少为 3；
- G-time 是否为有限值；
- G-time 是否严格递增；
- 压力列是否为有限值；
- 井口压力是否出现 0 或非正值。

该输出不计算：

- `dP/dG`；
- `G dP/dG`；
- closure；
- smoothing；
- 重采样；
- 去重；
- Carter；
- PKN；
- volume balance；
- fracture inversion。

如果存在重复 elapsed 或重复 G-time，只报告，不修正。

Phase 3F 的 CLI 输出字段使用 `derivative_readiness_` 前缀，并明确输出：

```text
derivative_was_computed=False
closure_was_computed=False
```

可选参考 smoke 摘要：

```text
stage 1:
elapsed_duplicate_step_count=3
g_time_duplicate_step_count=3
derivative_readiness_ready=False

stage 29:
elapsed_duplicate_step_count=1
g_time_duplicate_step_count=1
derivative_readiness_ready=False
```

## Phase 3G：well4 全 stage derivative-readiness 本地审计

本阶段只做本地审计，没有修改源码、测试或 CLI，没有提交真实井数据。

审计目标：

把 Phase 3F 的 derivative-readiness 数据质量检查扩展到 well4 全部 stage，
判断重复 elapsed、重复 G-time、井口压力 0 值是个别现象还是全井段普遍现象。

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

本地 CSV 只写入：

```text
/tmp/gfunction-ref-audit-phase3g/well4_all_stage_derivative_readiness.csv
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### 审计方法

每个 stage 使用当前 Clotho 代码：

- `read_stage_params()`
- `read_stage_curve()`
- `find_shut_in_index()`
- `elapsed_seconds_after()`
- `volume_over_max_rate_duration_seconds()`
- `nolte_g_time()`
- `add_estimated_bottomhole_pressure()`

时间尺度：

```text
tp_seconds = total_volume / P95 positive rate before shut-in
rate_time_unit = minute
m = 0.8
```

最基本 derivative-readiness 条件仍为：

- post-shut-in 样点数 >= 3
- G-time 为有限值
- G-time 严格递增
- 压力列为有限值

本阶段没有调用：

```text
np.gradient(P, G)
```

也没有计算：

- `dP/dG`
- `G dP/dG`
- closure
- Carter
- PKN
- volume balance
- fracture inversion

### 全 stage 摘要

本地输出：

```text
stage_count=30
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

重复 elapsed / G-time 分布：

```text
elapsed_duplicate_stage_count=16
elapsed_duplicate_stage_counts=1:3, 2:9, 5:55, 9:1, 10:1, 11:1, 13:3, 14:2, 16:2, 17:1, 18:1, 19:1, 21:68, 24:2, 27:1, 29:1

elapsed_backward_stage_count=0
elapsed_backward_stage_counts=none

g_time_duplicate_stage_count=16
g_time_duplicate_stage_counts=1:3, 2:9, 5:55, 9:1, 10:1, 11:1, 13:3, 14:2, 16:2, 17:1, 18:1, 19:1, 21:68, 24:2, 27:1, 29:1
```

压力质量摘要：

```text
wellhead_pressure_zero_stage_count=30
wellhead_pressure_nonpositive_stage_count=30
wellhead_pressure_nan_or_inf_stage_count=0
estimated_bottomhole_pressure_nan_or_inf_stage_count=0
```

blocker 统计：

```text
derivative_readiness_blockers
G-time is not strictly increasing    16
none                                 14
```

### 重点 stage 现象

重复 elapsed 最多的 stage：

```text
stage 21: elapsed_duplicate_step_count=68, g_time_duplicate_step_count=68
stage 5:  elapsed_duplicate_step_count=55, g_time_duplicate_step_count=55
stage 2:  elapsed_duplicate_step_count=9,  g_time_duplicate_step_count=9
stage 1:  elapsed_duplicate_step_count=3,  g_time_duplicate_step_count=3
```

早期重复 elapsed 的典型 stage：

```text
stage 14: first_duplicate_index=2, first_duplicate_value=3.0
stage 16: first_duplicate_index=3, first_duplicate_value=4.0
stage 17: first_duplicate_index=1, first_duplicate_value=2.0
stage 18: first_duplicate_index=1, first_duplicate_value=2.0
stage 19: first_duplicate_index=1, first_duplicate_value=2.0
stage 24: first_duplicate_index=1, first_duplicate_value=2.0
stage 27: first_duplicate_index=1, first_duplicate_value=2.0
stage 29: first_duplicate_index=1, first_duplicate_value=2.0
```

这说明重复 elapsed 既可能出现在停泵后早期，也可能出现在停泵后中后期。

### 井口压力 0 值分布

30/30 个 stage 都存在井口压力 0 值：

```text
wellhead_pressure_zero_stage_counts=1:15, 2:12, 3:9, 4:3, 5:5, 6:16, 7:6, 8:5, 9:24, 10:5, 11:2, 12:4, 13:4, 14:4, 15:3, 16:3, 17:3, 18:3, 19:3, 20:3, 21:3, 22:3, 23:3, 24:3, 25:3, 26:3, 27:3, 28:3, 29:3, 30:3
```

所有 stage 中：

```text
wellhead_pressure_trailing_zero_count = wellhead_pressure_zero_count
```

即井口压力 0 值全部集中在停泵后序列尾部。

示例：

```text
stage 1:
wellhead_pressure_zero_count=15
wellhead_pressure_trailing_zero_count=15
wellhead_pressure_first_zero_elapsed=1209.0
wellhead_pressure_last_zero_elapsed=1223.0

stage 29:
wellhead_pressure_zero_count=3
wellhead_pressure_trailing_zero_count=3
wellhead_pressure_first_zero_elapsed=1109.0
wellhead_pressure_last_zero_elapsed=1111.0
```

当前估算井底压力定义仍为：

```text
estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa
```

因此：

```text
30/30 个 stage 的 estimated_bottomhole_pressure_zero_count 都为 0
```

这不代表尾部井口压力 0 值没有问题，只代表加上液柱压力后估算井底压力不再为 0。

### 当前结论

Phase 3G 证明：

- 重复 elapsed / 重复 G-time 不是个别现象；
- well4 的 16/30 个 stage 不满足直接计算 `dP/dG` 的最基本 G-time 严格递增条件；
- 井口压力尾部 0 值是 30/30 个 stage 的普遍现象。

因此，当前仍然不能直接全井段进入：

- `dP/dG`
- `G dP/dG`
- closure diagnostics
- fracture inversion

即使 14 个 stage 通过当前最基本 derivative-readiness，也不能马上做全井段 closure 或反演，原因是：

1. 16 个 stage 的 G-time 不严格递增；
2. 30 个 stage 都有尾部井口压力 0 值；
3. 当前尚未定义重复 timestamp / 重复 G-time 的处理策略；
4. 当前尚未定义尾部压力 0 值的截断或质量标记策略；
5. 当前尚未定义 smoothing、重采样或导数算法。

### 后续候选方向

下一步不应直接实现 `dP/dG`。

更合理的下一步是先设计一个极小的数据质量策略审计阶段，例如：

```text
Phase 3H：设计停泵后有效压力段裁剪与重复时间处理策略
```

候选策略只能先作为方案比较，不能静默固化：

1. 尾部井口压力 0 值是否作为停泵后有效数据终点；
2. 重复 elapsed / 重复 G-time 是保留第一个点、保留最后一个点、取均值，还是直接标记为不可导；
3. 是否按 elapsed 聚合，而不是按 G-time 聚合；
4. 是否只对导数计算使用裁剪/聚合后的数据，但保留原始数据用于审计；
5. 是否需要独立输出 data-quality audit，而不是直接输出 closure。

这些策略都会改变导数形状和 closure 判断，因此不能默认静默处理。

## Phase 3H-revised：主动放压段候选识别本地审计

本阶段由人类澄清触发：

```text
许多段最后压力有阶梯下降，那个是主动放压了，那些段不应该再计算进来。
```

因此，Phase 3H 的口径从“尾部 0 压力质量问题”升级为：

```text
主动放压段有效性边界问题。
```

本阶段只做本地策略比较审计，没有修改源码、测试或 CLI，没有提交真实井数据。

本阶段没有实现：

```text
dP/dG
G dP/dG
pressure smoothing
timestamp 去重
重复 G-time 聚合
重采样
closure diagnostics
Carter
PKN
volume balance
fracture inversion
Excel/PNG reporting
```

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

本地输出只写入：

```text
/tmp/gfunction-ref-audit-phase3h_bleedoff/
```

其中包括：

```text
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_bleedoff_strategy_readiness.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_bleedoff_candidates.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_tail_metrics.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/stage_XX_tail_excerpt.csv
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### 有效数据段口径

人类澄清后的有效数据段定义为：

```text
有效停泵压降段 = 停泵后、主动放压开始前的压力自然降落段。
```

主动放压段定义为：

```text
人为打开阀门或放压导致的尾部阶梯式压力快速下降段。
```

主动放压段不是地层/裂缝自然压降响应，因此不应参与：

```text
G-function 压力导数
closure diagnostics
Carter / PKN / volume balance
fracture inversion
```

### 审计策略

本地比较了 5 种候选数据段策略：

```text
raw:
  原始 post-shut-in 序列。只作为基线，不作为推荐。

trim_trailing_nonpositive:
  只裁剪尾部连续 wellhead_pressure_mpa <= 0 行。
  这是旧压力 0 策略，只作为基线。人类澄清后，它通常不够。

active_bleedoff_drop_ge_0p5:
  在尾部正压力段中寻找候选主动放压开始点；
  候选规则为尾部阶梯式下降 step drop >= 0.5 MPa。

active_bleedoff_drop_ge_1p0:
  同上，但 step drop >= 1.0 MPa。

active_bleedoff_drop_ge_2p0:
  同上，但 step drop >= 2.0 MPa。
```

这些阈值只是本地审计候选，不是最终算法。

### Readiness by strategy

本地输出摘要：

```text
raw:
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
blocker_counts=G-time is not strictly increasing:16 | none:14

trim_trailing_nonpositive:
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
blocker_counts=G-time is not strictly increasing:16 | none:14

active_bleedoff_drop_ge_0p5:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15

active_bleedoff_drop_ge_1p0:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15

active_bleedoff_drop_ge_2p0:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15
```

### 尾部非正压力裁剪

30/30 个 stage 都有尾部非正井口压力被裁剪。

各 stage 裁剪行数：

```text
stage 1: 15
stage 2: 12
stage 3: 9
stage 4: 3
stage 5: 5
stage 6: 16
stage 7: 6
stage 8: 5
stage 9: 24
stage 10: 5
stage 11: 2
stage 12: 4
stage 13: 4
stage 14: 4
stage 15: 3
stage 16: 3
stage 17: 3
stage 18: 3
stage 19: 3
stage 20: 3
stage 21: 3
stage 22: 3
stage 23: 3
stage 24: 3
stage 25: 3
stage 26: 3
stage 27: 3
stage 28: 3
stage 29: 3
stage 30: 3
```

总裁剪尾部非正井口压力行数：

```text
162
```

但只裁剪尾部 `wellhead_pressure_mpa <= 0` 并没有改善 readiness：

```text
raw ready_stage_count=14
trim_trailing_nonpositive ready_stage_count=14
```

这说明：只裁剪尾部 0 值不足以处理主动放压段。

### 主动放压候选识别

三个阈值识别到的 stage 数完全一致：

```text
threshold 0.5 MPa: candidate_found_stage_count=28
threshold 1.0 MPa: candidate_found_stage_count=28
threshold 2.0 MPa: candidate_found_stage_count=28
```

识别到候选主动放压的 stage：

```text
1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30
```

没有识别到候选主动放压的 stage：

```text
4, 25
```

候选主动放压开始时间中位数：

```text
median_candidate_start_elapsed=1107.5 s
median_valid_end_elapsed=1106.5 s
```

对 28/28 个识别出的候选段：

```text
candidate_start_elapsed 早于 first_trailing_nonpositive_elapsed
```

这说明：

- 主动放压通常在井口压力变成 0 之前已经开始；
- 因此只裁剪尾部 0 值会把主动放压早期的正压力阶梯下降仍然留在数据里。

### 典型 stage 示例

Stage 1：

```text
first_trailing_nonpositive_elapsed=1209.0
candidate_start_elapsed=1201.0
valid_end_elapsed=1200.0
whp_before_step=63.06
whp_after_step=45.07
step_drop_mpa=17.99
```

解释：

Stage 1 在井口压力变成 0 之前约 8 s 已经出现明显阶梯式主动放压候选。只裁剪尾部 0 值不够。

Stage 2：

```text
first_trailing_nonpositive_elapsed=979.0
candidate_start_elapsed=971.0
valid_end_elapsed=970.0
whp_before_step=61.74
whp_after_step=38.69
step_drop_mpa=23.05
```

Stage 29：

```text
first_trailing_nonpositive_elapsed=1109.0
candidate_start_elapsed=1088.0
valid_end_elapsed=1087.0
whp_before_step=65.83
whp_after_step=59.77
step_drop_mpa=6.06
```

解释：

Stage 29 主动放压候选开始时间比尾部 0 开始时间早约 21 s。

Stage 10：

```text
raw ready=False
trim_trailing_nonpositive ready=False
active_bleedoff_drop_ge_0p5 ready=True
active_bleedoff_drop_ge_1p0 ready=True
active_bleedoff_drop_ge_2p0 ready=True
candidate_start_elapsed=1127.0
rows_removed=36
```

解释：

Stage 10 是本次 active-bleedoff 候选裁剪唯一让 readiness 从 False 变成 True 的 stage。

### 阈值敏感 stage

候选开始时间对阈值敏感的 stage：

```text
6, 13, 15, 16, 17, 18, 19, 22, 24, 27
```

对应 candidate_start_elapsed：

```text
stage 6:  0.5→1178.0, 1.0→1179.0, 2.0→1179.0
stage 13: 0.5→1038.0, 1.0→1042.0, 2.0→1085.0
stage 15: 0.5→1180.0, 1.0→1180.0, 2.0→1181.0
stage 16: 0.5→1066.0, 1.0→1066.0, 2.0→1067.0
stage 17: 0.5→906.0,  1.0→909.0,  2.0→933.0
stage 18: 0.5→1058.0, 1.0→1058.0, 2.0→1059.0
stage 19: 0.5→1058.0, 1.0→1058.0, 2.0→1059.0
stage 22: 0.5→1025.0, 1.0→1025.0, 2.0→1026.0
stage 24: 0.5→1188.0, 1.0→1188.0, 2.0→1189.0
stage 27: 0.5→1264.0, 1.0→1265.0, 2.0→1265.0
```

这说明：

主动放压候选识别虽然总体 stage 数稳定，但部分 stage 的候选开始时间对阈值敏感。

### 当前结论

Phase 3H-revised 证明：

1. 人类澄清后的主动放压段确实必须从有效停泵压降段中排除；
2. 只裁剪尾部井口压力 <= 0 行不够；
3. 主动放压候选通常早于尾部 0 值出现；
4. 三个 step-drop 阈值都识别出 28/30 个 stage；
5. 但 active-bleedoff 候选裁剪只让 stage 10 从 not-ready 变为 ready；
6. 多数 not-ready stage 仍然因为 G-time 不严格递增而不满足直接导数前置条件；
7. 当前仍不能直接进入 dP/dG、G dP/dG、closure 或反演。

当前不能把 active_bleedoff 识别逻辑直接写入 Clotho，原因是：

1. 这只是本地候选策略审计；
2. 主动放压开始时间尚未经过人工确认；
3. 阈值选择尚未验证；
4. 部分 stage 对阈值敏感；
5. stage 4 和 stage 25 没有被当前候选规则识别；
6. 仍未定义重复 elapsed / G-time 的处理策略；
7. 仍未定义 smoothing、重采样或导数算法。

### 后续候选方向

下一步不应直接实现 dP/dG。

更合理的下一步是设计一个显式的有效压降段边界策略，例如：

```text
Phase 3I：valid falloff window 口径设计
```

候选方向：

1. 人工给定 valid_end_time / bleedoff_start_time；
2. CLI 只输出候选 bleedoff_start_time，不自动裁剪；
3. 自动候选必须要求人工确认后才用于导数；
4. 有效压降段裁剪和重复 elapsed 处理必须分开审计；
5. 原始数据必须保留，处理后数据只能作为导数输入，不覆盖原始曲线。

## Phase 4A：最小有效停泵压降段管线

新增 `window-audit` 的人工有效压降窗口参数：

- `--valid-falloff-end-elapsed`
- `--elapsed-duplicate-policy`

目标是把“停泵后、主动放压前的自然压力降落段”显式作为后续导数/closure 的数据准备边界。

本阶段仍然不计算：

- dP/dG
- G dP/dG
- closure
- smoothing
- resampling
- Carter
- PKN
- volume balance
- fracture inversion

`--valid-falloff-end-elapsed` 是人工显式参数，不是自动主动放压识别。

`--elapsed-duplicate-policy` 默认 `none`，不会静默去重。只有用户显式选择 keep-first / keep-last / mean 时才处理重复 elapsed。

该阶段的意义是让 Clotho 从单纯审计推进到“可生成明确有效压降段输入”的最小可运行分析管线。


## Phase 4B：最小压力-G-time 导数预览

新增严格受限的压力导数预览：

- `pressure_derivative_against_g_time(g_time, pressure_mpa)`
- `window-audit --pressure-derivative-preview`
- `--pressure-derivative-count`

导数预览只在人工有效压降窗口上运行，并要求：

- `--derivative-readiness`
- `--g-time-m`
- `--valid-falloff-end-elapsed`

本阶段计算：

- dP/dG
- G dP/dG

但仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- reporting

如果有效窗口或重复 elapsed 策略不能让 G-time 严格递增，则不计算导数，只报告 blocker。

## Phase 4C：压力导数 CSV 导出与符号/尺度摘要

新增 `window-audit --pressure-derivative-output`。

当 `--pressure-derivative-preview` 成功计算导数时，可以把完整有效压降窗口导出为 CSV，字段包括：

- elapsed_seconds
- delta
- nolte_g_time
- pressure_mpa
- dP_dG_mpa
- G_dP_dG_mpa

同时输出 dP/dG 和 G dP/dG 的有限值数量、正负号数量和 min/median/max。

本阶段仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

如果 readiness 不通过，不写 CSV，只报告 blocker。

## Phase 4D：批量压力导数复现实验入口

新增 `clotho derivative-batch`。

该命令读取人工 manifest CSV，对多个 stage 批量执行：

- 人工有效压降窗口；
- 显式重复 elapsed policy；
- derivative-readiness；
- dP/dG / G dP/dG 预览；
- per-stage derivative CSV；
- batch summary CSV。

manifest 必须显式给出：

- stage
- max_sustained_rate
- valid_falloff_end_elapsed

本阶段仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

readiness 不通过的 stage 不写 derivative CSV，只在 summary 中记录 blocker。
