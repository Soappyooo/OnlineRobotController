# Online Robot Controller

[![GitHub stars](https://img.shields.io/github/stars/Soappyooo/OnlineRobotController?style=for-the-badge)](https://github.com/Soappyooo/OnlineRobotController/stargazers)
[![License](https://img.shields.io/github/license/Soappyooo/OnlineRobotController?style=for-the-badge)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Node.js LTS](https://img.shields.io/badge/Node.js-LTS-339933?style=for-the-badge&logo=node.js&logoColor=white)](https://nodejs.org/)

[English](README.md)

Online Robot Controller 是一个开源的机器人监控、遥操作、相机展示和 URDF 可视化 Web 界面。项目把机器人专有集成能力封装在后端插件中，让同一套 UI 和 API 可以复用于仿真、演示环境和真实硬件。

<p align="center">
	<img src="assets/readme_assets/main_page.png" alt="Online Robot Controller 主页面" width="100%" />
</p>

## ✨ 项目亮点

- 基于插件的后端架构，可热切换机器人适配器
- 统一的关节控制、笛卡尔控制、相机和安全接口
- 内置仿真流程，便于在无硬件环境下开发 UI 和插件
- 浏览器端 URDF 可视化，运行时可配置
- 自带公开示例插件，覆盖最小实现和完整参考实现两类场景

## 🚀 快速开始

### 1. 安装前置环境

- Python 3.11
- `uv` 或 `pip`
- Node.js LTS
- `npm`

### 2. 安装后端依赖

使用 `uv`：

```powershell
cd backend
uv sync
```

使用 `pip`：

```powershell
cd backend
python -m pip install -r requirements.txt
```

### 3. 安装前端依赖

```powershell
cd frontend
npm install
```

### 4. 启动项目

后端使用 `uv`：

```powershell
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

后端使用 `pip`：

```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

前端：

```powershell
cd frontend
npm run dev
```

启动后打开：

- 页面：http://127.0.0.1:5180
- API 文档：http://127.0.0.1:8100/docs

### 5. 先玩起来

仓库已经带有两个公开示例插件：

- `mock`：最小可用参考实现
- `ur5_shadow`：包含虚拟硬件、相机和自定义 IK 的完整示例

建议先直接启动页面，用内置示例插件把界面和交互方式摸熟，再开始写自己的插件。

## 🎮 页面使用方式

▶ 使用示例视频：[example_usage.mp4](assets/readme_assets/example_usage.mp4)

https://github.com/user-attachments/assets/45c3936a-3e7f-43d5-bd7c-42c662597575

整个页面围绕一个可自由编排的面板仪表盘展开：

- 左上角的 `+` 按钮用于添加新面板。
- 每个面板都可以缩放、拖拽移动，也可以关闭。
- 左下角的设置入口可以切换配置并修改配置内容。
- 顶部横条是安全面板，集中放置急停相关控制。
- 点击急停按钮，或直接按 `Shift`，都可以触发急停。
- 急停右侧的按钮用于松开急停。
- 最右侧按钮用于在仿真和实机模式之间切换。
- 页面主体部分就是各类工作面板，例如 Teach Panel、URDF View、Camera 和 Joint Snapshot。

如果你第一次接触这个项目，推荐按下面的顺序理解它：

1. 先启动后端和前端。
2. 打开页面并添加几个面板。
3. 拖拽和缩放这些面板，熟悉布局方式。
4. 使用右上角按钮切换仿真和实机模式。
5. 打开左下角设置，查看当前配置并尝试编辑。

## 🧩 编写自己的插件

当你准备接入自己的机器人时，可以从 `backend/app/plugins/` 里的示例开始。

推荐路径：

1. 如果想从最小骨架开始，复制 `backend/app/plugins/mock/`。
2. 如果想参考更完整的实现，复制 `backend/app/plugins/ur5_shadow/`。
3. 重命名目录并修改其中的 `config.toml`。
4. 在插件类中实现真实模式相关接口。

插件配置通常类似下面这样：

```toml
[general]
command_hz = 60  # 在 Teach Panel 中按住按钮时，命令会按这个频率发送
state_hz = 60  # 在实机模式下，后端会尝试按这个频率调用 get_joint_states 和 get_estop
camera_hz = 15  # 在实机模式下，后端会尝试按这个频率为每个相机调用 get_real_camera_frame
default_angle_step_deg = 0.5  # 在关节控制模式下使用 Teach Panel 按钮时，每次增量的角度
default_length_step_m = 0.001  # 在笛卡尔控制模式下使用 Teach Panel 按钮时，末端每次移动的距离


[sim]
urdf_path = "assets/your_assets/some_robot.urdf"  # 用于可视化的 URDF 路径，相对于项目根目录

[[sim.chains]]  # 你可以定义多个运动链。这里是一个 6 自由度链的示例。
id = "chain_id"  # 运动链唯一标识，在 API 调用中使用
name = "Chain Name"  # 显示名称，会出现在 UI 中
world_link = "world"  # URDF 中世界坐标链接名。如果 URDF 没有独立 world link，可使用 "base_link"。在笛卡尔控制中，末端位姿可以表达在这个世界坐标系下。
base_link = "base_link"  # 基座链接名，用于 IK 计算
tip_link = "tip_link"  # 末端执行器链接名
joints = [
	"joint_1",
	"joint_2",
	"joint_3",
	"joint_4",
	"joint_5",
	"joint_6",
]  # URDF 中从 base 到 tip 的关节名顺序。
joint_offsets_deg = [0.0, -90.0, 90.0, 0.0, 90.0, 0.0]  # 应用于 URDF 可视化的关节角偏移。例如偏移为 90 度时，真实关节角为 0，界面中的 URDF 会显示为 90 度。
initial_joints_deg = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # 初始真实关节角，单位为度。

[real]
dummy_var = "A dummy variable"  # 这里可以放任意自定义变量，可参考 ur5_shadow 插件的实际用法。

[[real.cameras]]  # 你可以定义多个相机。
id = "camera_id"  # 相机唯一标识，在 API 调用中使用
name = "Camera Name"  # 相机显示名称，会出现在 UI 中
```

插件作者通常需要重写的核心接口包括：

- `get_joint_states(chain_id) -> list[float]`
- `set_joint_targets(chain_id, target_angles_deg) -> None`
- `get_estop() -> bool`
- `set_estop(trigger) -> None`
- `get_ee_pose(chain_id) -> np.ndarray`
- `set_ee_pose_target(chain_id, se3_target_in_world) -> None`
- `get_real_camera_frame(camera_id) -> tuple[str, float] | None`
- `get_camera_receive_fps(camera_id) -> float`
- `on_mode_enter_real() -> str`
- `on_mode_exit_real() -> None`

插件通过 `backend/app/plugins/<plugin_name>/config.toml` 自动发现，所以常见工作流就是新建一个插件目录，先跑通配置，再把真实逻辑逐步填进去。

## 🧪 验证改动

后端：

```powershell
cd backend
uv run pytest -q
```

前端：

```powershell
cd frontend
npm run test
npm run build
```

## 📁 仓库结构

- `backend/`：FastAPI 后端、插件系统和后端测试
- `frontend/`：React + TypeScript + Three.js 操作界面
- `assets/ur5_shadow_example/`：示例插件使用的公开 URDF 和网格资源
- `assets/readme_assets/`：README 使用的截图和演示媒体

## 📄 许可证与第三方资源

项目源码采用 MIT License。

`assets/ur5_shadow_example/` 下的示例机器人资源包含第三方内容，并保留其原始许可证声明：

- `assets/ur5_shadow_example/urdf/ur5.urdf`：源文件头中标注为 MIT License
- `assets/ur5_shadow_example/urdf/shadow_hand_right.urdf`：Shadow Robot 的 BSD License
- `assets/ur5_shadow_example/urdf/ur5_shadow.urdf`：合并后的示例 URDF，继续保留上游许可证说明

详细说明见 `THIRD_PARTY_NOTICES.md`。
