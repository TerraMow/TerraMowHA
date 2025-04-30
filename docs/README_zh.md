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

### 系统要求

- Home Assistant 2023.9.3或更高版本（已在2025.1.1版本上测试）
- TerraMow固件版本6.6.0或更高
- TerraMow APP版本1.6.0或更高

### 支持

如需支持，请在[GitHub](https://github.com/TerraMow/TerraMowHA/issues)上提交问题。

### 开发者信息

对于有兴趣了解或扩展此集成的开发者，请参阅[开发者指南](../docs/zh/developers.md)。

---

## 许可证

本项目采用GNU通用公共许可证v3.0授权 - 详情请参阅[LICENSE](../LICENSE)文件。