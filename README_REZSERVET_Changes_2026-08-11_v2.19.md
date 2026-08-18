# REZSERVET – Changes Made 11 August 2026

## Current build

```text
REZSERVET Version 2.19.0
Build 2026-08-11 14:45
```

## Build 2.19.0 additions

### Startup database validation
REZSERVET now validates core SQL Server objects before entering the processing loop.

It checks the required tables:

```text
PFWIZREZ
ZAR1ZAR1
XMTOUTFL
XMTCFG1
XMTCFG2
XMTSTATS (when WRITE_XMTSTATS=True)
```

It also checks core required columns used by routing and output processing.

Successful startup writes:

```text
Startup DB validation: OK (... tables, ... required columns)
```

If a required table/column is missing, REZSERVET stops at startup rather than beginning processing with an invalid schema.

### Correct SQL Server version naming
The SQL Server major-version mapping now includes:

```text
13 = SQL Server 2016
14 = SQL Server 2017
15 = SQL Server 2019
16 = SQL Server 2022
17 = SQL Server 2025
```

This corrects the previous generic display for SQL Server 15.x.

### Process ID
Startup now records:

```text
Process ID          <PID>
```

This allows easy correlation with Task Manager and Windows Event Log entries.

### Python architecture
Python startup information now includes process architecture, for example:

```text
Python              3.14.4 (64bit)
```

### READY banner
The final startup banner is:

```text
------------------------------------------------------------
READY - waiting for reservations
Polling interval: 120 seconds
------------------------------------------------------------
```

### Daily log header
Date-based daily logging already existed.

Build 2.19.0 now writes a header when a new daily log file is first created:

```text
================================================================================
REZSERVET DAILY LOG 2026-08-11 Version=2.19.0 Build=2026-08-11 14:45
================================================================================
```

The existing log naming convention continues to provide daily rotation:

```text
XMTLOG.YYYYMMDD.log
```

### Daily log status in startup summary
Startup now explicitly reports:

```text
Daily Log File      Date-based rotation ON
```

### Existing features retained
All previous production features remain:

- no-route treated as informational
- LOG_NO_ROUTE switch
- VERBOSE_LOGGING switch
- DEBUG_LOGGING switch
- per-cycle reconciliation
- cumulative RECON_RUN
- FINAL_RECON
- per-destination mismatch detection
- character-length metadata guard
- legacy short-field normalisation
- daily operational summary
- clearer heartbeat/status
- Run ID
- SQL Server/environment diagnostics
- Execution Mode
- controlled stop event for future Windows Service use

## Deferred resilience changes

The following were deliberately not added to Build 2.19.0 because they need separate transaction/recovery testing.

### Automatic INSERT retry
Not added yet.

A blind retry is unsafe because the SQL Server INSERT may have succeeded while the client lost the acknowledgement. Automatically repeating the INSERT could therefore create a duplicate output.

Any retry design should first establish an idempotent key/check.

### Automatic SQL reconnect / SQL restart recovery
Not added yet.

This requires deciding what happens to a reservation already marked `I` when a SQL connection is lost midway through processing.

The reconnect logic and recovery of `I` rows should be designed and tested together.

### Windows Service SCM integration
Still best kept in the separate `rezservet_service.py` wrapper rather than embedded in the processing module.

### Log retention
Daily rotation exists. Automatic deletion/archive of logs older than a configured retention period remains optional housekeeping.

## Recommended production switches

```python
VERBOSE_LOGGING = False
LOG_NO_ROUTE = False
DEBUG_LOGGING = False
DAILY_SUMMARY_ENABLED = True
```
