# ArduSoar 项目结构图

> 本图按“当前主线、验证工具、保留的基线仿真”分层。图中节点和连线均为 Mermaid 文本，可直接修改。

```mermaid
flowchart TB
    OM["Open-Meteo<br/>天气 / GFS / W*"]
    SM["SoaringMeteo<br/>GFS 滑翔预报"]
    DEM["OpenTopoData DEM<br/>地形触发信息"]
    PILOT["地面站 / 操作者"]
    FC["ArduPilot Plane + ArduSoar<br/>战术层：探测、盘旋、爬升、返航"]
    HW["实机硬件<br/>Matek FC · Pi 5 · GPS · 空速计等"]

    subgraph REPO["autoglide 仓库"]
        direction TB

        subgraph ACTIVE["当前主线：天气驱动的战略层"]
            direction LR
            WEATHER["weather/<br/>天气采集、W*计算、地形热点、prior 生成"]
            PRIOR[("统一 thermal prior<br/>位置 · W* · 概率 · 风 · 云底")]
            NAV["navigation/<br/>BeliefMap · 可达性 · 价值判断 · 热气流地图"]
            PLAN["planner/<br/>贪心路径 · 电量约束 · 视觉反馈重规划"]
            ROUTE[("交付接口<br/>route.json + QGC WPL 110 .waypoints")]
            COMP["companion/<br/>Pi 5 运行时 · MAVLink · 热点接力 · ArduSoar移交"]

            WEATHER --> PRIOR --> NAV
            NAV --> PLAN --> ROUTE --> COMP
            PRIOR --> COMP
            COMP -.->|确认 / 排除候选点| NAV
            COMP -.->|状态 / 视觉报告| PLAN
        end

        subgraph VALIDATION["集成验证与飞行配置"]
            direction LR
            SITL["sitl/<br/>SITL启动、任务上传、天气真值、轨迹绘图"]
            APCFG["ardupilot_config/<br/>ArduSoar参数与安全/失效保护"]
            SETUP["scripts/ + SETUP.md<br/>安装外部ArduPilot、虚拟环境、SITL补丁"]
            TESTS["tests/ + GitHub Actions<br/>单元测试；在线API测试单独标记"]

            ROUTE --> SITL
            COMP --> SITL
            SETUP --> SITL
            APCFG --> FC
        end

        subgraph BASELINE["保留的 Python 基线仿真 / 研究工具"]
            direction LR
            WORLD["thermal_model/<br/>静态、高斯、生命周期、漂移、合并、随机场"]
            AIRFRAME["glider_model/<br/>运动学滑翔机 + 电动续航器"]
            SENSOR["sensors/<br/>传感器接口与带噪模拟"]
            EST["estimation/ + thermal_estimator/<br/>状态/风估计 + 高斯热气流拟合"]
            CTRL["controller/<br/>Cruise / Probe / Thermal 状态机与制导"]
            SIM["simulator/<br/>仿真循环、绘图、3D动画"]
            EXP["顶层实验脚本<br/>cross_country · endurance · explore · search/sweep"]
            MC["monte_carlo/<br/>批量鲁棒性分析"]
            DASH["dashboard/<br/>Engine步进器 + Plotly Dash界面"]
            OUT[("output/<br/>可再生图像与动画")]

            WORLD --> SIM
            AIRFRAME --> SIM
            SENSOR --> EST --> CTRL --> SIM
            EST --> NAV
            WORLD --> DASH
            AIRFRAME --> DASH
            SENSOR --> DASH
            EST --> DASH
            CTRL --> DASH
            NAV --> DASH
            SIM --> EXP
            SIM --> MC
            EXP --> OUT
            MC --> OUT
            PRIOR -.->|可装载| DASH
        end

        CONFIG["config.py / requirements.txt / pytest.ini<br/>基线参数、Python依赖与测试配置"]
        DOCS["README.md · docs/tasks.md · 模块README<br/>方向、部署、实验与硬件说明"]

        CONFIG -.-> SIM
        TESTS -.->|覆盖主线| PLAN
        TESTS -.->|覆盖基线| SIM
    end

    OM --> WEATHER
    SM --> WEATHER
    DEM --> WEATHER
    PILOT --> PLAN
    COMP <-->|"MAVLink 串口 / TCP"| FC
    SITL <-->|"软件在环"| FC
    HW -->|承载| FC
    HW -.->|遥测 / 视觉 / 实测反馈| COMP
```

## 阅读方式

- 实线表示主要数据或控制流；虚线表示反馈、装载、配置或测试关系。
- `weather → prior → navigation/planner → route → companion → ArduSoar` 是当前项目主线。
- `glider_model / thermal_model / controller / simulator` 是仍可运行的研究基线，不是实机内环飞控。
- ArduPilot 本体不在本仓库内；安装脚本把它放在仓库同级目录，SITL 与实机共同复用 MAVLink 接口。
