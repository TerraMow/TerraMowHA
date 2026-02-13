"""Constants for the TerraMow integration."""

DOMAIN = "terramow"

MQTT_PORT = 1883

MQTT_USERNAME = "terramow"

# MQTT主题
MAP_INFO_TOPIC = "map/current/info"
MAP_META_TOPIC = "map/current/meta"
PATH_META_TOPIC = "path/current/meta"
POSE_TOPIC = "pose/current"
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

# 维护周期常量 (单位: 分钟)
# 刀盘推荐清洁周期: 240小时 = 240 * 60 = 14400分钟
BLADE_MAINTENANCE_CYCLE_MINUTES = 14400

# 基站推荐清洁周期: 30天 = 30 * 24 * 60 = 43200分钟
BASE_STATION_MAINTENANCE_CYCLE_MINUTES = 43200
