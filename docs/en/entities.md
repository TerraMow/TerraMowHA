# TerraMow Entities

This page describes the entities that the integration adds to Home Assistant and
when they show an unknown or unavailable state. Entity names come from the
integration's translations; this page uses the English names.

Sensors and the existing status binary sensors are diagnostic entities. The
security alarm binary sensors appear in the main device section, so they are
easy to find for automations. The selects and numbers are configuration entities.

## Lawn mower

The lawn mower entity can start, pause, and dock the robot. Its activity
(`docked`, `mowing`, `paused`, `returning`, or `error`) follows the mission state
reported by the robot. A current fault sets it to `error` (see
[Events and faults](#events-and-faults)). It also shows `error` when the
connection to the robot fails or is lost unexpectedly, until the connection is
restored. The `back_to_station_reason` attribute explains why the robot is
returning to the station, and `active_faults` lists the current faults.

### Command confirmation

Start, pause, dock, zone mowing, and edge cutting commands wait up to five seconds for a
matching robot reply. A rejected command raises a Home Assistant error. A timeout
means the result is unconfirmed, and the integration does not retry
automatically. Firmware that does not send command replies also reports an
unconfirmed result. Acceptance of a command does not imply that mowing has begun:
the activity still follows the robot's mission state.

Only one command is confirmed at a time, and commands must be at least one second
apart. Otherwise Home Assistant reports an error.

### Zone mowing

**Zone Select** lists **All zones**, **Edge mowing**, and the zones of the current
map. If the reported map has no zones, **Edge mowing** remains available beside
**No zones available**; until a map is reported, only **No zones available** is
shown. Choosing a zone starts mowing that zone; choosing **Edge mowing** requests
an edge cutting job. Both commands wait for the robot's confirmation. Edge cutting
requires firmware control version 8 or later. Choosing **All zones** only changes
the selection and sends nothing to the robot. Use the lawn mower's Start command
to start global mowing.

## Events and faults

**Last Event** shows the code of the latest event reported by the robot. Its
attributes contain the event time and a description. **Active Fault** shows `0`
when the robot reports no faults and the lowest fault code when faults are
present; its attributes contain all active faults. Both sensors are unknown until
the robot has sent feedback.

A current fault sets the mower activity to `error`; clearing the fault restores
the reported mission state. Historical events do not set the current fault state.

**Robot lifted alert** turns on when the robot's current fault list contains code `201`
or `202`. **Anti-Theft Boundary Alarm** turns on for code `1409`. Each turns off
when its code is absent from the next complete fault list. A single fault
notification or a historical event cannot turn either alarm on. Both alarms are
unknown until a fault list arrives, unavailable while disconnected, and unknown
again after reconnecting until a new list arrives.

## Mission status

**Mission**, **Sub-mission**, and **Mission State** show the current mission,
sub-mission, and mission state reported by the robot. Their states use lowercase
keys such as `mission_global_clean` and `sub_mission_wait_for_rain_to_stop` so
Home Assistant can translate them; use these keys in automations. The
`protocol_value` attribute keeps the original uppercase robot value. A value that
this version of the integration does not recognize is shown as unknown.

These sensors are read-only and do not send commands to the mower.

## Current session

**Current Session Area** and **Current Session Time** show the mowed area and the
mowing time of the session that the robot last reported. Current Session Area is
unknown while the mowed area is zero.

**Current Session Progress** compares the mowed area with the total area. It stays
at 98% or below until the robot reports the work as completed, which is the only
time it shows 100%. While the robot waits for daylight it shows 0%.

Instead of a number, the sensor is unknown when progress does not apply:

- no complete map has been detected, the map can still be built, or the map
  status has not been reported yet
- the robot is in Spot mode
- the robot is mowing a drawn region or trimming edges
- the robot is mapping and mowing at the same time
- the robot has not reported any work yet

The sensor keeps showing the session that the robot last reported until a new
session starts. It is unavailable while Home Assistant is not connected to the
robot.

## Map

**Map Status** shows whether the robot has no map, an incomplete map, or a
complete map. Its attributes include the map ID, the number of maps, the backup
state, and the main direction angle. **Map Area** shows the area of the current
map in square meters. **Mowing mode** shows the type of the current job
(auto mowing, zone mowing, MowBox mowing, or move to target point); for zone
jobs its attributes list the selected regions. These three sensors are unknown
until the robot reports the matching information.

Three binary sensors expose map flags: **Map Detected** (the robot has recognized
its map), **Map Buildable** (the robot can currently build a map), and **Map
Backing Up** (a map backup or restore is in progress). They are unavailable while
Home Assistant is not connected to the robot and unknown until the robot has
reported its map status.

The **Map** camera draws the lawn map with its zones and obstacles, the mowing
path, the station, and the robot's position when it is known. See
[Map and Path Capabilities](developers/map_path.md) for the data behind it.
The **Clean Map** camera shows the same map layers without the surrounding
information panel or map labels, for compact dashboard cards.

## Maintenance and schedule

**Remaining Blade Time** and **Remaining Base Station Time** count down in minutes
to the recommended maintenance cycle. Their attributes show the time used, the
recommended cycle, and whether maintenance is due (`needs_maintenance`). **Next
Scheduled Start** shows the start time (HH:MM) of the next scheduled mowing and is
unknown when there is no schedule.

**Schedule** is the master switch for scheduled mowing. Turning it off pauses
all schedules without deleting them; turning it on enables them again. The
switch reflects the robot's reported setting, so it is unknown until the
setting is read and unavailable while disconnected or on firmware with schedule
protocol version below 2. A change waits for the robot's reply and reads the
setting again. This switch does not dock a mowing job already in progress.

Seven weekday switches, Monday through Sunday, control which days may run
time-slot schedules. Turning a weekday off disables schedules for that day;
turning it on allows them again. The master switch does not erase these choices.
They appear in the device's Configuration section. The weekday switches become
available after a valid schedule read and are
unavailable in frequency schedule mode, where this setting does not apply.

## Mowing settings

**Cutting height**, **Moving speed**, and **Main Direction Status** show the current
mowing settings reported by the robot. You can change them with these entities:

- **Mowing Height Setting**, **Edge Cutting Distance**, and **Mowing Spacing
  Setting** (millimeters)
- **Moving speed**: Fine, Default, and Adaptive, plus
  Auto Speed when the firmware supports it
- **Blade Speed Setting**: Low Speed, Medium Speed, and High Speed
- **Main Direction Mode**: Single, Dual, or Auto-rotating. The angle entities
  (**Single Direction Angle**, **First Direction
  Angle**, **Second Direction Angle**, and **Auto Rotate Angle Interval**, in
  degrees) are available only in the matching mode.

Settings are sent to the robot without waiting for a reply, so Home Assistant does
not raise an error if the robot does not apply one.

## Other diagnostics

**Battery** shows the battery level in percent. Its attributes include `state`,
`temperature`, `charger_connected`, and `is_switch_on`. **Charging State** is on
when the robot reports its charger as connected. **Battery Temperature State**
reports Normal, Overheated, or Too Cold from the robot's battery status; the
robot does not provide a temperature in degrees. It is unavailable while
disconnected and unknown until a fresh battery report arrives. **Pose** reports the robot's
position and heading: its state is the yaw, and the attributes hold `x`, `y`,
`yaw`, `timestamp_ms`, and `frame`. **Total Mowing Time** shows the total mowing
time reported by the robot. **Version Compatibility** compares the robot's
firmware with this integration, and its `message` attribute explains the result.
