# TerraMow 开发者指南

本文档提供了有关 TerraMow Home Assistant 集成组件的开发信息，帮助开发者理解代码结构并进行功能扩展。


<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [通信方式](#通信方式)
- [MQTT Topics 定义](#mqtt-topics-定义)

<!-- /code_chunk_output -->

## 通信方式

TerraMow 和 Home Assistant 之间的通信主要通过 MQTT 协议进行。为了简化配置，我们并没有使用 Home Assistant 侧的 MQTT Broker，而是内置了一个轻量的 MQTT Broker 在 TerraMow 中。这样一来在设置时就只需要填入 TerraMow 的 IP 和密码即可。

值得注意的是，TerraMow 的 MQTT Broker 使用了默认端口 1883，且没有启用 SSL/TLS 加密，因此最好在局域网内使用，并确保你的 Wifi 网络进行了合适的加密（WPA/WPA2）。

## MQTT Topics 定义

在 TerraMow 中，主要的数据协议是以 Data Point 为单元定义的。为了实现数据的双向通信，TerraMow 需要将数据点的状态通过 MQTT Topic 发布到 Home Assistant 中，同时也需要监听 Home Assistant 发布的 Topic 来接收指令。

有关于 Data Point 的相关的 Topic 定义如下：

| Topic | 描述 |
| ------- | ------ |
| data_point/{dp_id}/robot | 机器人发布消息的方向（从机器人到应用） |
| data_point/{dp_id}/app | 应用发布消息给机器人的方向（从应用到机器人） |

其中 `{dp_id}` 是 Data Point 的 ID，类型为整数，范围为 0-200。

具体 Data Point 的定义可以参考 [Data Point 定义](./developers/data_point.md)。
