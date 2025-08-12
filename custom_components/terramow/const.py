"""Constants for the TerraMow integration."""

DOMAIN = "terramow"

MQTT_PORT = 1883

MQTT_USERNAME = "terramow"

# MQTT主题
MAP_INFO_TOPIC = "map/current/info"
MODEL_NAME_TOPIC = "model/name"

# 版本兼容性相关常量
# 当前插件支持的HA版本号
CURRENT_HA_VERSION = 2

# 最低要求的固件overall版本号
MIN_REQUIRED_OVERALL_VERSION = 25

# 版本兼容性检查结果
class CompatibilityStatus:
    COMPATIBLE = "compatible"
    UPGRADE_REQUIRED = "upgrade_required"  # 需要升级固件
    DOWNGRADE_RECOMMENDED = "downgrade_recommended"  # 建议降级插件
    INCOMPATIBLE = "incompatible"  # 完全不兼容

# 版本兼容性信息获取的数据点ID
COMPATIBILITY_INFO_DP = 127
