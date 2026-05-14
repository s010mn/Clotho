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

## 下一步提醒

下一步仍不直接迁移旧库公式。优先候选是教学版 `tp/window policy` 实现和对比，因为泵注时间和停泵窗口会强烈影响后续 G-function 结果。
