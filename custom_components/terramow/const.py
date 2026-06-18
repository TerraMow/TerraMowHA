"""Constants for the TerraMow integration."""

DOMAIN = "terramow"

MQTT_PORT = 1883

MQTT_USERNAME = "terramow"

# MQTT 重连退避（秒）
# 首次连接失败后的基础等待时间，之后按指数退避，封顶为 MQTT_RECONNECT_MAX_DELAY。
# 这样在割草机不可达（休眠/回基站/IP 变化）时不会每隔几秒刷一条 ERROR，也不会频繁拍打网络。
MQTT_RECONNECT_BASE_DELAY = 5
MQTT_RECONNECT_MAX_DELAY = 60

# 实体移除时等待 MQTT 工作线程退出的最长时间（秒），避免线程残留为僵尸继续重连。
MQTT_THREAD_JOIN_TIMEOUT = 10

# MQTT主题
MAP_INFO_TOPIC = "map/current/info"
MAP_META_TOPIC = "map/current/meta"
PATH_META_TOPIC = "path/current/meta"
PATH_HISTORY_META_TOPIC = "path/history/meta"
POSE_TOPIC = "pose/current"
MODEL_NAME_TOPIC = "model/name"

# 版本兼容性相关常量
# 当前插件要求的固件 home_assistant 兼容版本
CURRENT_HA_VERSION = 3

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

# dp_155 割草速度枚举（与 work_param.proto 对齐）
MOW_SPEED_TYPE_LOW = "MOW_SPEED_TYPE_LOW"
MOW_SPEED_TYPE_MEDIUM = "MOW_SPEED_TYPE_MEDIUM"
MOW_SPEED_TYPE_ADAPTIVE_HIGH = "MOW_SPEED_TYPE_ADAPTIVE_HIGH"
MOW_SPEED_TYPE_AUTO = "MOW_SPEED_TYPE_AUTO"

MOW_SPEED_TYPES = [
    MOW_SPEED_TYPE_LOW,
    MOW_SPEED_TYPE_MEDIUM,
    MOW_SPEED_TYPE_ADAPTIVE_HIGH,
    MOW_SPEED_TYPE_AUTO,
]

# 功能级兼容版本：割草速度支持 AUTO 档位的最小版本号
MIN_MOW_SPEED_VERSION_FOR_AUTO = 3

# dp_155 刀盘转速默认值（与固件实际初始化路径一致）
DEFAULT_BLADE_DISK_SPEED_TYPE = "BLADE_DISK_SPEED_TYPE_MEDIUM"
