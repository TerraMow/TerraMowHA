# Global schedule protocol and calendar

This integration exposes one calendar per mower for global **time-slot** mowing
schedules (`SCHEDULE_TYPE_GLOBAL_V2`). The existing global switch, seven weekday
switches and next-schedule sensor remain available. Zone, edge-trim, legacy
`SCHEDULE_TYPE_GLOBAL`, frequency schedules and weather policies are outside this
calendar's scope. Other schedule types returned by GET are preserved and never
modified by calendar operations. The calendar is unavailable in frequency mode;
it does not change modes automatically.

## Firmware capabilities

After every successful MQTT connection, the integration subscribes to
`data_point/122/robot` and sends a DP122 GET directly. Schedule availability does
not depend on DP127 or `module.schedule`. The calendar becomes available only
after receiving a valid schedule list in time-slot mode (an empty list is valid).
Frequency mode and malformed data do not enable the calendar. Calendar polling
runs every 300 seconds (five minutes) and can retry an initially failed GET
without requiring a reconnect. Connection reads, calendar event requests and
write verification GETs run immediately, independently of this interval.

The protocol defines these firmware capabilities for reference; the integration
does not use the reported version as a gate:

| Schedule module version | Relevant capability |
| --- | --- |
| 0–1 | Legacy formats outside this calendar's scope |
| 2 | GLOBAL_V2 weekly schedules, global disable, disabled weekdays |
| 3 | Adds `basic_config.run_once` |
| 4+ | Adds `repeat_until_end_time` |

Valid GET data establishes readable state, not proof of write support. Every
write must receive a matching successful ACK and pass a verification GET.
Unused optional fields (`run_once`, `repeat_until_end_time`) are omitted from
new weekly schedules; existing optional fields are preserved when editing.
Non-default optional values are sent when requested and must be verified by
readback, so firmware silently ignoring them is reported as a failure.
Firmware support for each operation is determined by its ACK and readback.
An unanswered or rejected request must not be treated as a confirmed save.

## Transport and correlation

Connect to the mower's MQTT broker on TCP 1883 using its configured credentials.
Subscribe to `data_point/122/robot` **before** sending commands to
`data_point/122/app`. Both payloads are protobuf JSON, using the snake_case field
names below. DP119 is not the schedule reply topic.

Use a different positive signed-int32 `seq` (1–2147483647) for every request,
including verification GETs. Match both `seq` and `cmd_type`. Ignore retained
replies and replies for other requests. MQTT publish/PUBACK only confirms
transport; `ScheduleAck` confirms device processing. Neither replaces readback.

Protobuf may omit zero-valued scalars. An omitted ACK `cmd_type` means GET; an
omitted `code` means 0 (success). An omitted boolean is false; omitted repeated
fields such as `items` and `disabled_week_days` are empty. A successful GET must
still contain a `schedule_list` object. Malformed data must not be interpreted as
an empty successful result. The integration normalizes omitted defaults and
weekday ordering before comparing schedule content.

| Operation | `cmd_type` | Numeric value | Parameter |
| --- | --- | --- | --- |
| Read | `SCHEDULE_CMD_TYPE_GET` | 0 | none |
| Create | `SCHEDULE_CMD_TYPE_ADD` | 1 | `add_param` |
| Delete | `SCHEDULE_CMD_TYPE_DELETE` | 2 | `delete_param.id` |
| Update | `SCHEDULE_CMD_TYPE_MODIFY` | 3 | `modify_param` |

`UPDATE` and `SAVE` are not command names. ADD and MODIFY parameters contain a
`schedule_type` and its matching `global_schedule_v2` object, not a GET
`schedule_list` wrapper. MODIFY sends the complete replacement parameter, plus
its existing ID. DELETE sends only the ID.

## Editable fields

| Path within `global_schedule_v2` | Type and constraints |
| --- | --- |
| `basic_config.week_days` | Nonempty weekday list: `WEEK_DAY_MONDAY` … `WEEK_DAY_SUNDAY` (ISO values 1…7). Treat as a set. |
| `basic_config.start_time.hour` | Integer 0…23 |
| `basic_config.start_time.minute` | Integer 0…59 |
| `basic_config.end_time.hour` | Integer 0…23 |
| `basic_config.end_time.minute` | Integer 0…59 |
| `basic_config.disabled` | Boolean; disables this schedule |
| `basic_config.run_once` | Boolean, schedule v3+; one execution. A disabled item is not proof of completion. Omit on v2. |
| `repeat_until_end_time` | Boolean, schedule v4+; repeats mowing within the window. Omit on earlier firmware. |

The calendar requires end after start on the same local date, at whole-minute
precision. Single-day all-day events map to 00:00–23:59; overnight and zero-length
timed events are rejected. This is the
calendar's supported subset; it does not claim additional firmware capacity or
validation guarantees. Firmware may reject conflicts, capacity limits or other
business constraints with a nonzero code.

Times are local wall-clock times without dates or a timezone in this protocol.
**Set Home Assistant and the mower to the same timezone.** Weekly occurrences
keep their local clock time across DST changes. The calendar skips nonexistent
spring-forward windows and projects the first occurrence of an ambiguous
fall-back window; actual firmware DST execution still needs target validation.
It rejects creation/editing targeting the second repeated clock-hour occurrence.

## Complete request/reply examples

Publish all requests below on `data_point/122/app`; read all ACKs on
`data_point/122/robot`. Example IDs and sequences are illustrative. Obtain the
actual assigned ID by the verification procedure below.

### Read

Request:

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_GET","seq":1001}
```

Successful empty list (the sunrise/sunset fields may also be present):

```json
{
  "cmd_type":"SCHEDULE_CMD_TYPE_GET",
  "seq":1001,
  "code":0,
  "schedule_list":{
    "items":[],
    "global_disabled":false,
    "disabled_week_days":[],
    "schedule_mode":"SCHEDULE_MODE_TIME_SLOT"
  }
}
```

### Create

Schedule every Wednesday and Friday, 09:00–10:00 (v4+ example):

```json
{
  "cmd_type":"SCHEDULE_CMD_TYPE_ADD",
  "seq":1002,
  "add_param":{
    "schedule_type":"SCHEDULE_TYPE_GLOBAL_V2",
    "global_schedule_v2":{
      "basic_config":{
        "week_days":["WEEK_DAY_WEDNESDAY","WEEK_DAY_FRIDAY"],
        "start_time":{"hour":9,"minute":0},
        "end_time":{"hour":10,"minute":0},
        "disabled":false,
        "run_once":false
      },
      "repeat_until_end_time":false
    }
  }
}
```

Successful processing ACK, **without an assigned schedule ID**:

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_ADD","seq":1002,"code":0}
```

Verification request:

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_GET","seq":1003}
```

Example readback identifying new ID 7:

```json
{
  "cmd_type":"SCHEDULE_CMD_TYPE_GET",
  "seq":1003,
  "code":0,
  "schedule_list":{
    "items":[{
      "id":7,
      "schedule_type":"SCHEDULE_TYPE_GLOBAL_V2",
      "global_schedule_v2":{
        "basic_config":{
          "week_days":["WEEK_DAY_WEDNESDAY","WEEK_DAY_FRIDAY"],
          "start_time":{"hour":9,"minute":0},
          "end_time":{"hour":10,"minute":0},
          "disabled":false,
          "run_once":false
        },
        "repeat_until_end_time":false
      }
    }],
    "global_disabled":false,
    "disabled_week_days":[],
    "schedule_mode":"SCHEDULE_MODE_TIME_SLOT"
  }
}
```

### Update

Change ID 7 to end at 11:00, preserving the remaining settings:

```json
{
  "cmd_type":"SCHEDULE_CMD_TYPE_MODIFY",
  "seq":1004,
  "modify_param":{
    "id":7,
    "schedule_type":"SCHEDULE_TYPE_GLOBAL_V2",
    "global_schedule_v2":{
      "basic_config":{
        "week_days":["WEEK_DAY_WEDNESDAY","WEEK_DAY_FRIDAY"],
        "start_time":{"hour":9,"minute":0},
        "end_time":{"hour":11,"minute":0},
        "disabled":false,
        "run_once":false
      },
      "repeat_until_end_time":false
    }
  }
}
```

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_MODIFY","seq":1004,"code":0}
```

Then GET with a new sequence and check that **ID 7** has exactly the intended
weekday/time/boolean settings. Keep unknown fields from the pre-edit parameter;
the integration also preserves disabled and repeat-until-end settings.

### Delete

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_DELETE","seq":1006,"delete_param":{"id":7}}
```

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_DELETE","seq":1006,"code":0}
```

Then GET with a new sequence and require that ID 7 is absent.

### Failure

```json
{"cmd_type":"SCHEDULE_CMD_TYPE_MODIFY","seq":1004,"code":-1}
```

Any nonzero code is a failure; do not assign unsupported detailed meanings to
`-1`. A missing, malformed or mismatched reply cannot confirm a saved edit.
Even a matching successful ACK requires a verification GET showing the intended
state. This calendar sends only known, validated commands and requires readback
for every edit.

## Transaction and ID rules

For every edit, the integration holds the same lock used by the schedule
switches and performs:

1. A fresh GET baseline, retaining all item IDs and types.
2. ADD/MODIFY/DELETE with a new sequence; wait up to five seconds for its matching
   successful processing ACK.
3. GET with another sequence; wait up to five seconds for its matching success.
   Publish the valid snapshot and notify HA calendar listeners when it changes.
4. ADD: require exactly one new ID and matching GLOBAL_V2 content. MODIFY:
   require the same ID/type and matching content. DELETE: require absence of the
   target ID.
5. Report the edit as successful only if step 4 passes. A valid readback that
   differs from the requested edit is still displayed as the actual device state,
   while the edit reports a failure. This also applies to ambiguous ADD results.

There is no device transaction token, idempotency key, assigned ID in ADD ACK,
revision or compare-and-swap. The integration rejects ambiguous concurrent ADD
results, including multiple new IDs, instead of guessing. A simultaneous remote
edit can still race with readback; clients should avoid concurrent edits.
A dropped ACK/readback can follow a successful device write: report failure and
retain the last successfully read snapshot. Read/edit failures do not clear the
calendar cache or by themselves mark it unavailable. A retained snapshot may be
stale; it does not confirm that a failed or timed-out edit was applied. Refresh
before retrying. Malformed item lists cannot replace the last valid snapshot.
Without an initial valid snapshot, or after a disconnect/reset, the calendar
remains unavailable until fresh valid data is read. Never blindly retry ADD or
attempt an automatic destructive rollback. No device schema or new error codes
are invented by this integration.

IDs are signed-int32 device identifiers (the calendar accepts nonnegative IDs,
including 0), not list indexes. HA series UID is `global-<id>`; it is scoped to
that mower's calendar, whose unique identity uses the stable device ID.
Weekly entries share the UID and RRULE, but intentionally omit `recurrence_id`:
each displayed entry represents the editable device rule. The HA frontend's
occurrence dialog has no whole-series option. Editing or deleting an entry
therefore affects the entire device schedule, including every configured
weekday and future occurrence.
Only whole-series update/delete is supported: leave `recurrence_id` and
`recurrence_range` unset or empty (the frontend sends empty values).
Explicit individual-occurrence and this-and-future requests fail without
writing to the device. After upgrading, refresh the calendar to discard old
entries containing occurrence IDs.

## Calendar editing contract

Use the HA calendar UI or standard calendar WebSocket APIs. Titles, locations
and descriptions are saved locally in HA, linked to the stable mower identity
and integer device item ID. These fields are **never sent in DP122**. Events do
not have generated descriptions. The native HA editor remains unchanged; Python
validation reports unsupported choices when saving.

| HA field | Device mapping / supported behavior |
| --- | --- |
| Timed start / end | Local whole-minute `start_time` / `end_time` on one day, plus weekdays; dates are not sent |
| Single-day all-day | Device 00:00–23:59; select the same start/end date in the UI; the API end date is exclusive (e.g. Nov 18 → Nov 19) |
| Multi-day all-day | Rejected; choose exactly one local calendar day |
| Does not repeat | `run_once=true`, with one weekday |
| Daily, interval 1 | All seven weekdays, `run_once=false` |
| Weekly, interval 1, selected weekdays | `run_once=false` and `week_days` |
| Monthly / yearly, or interval other than 1 | Rejected |
| Recurrence ends: never | Unbounded daily/weekly rule; no device end-date field |
| Recurrence ends: on a date / after a count | `UNTIL` / `COUNT`, rejected |
| Title / location / description | HA local metadata, not device configuration |

All-day means a configured execution window, not guaranteed continuous mowing.
The final minute is intentionally excluded from the device window. HA still
shows one full calendar day. This integration cannot automatically change the
native editor's end date when the user chooses a start date. In that editor,
both dates should be the same for a single-day event. The frontend adds one day
to the displayed end date when submitting, and subtracts one day when opening
an all-day event. Selecting Nov 18 through Nov 19 in the UI means two days
(API Nov 18 through Nov 20) and is rejected.

For example, daily with interval 3 means every three days, not three executions;
with no recurrence end, it continues indefinitely. This is `FREQ=DAILY;INTERVAL=3`
and is rejected. Device frequency schedules are a separate mode outside this
calendar's scope. `repeat_until_end_time` repeats mowing within a single work
window; it is not HA's recurrence-end setting and is preserved on update.

Rules support `FREQ=DAILY` or `FREQ=WEEKLY`, optional `INTERVAL=1`, and, for weekly
rules, unnumbered `BYDAY=MO,TU,WE,TH,FR,SA,SU` subsets containing the start weekday.
`WKST` is harmless for interval 1. Daily BYDAY filters, COUNT, UNTIL, other
frequencies and repeat exceptions are rejected.
New recurring events must select the next matching window, which may already
be in progress (`start <= now < end`). For example, at Wednesday 20:00, a weekly
Wednesday 18:00–21:00 event can be saved. Saving an already-started window only
updates the stored schedule; the integration sends no immediate mowing command.
Daily rules follow the same policy. Today's single-day all-day recurring
event is likewise accepted while its device window (00:00–23:59) is still open.
An already-ended window and a DTSTART later than the next matching window are
rejected on creation: the device stores no start date to delay activation.

Recurring updates change the complete device rule, including while mowing is
running. The integration sends only the schedule edit and verification requests,
with no command to stop, restart or reschedule the current mission.
Subsequent starts depend on the saved rule and device conditions. The selected
calendar date cannot defer device activation. An omitted rule on update
preserves the current recurring rule and daily/weekly presentation choice.

Without a rule, the calendar requests **next-occurrence-only** using `run_once`.
Only the next occurrence of the chosen weekday/time is accepted, not an arbitrary
future date. A one-time start must be strictly in the future, even if the end
has not passed: an already-started window is rejected with
`A one-time event must start in the future; choose a future start time`.
HA rejects such a window to avoid presenting an elapsed start time as a future
one-time execution.
This also rejects a new all-day one-time event for today after midnight.
Creating or changing an enabled one-time device window requires its item,
weekday and global schedule switches to be enabled, so its chosen date is not
silently deferred.

Once the individual item reports both `run_once=true` and `disabled=true`, only
its title, description and location can be edited in HA. Its times, recorded
date, weekdays, recurrence and all-day choice are frozen, including conversion
to a weekly/daily rule. Saving a disallowed change reports
`This one-time schedule is disabled; only its title, description and location
can be changed. Create a new event to schedule mowing again`.
No MODIFY is sent and any accompanying text changes are not partially saved.
A permitted text-only edit performs a fresh GET, preserves the recorded date
and disabled flag, and saves only HA metadata. Deletion remains available and
requires the normal ACK and verification GET. Create a new event to schedule
another execution; the calendar does not automatically re-enable old items.

This restriction uses the individual item's flags, not the global switch or
disabled-weekday list, and does not freeze recurring rules. It applies whenever
both item flags match, including while a mission is running. Disabled is not
proof of completion or even execution. The native HA form still displays its
normal controls; Python validates these restrictions when saving. There is no
individual-item enable/disable button added to that form.

Accepting an already-started recurring window does not relax device write
verification: every ADD/MODIFY/DELETE still requires a matching successful ACK
and a verification GET showing the expected result. A confirmed save describes
the stored configuration, not a successful or immediate mowing start.

### Local metadata and fallback

After device edits, new local metadata is committed only after the matching
success ACK and matching GET verification. A local-only edit (text, or a display
choice with identical device configuration) performs a fresh baseline GET under
the same schedule lock, then saves local metadata without a MODIFY. The local
store is read back before reporting persistence success. If persistence fails,
HA reports the error while retaining confirmed device state; refresh before
retrying a write, especially ADD. Read failures and unsuccessful device writes
do not commit requested metadata.

HA remembers the all-day and daily/weekly display choices across GETs and
restarts. Device configuration remains authoritative: a window changed away
from 00:00–23:59 loses its all-day hint; a daily appointment changed away from all
seven weekdays or made one-time loses its daily hint. The local text stays
associated with the same ID. A valid time-slot GET confirming deletion or a
change to another schedule type removes that ID's metadata.

Device IDs can be reused; they are not UUIDs or timestamps and are not guaranteed
to increase forever. HA does not attempt to detect a delete/reuse cycle missed
while offline. If the same ID remains, local text can stay attached while
reported device fields follow GET. There is no additional protocol identity.

If local metadata is missing, recurring events still appear at the actual device
times on every reported weekday within the queried calendar range. The fallback
is title **Global mowing**, empty location/description, a timed event and a
weekly RRULE, even for 00:00–23:59 or all seven weekdays. Device data cannot prove
that the original user selected all-day or daily. One-time date fallback is
limited as described below.

For each run-once item, HA records its next eligible planned window when it is
first observed enabled in a valid GET, respecting weekday disables. That date
stays fixed when the window expires or the device disables the item; querying
a past calendar range still returns the original event. Global/weekday pauses
do not erase a known date, and an unchanged overdue item never rolls into the
following week. This is a planned window, not confirmation that mowing occurred:
a disable sent by another protocol client is indistinguishable from the device
automatically disabling a one-time item.

Dates and local metadata are persisted together with HA's `Store` helper under
`.storage/terramow.schedule_history.<hashed-stable-device-id>` and survive
reconnects, integration reloads and normal HA restarts. The additive metadata
section is compatible with the existing date-only store. Include the HA config
directory (including `.storage`) in backups. Recreating a container with the same
config keeps these fields; a new HA instance/config without a restored backup
cannot recover local text or display choices from the mower. Stored history alone
does not make the calendar available: a fresh valid DP122 GET is still required
after connecting. Read/edit failures preserve the last valid history. Writes
still require the same device ACK and verification GET; sending a command does
not create a confirmed calendar record.

The device stores weekdays and times, not a dated execution history. An item
first observed already disabled, with no previously recorded date, cannot be
placed on a historical date and remains in the DP122 snapshot without a calendar
event. Earlier execution dates cannot be backfilled by this change. Initially
paused items likewise have no date until first observed eligible. Missing an
entire disable/re-enable or ID-reuse cycle while HA is offline cannot be detected
from an identical GET alone.

An observed re-enable or changed time/rule replaces that item's stored planned
window with the next eligible one. Converting it to a weekly schedule or removing
it from a valid device list removes its local one-time record, so deleting a
historical event still deletes the device item through DP122 and verification
GET. Removing the integration removes its local metadata/date store. This is history of
the currently stored one-time appointments, not an immutable execution log.

Weekly configured windows remain visible when disabled. Calendar `on` means the
configured window is current, not that the
mower is physically mowing or will execute despite disable/weather/business
conditions. Use the existing mower/mission entities for actual execution and the
existing switches to enable/disable schedules. The calendar does not toggle
global or weekday switches automatically.

The standard `calendar.create_event` action can create a one-time event using
`summary`, `start_date_time` and `end_date_time`. HA's action schema has no RRULE
field; use the calendar UI/WebSocket API for recurring event creation. Restart
HA after adding the calendar platform, or reload the integration after the new
code has been loaded into the HA process.

## Validation

`tests/test_calendar.py` exercises real HA calendar platform/service loading,
weekly expansion, exclusive interval boundaries, timezones/DST, one-time limits,
whole-series editing, omitted defaults, DP122 initialization without DP127, CRUD ACK/GET
ordering, mismatched/retained replies, timeouts, disconnects, ambiguous ADDs,
malformed snapshots and preservation of unrelated schedule fields/types.
The tests also cover fixed historical one-time dates, local persistence and
restore, pauses, re-enables, deletion/ID reuse, corrupt stored dates/metadata,
unknown disabled items without fabricated dates, daily/all-day mapping,
HA-only text persistence, external changes, metadata-only edits and local
storage failures. Standard HA WebSocket date conversion is tested as well.
`tests/test_schedule_switch.py` continues to cover the existing switch behavior.
Run `scripts/test` and `scripts/lint` to check changes to the integration.
