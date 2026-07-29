# 打破 SITL 循环验证的实施任务

## 1. 目标

建立一套能够独立验证以下问题的实验链：

> weather/terrain prior 是否能让规划器在未知大气真值中，比随机或无天气基线更有效、更安全地找到并利用热气流？

当前验证只能证明软件集成：

```text
weather prior → planner route ─┬→ aircraft mission
                               └→ SITL thermal truth
```

规划路线同时决定了 SITL 热气流位置，因此飞机命中升力是预先保证的。新的实验必须改成：

```text
hidden seed → independent truth generator → SITL thermal field

weather/terrain input → prior → planner → mission → aircraft
                                             │
                                             └→ telemetry

hidden truth + telemetry + mission → evaluator → metrics
```

规划器只能看到先验，不能读取隐藏真值。真值生成器不能读取 prior、route 或 planner 输出。

## 2. 非目标

- 本阶段不声称 Open-Meteo、SoaringMeteo 或 terrain prior 能预测真实 thermal core。
- 本阶段不实现完整 AutoSOAR 或 POMDSoar。
- 本阶段不进行无人监督的真实飞行。
- 本阶段不把 stock ArduSoar 的热气流居中性能归功于天气规划器。
- 增加第二个天气源不能替代独立真值；即使有多个天气源，truth 仍必须与 route 解耦。

## 3. P0：立即切断 prediction-to-truth leakage

### T0.1 将旧演示明确降级为 integration fixture

- [ ] 将 `sitl/run_weather_truth_demo.sh` 重命名为表达真实用途的名称，例如 `run_forecast_conditioned_integration.sh`。
- [ ] 将 `sitl/fly_weather_truth.py` 中所有 “weather truth”“real lift”“forecast accuracy” 表述改成 “injected integration fixture”。
- [x] 删除历史循环验证截图 `sitl/weather_truth_demo.png`，避免其继续被当作算法证据。
- [ ] 在报告输出中打印醒目标记：`VALIDATION_CLASS=INTEGRATION_ONLY_CIRCULAR_TRUTH`。
- [ ] 保留该演示用于验证 mission upload 和 ArduSoar handoff，但禁止把结果计入预测性能。

验收标准：

- 文件名、README、终端输出和图标题均不再暗示独立大气验证。
- 运行结果只报告接口/任务/ArduSoar 状态，不报告“预测命中率”。

### T0.2 从规划器移除真值生成职责

- [ ] 从 `planner/route_planner.py` CLI 移除或废弃 `--sitl-thermals`。
- [ ] 把 `write_sitl_thermals()` 移出 `planner/`，仅保留在独立 SITL truth 工具中。
- [ ] 删除测试 `test_write_sitl_thermals_relative_to_first`，替换为独立 truth generator 测试。
- [ ] 规划器输出中禁止出现隐藏真值文件路径。
- [ ] 给 route JSON 增加 `artifact_role: "planner_output"`。

验收标准：

- 对相同 truth seed 使用任意 planner 参数时，truth 文件字节完全不变。
- 修改 route waypoint 不会改变 truth 文件。
- `planner/` 不再 import、调用或写入任何 SITL thermal truth 工具。

## 4. P1：建立独立隐藏真值

### T1.1 定义 truth schema

- [ ] 新增版本化 schema，建议路径：`sitl/truth/schema_v1.json`。
- [ ] 每次实验的隐藏真值至少记录：
  - `schema_version`
  - `truth_seed`
  - 坐标原点和 ENU 边界
  - thermal center、初始 strength、radius
  - birth/death time
  - drift vector和演化模型
  - background sink/gust 参数
  - generator version/commit
- [ ] 为静态 SITL patch 生成兼容的 `x_north y_east w r` 文件。
- [ ] 原始 JSON 作为权威真值；文本文件只是 ArduPilot 适配产物。

验收标准：

- schema validation 测试覆盖缺字段、错误单位、非法半径、越界位置和重复 seed。
- 所有长度、速度、时间和坐标方向均带明确单位。

### T1.2 实现独立 truth generator

- [ ] 新增 `sitl/truth/generate_truth.py`。
- [ ] 输入仅允许：
  - seed
  - 场地边界
  - thermal 数量/密度分布
  - strength/radius/lifetime 分布
  - 风和背景湍流参数
- [ ] 禁止输入 prior、route、candidate、waypoint 或 planner score。
- [ ] 第一版支持确定性静态 Gaussian thermals。
- [ ] 第二版支持生命周期、风漂移、强度变化和负升力区域。
- [ ] 为每类场景建立命名配置：`weak_day`、`mixed_day`、`strong_day`、`windy_day`。

验收标准：

- 同一 seed 与配置生成完全相同的真值。
- 改变 planner 或天气源不会影响真值。
- 生成结果不保证靠近任何 candidate 或 waypoint。

### T1.3 建立信息隔离

- [ ] batch runner 在独立目录写隐藏 truth，例如 `runs/<run_id>/private/`。
- [ ] planner 只收到 `public/forecast.json` 和公开场景边界。
- [ ] evaluator 可读取 private truth；planner 和 companion 不可读取。
- [ ] 在 run manifest 中记录每个进程允许的输入文件。
- [ ] CI 增加静态检查，阻止 `planner/`、`weather/`、`companion/` 引用 `private/` 或 truth schema。

验收标准：

- 自动测试证明 planner 输入不包含 thermal 真值坐标。
- evaluator 之外的代码不能通过正常 CLI 获得 truth path。

## 5. P2：构造有相关性但不泄漏的天气先验

完全独立的随机 truth 可以验证导航鲁棒性，却不能评价天气预报价值。需要同时准备两类实验。

### T2.1 Null-correlation 场景

- [ ] truth 与天气 prior 完全独立。
- [ ] 用于确认天气算法不会在无预测能力时虚假优于 baseline。
- [ ] 预期 weather planner 不应稳定优于匹配的随机规划器。

### T2.2 Controlled-correlation 场景

- [ ] 先由隐藏大尺度场生成 truth，再通过独立 observation model 产生低分辨率、带噪声的公开 forecast。
- [ ] observation model 只能泄露区域级统计，例如：
  - 粗网格 W* 均值
  - 带偏差的风
  - 云底范围
  - 不精确的 terrain likelihood
- [ ] 不得复制 thermal center。
- [ ] 设置多个已知相关性等级：`none`、`weak`、`medium`、`strong`。
- [ ] 将噪声、分辨率、偏差和缺失率写进 manifest。

验收标准：

- `none` 场景中 forecast 与 truth 的空间关联接近零。
- 相关性升高时，评估器能检测到先验包含更多信息，但不保证规划器必然获益。
- forecast 网格分辨率明显低于 thermal core 尺度。

### T2.3 Live-weather replay 场景

- [ ] 保存 Open-Meteo/SoaringMeteo 原始响应、run time、model ID 和请求坐标。
- [ ] live forecast 只能作为公开输入。
- [ ] SITL truth 仍由独立 generator 产生；不得把 forecast candidates 复制进 truth。
- [ ] 将此场景标记为软件压力测试，而不是真实预报精度验证。

验收标准：

- 没有真实观测 truth 时，报告不得产生“forecast accuracy”结论。

## 6. P3：建立公平 baseline

每个隐藏 truth seed 必须在相同初始状态、参数和资源约束下运行以下策略：

- [ ] `weather_planner`：当前天气/地形先验规划器。
- [ ] `random_matched`：相同 waypoint 数量、距离预算和高度预算的随机路线。
- [ ] `uniform_grid`：与天气无关的规则网格/扫描路线。
- [ ] `no_prior`：仅执行安全巡航或预定义任务。
- [ ] `terrain_only`：不使用天气强度，仅使用地形启发式。
- [ ] `weather_only`：不使用 terrain placement。
- [ ] `oracle`：允许读取 truth 的理论上界；必须单独标记，不能作为可部署算法。

公平性要求：

- waypoint 数量、最大航程、初始高度、飞行时间、能量预算和 ArduSoar 参数相同。
- 所有非 oracle 策略看不到 truth。
- 同一 seed 上的策略运行顺序随机化，避免固定顺序偏差。
- 随机 baseline 的 seed 与 truth seed 分离并记录。

验收标准：

- evaluator 能拒绝预算不匹配的策略对比。
- 每个策略产物都能追溯到同一 scenario manifest。

## 7. P4：定义指标和成功标准

### T4.1 主要指标

- [ ] `safe_rtl_rate`：安全进入 RTL/完成任务的比例。
- [ ] `motor_energy_wh` 或可替代的 motor-on time。
- [ ] `net_altitude_gain_m`：扣除动力爬升后的净高度收益。
- [ ] `usable_thermal_encounters`：进入真实升力区且获得最低高度收益的次数。
- [ ] `time_in_positive_airmass_s`。
- [ ] `mission_progress_m` 或到目标的剩余距离。

### T4.2 诊断指标

- [ ] candidate 到最近 truth thermal 的距离分布。
- [ ] thermal detection precision/recall。
- [ ] false-positive search time。
- [ ] 最低高度、reserve margin 和最大离 home 距离。
- [ ] mission upload/command rejection 和 MAVLink timeout。
- [ ] ArduSoar 进入/退出次数及每次高度变化。

### T4.3 预注册成功标准

- [ ] 在看批量结果前确定主要指标和统计方法。
- [ ] 至少使用多个场景和多个 seed，不接受单次漂亮轨迹。
- [ ] 报告均值、中位数、分位数和置信区间。
- [ ] 只有当 weather planner 相对 `random_matched` 和 `uniform_grid` 在安全不下降的前提下稳定改善主要指标，才能称为“规划有效”。
- [ ] 只有加入真实留出观测后，才能称为“天气预测有效”。

验收标准：

- 结果报告由脚本从原始产物生成，禁止手工挑选成功案例。

## 8. P5：批量运行器与证据留档

### T5.1 实验 manifest

- [ ] 每次运行创建唯一 `run_id`。
- [ ] 保存：
  - autoglide commit/diff 状态
  - ArduPilot commit
  - scenario-5 patch hash
  - Python/pymavlink 版本
  - FC parameter snapshot
  - truth seed、planner seed、baseline seed
  - forecast 原始输入
  - route JSON/QGC mission
  - truth JSON与 SITL adapter file
  - stdout/stderr
  - `.tlog` 和 DataFlash `.BIN`
  - evaluator 输出

### T5.2 Batch runner

- [ ] 新增 `sitl/evaluation/run_batch.py` 或等价工具。
- [ ] 支持场景 × seed × strategy 的矩阵运行。
- [ ] 单次失败不得终止整个 batch。
- [ ] 支持断点续跑，不覆盖已有 run。
- [ ] 生成 machine-readable `summary.json/csv`。

### T5.3 Evaluator

- [ ] evaluator 独立于 planner。
- [ ] 从 telemetry 与 hidden truth 计算指标。
- [ ] 对坐标 frame、时间对齐、缺失遥测和重复 thermal episode 做单元测试。
- [ ] 输出每次运行的判定原因，不只输出 pass/fail。

验收标准：

- 任意汇总数字都能追溯到原始日志和确定的 run manifest。

## 9. P6：自动化防泄漏测试

- [ ] `test_truth_unchanged_when_route_changes`
- [ ] `test_truth_unchanged_when_weather_source_changes`
- [ ] `test_planner_cannot_read_private_truth`
- [ ] `test_truth_seed_is_deterministic`
- [ ] `test_planner_seed_is_separate_from_truth_seed`
- [ ] `test_no_exact_candidate_copy_into_truth`
- [ ] `test_baselines_share_equal_resource_budget`
- [ ] `test_evaluator_uses_truth_but_planner_does_not`
- [ ] `test_run_manifest_contains_versions_and_seeds`
- [ ] `test_report_rejects_integration_fixture_as_validation`

最低门槛：

- 单元测试和静态防泄漏检查在普通 Windows 环境可运行。
- 真实 ArduPilot SITL 验收在组内具备 SITL 的电脑运行。

## 10. P7：SITL 验收顺序

1. [ ] 独立 truth generator 的纯 Python 单元测试。
2. [ ] 不启动飞机，验证 truth/prior/route 三类产物严格分离。
3. [ ] 单个静态 truth 场，执行所有 baseline。
4. [ ] 10 个 seed 的 smoke batch。
5. [ ] 多场景、多 seed 的正式 batch。
6. [ ] 加入链路丢包、mission reject、GPS 延迟和参数 ACK 故障注入。
7. [ ] 锁定结果后才允许进入 Pi 5 + FC 台架测试。

SITL 阶段完成定义：

- 至少一个可复现的批量结果包。
- weather planner 与公平 baseline 的对比完整。
- 没有 route-to-truth 数据通路。
- 所有失败都有日志，不以截图代替证据。

## 11. P8：真实数据闭环（SITL 之后）

- [ ] 先收集不用于调参的留出飞行日志。
- [ ] 从飞控估计 air-mass vertical speed，并记录模式、动力、空速、位置和高度 frame。
- [ ] 用留出数据比较 candidate score 与实际观测升力。
- [ ] 同时纳入负观测和无升力搜索，避免只保留成功热气流。
- [ ] 在同一场地/相近天气下比较 weather route 与预先定义 baseline。
- [ ] 在真实飞行前完成 geofence、RC loss、battery failsafe、pilot override 和 mission reject 台架验证。

只有完成留出真实观测后，才可以评估“天气源是否能预测可用升力位置”。

## 12. 建议实施顺序

| 顺序 | 任务 | 预计产物 | 阻塞关系 |
|---:|---|---|---|
| 1 | T0.1–T0.2 | 旧演示降级；planner 不再写 truth | 无 |
| 2 | T1.1–T1.2 | truth schema 与 generator | 1 |
| 3 | T1.3、P6 | 信息隔离和防泄漏测试 | 2 |
| 4 | P3、P4 | baseline、指标和预注册标准 | 2 |
| 5 | P5 | batch runner、evaluator、manifest | 2–4 |
| 6 | P2 | 可控相关性与 live-weather replay | 2、5 |
| 7 | P7 | 组内电脑正式 SITL batch | 1–6 |
| 8 | P8 | Pi/FC 台架与留出真实观测 | 7 |

## 13. 最小可交付版本

第一阶段不需要实现动态大气。最小可信版本只需：

- 独立 seed 生成的静态 Gaussian thermal truth；
- planner 完全看不到 truth；
- weather、random-matched、uniform-grid 三种策略；
- 相同的距离、高度和能量预算；
- 至少 10 个 truth seeds；
- 自动保存 route、truth、telemetry、参数和结果；
- 报告 safe RTL、motor time、净高度收益和 thermal encounters。

满足以上条件后，项目才能从“循环集成演示”升级为“具有独立真值的算法实验”。
