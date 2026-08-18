# REZSERVET – Changes Made 11 August 2026

## Overview

Today’s work focused on making `rezservet.py` safer for production use, easier to support, and easier to reconcile against input/output processing.

The main areas changed were:

- Routing and no-route handling
- Input/output reconciliation
- Protection against SQL Server character truncation
- Logging controls
- Startup diagnostics
- Windows Service preparation
- Operational testing and error handling

---

## 1. No-route handling

Previously, when no route was found through `XMTCFG1` / `XMTCFG2`, REZSERVET raised an error:

```text
ERROR ... No route found (XMTCFG1/XMTCFG2 produced 0 SY2_DESTID)
```

This was changed because a missing route can be a valid/normal condition.

### New behaviour

A no-route record:

- is no longer treated as a processing error
- is marked complete
- does not write an `XMTOUTFL` row
- is counted separately as `NoRoute`
- does not stop processing of later reservations

The exact routing keys can be logged when required.

---

## 2. Separate no-route logging switch

Added:

```python
LOG_NO_ROUTE = False
```

### When `False`

Individual no-route reservations are not written to the log.

The reconciliation summary still reports the number:

```text
RECON Input=243 Routed=236 NoRoute=7 Error=0 ...
```

The 7 represent 7 separate input reservations.

A summary is also written when no-route records occurred:

```text
NO_ROUTE SUMMARY NoRoute=7
(set LOG_NO_ROUTE=True to list individual reservations)
```

### When `True`

Each no-route reservation is logged with details such as:

- rowid
- CNF
- ROUTE_SYS
- ROUTE_SYS_PUL
- PUL
- XMTCFG1 results / XMTCFG2 results

The summary still appears.

---

## 3. Routing diagnostics

Successful routing detail was moved behind verbose logging.

Example verbose output:

```text
ROUTE_SYS='ITARC     ' PUL='VCE'
ROUTE_DESTS=['XMT2JARS', 'XMT2WOS']
```

Missing `XMTCFG2` configuration remains visible because it indicates a configuration inconsistency rather than a normal no-route condition.

---

## 4. Input/output reconciliation

A reconciliation mechanism was added.

For each processing cycle REZSERVET tracks:

- Input rows claimed
- Routed input rows
- No-route input rows
- Error input rows
- Destinations found
- Output rows written

### Input reconciliation

Expected:

```text
Input = Routed + NoRoute + Error
```

Reported as:

```text
InputBalance=0
```

### Output reconciliation

Expected:

```text
OutputRowsWritten = DestinationsFound
```

Reported as:

```text
OutputBalance=0
```

Example:

```text
RECON Input=13 Routed=13 NoRoute=0 Error=0
      DestinationsFound=28 OutputRowsWritten=28
      InputBalance=0 OutputBalance=0
```

---

## 5. Per-destination reconciliation

If output reconciliation fails, REZSERVET reports which destination is short.

Example:

```text
WARNING RECON DESTINATION MISMATCH
DEST=XMT2JARS Expected=13 Written=12 Difference=-1
```

This was validated during testing when one reservation failed before output.

---

## 6. Cumulative reconciliation

Added cumulative service-run totals:

```text
RECON_RUN
```

This tracks totals since REZSERVET was started.

On controlled shutdown a final summary is written:

```text
FINAL_RECON
```

---

## 7. Idle reconciliation logging reduced

Originally REZSERVET produced repeated messages such as:

```text
RECON Input=0 Routed=0 ...
RECON_RUN Input=0 Routed=0 ...
```

during idle polling cycles.

This was changed.

Reconciliation detail is now written only when at least one input row was processed.

Heartbeat logging continues while idle.

---

## 8. Character truncation protection

A SQL Server failure was identified:

```text
String or binary data would be truncated
table 'XMT.dbo.XMTOUTFL'
column 'OUTSTN3C'
Truncated value: 'B40'
```

`OUTSTN3C` is a 3-character compatibility field derived from a longer station value.

Rather than allowing non-critical legacy fields to reject the entire reservation, protection was added.

---

## 9. Legacy short-field normalisation

The following long/short field relationships are explicitly normalised before insert:

```text
OUT_LOCN8  -> OUT_LOCN   (5)
OUTCAR20   -> OUTCAR1C   (1)
OUTDOL20   -> OUTDOL3C   (3)
OUTPUL20   -> OUTPUL3C   (3)
OUTSTN20   -> OUTSTN3C   (3)
```

The short field is derived/truncated to its permitted length.

Example:

```text
OUTSTN3C 'B40K' -> 'B40'
```

This prevented the previous reservation failure.

---

## 10. General XMTOUTFL character-length guard

A broader protection mechanism was added.

At startup REZSERVET reads SQL Server metadata for all:

- `char`
- `varchar`
- `nchar`
- `nvarchar`

columns in `XMTOUTFL`.

Current test environment:

```text
XMTOUTFL character columns: 379
```

Before each insert, character values are checked against the actual SQL Server column length.

If a value is too long:

- it is truncated to the SQL Server maximum
- the reservation continues
- the truncation is always logged

Example:

```text
INFO TRUNCATE_CHAR rowid=40055 DEST=XMT2WOS
column=OUTSTN3C max=3 from='B40K' to='B40'
```

This is intended to prevent non-critical character overflow from losing an otherwise valid reservation.

---

## 11. Logging switches

Three independent diagnostic switches now exist:

```python
VERBOSE_LOGGING = False
LOG_NO_ROUTE    = False
DEBUG_LOGGING   = False
```

### `VERBOSE_LOGGING`

Controls routine diagnostic detail including:

- `DR_SAMPLE`
- `TAGS_FOUND`
- successful route details
- normalisation diagnostics

### `LOG_NO_ROUTE`

Controls individual no-route reservation detail.

No-route counts remain in reconciliation regardless of this switch.

### `DEBUG_LOGGING`

Controls lower-level diagnostics such as:

- last SQL statement
- duplicate-count calculation details
- investigation-level processing information

---

## 12. Always-logged events

The following are not suppressed by the diagnostic switches:

- START / END
- database connection
- heartbeat
- processing errors
- character truncation
- reconciliation
- reconciliation mismatches
- no-route summary
- final reconciliation
- controlled shutdown

---

## 13. Normalisation log noise reduced

Routine messages such as:

```text
INFO NORMALISE OUT_LOCN from='ITARC' to='ITARC'
```

were unnecessary.

Normalisation diagnostics are now:

- written only when the value actually changes
- controlled by `VERBOSE_LOGGING`

Actual `TRUNCATE_CHAR` events remain always visible.

---

## 14. Startup diagnostics

Startup logging was expanded to make the running copy self-documenting.

It now reports:

- REZSERVET version
- build date/time
- base directory
- shutdown flag path
- status flag path
- mapping configuration loaded
- database configuration loaded
- SQL Server name
- database name
- SQL login/user
- polling interval
- heartbeat interval
- SQL login timeout
- XMTCFG1 row count
- XMTCFG2 row count
- XMTOUTFL character-column count
- overflow protection status
- legacy normalisation status
- logging switch states

Example:

```text
START REZSERVET Version=2.16.0 Build=2026-08-11 13:50
BaseDir=C:\WestPier\Installed\REZSERVET\rezservet_operation
CONNECTED server=BEUDC1SQL03 db=XMT user=xmt
```

Followed by a startup summary similar to:

```text
------------------------------------------------------------
REZSERVET Startup Summary
------------------------------------------------------------
Version             2.16.0
Build               2026-08-11 13:50
Base Directory      ...
Server              BEUDC1SQL03
Database            XMT
User                xmt
Poll Interval       120s
Heartbeat Interval  120s
SQL Login Timeout   5s
XMTCFG1 Rows        ...
XMTCFG2 Rows        ...
XMTOUTFL Char Cols  379
Overflow Protect    ON
Legacy Normalise    ON
Logging             Verbose=OFF NoRoute=OFF Debug=OFF
------------------------------------------------------------
```

---

## 15. SQL Server shutdown issue identified

During testing the previous REZSERVET process exited with:

```text
[Microsoft][ODBC Driver 18 for SQL Server]
[SQL Server]SHUTDOWN is in progress. (6005)
```

This was confirmed as a SQL Server shutdown/restart condition rather than a routing or REZSERVET logic error.

A future resilience improvement is to add reconnect/retry handling so REZSERVET can recover automatically after a transient SQL Server outage.

---

## 16. Base directory correction

A replacement script initially referenced:

```text
C:\WestPier\REZSERVET_on_Sql_Server\rezservet_operation
```

while the active installation is under:

```text
C:\WestPier\Installed\REZSERVET\rezservet_operation
```

The deployed version must use the actual installation path so that:

- `db.ini`
- `xmtmaptag.ini`
- logs
- archive
- status flag
- shutdown flag

are all resolved correctly.

---

## 17. Windows Service preparation

REZSERVET already contains:

```python
STOP_EVENT = threading.Event()
```

and controlled stop handling through:

```python
should_stop()
sleep_interruptible()
```

A separate Windows Service wrapper was prepared using `pywin32`.

The recommended structure is:

```text
rezservet.py
rezservet_service.py
install_service.cmd
start_service.cmd
stop_service.cmd
restart_service.cmd
remove_service.cmd
debug_service.cmd
```

The service wrapper calls:

```python
rezservet.main()
```

and uses:

```python
rezservet.STOP_EVENT.set()
```

for controlled shutdown.

Business logic remains separate from Windows Service logic.

---

## 18. Service recovery

The service installation script includes Windows Service recovery configuration so the service can restart after a process/service failure.

This is separate from application-level SQL reconnect logic.

---

## 19. Current validated processing result

After the character-length fix and reconciliation changes, a test batch produced:

```text
Input=13
Routed=13
NoRoute=0
Error=0
DestinationsFound=28
OutputRowsWritten=28
InputBalance=0
OutputBalance=0
```

This confirms:

- all 13 reservations were accounted for
- all routing destinations produced output
- no output rows were lost
- the previous `OUTSTN3C` truncation failure was prevented

---

## 20. Current recommended production logging

Recommended settings:

```python
VERBOSE_LOGGING = False
LOG_NO_ROUTE    = False
DEBUG_LOGGING   = False
```

This provides a concise production log while retaining:

- reconciliation
- no-route counts
- errors
- truncation events
- heartbeats
- operational startup information

Temporarily enable the relevant switch when investigating a specific issue.

---

## Current build

Latest build produced today:

```text
REZSERVET Version 2.16.0
Build 2026-08-11 13:50
```

The latest replacement module includes all changes listed above.

