# TerraMow Home Assistant集成

<div align="center">
  <p>
    <a href="../README.md"><img src="https://img.shields.io/badge/English-blue?style=for-the-badge" alt="English"/></a>
    <a href="#"><img src="https://img.shields.io/badge/中文-red?style=for-the-badge" alt="中文"/></a>
  </p>
  <img src="../docs/images/terramow_logo.png" alt="TerraMow Logo" width="400">
</div>

---

这是一个适用于TerraMow机器人割草机的Home Assistant集成。

### 功能特性

- 控制割草机（启动、暂停和回充）
- 监控电池状态和活动状态
- 基于MQTT的实时通信

控制操作会等待最多 5 秒，确认机器人返回了与本次命令匹配的回复。设备拒绝时，
Home Assistant 会显示错误；超时表示结果尚未确认，不会自动重发。未提供命令回复
的旧固件也会返回“未确认”。回复成功表示命令已接受，是否开始割草仍以设备作业状态为准。

诊断实体“最近事件”显示最近事件码、时间和说明；“当前故障”在设备明确报告无故障时为
`0`，有故障时显示首个故障码，属性中包含全部当前故障。未收到反馈前显示未知。
当前故障会使割草机显示 `error`，故障清除后恢复设备上报的作业状态；历史事件不会
改变当前故障状态。割草机属性 `back_to_station_reason` 保留回基站原因。

三个诊断传感器分别显示设备当前任务、子任务和任务阶段。传感器状态使用
`mission_global_clean`、`sub_mission_wait_for_rain_to_stop` 等小写值，
以便 Home Assistant 显示翻译；`protocol_value` 属性保留设备原始的大写枚举值。
收到新任务状态时会立即更新，这些传感器不会向割草机发送控制命令。

诊断传感器“当前会话进度”按已作业面积与总面积
计算百分比，在设备报告作业完成前最高显示 98%，只有完成时才显示 100%。
进度不适用时传感器为未知：地图未建完或仍可建图、Spot 模式、
划区或沿边割草、边建图边割草，以及机器人尚无作业可显示（从未作业或尚未
收到作业数据）。等待日照时显示 0%。作业数据、地图状态、任务状态或工作模式
变化时立即更新；新会话开始前，传感器保持设备最后一次上报的会话进度。
Home Assistant 与机器人断开连接时该传感器不可用。

### 安装方法

#### 方法一：通过HACS安装（推荐）
1. 确保已安装[HACS](https://hacs.xyz/)
2. 进入HACS → 集成 → 三点菜单(⋮) → 自定义存储库
3. 添加 `https://github.com/TerraMow/TerraMowHA` 作为存储库URL，类别选择"集成"
4. 进入HACS → 集成 → + → 搜索"TerraMow"
5. 安装并重启Home Assistant

#### 方法二：手动安装
1. 将`custom_components/terramow`文件夹复制到Home Assistant的`/config/custom_components`目录
2. 重启Home Assistant
3. 进入设置 → 设备与服务 → 添加集成
4. 搜索"TerraMow"并按照配置步骤进行设置

### 配置参数

需要配置以下参数：
- **主机地址**：TerraMow设备的IP地址或主机名
- **密码**：MQTT认证密码

如需修改地址或密码，进入“设置 → 设备与服务 → TerraMow”，在集成菜单中选择
“重新配置”。原有实体及其名称会保留；不能选择已被另一项 TerraMow 配置使用的地址。

### 系统要求

- Home Assistant 2025.3.4或更高版本（开发环境会同时验证2025.3.4和当前稳定版）
- TerraMow固件版本6.6.0或更高
- TerraMow APP版本1.6.0或更高

### 参与开发

仓库已内置推荐的 VS Code Dev Container 开发环境。Home Assistant、Python
和全部依赖都在容器内运行，不会修改宿主机软件包。首次搭建、断点调试、测试以及
可选的完整 Home Assistant Core 模式请参阅 [CONTRIBUTING.md](../CONTRIBUTING.md)。

### 支持

如需支持，请在[GitHub](https://github.com/TerraMow/TerraMowHA/issues)上提交问题。

### 开发者信息

对于有兴趣了解或扩展此集成的开发者，请参阅[开发者指南](../docs/zh/developers.md)。

---

## 许可证

本项目采用GNU通用公共许可证v3.0授权 - 详情请参阅[LICENSE](../LICENSE)文件。
