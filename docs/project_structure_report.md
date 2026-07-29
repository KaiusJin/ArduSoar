# ArduSoar 项目结构简报

## 阅览范围

本次检查精读了原仓库内 14 份 Markdown 文档，并粗读了 98 个 Python 文件（约 9,689 行）、Shell/PowerShell 启动脚本、ArduPilot 参数、CI、依赖和 17 个测试文件。`.git/`、`.venv/`、缓存、天气 CSV 与已生成图片/动画只做了目录识别，没有作为项目源码分析。

## 总体判断

项目已经从“自研完整滑翔控制仿真”转向清晰的两层架构：本仓库负责天气驱动的战略决策，ArduPilot/ArduSoar 负责机载战术控制。当前最连贯的主链是：

`真实天气/地形 → thermal prior → 候选点评分与路径规划 → QGC任务 → Pi 5/MAVLink → ArduSoar → 观测反馈与重规划`。

旧的 Python 飞控、热气流、传感器与仿真代码没有删除，而是作为算法基线、Dashboard 演示和 Monte Carlo 研究平台继续保留。因此仓库实际上同时包含“面向实机的战略层”和“面向研究的完整离线仿真”两套运行路径。

## 目录职责

| 目录/文件 | 当前角色 |
|---|---|
| `weather/` | 主线数据入口；接入 Open-Meteo、SoaringMeteo、DEM，生成统一 thermal prior。 |
| `navigation/` | 主线共享决策内核；维护候选热气流置信度、漂移、可达性和爬升价值。 |
| `planner/` | 地面路径规划；输出富信息 JSON 和可直接上传的 QGC WPL 110 任务，并接收视觉/升力反馈重规划。 |
| `companion/` | Pi 5/MAVLink 桥；上传任务、选择或接力热点、起飞后启用 ArduSoar、回传状态。 |
| `sitl/` | 与外部 ArduPilot SITL 的端到端验证；包含任意热气流位置补丁和天气真值实验。 |
| `ardupilot_config/` | 实机起始参数与强制安全/失效保护参数。 |
| `dashboard/` | 可交互的离线演示；复用天气 prior、导航逻辑和基线仿真组件。 |
| `glider_model/`、`thermal_model/`、`thermal_estimator/`、`controller/`、`simulator/` | 原始 Python 基线控制闭环；用于研究、对照和可视化，不替代实机 ArduSoar。 |
| `sensors/`、`estimation/` | 传感器与融合接口；当前实现以仿真和直通估计为主，为未来硬件实现留出替换点。 |
| `tests/`、`.github/workflows/tests.yml` | 单元测试和 Python 3.12 CI；实时天气 API 测试通过 `integration` 标记从常规 CI 排除。 |

## 关键接口

- thermal prior 是跨模块核心契约：候选点使用 `[east_m, north_m, strength/W*, probability]`，同时携带风、云底、边界和地理原点。
- 规划结果分成 `route.json`（天气、概率、目标、移交说明）与 `.waypoints`（ArduPilot 原生任务）。
- companion 与 ArduPilot 通过 MAVLink 通信；SITL 使用 TCP，Pi 5 实机使用串口，业务层基本共用。
- 离线传感器链为 `SensorSnapshot → VehicleState → Wind → estimator/navigation`，但实机 `SensorSuite` 和真实 EKF/AHRS 尚未落地。

## 当前质量与结构性注意点

- 2026-07-28 清理后的完整测试结果为 **95 passed**；该结果仍不能替代 SITL、Pi 5、飞控或真实飞行证据。
- 已删除过期的 `proposal.md`、`goals.md` 和旧审查产物；当前验证改进路线统一记录在 `docs/tasks.md`。
- `planner.route_planner` 与 `companion.geo` 各自维护一份 ENU/经纬度转换；已有一致性测试，但长期建议收敛为单一实现。
- `dashboard.Engine` 明确复制/演化自 `explore.py` 的逐步逻辑，方便界面使用但形成两处仿真编排；修改策略时需同步核对。
- 视觉反馈目前是文件轮询/人工或外部传输落盘，重规划后任务再次上传仍依赖部署侧衔接；这是实机闭环中最明显的集成缺口之一。
- 路径规划采用贪心候选链和简化能量模型，适合作为当前可解释基线；大范围、强风、候选点稀疏时还不是全局最优规划器。
- ArduPilot、`soar-venv` 与 SITL 工具链位于仓库外部；Windows 依赖 WSL2，天气与地形功能依赖在线 API，这些都是复现实验时需要单独确认的外部条件。

结构图见 [`project_structure.md`](project_structure.md)。
