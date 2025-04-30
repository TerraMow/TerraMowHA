Data Point 定义
===

<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Data Point 索引表](#data-point-索引表)
- [电量](#电量)
- [电池状态](#电池状态)
- [任务状态](#任务状态)
- [作业数据统计](#作业数据统计)
- [当前作业数据](#当前作业数据)
- [基站使用时间](#基站使用时间)
- [作业刀盘使用时间](#作业刀盘使用时间)
- [即将到来的预约](#即将到来的预约)
- [全局作业参数设置](#全局作业参数设置)
- [地图状态](#地图状态)

<!-- /code_chunk_output -->

## Data Point 索引表

| ID | 名称 | 数据方向 | 描述 |
|-------|------|------|------|
| 8 | [电量](#电量) | 机器人→HA | 电池电量百分比 |
| 107 | [任务状态](#任务状态) | 机器人→HA | 任务状态信息(主任务、子任务、运行状态等) |
| 108 | [电池状态](#电池状态) | 机器人→HA | 电池状态信息(充电状态、温度等) |
| 113 | [当前作业数据](#当前作业数据) | 机器人→HA | 当前运行数据(面积、进度等) |
| 117 | [地图状态](#地图状态) | 机器人→HA | 地图状态(ID、状态、数量等) |
| 124 | [作业数据统计](#作业数据统计) | 机器人→HA | 运行统计数据(总时长、面积、次数) |
| 125 | [基站使用时间](#基站使用时间) | 机器人↔HA | 基站使用时间 |
| 126 | [作业刀盘使用时间](#作业刀盘使用时间) | 机器人↔HA | 刀盘使用时间 |
| 138 | [即将到来的预约](#即将到来的预约) | 机器人→HA | 即将执行的计划任务 |
| 155 | [全局作业参数设置](#全局作业参数设置) | 机器人↔HA | 全局运行参数设置 |

## 电量

- **ID**：8
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | int_value | 整数 | % | 电量百分比 |

## 电池状态

- **ID**：108
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | state | 字符串 | - | 电池状态：<br>"BATTERY_STATE_DISCHARGE" - 放电中<br>"BATTERY_STATE_CHARGING" - 充电中<br>"BATTERY_STATE_CHARGED" - 充电完成 |
  | charger_connected | 布尔值 | - | 适配器是否连接（连接未必代表一定会充电） |
  | is_switch_on | 布尔值 | - | 电源开关是否打开 |
  | tempreture | 字符串 | - | 电池温度状态：<br>"BATTERY_TEMPRETURE_NORMAL" - 电池温度正常<br>"BATTERY_TEMPRETURE_OVERHEAT" - 电池温度过高<br>"BATTERY_TEMPRETURE_UNDERHEAT" - 电池温度过低 |

- 示例：
  ```json
  {
    "state": "BATTERY_STATE_CHARGING",
    "charger_connected": true,
    "is_switch_on": true,
    "tempreture": "BATTERY_TEMPRETURE_NORMAL"
  }
  ```
  表示电池正在充电，适配器已连接，电源开关已打开，电池温度正常。
- 备注：
  - 当`charger_connected`为`true`但`state`为`BATTERY_STATE_DISCHARGE`时，表示适配器已连接但未进行充电
  - 电池温度异常会影响充电状态，当`tempreture`不为`BATTERY_TEMPRETURE_NORMAL`时，可能影响机器人的工作状态

## 任务状态

- **ID**：107
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | mission | 字符串 | - | 主任务类型：<br>"MISSION_IDLE" - 待机<br>"MISSION_RECHARGE" - 回充<br>"MISSION_GLOBAL_CLEAN" - 全局作业<br>"MISSION_BUILD_MAP" - 建图<br>"MISSION_BUILD_MAP_AND_CLEAN" - 边建图边作业<br>"MISSION_TEMPORARY_CLEAN" - 临时作业<br>"MISSION_BACK_TO_STARTING_POINT" - 返回起始点<br>"MISSION_REMOTE_CONTROL_CLEAN" - 遥控作业中<br>"MISSION_SCHEDULE_GLOBAL_CLEAN" - 预约全局作业<br>"MISSION_SCHEDULE_BUILD_MAP_AND_CLEAN" - 预约边建图边作业<br>"MISSION_SELECT_REGION_CLEAN" - 选区域作业<br>"MISSION_CREATE_CUSTOM_PASSAGE" - 创建自定义通道<br>"MISSION_BACKUP_MAP" - 备份地图<br>"MISSION_RELOCATE_BASE_STATION" - 重定位基站<br>"MISSION_USER_AUTO_CALIBRATION" - 用户触发自动标定<br>"MISSION_RESTORE_BACKUP_MAP" - 恢复备份地图<br>"MISSION_SCHEDULE_SELECT_REGION_CLEAN" - 预约选区域清扫<br>"MISSION_DRAW_REGION_CLEAN" - 划区域作业<br>"MISSION_EDGE_TRIM_CLEAN" - 沿边作业<br>"MISSION_UPDATE_BACKUP_MAP" - 更新备份地图<br>"MISSION_USER_TRIGGERED_SELF_CALIBRATION" - 用户触发自标定（使用基站） |
  | sub_mission | 字符串 | - | 子任务类型：<br>"SUB_MISSION_IDLE" - 待机<br>"SUB_MISSION_RELOCATION" - 重定位<br>"SUB_MISSION_RETURN_TO_BASE" - 返回基站<br>"SUB_MISSION_OUT_OF_STATION" - 出基站<br>"SUB_MISSION_REMOTE_CONTROL" - 遥控<br>"SUB_MISSION_SAVING_MAP" - 保存地图中<br>"SUB_MISSION_SETTING_BLADE_HEIGHT" - 刀盘升降中<br>"SUB_MISSION_DEFOGGING" - 除雾<br>"SUB_MISSION_WAIT_FOR_DAYLIGHT" - 等待天亮<br>"SUB_MISSION_COOLING_DOWN_MOTOR" - 冷却电机中<br>"SUB_MISSION_FLEXIBLE_STATION_WAIT" - 基站内等待 |
  | state | 字符串 | - | 任务状态：<br>"MISSION_STATE_IDLE" - 待机<br>"MISSION_STATE_RUNNING" - 运行中<br>"MISSION_STATE_PAUSE" - 暂停<br>"MISSION_STATE_ABORT" - 中止<br>"MISSION_STATE_COMPLETE" - 完成 |
  | power_mode | 字符串 | - | 功耗等级：<br>"POWER_MODE_RUNNING" - 运行中<br>"POWER_MODE_STANDBY" - 待机功耗<br>"POWER_MODE_HIBERNATE" - 休眠功耗 |
  | has_error | 布尔值 | - | 机器人当前是否有故障 |
  | is_saving_data | 布尔值 | - | 机器人是否正在保存数据 |
  | back_to_station_reason | 字符串 | - | 返回基站原因：<br>"BACK_TO_STATION_REASON_NONE" - 无<br>"BACK_TO_STATION_REASON_LOW_BATTERY" - 低电量<br>"BACK_TO_STATION_REASON_RAINING" - 下雨<br>"BACK_TO_STATION_REASON_MOW_MOTOR_OVERHEAT" - 割草电机过热<br>"BACK_TO_STATION_REASON_WHEEL_OVERHEAT" - 驱动轮电机过热<br>"BACK_TO_STATION_REASON_NIGHT_TIME" - 天黑 |
  | is_robot_navi_located | 布尔值 | - | 机器人当前是否有准确的导航定位信息 |
  | is_upgrading | 布尔值 | - | 机器人是否正在升级固件中 |
  | is_data_conversion_in_progress | 布尔值 | - | 机器人是否正在进行数据兼容性转换 |

- 示例：
  ```json
  {
    "mission": "MISSION_GLOBAL_CLEAN",
    "sub_mission": "SUB_MISSION_IDLE",
    "state": "MISSION_STATE_RUNNING",
    "power_mode": "POWER_MODE_RUNNING",
    "has_error": false,
    "is_saving_data": false,
    "back_to_station_reason": "BACK_TO_STATION_REASON_NONE",
    "is_robot_navi_located": true,
    "is_upgrading": false,
    "is_data_conversion_in_progress": false
  }
  ```
  表示机器人当前正在执行全局作业任务，状态为运行中，处于正常功耗模式，没有故障，没有在保存数据，有准确的导航定位信息，不在升级固件，不在进行数据兼容性转换。
- 备注：
  - `back_to_station_reason`字段仅当子任务为`SUB_MISSION_FLEXIBLE_STATION_WAIT`或`SUB_MISSION_RETURN_TO_BASE`时有意义
  - 即使任务状态为`MISSION_STATE_RUNNING`，当`has_error`为`true`时，表示机器人当前存在故障但仍在运行
  - 当`is_saving_data`为`true`时，机器人可能无法响应操作命令

## 作业数据统计

- **ID**：124
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | duration | 整数 | 秒 | 清扫总时长 |
  | clean_area | 整数 | 0.1平方米 | 清扫总面积（例如1500表示150平方米） |
  | clean_times | 整数 | 次 | 清扫总次数 |

- 示例：
  ```json
  {
    "duration": 7200,
    "clean_area": 2000,
    "clean_times": 5
  }
  ```
  表示总共清扫了2小时，覆盖了200平方米的面积，共完成了5次清扫任务。

## 当前作业数据

- **ID**：113
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | type | 字符串 | - | 面积类型：<br>"MAP_AREA_TYPE_NONE" - 无类型，代表当前未有过任何作业<br>"MAP_AREA_TYPE_BUILD_MAP" - 建图面积<br>"MAP_AREA_TYPE_CLEANING" - （全局）作业面积<br>"MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING" - 边建图边作业面积<br>"MAP_AREA_TYPE_SELECT_REGION_CLEANING" - 选区作业面积<br>"MAP_AREA_TYPE_DRAW_REGION_CLEANING" - 划区作业面积<br>"MAP_AREA_TYPE_EDGE_TRIM_CLEANING" - 沿边作业面积 |
  | total_area | 整数 | 0.1平方米 | 总面积，根据type类型含义不同:<br>- type="MAP_AREA_TYPE_BUILD_MAP"：建图面积<br>- type="MAP_AREA_TYPE_CLEANING"：地图总面积(总可作业面积)<br>- type="MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING"：地图(已探索区域)总面积<br>- type="MAP_AREA_TYPE_SELECT_REGION_CLEANING"：选区总面积<br>- type="MAP_AREA_TYPE_DRAW_REGION_CLEANING"或"MAP_AREA_TYPE_EDGE_TRIM_CLEANING"：无效 |
  | clean_area | 整数 | 0.1平方米 | 清扫面积，仅在以下情况有效:<br>- type="MAP_AREA_TYPE_CLEANING"或"MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING"或"MAP_AREA_TYPE_SELECT_REGION_CLEANING"：已作业面积(包括历史作业)<br>- type="MAP_AREA_TYPE_DRAW_REGION_CLEANING"：已作业面积 |
  | is_completed | 布尔值 | - | 清扫是否已完成(用于校正已作业面积小于总面积情况下作业进度的计算)<br>仅当type="MAP_AREA_TYPE_CLEANING"或"MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING"或"MAP_AREA_TYPE_SELECT_REGION_CLEANING"时有效 |
  | work_duration | 整数 | 秒 | 作业或建图时长，指的是这一次总覆盖的时长 |

- 示例：
  ```json
  {
    "type": "MAP_AREA_TYPE_CLEANING",
    "total_area": 3000,
    "clean_area": 1500,
    "is_completed": false,
    "work_duration": 1800
  }
  ```
  表示全局作业，总面积为300平方米，已清扫150平方米，清扫尚未完成，已工作了30分钟。

## 基站使用时间

- **ID**：125
- 数据方向：机器人↔HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | int_value | 整数 | 分钟 | 基站使用时间 |

- 示例：
  ```json
  {
    "int_value": 120
  }
  ```
  表示基站使用了120分钟。
- 备注：
  - 基站的推荐清洁周期为30天，也就是30*24*60=43200分钟。
  - 当机器人收到数值为0的数据时，将会重置机器人内部记录的基站使用时间为0。

## 作业刀盘使用时间

- **ID**：126
- 数据方向：机器人↔HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | int_value | 整数 | 分钟 | 刀盘使用时间 |

- 示例：
  ```json
  {
    "int_value": 120
  }
  ```
  表示刀盘使用了120分钟。
- 备注：
  - 刀盘的推荐清洁周期为240分钟。
  - 当机器人收到数值为0的数据时，将会重置机器人内部记录的刀盘使用时间为0。

## 即将到来的预约

- **ID**：138
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | exist | 布尔值 | - | 是否存在即将执行的预约 |
  | item_id | 整数 | - | 下一次预约的ID |
  | shift_id | 整数 | - | 下一次预约的时段ID |
  | start_time | 对象 | - | 下一次预约的开始时间 |
  | start_time.hour | 整数 | 小时 | 开始时间的小时（24小时制） |
  | start_time.minute | 整数 | 分钟 | 开始时间的分钟 |
  | end_time | 对象 | - | 下一次预约的结束时间 |
  | end_time.hour | 整数 | 小时 | 结束时间的小时（24小时制） |
  | end_time.minute | 整数 | 分钟 | 结束时间的分钟 |

- 示例：
  ```json
  {
    "exist": true,
    "item_id": 1,
    "shift_id": 0,
    "start_time": {
      "hour": 14,
      "minute": 30
    },
    "end_time": {
      "hour": 16,
      "minute": 0
    }
  }
  ```
  表示存在一个即将执行的预约，预约ID为1，时段ID为0，将于14:30开始，16:00结束。
- 备注：
  - 当`exist`为`false`时，其他字段可能为空或默认值
  - `item_id`对应于`ScheduleList`中的预约ID
  - `shift_id`表示该预约中的具体时段索引（当预约包含多个时段时使用）

## 全局作业参数设置

- **ID**：155
- 数据方向：机器人↔HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | mow_height | 对象 | - | 割草高度设置 |
  | mow_height.value | 整数 | 毫米 | 割草高度值 |
  | mow_speed | 对象 | - | 割草速度设置 |
  | mow_speed.speed_type | 字符串 | - | 割草速度类型：<br>"MOW_SPEED_TYPE_LOW" - 低速<br>"MOW_SPEED_TYPE_MEDIUM" - 中速（默认值）<br>"MOW_SPEED_TYPE_ADAPTIVE_HIGH" - 自适应高速 |
  | edge_cutting_distance | 对象 | - | 沿边割草距离设置 |
  | edge_cutting_distance.value | 整数 | 毫米 | 沿边割草距离值 |
  | main_direction_angle_config | 对象 | - | 主方向角度配置 |
  | main_direction_angle_config.mode | 字符串 | - | 主方向配置模式：<br>"MAIN_DIRECTION_MODE_SINGLE" - 单主方向<br>"MAIN_DIRECTION_MODE_MULTIPLE" - 多主方向<br>"MAIN_DIRECTION_MODE_AUTO_ROTATE" - 自动旋转主方向 |
  | main_direction_angle_config.single_mode_config | 对象 | - | 单主方向模式配置（mode为MAIN_DIRECTION_MODE_SINGLE时有效） |
  | main_direction_angle_config.single_mode_config.angle | 整数 | 度 | 主方向角度 |
  | main_direction_angle_config.multiple_mode_config | 对象 | - | 多主方向模式配置（mode为MAIN_DIRECTION_MODE_MULTIPLE时有效） |
  | main_direction_angle_config.multiple_mode_config.angles | 数组 | 度 | 多个主方向角度列表 |
  | main_direction_angle_config.auto_rotate_mode_config | 对象 | - | 自动旋转主方向配置（mode为MAIN_DIRECTION_MODE_AUTO_ROTATE时有效） |
  | main_direction_angle_config.auto_rotate_mode_config.angle_interval | 整数 | 度 | 自动旋转的角度间隔 |
  | main_direction_angle_config.current_angle | 整数 | 度 | 当前主方向角度（仅机器人上传时使用） |
  | mow_spacing | 对象 | - | 割草间距设置 |
  | mow_spacing.value | 整数 | 毫米 | 割草间距值（修改将会重置作业进度） |
  | blade_disk_speed | 对象 | - | 刀盘转速设置 |
  | blade_disk_speed.speed_type | 字符串 | - | 刀盘转速类型：<br>"BLADE_DISK_SPEED_TYPE_LOW" - 低速<br>"BLADE_DISK_SPEED_TYPE_MEDIUM" - 中速<br>"BLADE_DISK_SPEED_TYPE_HIGH" - 高速（默认值） |
  | current_mow_spacing | 整数 | 毫米 | 当前的割草间距（仅机器人上传时使用） |

- 示例：
  ```json
  {
    "mow_height": {
      "value": 40
    },
    "mow_speed": {
      "speed_type": "MOW_SPEED_TYPE_MEDIUM"
    },
    "edge_cutting_distance": {
      "value": 10
    },
    "main_direction_angle_config": {
      "mode": "MAIN_DIRECTION_MODE_SINGLE",
      "single_mode_config": {
        "angle": 0
      },
      "current_angle": 0
    },
    "mow_spacing": {
      "value": 100
    },
    "blade_disk_speed": {
      "speed_type": "BLADE_DISK_SPEED_TYPE_HIGH"
    },
    "current_mow_spacing": 100
  }
  ```
  表示割草高度设置为40毫米，割草速度为中速，沿边割草距离为10毫米，使用单主方向模式（角度为0度），割草间距为100毫米，刀盘转速为高速。
- 备注：
  - 可以从HA下发该协议给机器人以修改对应的参数设置，且可以仅发送其中一个字段，例如只发送`mow_height`字段，则只会修改割草高度。
  - 修改割草间距或主方向角度配置将会重置作业进度
  - 当机器人上报该协议时才包含`current_mow_spacing`和`main_direction_angle_config.current_angle`字段

## 地图状态

- **ID**：117
- 数据方向：机器人→HA
- 字段说明：

  | 字段名 | 类型 | 单位 | 说明 |
  |-------|------|------|------|
  | is_map_detected | 布尔值 | - | 是否检测到地图（取决于是否曾经检测到基站ID） |
  | map_id | 整数 | - | 当前地图ID |
  | map_state | 字符串 | - | 地图状态：<br>"MAP_STATE_EMPTY" - 地图完全为空<br>"MAP_STATE_INCOMPLETE" - 已开始建图但未完成<br>"MAP_STATE_COMPLETE" - 地图已建完 |
  | map_number | 整数 | - | 地图的数量 |
  | is_backing_up_map | 布尔值 | - | 是否正在备份/恢复地图 |
  | backup_map_id | 整数 | - | 备份/恢复中的地图ID（仅当正在备份地图时有效） |
  | main_direction_angle | 整数 | 度 | 当前地图的主方向角度（仅当地图存在时有效） |
  | is_spot_mode_map | 布尔值 | - | 当前地图是否为Spot模式地图（仅当地图存在时有效） |
  | spot_mode_map_number | 整数 | - | Spot模式保存地图的数量 |
  | is_able_to_run_build_map | 布尔值 | - | 地图是否可以进行建图 |
  | backup_map_backup_id | 整数 | - | 备份/恢复操作的备份ID（用于区分多张不同的备份地图） |

- 示例：
  ```json
  {
    "is_map_detected": true,
    "map_id": 1,
    "map_state": "MAP_STATE_COMPLETE",
    "map_number": 2,
    "is_backing_up_map": false,
    "main_direction_angle": 0,
    "is_spot_mode_map": false,
    "spot_mode_map_number": 0,
    "is_able_to_run_build_map": false,
    "backup_map_backup_id": 0
  }
  ```
  表示已检测到地图，当前地图ID为1，地图已建完，总共有2张地图，当前不在备份操作中，主方向角度为0度，不是Spot模式地图，无Spot模式地图，不可以进行建图操作，备份ID为0。
- 备注：
  - 当`is_map_detected`为`false`时，表示机器人未检测到地图，可能需要进行基站配对
  - 地图状态(`map_state`)直接影响机器人可执行的作业类型
  - 即使地图状态为`MAP_STATE_COMPLETE`，如果`is_able_to_run_build_map`为`true`，仍然可以启动建图（例如存在虚拟通道的情况）
  - 当`is_backing_up_map`为`true`时，`backup_map_id`字段才有意义
