Data Point Definition
===

<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Battery Level](#battery-level)
- [Battery Status](#battery-status)
- [Task Status](#task-status)
- [Operation Statistics](#operation-statistics)
- [Current Operation Data](#current-operation-data)
- [Base Station Usage Time](#base-station-usage-time)
- [Mowing Blade Disk Usage Time](#mowing-blade-disk-usage-time)
- [Upcoming Schedule](#upcoming-schedule)
- [Global Operation Parameter Settings](#global-operation-parameter-settings)
- [Map Status](#map-status)

<!-- /code_chunk_output -->

## Data Point Index

| ID | Name | Data Direction | Description |
|-------|------|------|------|
| 8 | [Battery Level](#battery-level) | Robot→HA | Battery percentage |
| 107 | [Task Status](#task-status) | Robot→HA | Task status information (main task, sub-task, running state, etc.) |
| 108 | [Battery Status](#battery-status) | Robot→HA | Battery status information (charging state, temperature, etc.) |
| 113 | [Current Operation Data](#current-operation-data) | Robot→HA | Current operation data (area, progress, etc.) |
| 117 | [Map Status](#map-status) | Robot→HA | Map status (ID, state, count, etc.) |
| 124 | [Operation Statistics](#operation-statistics) | Robot→HA | Operation statistics (total duration, area, count) |
| 125 | [Base Station Usage Time](#base-station-usage-time) | Robot↔HA | Base station usage time |
| 126 | [Mowing Blade Disk Usage Time](#mowing-blade-disk-usage-time) | Robot↔HA | Mowing blade disk usage time |
| 138 | [Upcoming Schedule](#upcoming-schedule) | Robot→HA | Upcoming scheduled task |
| 155 | [Global Operation Parameter Settings](#global-operation-parameter-settings) | Robot↔HA | Global operation parameter settings |

## Battery Level

- **ID**: 8
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | int_value | Integer | % | Battery percentage |

## Battery Status

- **ID**: 108
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | state | String | - | Battery state:<br>"BATTERY_STATE_DISCHARGE" - Discharging<br>"BATTERY_STATE_CHARGING" - Charging<br>"BATTERY_STATE_CHARGED" - Fully charged |
  | charger_connected | Boolean | - | Whether the adapter is connected (connection doesn't necessarily mean charging) |
  | is_switch_on | Boolean | - | Whether the power switch is turned on |
  | tempreture | String | - | Battery temperature status:<br>"BATTERY_TEMPRETURE_NORMAL" - Normal battery temperature<br>"BATTERY_TEMPRETURE_OVERHEAT" - Battery temperature too high<br>"BATTERY_TEMPRETURE_UNDERHEAT" - Battery temperature too low |

- Example:
  ```json
  {
    "state": "BATTERY_STATE_CHARGING",
    "charger_connected": true,
    "is_switch_on": true,
    "tempreture": "BATTERY_TEMPRETURE_NORMAL"
  }
  ```
  This indicates the battery is charging, the adapter is connected, the power switch is on, and the battery temperature is normal.
- Notes:
  - When `charger_connected` is `true` but `state` is `BATTERY_STATE_DISCHARGE`, it means the adapter is connected but not charging
  - Abnormal battery temperature will affect charging status; when `tempreture` is not `BATTERY_TEMPRETURE_NORMAL`, it may affect the robot's operational status

## Task Status

- **ID**: 107
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | mission | String | - | Main task type:<br>"MISSION_IDLE" - Idle<br>"MISSION_RECHARGE" - Recharging<br>"MISSION_GLOBAL_CLEAN" - Global operation<br>"MISSION_BUILD_MAP" - Mapping<br>"MISSION_BUILD_MAP_AND_CLEAN" - Mapping and operation<br>"MISSION_TEMPORARY_CLEAN" - Temporary operation<br>"MISSION_BACK_TO_STARTING_POINT" - Return to starting point<br>"MISSION_REMOTE_CONTROL_CLEAN" - Remote control operation<br>"MISSION_SCHEDULE_GLOBAL_CLEAN" - Scheduled global operation<br>"MISSION_SCHEDULE_BUILD_MAP_AND_CLEAN" - Scheduled mapping and operation<br>"MISSION_SELECT_REGION_CLEAN" - Selected area operation<br>"MISSION_CREATE_CUSTOM_PASSAGE" - Create custom passage<br>"MISSION_BACKUP_MAP" - Backup map<br>"MISSION_RELOCATE_BASE_STATION" - Relocate base station<br>"MISSION_USER_AUTO_CALIBRATION" - User triggered auto calibration<br>"MISSION_RESTORE_BACKUP_MAP" - Restore backup map<br>"MISSION_SCHEDULE_SELECT_REGION_CLEAN" - Scheduled selected area operation<br>"MISSION_DRAW_REGION_CLEAN" - Drawn area operation<br>"MISSION_EDGE_TRIM_CLEAN" - Edge trimming operation<br>"MISSION_UPDATE_BACKUP_MAP" - Update backup map<br>"MISSION_USER_TRIGGERED_SELF_CALIBRATION" - User triggered self-calibration (using base station) |
  | sub_mission | String | - | Sub-task type:<br>"SUB_MISSION_IDLE" - Idle<br>"SUB_MISSION_RELOCATION" - Relocation<br>"SUB_MISSION_RETURN_TO_BASE" - Return to base<br>"SUB_MISSION_OUT_OF_STATION" - Exiting base station<br>"SUB_MISSION_REMOTE_CONTROL" - Remote control<br>"SUB_MISSION_SAVING_MAP" - Saving map<br>"SUB_MISSION_SETTING_BLADE_HEIGHT" - Adjusting blade height<br>"SUB_MISSION_DEFOGGING" - Defogging<br>"SUB_MISSION_WAIT_FOR_DAYLIGHT" - Waiting for daylight<br>"SUB_MISSION_COOLING_DOWN_MOTOR" - Cooling down motor<br>"SUB_MISSION_FLEXIBLE_STATION_WAIT" - Waiting in base station |
  | state | String | - | Task state:<br>"MISSION_STATE_IDLE" - Idle<br>"MISSION_STATE_RUNNING" - Running<br>"MISSION_STATE_PAUSE" - Paused<br>"MISSION_STATE_ABORT" - Aborted<br>"MISSION_STATE_COMPLETE" - Completed |
  | power_mode | String | - | Power consumption level:<br>"POWER_MODE_RUNNING" - Operating<br>"POWER_MODE_STANDBY" - Standby power consumption<br>"POWER_MODE_HIBERNATE" - Sleep power consumption |
  | has_error | Boolean | - | Whether the robot currently has a fault |
  | is_saving_data | Boolean | - | Whether the robot is saving data |
  | back_to_station_reason | String | - | Reason for returning to base station:<br>"BACK_TO_STATION_REASON_NONE" - None<br>"BACK_TO_STATION_REASON_LOW_BATTERY" - Low battery<br>"BACK_TO_STATION_REASON_RAINING" - Raining<br>"BACK_TO_STATION_REASON_MOW_MOTOR_OVERHEAT" - Mowing motor overheating<br>"BACK_TO_STATION_REASON_WHEEL_OVERHEAT" - Drive wheel motor overheating<br>"BACK_TO_STATION_REASON_NIGHT_TIME" - Darkness |
  | is_robot_navi_located | Boolean | - | Whether the robot currently has accurate navigation location information |
  | is_upgrading | Boolean | - | Whether the robot is upgrading firmware |
  | is_data_conversion_in_progress | Boolean | - | Whether the robot is performing data compatibility conversion |

- Example:
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
  This indicates the robot is currently performing a global operation task, is in running state, in normal power consumption mode, has no faults, is not saving data, has accurate navigation location information, is not upgrading firmware, and is not performing data compatibility conversion.
- Notes:
  - The `back_to_station_reason` field is only meaningful when the sub-task is `SUB_MISSION_FLEXIBLE_STATION_WAIT` or `SUB_MISSION_RETURN_TO_BASE`
  - Even if the task status is `MISSION_STATE_RUNNING`, when `has_error` is `true`, it indicates the robot currently has a fault but is still running
  - When `is_saving_data` is `true`, the robot may not respond to operation commands

## Operation Statistics

- **ID**: 124
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | duration | Integer | Seconds | Total mowing duration |
  | clean_area | Integer | 0.1 sq.m | Total mowed area (e.g., 1500 represents 150 square meters) |
  | clean_times | Integer | Times | Total number of mowing operations |

- Example:
  ```json
  {
    "duration": 7200,
    "clean_area": 2000,
    "clean_times": 5
  }
  ```
  This indicates a total of 2 hours of mowing, covering an area of 200 square meters, and completing 5 mowing tasks.

## Current Operation Data

- **ID**: 113
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | type | String | - | Area type:<br>"MAP_AREA_TYPE_NONE" - No type, indicates no previous operations<br>"MAP_AREA_TYPE_BUILD_MAP" - Mapping area<br>"MAP_AREA_TYPE_CLEANING" - (Global) operation area<br>"MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING" - Mapping and operation area<br>"MAP_AREA_TYPE_SELECT_REGION_CLEANING" - Selected area operation<br>"MAP_AREA_TYPE_DRAW_REGION_CLEANING" - Drawn area operation<br>"MAP_AREA_TYPE_EDGE_TRIM_CLEANING" - Edge trimming operation area |
  | total_area | Integer | 0.1 sq.m | Total area, meaning differs by type:<br>- type="MAP_AREA_TYPE_BUILD_MAP": Mapping area<br>- type="MAP_AREA_TYPE_CLEANING": Total map area (total operable area)<br>- type="MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING": Total map (explored area) area<br>- type="MAP_AREA_TYPE_SELECT_REGION_CLEANING": Total selected area<br>- type="MAP_AREA_TYPE_DRAW_REGION_CLEANING" or "MAP_AREA_TYPE_EDGE_TRIM_CLEANING": Invalid |
  | clean_area | Integer | 0.1 sq.m | Mowed area, only valid in the following cases:<br>- type="MAP_AREA_TYPE_CLEANING" or "MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING" or "MAP_AREA_TYPE_SELECT_REGION_CLEANING": Area completed (including historical operations)<br>- type="MAP_AREA_TYPE_DRAW_REGION_CLEANING": Area completed |
  | is_completed | Boolean | - | Whether the operation is completed (used to correct progress calculation when operated area is less than total area)<br>Only valid when type="MAP_AREA_TYPE_CLEANING" or "MAP_AREA_TYPE_BUILD_MAP_AND_CLEANING" or "MAP_AREA_TYPE_SELECT_REGION_CLEANING" |
  | work_duration | Integer | Seconds | Operation or mapping duration, referring to the total coverage time for this session |

- Example:
  ```json
  {
    "type": "MAP_AREA_TYPE_CLEANING",
    "total_area": 3000,
    "clean_area": 1500,
    "is_completed": false,
    "work_duration": 1800
  }
  ```
  This indicates a global operation, total area of 300 square meters, 150 square meters already mowed, operation not yet completed, and has been working for 30 minutes.

## Base Station Usage Time

- **ID**: 125
- Data Direction: Robot↔HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | int_value | Integer | Minutes | Base station usage time |

- Example:
  ```json
  {
    "int_value": 120
  }
  ```
  This indicates the base station has been used for 120 minutes.
- Notes:
  - The recommended cleaning cycle for the base station is 30 days, which is 30*24*60=43200 minutes.
  - When the robot receives a value of 0, it will reset the internal record of base station usage time to 0.

## Mowing Blade Disk Usage Time

- **ID**: 126
- Data Direction: Robot↔HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | int_value | Integer | Minutes | Blade disk usage time |

- Example:
  ```json
  {
    "int_value": 120
  }
  ```
  This indicates the blade disk has been used for 120 minutes.
- Notes:
  - The recommended cleaning cycle for the blade disk is 240 minutes.
  - When the robot receives a value of 0, it will reset the internal record of blade disk usage time to 0.

## Upcoming Schedule

- **ID**: 138
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | exist | Boolean | - | Whether there is an upcoming schedule |
  | item_id | Integer | - | ID of the next scheduled operation |
  | shift_id | Integer | - | Time slot ID of the next scheduled operation |
  | start_time | Object | - | Start time of the next scheduled operation |
  | start_time.hour | Integer | Hour | Hour of the start time (24-hour format) |
  | start_time.minute | Integer | Minute | Minute of the start time |
  | end_time | Object | - | End time of the next scheduled operation |
  | end_time.hour | Integer | Hour | Hour of the end time (24-hour format) |
  | end_time.minute | Integer | Minute | Minute of the end time |

- Example:
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
  This indicates there is an upcoming scheduled operation, with schedule ID 1, time slot ID 0, starting at 14:30 and ending at 16:00.
- Notes:
  - When `exist` is `false`, other fields may be empty or default values
  - `item_id` corresponds to the schedule ID in `ScheduleList`
  - `shift_id` indicates the specific time slot index within that schedule (used when a schedule contains multiple time slots)

## Global Operation Parameter Settings

- **ID**: 155
- Data Direction: Robot↔HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | mow_height | Object | - | Mowing height setting |
  | mow_height.value | Integer | mm | Mowing height value |
  | mow_speed | Object | - | Mowing speed setting |
  | mow_speed.speed_type | String | - | Mowing speed type:<br>"MOW_SPEED_TYPE_LOW" - Low speed<br>"MOW_SPEED_TYPE_MEDIUM" - Medium speed (default)<br>"MOW_SPEED_TYPE_ADAPTIVE_HIGH" - Adaptive high speed |
  | edge_cutting_distance | Object | - | Edge cutting distance setting |
  | edge_cutting_distance.value | Integer | mm | Edge cutting distance value |
  | main_direction_angle_config | Object | - | Main direction angle configuration |
  | main_direction_angle_config.mode | String | - | Main direction configuration mode:<br>"MAIN_DIRECTION_MODE_SINGLE" - Single main direction<br>"MAIN_DIRECTION_MODE_MULTIPLE" - Multiple main directions<br>"MAIN_DIRECTION_MODE_AUTO_ROTATE" - Auto-rotate main direction |
  | main_direction_angle_config.single_mode_config | Object | - | Single main direction mode configuration (valid when mode is MAIN_DIRECTION_MODE_SINGLE) |
  | main_direction_angle_config.single_mode_config.angle | Integer | Degrees | Main direction angle |
  | main_direction_angle_config.multiple_mode_config | Object | - | Multiple main direction mode configuration (valid when mode is MAIN_DIRECTION_MODE_MULTIPLE) |
  | main_direction_angle_config.multiple_mode_config.angles | Array | Degrees | List of multiple main direction angles |
  | main_direction_angle_config.auto_rotate_mode_config | Object | - | Auto-rotate main direction configuration (valid when mode is MAIN_DIRECTION_MODE_AUTO_ROTATE) |
  | main_direction_angle_config.auto_rotate_mode_config.angle_interval | Integer | Degrees | Auto-rotate angle interval |
  | main_direction_angle_config.current_angle | Integer | Degrees | Current main direction angle (used only when uploaded by robot) |
  | mow_spacing | Object | - | Mowing spacing setting |
  | mow_spacing.value | Integer | mm | Mowing spacing value (modification will reset operation progress) |
  | blade_disk_speed | Object | - | Blade disk speed setting |
  | blade_disk_speed.speed_type | String | - | Blade disk speed type:<br>"BLADE_DISK_SPEED_TYPE_LOW" - Low speed<br>"BLADE_DISK_SPEED_TYPE_MEDIUM" - Medium speed<br>"BLADE_DISK_SPEED_TYPE_HIGH" - High speed (default) |
  | current_mow_spacing | Integer | mm | Current mowing spacing (used only when uploaded by robot) |

- Example:
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
  This indicates the mowing height is set to 40mm, mowing speed is medium, edge cutting distance is 10mm, using single main direction mode (angle 0 degrees), mowing spacing is 100mm, and blade disk speed is high.
- Notes:
  - This protocol can be sent from HA to the robot to modify the corresponding parameter settings, and can include just one field, e.g., sending only the `mow_height` field will only modify the mowing height.
  - Modifying mowing spacing or main direction angle configuration will reset operation progress
  - The `current_mow_spacing` and `main_direction_angle_config.current_angle` fields are only included when the protocol is reported by the robot

## Map Status

- **ID**: 117
- Data Direction: Robot→HA
- Field Description:

  | Field Name | Type | Unit | Description |
  |-------|------|------|------|
  | is_map_detected | Boolean | - | Whether a map is detected (depends on whether a base station ID has been detected) |
  | map_id | Integer | - | Current map ID |
  | map_state | String | - | Map state:<br>"MAP_STATE_EMPTY" - Map is completely empty<br>"MAP_STATE_INCOMPLETE" - Mapping has started but is incomplete<br>"MAP_STATE_COMPLETE" - Map is complete |
  | map_number | Integer | - | Number of maps |
  | is_backing_up_map | Boolean | - | Whether a map backup/restore is in progress |
  | backup_map_id | Integer | - | ID of the map being backed up/restored (only valid when map backup is in progress) |
  | main_direction_angle | Integer | Degrees | Main direction angle of the current map (only valid when a map exists) |
  | is_spot_mode_map | Boolean | - | Whether the current map is a Spot mode map (only valid when a map exists) |
  | spot_mode_map_number | Integer | - | Number of saved Spot mode maps |
  | is_able_to_run_build_map | Boolean | - | Whether the map can be mapped |
  | backup_map_backup_id | Integer | - | Backup ID of the backup/restore operation (used to distinguish multiple different backup maps) |

- Example:
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
  This indicates a map is detected, current map ID is 1, the map is complete, there are 2 maps in total, no backup operation is in progress, main direction angle is 0 degrees, it's not a Spot mode map, there are no Spot mode maps, mapping operation not possible, and backup ID is 0.
- Notes:
  - When `is_map_detected` is `false`, it indicates the robot has not detected a map and may need base station pairing
  - Map state (`map_state`) directly affects the types of operations the robot can perform
  - Even if the map state is `MAP_STATE_COMPLETE`, if `is_able_to_run_build_map` is `true`, mapping can still be started (e.g., in cases with virtual passages)
  - The `backup_map_id` field is only meaningful when `is_backing_up_map` is `true`