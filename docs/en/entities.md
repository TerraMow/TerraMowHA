# TerraMow Entities

This page describes the entities that the integration adds to Home Assistant and
when they show an unknown or unavailable state. Entity names come from the
integration's translations; this page uses the English names.

All sensors and binary sensors are diagnostic entities, so Home Assistant lists
them in the **Diagnostic** section of the device page. The selects and numbers
are configuration entities.

## Lawn mower

The lawn mower entity can start, pause, and dock the robot. Its activity
(`docked`, `mowing`, `paused`, `returning`, or `error`) follows the mission state
reported by the robot. A current fault sets it to `error` (see
[Events and faults](#events-and-faults)). It also shows `error` when the
connection to the robot fails or is lost unexpectedly, until the connection is
restored. The `back_to_station_reason` attribute explains why the robot is
returning to the station, and `active_faults` lists the current faults.

### Command confirmation

Start, pause, dock, and zone mowing commands wait up to five seconds for a
matching robot reply. A rejected command raises a Home Assistant error. A timeout
means the result is unconfirmed, and the integration does not retry
automatically. Firmware that does not send command replies also reports an
unconfirmed result. Acceptance of a command does not imply that mowing has begun:
the activity still follows the robot's mission state.

Only one command is confirmed at a time, and commands must be at least one second
apart. Otherwise Home Assistant reports an error.

### Zone mowing

**Zone Select** lists **All zones** and the zones of the current map, or **No
zones available** until the robot reports a map with zones. Choosing a zone starts
mowing that zone and is confirmed like the commands above. Choosing **All zones**
only changes the selection and sends nothing to the robot.

## Events and faults

**Last Event** shows the code of the latest event reported by the robot. Its
attributes contain the event time and a description. **Active Fault** shows `0`
when the robot reports no faults and the lowest fault code when faults are
present; its attributes contain all active faults. Both sensors are unknown until
the robot has sent feedback.

A current fault sets the mower activity to `error`; clearing the fault restores
the reported mission state. Historical events do not set the current fault state.

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
map in square meters. **Operation Mode** shows the type of the current job
(global, select region, draw region, or move to target point); for select-region
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

## Maintenance and schedule

**Remaining Blade Time** and **Remaining Base Station Time** count down in minutes
to the recommended maintenance cycle. Their attributes show the time used, the
recommended cycle, and whether maintenance is due (`needs_maintenance`). **Next
Scheduled Start** shows the start time (HH:MM) of the next scheduled mowing and is
unknown when there is no schedule.

## Mowing settings

**Mow Height**, **Mow Speed**, and **Main Direction Status** show the current
mowing settings reported by the robot. You can change them with these entities:

- **Mowing Height Setting**, **Edge Cutting Distance**, and **Mowing Spacing
  Setting** (millimeters)
- **Mow Speed Setting**: Low Speed, Medium Speed, and Adaptive High Speed, plus
  Auto Speed when the firmware supports it
- **Blade Speed Setting**: Low Speed, Medium Speed, and High Speed
- **Main Direction Mode**: Single Direction, Multiple Directions, or Auto Rotate
  Direction. The angle entities (**Single Direction Angle**, **First Direction
  Angle**, **Second Direction Angle**, and **Auto Rotate Angle Interval**, in
  degrees) are available only in the matching mode.

Settings are sent to the robot without waiting for a reply, so Home Assistant does
not raise an error if the robot does not apply one.

## Other diagnostics

**Battery** shows the battery level in percent. Its attributes include `state`,
`temperature`, `charger_connected`, and `is_switch_on`. **Charging State** is on
when the robot reports its charger as connected. **Pose** reports the robot's
position and heading: its state is the yaw, and the attributes hold `x`, `y`,
`yaw`, `timestamp_ms`, and `frame`. **Total Mowing Time** shows the total mowing
time reported by the robot. **Version Compatibility** compares the robot's
firmware with this integration, and its `message` attribute explains the result.
