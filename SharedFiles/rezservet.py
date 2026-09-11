
#-----------------------------------------------------------------------------------------------------------------
#
#   Library Imports  -  S E C T I O N   A   -   Needed for PYTHON to operate 
#
#------------------------------------------------------------------------------------------------------------------
import os
import json
import pyodbc
import configparser
import threading
import signal
STOP_EVENT = threading.Event()                               # Windows Service to Stop Service - do not change
# 2026-08-12 Moved this following line and put under guard to end
#signal.signal(signal.SIGINT, lambda s, f: STOP_EVENT.set())  # Controlled CTRL-C redirect - do not change   
# added these two (for now) but functions where used may not be called (working without them previously)
import re
import time
import sys
import getpass
import uuid
import platform

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple




#-----------------------------------------------------------------------------------------------------------------
#
#   C O N F I G U R A T I O N   S E C T I O N   B   -   Tailorable Options
#
#------------------------------------------------------------------------------------------------------------------

VERSION = "2.19.3"
BUILD = "2026-08-11 17:15"

PROCESS_START_MONO = time.perf_counter()
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]

BASE_DIR = r"C:\WestPier\Installed\REZSERVET\rezservet_operation"
LOG_DIR = r"C:\WestPier\Installed\REZSERVET\rezservet_operation\logs"
ARC_DIR = r"C:\WestPier\Installed\REZSERVET\rezservet_operation\archive"

MAP_INI_PATH   = os.path.join(BASE_DIR, "xmtmaptag.ini")

STATUS_FLAG    = os.path.join(BASE_DIR, "status.flag")
SHUTDOWN_FLAG  = os.path.join(BASE_DIR, "shutdown.flag")

HEARTBEAT_SECS         = 120
SLEEP_SECS             = 120
DEFAULT_DB_TIMEOUT     = 5   

PRINT_CONSOLE = True  # False      # <- turn off console spam
WRITE_LOGFILE = True       # <- keep daily file logging

# Logging controls
#
# VERBOSE_LOGGING:
#   Routine processing detail such as DR_SAMPLE, TAGS_FOUND and successful route detail.
#
# LOG_NO_ROUTE:
#   Individual "no configured route" records.  No-route counts are ALWAYS included
#   in RECON summaries even when these individual messages are disabled.
#
# DEBUG_LOGGING:
#   Low-level diagnostics intended only for investigation/development.
#
# IMPORTANT events such as truncation, reconciliation mismatch and processing
# errors are always logged regardless of these switches.
VERBOSE_LOGGING = True
LOG_NO_ROUTE    = True 
DEBUG_LOGGING   = False

# Optional source-row diagnostic for tracing data written to XMTOUTFL and later
# consumed by XmtFio.  OFF in normal operation.
#
# When enabled, writes one JSON line per XMTOUTFL row to:
#   logs\XMTOUT_DIAG.YYYYMMDD.jsonl
#
# This is intentionally separate from the normal REZSERVET log.
LOG_XMTOUT_DIAGNOSTICS = False

# Operational reporting
DAILY_SUMMARY_ENABLED = True

# Console by default.  The Windows Service wrapper should set:
#   REZSERVET_EXECUTION_MODE=Windows Service
EXECUTION_MODE = os.environ.get("REZSERVET_EXECUTION_MODE", "Console")

# Kill switch for REZSERVEP writing XMTSTATS (does NOT affect XmtFio)
WRITE_XMTSTATS = True

# If True: any CHAR/VARCHAR column in XMTOUTFL not mapped gets '' instead of NULL
FILL_MISSING_CHAR_WITH_BLANKS = False


#-----------------------------------------------------------------------------------------------------------------
#
#   C O N F I G U R A T I O N   S E C T I O N   C    -   No Change Recommended Here  
#
#------------------------------------------------------------------------------------------------------------------
T_PF    = "dbo.PFWIZREZ"
T_AR1   = "dbo.ZAR1ZAR1"
T_OUT   = "dbo.XMTOUTFL"
T_CFG1  = "dbo.XMTCFG1"
T_CFG2  = "dbo.XMTCFG2"
T_STATS = "dbo.XMTSTATS"  # optional for REZSERVEP only

# Configured dummy destination.
# If XMTCFG1/XMTCFG2 resolve to this key, the route is considered valid
# but intentionally produces no XMTOUTFL output row.
DUMMY_NO_ROUTE_DEST = "NOROUTE"

PF_ROWID_COL = "XMT_ROWID"
PF_STAT_COL  = "WHSOH"
PF_DR_COL    = "DR"

# Claim logic: In progress / complete / error
ZERO   = '0'  # inputs from XmtFileLink   2025-03-16
INPROG = "I"  # In Progress
DONE   = "C"  # Complete
ERROR  = "E"  # Error


# Routing inputs (PF header based)
PF_INSNDL_COL = "IHSNDL"
PF_IHSITE_COL = "IHSITE"   # <-- FIX: routing uses PF header, not DR tag

TAG_OUTCNF20 = "CNF"
TAG_OUTSEQ20 = "SEQ"



MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}






#-----------------------------------------------------------------------------------------------------------------
#
#   C O N F I G U R A T I O N   S E C T I O N   D    -   Database Connection to SQL Server - db.ini externalised 

#
#------------------------------------------------------------------------------------------------------------------
# ---------------- CONFIG-ODBC ----------------
# "Server=beudc1del03,1433;"
#CS = (
#    "Driver={ODBC Driver 17 for SQL Server};"
#    "Server=beudc1sql03\\SQLEXPRESS,1433;"
#    "Database=Xxx;"
#    "UID=xxxx;"
#    "PWD=xxxxx;"  
#    "TrustServerCertificate=yes;"
#    "Application Name=XMTWorker;" 
#)
# ---------------- CONFIG-ODBC ----------------

# ---------------------------------------------------------------------------------------------------
#  Function: load_cs - Reads db.ini and builds the SQL Server connection string and DB timeout value.
# ---------------------------------------------------------------------------------------------------
def load_cs(path="db.ini") -> tuple[str, int]:
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    s = cfg["sqlserver"]

    cs = (
        f"Driver={{{s['driver']}}};"
        f"Server={s['server']};"
        f"Database={s['database']};"
        f"UID={s['uid']};"
        f"PWD={s['pwd']};"
        f"Encrypt={s.get('encrypt', 'yes')};"
        f"TrustServerCertificate={s.get('trust_server_certificate', 'yes')};"
        f"Application Name={s.get('application_name', 'XMTWorker')};"
    )
    #  timeout = int(s.get("timeout", "5"))     # 2026-03-10 removed
    timeout = int(s.get("timeout", str(DEFAULT_DB_TIMEOUT)))
    return cs, timeout

# ---------------------------------------------------------------------------------------------------
#  Function: ensure_db_ini() – Verifies that the db.ini configuration file exists before the program starts.
# ---------------------------------------------------------------------------------------------------
def ensure_db_ini(path: str) -> None:
    if not os.path.isfile(path):
        raise RuntimeError(f"Missing required SQL Server DB configuration file: {path}")

DB_INI_PATH = os.path.join(BASE_DIR, "db.ini")

ensure_db_ini(DB_INI_PATH)    # ensure the 'db.ini'file exists

CS, DB_TIMEOUT = load_cs(DB_INI_PATH)
### CS, DB_TIMEOUT = load_cs()     2026-03-10 removed












#-----------------------------------------------------------------------------------------------------------------
#
#   U T I L I T Y   F U N C T I O N S      S E C T I O N   E   -    ( R E Z S E R V E P )
#
#------------------------------------------------------------------------------------------------------------------

# ---------------- TIME / LOGGING ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: ts() – Returns a formatted UTC timestamp string for logging.
# ---------------------------------------------------------------------------------------------------
def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------------------------------------
#  Function: now_stamp_str() – Returns current UTC time as a compact string used in filenames or records.
# ---------------------------------------------------------------------------------------------------
def now_stamp_str() -> str:
    # YYYY-MM-DD:HH:MM:SS.mmmm (23 chars)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d:%H:%M:%S.%f")[:23]

# ---------------------------------------------------------------------------------------------------
#  Function: now_stamp_dt() – Returns the current UTC time as a datetime object.
# ---------------------------------------------------------------------------------------------------
def now_stamp_dt() -> datetime:
    # Use for SQL datetime2 columns (pyodbc sends proper datetime)
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------------------------------------------
#  Function: log() – Writes timestamped log messages to console and/or logfile depending on configuration.
# ---------------------------------------------------------------------------------------------------
def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"

    # console (controlled, but defaults to on if the flags don't exist)
    if globals().get("PRINT_CONSOLE", True):
        print(line, flush=True)

    # logfile (controlled, but defaults to on if the flags don't exist)
    if globals().get("WRITE_LOGFILE", True):
        os.makedirs(globals().get("LOG_DIR", "."), exist_ok=True)
        path = log_file_path()
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if is_new:
                f.write("=" * 80 + "\n")
                f.write(
                    f"REZSERVET DAILY LOG {datetime.now().strftime('%Y-%m-%d')} "
                    f"Version={VERSION} Build={BUILD}\n"
                )
                f.write("=" * 80 + "\n")
            f.write(line + "\n")


# ---------------------------------------------------------------------------------------------------
#  Function: verbose_log() – Writes routine diagnostic information only when VERBOSE_LOGGING is enabled.
# ---------------------------------------------------------------------------------------------------
def verbose_log(msg: str) -> None:
    if globals().get("VERBOSE_LOGGING", False):
        log(msg)


# ---------------------------------------------------------------------------------------------------
#  Function: no_route_log() – Logs individual normal no-route records only when enabled.
# ---------------------------------------------------------------------------------------------------
def no_route_log(msg: str) -> None:
    if globals().get("LOG_NO_ROUTE", False):
        log(msg)


# ---------------------------------------------------------------------------------------------------
#  Function: debug_log() – Writes low-level diagnostics only when DEBUG_LOGGING is enabled.
# ---------------------------------------------------------------------------------------------------
def debug_log(msg: str) -> None:
    if globals().get("DEBUG_LOGGING", False):
        log(msg)


# ---------------------------------------------------------------------------------------------------
#  Function: pop_flag() – Reads and clears a control flag value used for runtime process signalling.
# ---------------------------------------------------------------------------------------------------
def pop_flag(path: str) -> bool:
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
        return True
    return False

# ---------------------------------------------------------------------------------------------------
#  Function: should_stop() – Determines whether the worker should terminate based on control flags.
# ---------------------------------------------------------------------------------------------------
#def should_stop() -> bool:
#    if pop_flag(SHUTDOWN_FLAG):
#        log("STOP: shutdown.flag detected")
#        return True
#    return False

# ---------------------------------------------------------------------------------------------------
#  Function: should_stop() – Determines whether the worker should terminate based on control flags + Windows Service
# ---------------------------------------------------------------------------------------------------
def should_stop() -> bool:                  # Added for future Windows Service Implementation 2026-03-11
    if STOP_EVENT.is_set():
        log("STOP: service stop requested")
        return True
    if pop_flag(SHUTDOWN_FLAG):
        log("STOP: shutdown.flag detected")
        return True
    return False


# ---------------------------------------------------------------------------------------------------
#  Function: sleep_interruptible() – Sleeps for a period but wakes early if a stop signal is detected.
# ---------------------------------------------------------------------------------------------------
def sleep_interruptible(seconds: int) -> bool:
    for _ in range(max(1, int(seconds))):
    # for _ in range(max(1, seconds)):     #  Replaced this line 2026-10-03
        if should_stop():
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------------------------------
#  Function: safe_xmlstr() – Sanitises text so it is safe for XML or downstream systems.
# ---------------------------------------------------------------------------------------------------
def safe_xmlstr(val: str, max_len: int) -> str:
    if not val:
        return ""
    return val[:max_len]



# ---------------- IMF PARSE / CLEANSE ----------------
NON_PRINTABLE_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
TAG_OK = re.compile(r"^[A-Z0-9]{3}$")


# ---------------------------------------------------------------------------------------------------
#  Function: cleanse() – Performs general string cleaning and normalisation.
# ---------------------------------------------------------------------------------------------------
def cleanse(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return NON_PRINTABLE_RE.sub("", s)

# ---------------------------------------------------------------------------------------------------
#  Function: parse_tags() – Parses IMF-style tagged input lines into tag/value structures.
# ---------------------------------------------------------------------------------------------------
def parse_tags(dr: str) -> Tuple[Dict[str, str], List[str]]:
    tags: Dict[str, str] = {}
    errs: List[str] = []
    if not dr:
        return tags, errs

    s = dr.replace("\\/", "/")
    parts = [p for p in s.split("/") if p != ""]

    for part in parts:
        if len(part) < 3:
            continue
        tag = part[:3].upper()
        val = part[3:].strip()
        if not TAG_OK.match(tag):
            errs.append(f"BadTag:{tag!r} frag={part[:20]!r}")
            continue
        tags[tag] = val

    tags["DR"] = s
    return tags, errs

# ---------------------------------------------------------------------------------------------------
#  Function: drconv_ddmonyy_hhmm_to_yyyymmdd_hhmm00() – Converts legacy DDMONYY HHMM timestamps into YYYYMMDD HHMM00 format.
# ---------------------------------------------------------------------------------------------------
def drconv_ddmonyy_hhmm_to_yyyymmdd_hhmm00(s: str) -> str:
    s = (s or "").strip().upper()
    m = re.match(r"(\d{2})([A-Z]{3})(\d{2})/(\d{4})$", s)
    if not m:
        return s
    dd, mon, yy, hhmm = m.groups()
    yyyy = 2000 + int(yy)
    mm = MONTHS.get(mon, 0)
    if mm == 0:
        return s
    return f"{yyyy:04d}{mm:02d}{int(dd):02d}.{hhmm}00"




#-----------------------------------------------------------------------------------------------------------------
#
#   M A P P I N G   S E C T I O N   F   -   (xmtmaptag.ini)
#
#------------------------------------------------------------------------------------------------------------------
# ---------------- MAPPING (xmtmaptag.ini) ----------------
@dataclass
class MapRow:
    seq: int
    target: str
    kind: str
    spec: str

@dataclass
class StatsMapRow:
    target_col: str
    rule: str
    arg: str


@dataclass
class ProcessResult:
    """Result of processing one claimed PFWIZREZ row."""
    claimed: bool
    status: str
    destination_ids: Tuple[str, ...] = ()
    written_ids: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------------------------------
#  Function: load_map_ini_section_a() – Loads mapping rules for section A from the mapping configuration file.
# ---------------------------------------------------------------------------------------------------
def load_map_ini_section_a(path: str) -> List[MapRow]:
    rows: List[MapRow] = []
    in_a = False
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            u = s.upper()
            if u.startswith("SECTION-A"):
                in_a = True
                continue
            if u.startswith("SECTION-B"):
                break
            if not in_a:
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) < 4:
                continue
            try:
                seq = int(parts[0])
            except Exception:
                continue
            rows.append(MapRow(seq=seq, target=parts[1], kind=parts[2].upper(), spec=parts[3]))
    return rows

# ---------------------------------------------------------------------------------------------------
#  Function: load_map_ini_section_b() – Loads mapping rules for section B from the mapping configuration file.
# ---------------------------------------------------------------------------------------------------
def load_map_ini_section_b(path: str) -> List[StatsMapRow]:
    rows: List[StatsMapRow] = []
    in_b = False
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            u = s.upper()
            if u.startswith("SECTION-B"):
                in_b = True
                continue
            if u.startswith("SECTION-") and in_b:
                break
            if not in_b:
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) < 4:
                continue
            try:
                _ = int(parts[0])
            except Exception:
                continue
            rows.append(StatsMapRow(target_col=parts[1], rule=parts[2].upper(), arg=parts[3]))
    return rows

# ---------------------------------------------------------------------------------------------------
#  Function: eval_concat() – Evaluates concatenation expressions defined in the mapping configuration.
# ---------------------------------------------------------------------------------------------------
def eval_concat(spec: str, pf: Dict[str, Any]) -> str:
    if "!!" in spec:
        parts = spec.split("!!")
        out = []
        for p in parts:
            p = p.strip()
            if p.startswith('"') and p.endswith('"'):
                out.append(p[1:-1])
            elif p == ".":
                out.append(".")
            else:
                out.append(str(pf.get(p, "") or ""))
        return "".join(out)
    return spec

# ---------------------------------------------------------------------------------------------------
#  Function: mapped_value() – Determines the mapped output value for a given input field using the mapping rules.
# ---------------------------------------------------------------------------------------------------
def mapped_value(m: MapRow, pf: Dict[str, Any], tags: Dict[str, str], cfg2: Dict[str, Any]) -> Any:
    k = (m.kind or "").strip().upper()
    spec = (m.spec or "").strip()

    if k == "IGNORE":
        return None
    if k == "INIT":
        return spec
    if k == "PFHDR":
        return pf.get(spec)
    if k == "PFVAR":
        return pf.get(spec)
    if k == "DR":
        return tags.get(spec.upper())
    if k == "DRCONV":
        return drconv_ddmonyy_hhmm_to_yyyymmdd_hhmm00(tags.get(spec.upper(), "") or "")
    if k in ("TSTAMP", "NOWDT", "NOW"):
        # safest: return datetime (for datetime2 columns); char columns will accept str later via defaults
        return now_stamp_dt()
    if k == "CFG2":
        return cfg2.get(spec)
    if k == "CONCAT":
        return eval_concat(spec, pf)
    return None

# ---------------- DB HELPERS ----------------
LAST_SQL = ""

# ---------------------------------------------------------------------------------------------------
#  Function: _set_last() – Helper that tracks the last mapped value during mapping evaluation.
# ---------------------------------------------------------------------------------------------------
def _set_last(sql: str) -> None:
    global LAST_SQL
    LAST_SQL = (sql or "").strip()

# def open_con() -> pyodbc.Connection:               # 2026-03-10 replaced 
#    return pyodbc.connect(CS, autocommit=False)

# def open_con() -> pyodbc.Connection:               # 2026-03-10 replaced 
#    return pyodbc.connect(CS, autocommit=False, timeout=DB_TIMEOUT)

# ---------------------------------------------------------------------------------------------------
#  Function: open_con() – Opens a SQL Server connection using the configured connection string and timeout.
# ---------------------------------------------------------------------------------------------------
def open_con(timeout: int = DB_TIMEOUT) -> pyodbc.Connection:
    try:
        return pyodbc.connect(CS, autocommit=False, timeout=timeout)
    except pyodbc.Error as e:
        log(f"DB connection to SQL Server failed: {e}")
        raise



# ---------------------------------------------------------------------------------------------------
#  Function: safe_execute() – Executes SQL statements with error protection and logging. 
# ---------------------------------------------------------------------------------------------------
def safe_execute(cur: pyodbc.Cursor, sql: str, *params):
    _set_last(sql)
    return cur.execute(sql, *params)


# ---------------------------------------------------------------------------------------------------
#  Function: status_snapshot() – Retrieves a snapshot of worker or processing status from the database. 
# ---------------------------------------------------------------------------------------------------
def status_snapshot(con) -> str:
    cur = con.cursor()

    status_col = "WHSOH"
    t_pf = T_PF
    t_out = T_OUT

    sql = f"""
    SELECT
      SUM(
          CASE
              WHEN NULLIF(LTRIM(RTRIM({status_col})), '') IS NULL
                   OR LTRIM(RTRIM({status_col})) = '0'
              THEN 1 ELSE 0
          END
      ) AS pending,
      SUM(CASE WHEN {status_col}={INPROG!r} THEN 1 ELSE 0 END) AS icnt,
      SUM(CASE WHEN {status_col}={DONE!r}   THEN 1 ELSE 0 END) AS ccnt,
      SUM(CASE WHEN {status_col}={ERROR!r}  THEN 1 ELSE 0 END) AS ecnt,
      COUNT(*) AS total
    FROM {t_pf};
    """

    pending, icnt, ccnt, ecnt, total = cur.execute(sql).fetchone()
    outcnt = cur.execute(f"SELECT COUNT(*) FROM {t_out};").fetchone()[0]

    return (
        f"STATUS: Total={int(total or 0)} "
        f"Pending={int(pending or 0)} "
        f"InProgress={int(icnt or 0)} "
        f"Complete={int(ccnt or 0)} "
        f"Error={int(ecnt or 0)} "
        f"OutputRows={int(outcnt or 0)}"
    )




def status_snapshot_Parked220260316(con) -> str:
    cur = con.cursor()

    status_col = "WHSOH"
    t_pf = T_PF
    t_out = T_OUT

    sql = f"""
    SELECT
      SUM(CASE WHEN LTRIM(RTRIM({status_col}))='0' THEN 1 ELSE 0 END) AS zcnt,
      SUM(CASE WHEN {status_col}={INPROG!r} THEN 1 ELSE 0 END) AS icnt,
      SUM(CASE WHEN {status_col}={DONE!r}   THEN 1 ELSE 0 END) AS ccnt,
      SUM(CASE WHEN {status_col}={ERROR!r}  THEN 1 ELSE 0 END) AS ecnt,
      COUNT(*) AS total
    FROM {t_pf};
    """
    zcnt, icnt, ccnt, ecnt, total = cur.execute(sql).fetchone()
    outcnt = cur.execute(f"SELECT COUNT(*) FROM {t_out};").fetchone()[0]

    return (
        f"STATUS: Input PFWIZREZ={int(total or 0)} "
        f"I('in progress')={int(icnt or 0)} C('complete')={int(ccnt or 0)} E('error')={int(ecnt or 0)} "
        f"Output XMTOUTFL={int(outcnt or 0)} 0('WHSOH input')={int(zcnt or 0)} "
    )



def status_snapshot_parked20260316(con) -> str:
    cur = con.cursor()

    # status_col = "XMT_STATUS"   # <-- change if column name differs
    status_col = "WHSOH"          # <-- change if column name differs
    t_pf = T_PF
    t_out = T_OUT

    sql = f"""
    SELECT
      SUM(CASE WHEN LTRIM(RTRIM({status_col}))='0' THEN 1 ELSE 0 END) AS zcnt,    # Added 2026-03-16 
      SUM(CASE WHEN {status_col}={INPROG!r} THEN 1 ELSE 0 END) AS icnt,
      SUM(CASE WHEN {status_col}={DONE!r}   THEN 1 ELSE 0 END) AS ccnt,
      SUM(CASE WHEN {status_col}={ERROR!r}  THEN 1 ELSE 0 END) AS ecnt,
      COUNT(*) AS total
    FROM {t_pf};
    """
    # icnt, ccnt, ecnt, total = cur.execute(sql).fetchone()                        # Removed 2026-03-16 
    zcnt, icnt, ccnt, ecnt, total = cur.execute(sql).fetchone()                    # Added 2026-03-16 
    outcnt = cur.execute(f"SELECT COUNT(*) FROM {t_out};").fetchone()[0]

    return (
        f"STATUS: Input PFWIZREZ={int(total or 0)} "
        f"I('in progress')={int(icnt or 0)} C('complete')={int(ccnt or 0)} E('error')={int(ecnt or 0)} "
        f"Output XMTOUTFL={int(outcnt or 0)} 0('WHSOH input')={int(zcnt or 0)} ")   


#   Output XMTOUTFL={int(outcnt or 0)} # Removed 2026-03-16  Added to end of it with zcnt 2026-03-16

# ---------------------------------------------------------------------------------------------------
#  Function: get_col_type() – Determines SQL column type metadata for a specified table/column.
# ---------------------------------------------------------------------------------------------------
def get_col_type(con, table, col):
    row = con.cursor().execute("""
        SELECT t.name
        FROM sys.columns c
        JOIN sys.types t ON t.user_type_id=c.user_type_id
        WHERE c.object_id = OBJECT_ID(?) AND c.name = ?;
    """, table, col).fetchone()
    return (row[0] or "").lower() if row else ""

# ---------------------------------------------------------------------------------------------------
#  Function: mark_pf() – Updates a PF record to mark it as processed or in-progress. 
#  [Status on Table PFWIZREZ transitions attribute WHSOH from ' ' or '0' to 'I'(in-progress) to 'C'(complete) ('E' if Error)] 
# ---------------------------------------------------------------------------------------------------
def mark_pf(con, rowid:int, code:str):
    t = get_col_type(con, T_PF, PF_STAT_COL)
    cur = con.cursor()
    if t in ("varbinary","binary"):
        sql = f"UPDATE {T_PF} SET {PF_STAT_COL} = CONVERT(varbinary(1), ASCII(?)) WHERE {PF_ROWID_COL} = ?;"
        cur.execute(sql, code, rowid)
    else:
        sql = f"UPDATE {T_PF} SET {PF_STAT_COL} = ? WHERE {PF_ROWID_COL} = ?;"
        cur.execute(sql, code, rowid)
    con.commit()

# ---------------------------------------------------------------------------------------------------
#  Function: claim_one_row() – selects and claims the next PF row from Table PFWIZREZ.
# ---------------------------------------------------------------------------------------------------
def claim_one_row(con) -> Optional[Dict[str, Any]]:
    sql = f"""
;WITH cte AS (
    SELECT TOP (1) *
    FROM {T_PF} WITH (UPDLOCK, READPAST, ROWLOCK)
    WHERE NULLIF(LTRIM(RTRIM({PF_STAT_COL})), '') IS NULL
          OR LTRIM(RTRIM({PF_STAT_COL})) = ?                    
          OR LTRIM(RTRIM({PF_STAT_COL})) NOT IN (?, ?, ?)
    ORDER BY {PF_ROWID_COL}
)
UPDATE cte
   SET {PF_STAT_COL} = ?
OUTPUT inserted.*;
"""
    cur = con.cursor()
    _set_last(sql)
    cur.execute(sql, ZERO, INPROG, DONE, ERROR, INPROG)    
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

#   cur.execute(sql, INPROG, DONE, ERROR, INPROG)      # Removed 2026-03-16  # Added ZERO to line 2026-03-16
#   OR LTRIM(RTRIM({PF_STAT_COL})) = ?   ...added 2026-03-16
# ---------------------------------------------------------------------------------------------------
#  Function: archive_pf_row() – Archives a processed PF row for traceability.
# ---------------------------------------------------------------------------------------------------
def archive_pf_row(con: pyodbc.Connection, pf: Dict[str, Any]) -> None:
    try:
        cur = con.cursor()
        cols = [r[0] for r in cur.execute(
            "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) ORDER BY column_id", T_AR1
        ).fetchall()]
        common = [c for c in pf.keys() if c in cols]
        if not common:
            return
        col_list = ", ".join(f"[{c}]" for c in common)
        ph = ", ".join("?" for _ in common)
        sql = f"INSERT INTO {T_AR1} ({col_list}) VALUES ({ph})"
        _set_last(sql)
        cur.execute(sql, *[pf[c] for c in common])
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass



# ---------------------------------------------------------------------------------------------------
#  Function: out_char_columns() – Returns the list of character columns used when constructing output records.
# ---------------------------------------------------------------------------------------------------
def out_char_columns(con: pyodbc.Connection) -> List[str]:
    cur = con.cursor()
    sql = """
SELECT c.name
FROM sys.columns c
JOIN sys.types t ON c.user_type_id = t.user_type_id
WHERE c.object_id = OBJECT_ID(?)
  AND t.name IN ('char','varchar','nchar','nvarchar')
"""
    _set_last(sql)
    return [r[0] for r in cur.execute(sql, T_OUT).fetchall()]


# ---------------------------------------------------------------------------------------------------
#  Function: out_char_limits() – Returns maximum character lengths for character columns in XMTOUTFL.
# ---------------------------------------------------------------------------------------------------
def out_char_limits(con: pyodbc.Connection) -> Dict[str, int]:
    cur = con.cursor()
    sql = """
SELECT
    c.name,
    t.name,
    c.max_length
FROM sys.columns c
JOIN sys.types t ON c.user_type_id = t.user_type_id
WHERE c.object_id = OBJECT_ID(?)
  AND t.name IN ('char','varchar','nchar','nvarchar')
"""
    _set_last(sql)

    limits: Dict[str, int] = {}

    for name, typename, max_length in cur.execute(sql, T_OUT).fetchall():
        if max_length is None or int(max_length) < 0:
            continue

        length = int(max_length)

        if str(typename).lower() in ("nchar", "nvarchar"):
            length //= 2

        limits[str(name)] = length

    return limits


# ---------------------------------------------------------------------------------------------------
#  Function: routing_config_counts() – Returns current XMTCFG1/XMTCFG2 configuration counts.
# ---------------------------------------------------------------------------------------------------
def routing_config_counts(con: pyodbc.Connection) -> Tuple[int, int]:
    cur = con.cursor()

    sql1 = f"SELECT COUNT(*) FROM {T_CFG1};"
    _set_last(sql1)
    cfg1_count = int(cur.execute(sql1).fetchone()[0] or 0)

    sql2 = f"SELECT COUNT(*) FROM {T_CFG2};"
    _set_last(sql2)
    cfg2_count = int(cur.execute(sql2).fetchone()[0] or 0)

    return cfg1_count, cfg2_count


# ---------------------------------------------------------------------------------------------------
#  Function: normalise_legacy_short_fields() – Enforces known short/long compatibility relationships.
# ---------------------------------------------------------------------------------------------------
def normalise_legacy_short_fields(outrow: Dict[str, Any]) -> None:
    pairs = [
        ("OUT_LOCN8", "OUT_LOCN", 5),
        ("OUTCAR20",  "OUTCAR1C", 1),
        ("OUTDOL20",  "OUTDOL3C", 3),
        ("OUTPUL20",  "OUTPUL3C", 3),
        ("OUTSTN20",  "OUTSTN3C", 3),
    ]

    for long_col, short_col, short_len in pairs:
        long_value = str(outrow.get(long_col) or "")
        old_short = str(outrow.get(short_col) or "")

        if long_value:
            new_short = long_value[:short_len]
        else:
            new_short = old_short[:short_len]

        if old_short != new_short:
            verbose_log(
                f"INFO NORMALISE {short_col} "
                f"from={old_short!r} to={new_short!r} "
                f"source={long_col} value={long_value!r}"
            )

        outrow[short_col] = new_short


# ---------------------------------------------------------------------------------------------------
#  Function: enforce_out_char_limits() – Final safety net before INSERT into XMTOUTFL.
#  Overlength character values are truncated to the SQL column length and logged as INFO.
# ---------------------------------------------------------------------------------------------------
def enforce_out_char_limits(
    outrow: Dict[str, Any],
    char_limits: Dict[str, int],
    rowid: Optional[int] = None,
    destid: Optional[str] = None,
) -> None:
    for col, max_len in char_limits.items():
        if col not in outrow:
            continue

        value = outrow.get(col)

        if value is None or not isinstance(value, str):
            continue

        if len(value) > max_len:
            truncated = value[:max_len]

            log(
                f"INFO TRUNCATE_CHAR rowid={rowid} DEST={destid} "
                f"column={col} max={max_len} "
                f"from={value!r} to={truncated!r}"
            )

            outrow[col] = truncated



# ---------------------------------------------------------------------------------------------------
#  Function: xmto_diag_path() – Builds the optional XMTOUTFL diagnostic trace path.
# ---------------------------------------------------------------------------------------------------
def xmto_diag_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(
        LOG_DIR,
        f"XMTOUT_DIAG.{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl",
    )


# ---------------------------------------------------------------------------------------------------
#  Function: _diag_value() – Produces JSON-safe value/type/length metadata for an XMTOUTFL field.
# ---------------------------------------------------------------------------------------------------
def _diag_value(value: Any) -> Dict[str, Any]:
    if value is None:
        return {
            "type": "NoneType",
            "length": None,
            "value": None,
        }

    if isinstance(value, datetime):
        return {
            "type": "datetime",
            "length": None,
            "value": value.isoformat(),
        }

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "length": len(value),
            "value": value.hex(),
        }

    if isinstance(value, bytearray):
        b = bytes(value)
        return {
            "type": "bytearray",
            "length": len(b),
            "value": b.hex(),
        }

    if isinstance(value, memoryview):
        b = value.tobytes()
        return {
            "type": "memoryview",
            "length": len(b),
            "value": b.hex(),
        }

    if isinstance(value, str):
        return {
            "type": "str",
            "length": len(value),
            "value": value,
        }

    return {
        "type": type(value).__name__,
        "length": None,
        "value": value,
    }


# ---------------------------------------------------------------------------------------------------
#  Function: log_xmto_diagnostic() – Writes one optional JSON diagnostic row for each XMTOUTFL insert.
#
#  Correlation keys mirror the values XmtFio already logs on failure:
#    OUTFTXD45, OUTCNF20, OUTSEQ20, OUT_DUPCNT, SY2_DESTID
#
#  The full outbound row is also recorded with Python type and string/byte length,
#  allowing an intermittent downstream XmtFio failure to be matched back exactly.
# ---------------------------------------------------------------------------------------------------
def log_xmto_diagnostic(rowid: int, outrow: Dict[str, Any]) -> None:
    if not globals().get("LOG_XMTOUT_DIAGNOSTICS", False):
        return

    rec = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "run_id": RUN_ID,
        "source_rowid": rowid,
        "correlation": {
            "OUTFTXD45": outrow.get("OUTFTXD45"),
            "OUTCNF20": outrow.get("OUTCNF20"),
            "OUTSEQ20": outrow.get("OUTSEQ20"),
            "OUT_DUPCNT": outrow.get("OUT_DUPCNT"),
            "SY2_DESTID": outrow.get("SY2_DESTID"),
        },
        "columns": {
            col: _diag_value(value)
            for col, value in sorted(outrow.items())
        },
    }

    with open(
        xmto_diag_path(),
        "a",
        encoding="utf-8",
        newline="\n",
    ) as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


#-----------------------------------------------------------------------------------------------------------------
#
#   R O U T I N G   S E C T I O N   G   -   (route a rez to one of more destinations)
#
#------------------------------------------------------------------------------------------------------------------
    
# ---------------- ROUTING (XMTCFG1 / XMTCFG2) ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: _pad5() – Pads or formats values to width 5.
# ---------------------------------------------------------------------------------------------------
def _pad5(s: str) -> str:
    s = (s or "").strip().upper()
    return (s + "     ")[:5]

# ---------------------------------------------------------------------------------------------------
#  Function: _pad10() – Pads or formats values to width 10.
# ---------------------------------------------------------------------------------------------------
def _pad10(s: str) -> str:
    s = (s or "").strip().upper()
    return (s + (" " * 10))[:10]

# ---------------------------------------------------------------------------------------------------
#  Function: _fetch_c1dests() – Retrieves routing destinations for C1 records from the database.
# ---------------------------------------------------------------------------------------------------
def _fetch_c1dests(con: pyodbc.Connection, key10: str) -> List[str]:
    cur = con.cursor()
    sql = f"""
SELECT DISTINCT XMT_C1DEST
FROM {T_CFG1}
WHERE XMT_C1KEY = ?
  AND XMT_C1DEST IS NOT NULL;
"""
    _set_last(sql)
    rows = cur.execute(sql, key10).fetchall()
    out: List[str] = []
    for r in rows:
        if r and r[0] is not None:
            d = str(r[0]).strip()
            if d:
                out.append(d)
    return out

# ---------------------------------------------------------------------------------------------------
#  Function: _fetch_cfg2_rows() – Loads routing configuration rows used by the routing engine.
# ---------------------------------------------------------------------------------------------------
def _fetch_cfg2_rows(con: pyodbc.Connection, c1dests: List[str]) -> List[Dict[str, Any]]:
    if not c1dests:
        return []
    cur = con.cursor()
    ph = ",".join("?" for _ in c1dests)
    sql = f"SELECT * FROM {T_CFG2} WHERE XMT_C2KEY IN ({ph});"
    _set_last(sql)
    cur.execute(sql, *c1dests)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

# ---------------------------------------------------------------------------------------------------
#  Function: route() – Determines where a processed record should be sent based on routing rules.
# ---------------------------------------------------------------------------------------------------
def route(con: pyodbc.Connection,
          pf: Dict[str, Any],
          tags: Optional[Dict[str, str]] = None,
          trace: bool = False) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    """
    RULES:
      1) Build two XMTCFG1 keys:
         - k_sys     = IHSNDL (5) + blanks (5)
         - k_sys_pul = IHSNDL (5) + IHSITE/PUL (<=5)
      2) Query XMTCFG1 for BOTH keys and union the destinations.
      3) Query XMTCFG2 for the resulting C1 destinations.
      4) Each final XMTCFG2 destination produces one XMTOUTFL output row.

    A missing route is informational, not an application error.
    """
    tags = tags or {}

    rowid = pf.get(PF_ROWID_COL)
    cnf = tags.get("CNF")

    ihsndl_5 = _pad5(str(pf.get("IHSNDL") or pf.get("IHSNDL".upper()) or ""))

    # Prefer DR tag PUL as "site" input, else PF IHSITE.
    ihsite_5 = _pad5(
        str(tags.get("PUL") or pf.get("IHSITE") or pf.get("IHSITE".upper()) or "")
    )

    if not ihsndl_5.strip():
        no_route_log(
            f"INFO NO_ROUTE rowid={rowid} CNF={cnf!r} "
            f"reason='IHSNDL blank' PUL={ihsite_5!r}"
        )
        return [], {}

    k_sys = _pad10(ihsndl_5)
    k_sys_pul = _pad10(ihsndl_5 + ihsite_5)

    # UNION results from BOTH XMTCFG1 lookups.
    dests: List[str] = []
    seen = set()

    for key10 in [k_sys, k_sys_pul]:
        if not key10.strip():
            continue
        for d in _fetch_c1dests(con, key10):
            if d not in seen:
                seen.add(d)
                dests.append(d)

    if trace:
        log(
            f"ROUTE_SYS={k_sys!r} ROUTE_SYS_PUL={k_sys_pul!r} "
            f"PUL={ihsite_5!r}"
        )
        log(f"ROUTE_C1DESTS={dests}")

    # No XMTCFG1 route is normal/informational.
    if not dests:
        no_route_log(
            f"INFO NO_ROUTE rowid={rowid} CNF={cnf!r} "
            f"ROUTE_SYS={k_sys!r} ROUTE_SYS_PUL={k_sys_pul!r} "
            f"PUL={ihsite_5!r} C1DESTS=[]"
        )
        return [], {}

    cfg2_rows = _fetch_cfg2_rows(con, dests)

    cfg2_by_dest: Dict[str, Dict[str, Any]] = {}
    destids: List[str] = []

    for r in cfg2_rows:
        k = str(r.get("XMT_C2KEY") or "").strip()
        if k:
            cfg2_by_dest[k] = r
            destids.append(k)

    # Report any XMTCFG1 destinations which had no XMTCFG2 row.
    cfg2_keys = set(destids)
    missing_cfg2 = [d for d in dests if d not in cfg2_keys]
    if missing_cfg2:
        log(
            f"INFO ROUTE_CFG2_MISSING rowid={rowid} CNF={cnf!r} "
            f"ROUTE_SYS={k_sys!r} ROUTE_SYS_PUL={k_sys_pul!r} "
            f"C1DESTS={dests} MISSING_CFG2={missing_cfg2}"
        )

    if not destids:
        no_route_log(
            f"INFO NO_ROUTE rowid={rowid} CNF={cnf!r} "
            f"ROUTE_SYS={k_sys!r} ROUTE_SYS_PUL={k_sys_pul!r} "
            f"PUL={ihsite_5!r} C1DESTS={dests} CFG2_DESTS=[]"
        )
        return [], {}

    # A configured NOROUTE row is a deliberate no-output route.
    # It satisfies the XMTCFG1/XMTCFG2 configuration lookup but must never
    # create an XMTOUTFL row.  If real destinations are also present, keep
    # routing to those real destinations and simply ignore NOROUTE.
    dummy_destids = [
        d for d in destids
        if str(d).strip().upper() == DUMMY_NO_ROUTE_DEST
    ]

    if dummy_destids:
        no_route_log(
            f"INFO CONFIGURED_NO_ROUTE rowid={rowid} CNF={cnf!r} "
            f"ROUTE_SYS={k_sys!r} ROUTE_SYS_PUL={k_sys_pul!r} "
            f"PUL={ihsite_5!r} DUMMY_DEST={DUMMY_NO_ROUTE_DEST!r}"
        )

        destids = [
            d for d in destids
            if str(d).strip().upper() != DUMMY_NO_ROUTE_DEST
        ]

        cfg2_by_dest = {
            k: v for k, v in cfg2_by_dest.items()
            if str(k).strip().upper() != DUMMY_NO_ROUTE_DEST
        }

        # NOROUTE was the only configured destination.
        # Return no output destinations so process_one() counts this
        # reservation as NO_ROUTE and marks it complete.
        if not destids:
            return [], {}

    if trace:
        log(f"ROUTE_DESTIDS={destids}")

    return destids, cfg2_by_dest

# ---------------- END ROUTING ----------------



#-----------------------------------------------------------------------------------------------------------------
#
#   L O G G I N G    S E C T I O N   H   
#
#------------------------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------------
#  Function: yyyymmdd_utc() – Returns the current UTC date in YYYYMMDD format.
# ---------------------------------------------------------------------------------------------------
def yyyymmdd_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")

# ---------------------------------------------------------------------------------------------------
#  Function: log_file_path() – Builds the current log file path.
# ---------------------------------------------------------------------------------------------------
def log_file_path() -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"XMTLOG.{yyyymmdd_utc()}.log")

# ---------------------------------------------------------------------------------------------------
#  Function: rezarc_path() – Builds the archive file path for processed records.
# ---------------------------------------------------------------------------------------------------
def rezarc_path() -> str:
    os.makedirs(ARC_DIR, exist_ok=True)
    return os.path.join(ARC_DIR, f"XMTREZAR1.{yyyymmdd_utc()}.txt")

# ---------------------------------------------------------------------------------------------------
#  Function: archive_pf_text() – Writes processed PF records to the archive text file.
# ---------------------------------------------------------------------------------------------------
def archive_pf_text(pf: dict) -> None:
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rowid": pf.get("XMT_ROWID"),
        "WHSOH": pf.get("WHSOH"),
        "WHDATE": pf.get("WHDATE"),
        "IHSNDL": pf.get("IHSNDL"),
        "DR": (pf.get("DR") or "")[:4096],
    }
    with open(rezarc_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        



# ---------------- OUT DUPCNT + INSERT ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: next_dupcnt() – Determines the next duplicate counter value for outbound records
# ---------------------------------------------------------------------------------------------------
def next_dupcnt(con, destid: str, ftxd: str, cnf: str, seq: str) -> int:
    cur = con.cursor()
    sql = f"""
SELECT ISNULL(MAX(CAST(OUT_DUPCNT AS INT)), -1) + 1
FROM {T_OUT}
WHERE SY2_DESTID=? AND OUTFTXD45=? AND OUTCNF20=? AND OUTSEQ20=?
  AND OUT_DUPCNT IS NOT NULL;
"""
    _set_last(sql)
    v = int(cur.execute(sql, destid, ftxd, cnf, seq).fetchone()[0] or 0)
    result = min(v, 9)
    debug_log(
        f"DEBUG DUPCNT DEST={destid} FTXD={ftxd!r} "
        f"CNF={cnf!r} SEQ={seq!r} RESULT={result}"
    )
    return result

# ---------------------------------------------------------------------------------------------------
#  Function: insert_out() – Inserts a processed record into the outbound table.
# ---------------------------------------------------------------------------------------------------
def insert_out(con: pyodbc.Connection, row: Dict[str, Any]) -> None:
    cur = con.cursor()
    cols = list(row.keys())
    col_list = ", ".join(f"[{c}]" for c in cols)
    ph = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {T_OUT} ({col_list}) VALUES ({ph});"
    _set_last(sql)
    cur.execute(sql, *[row[c] for c in cols])
    con.commit()



#-----------------------------------------------------------------------------------------------------------------
#
#   X M T S T A T S     S E C T I O N   I   
#
#------------------------------------------------------------------------------------------------------------------
# ---------------- SECTION-B : XMTSTATS (REZSERVEP only) ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: next_stats_seq() – Retrieves the next sequence number for statistics records.
# ---------------------------------------------------------------------------------------------------
def next_stats_seq(con: pyodbc.Connection, cnf: str, destid: str) -> str:
    cur = con.cursor()
    sql = f"""
SELECT ISNULL(MAX(TRY_CONVERT(int, XMT_SSEQ)), 0)
FROM {T_STATS}
WHERE XMT_SCNF = ? AND XMT_STDEST = ?;
"""
    _set_last(sql)
    n = int(cur.execute(sql, cnf, destid).fetchone()[0] or 0) + 1
    return f"{n:04d}"

# ---------------------------------------------------------------------------------------------------
#  Function: stats_mapped_value() – Extracts mapped values used for statistical reporting.
# ---------------------------------------------------------------------------------------------------
def stats_mapped_value(m: StatsMapRow, tags: Dict[str, str], pf: Dict[str, Any], outrow: Dict[str, Any], cfg2: Dict[str, Any], destid: str) -> Any:
    r = (m.rule or "").strip().upper()
    a = (m.arg or "").strip()

    if r == "INIT":
        return a
    if r == "DR":
        if a.upper() == "DR":
            return (tags.get("DR") or "")[:4096]
        v = tags.get(a.upper())
        if v is None and a.upper() == "TXD":
            v = outrow.get("OUT_TXD") or ""
        return v
    if r == "PFHDR":
        return pf.get(a)
    if r == "CFG2":
        if a == "XMT_C2KEY":
            return destid
        return cfg2.get(a)
    if r == "DATE":
        return now_stamp_str()
    return None

# ---------------------------------------------------------------------------------------------------
#  Function: insert_xmtstats() – Inserts a statistics record describing the processed transaction.
# ---------------------------------------------------------------------------------------------------
def insert_xmtstats(con: pyodbc.Connection,
                    stats_map: List[StatsMapRow],
                    tags: Dict[str, str],
                    pf: Dict[str, Any],
                    outrow: Dict[str, Any],
                    cfg2: Dict[str, Any],
                    destid: str) -> None:
    cnf = str(outrow.get("OUTCNF20") or tags.get("CNF") or "").strip()
    if not cnf:
        raise RuntimeError("XMTSTATS: CNF missing")

    row: Dict[str, Any] = {}
    for m in stats_map:
        v = stats_mapped_value(m, tags=tags, pf=pf, outrow=outrow, cfg2=cfg2, destid=destid)
        if v is not None:
            row[m.target_col] = v

    # always enforce keys/sequence
    row["XMT_SRID"]   = str(row.get("XMT_SRID") or "STATS")[:5]
    row["XMT_SCNF"]   = cnf
    row["XMT_STDEST"] = destid
    row["XMT_SSEQ"]   = next_stats_seq(con, cnf, destid)

    # NOT NULLs in XMTSTATS (per your schema)
    row.setdefault("XMT_STXD",  (outrow.get("OUT_TXD") or tags.get("TXD") or "00000000")[:8])
    row.setdefault("XMT_SDCNT", 1)  # decimal(1,0) NOT NULL
    row.setdefault("XMT_SHSEQ", 1)  # decimal(2,0) NOT NULL
    row.setdefault("XMT_SSCNT", 1)  # decimal(2,0) NOT NULL

    # XMLSTR is CHAR(196)
    dr = tags.get("DR") or pf.get("DR") or ""
    row["XMT_XMLSTR"] = safe_xmlstr(dr, 196)

    cols = list(row.keys())
    sql = f"INSERT INTO {T_STATS} ({', '.join(f'[{c}]' for c in cols)}) VALUES ({', '.join('?' for _ in cols)});"
    _set_last(sql)
    cur = con.cursor()
    cur.execute(sql, *[row[c] for c in cols])
    con.commit()

# ---------------------------------------------------------------------------------------------------
#  Function: txd_to_yyyymmdd() – Converts transaction date formats into YYYYMMDD.
# ---------------------------------------------------------------------------------------------------
def txd_to_yyyymmdd(txd: str) -> str:
    s = (txd or "").strip()

    # already YYYYMMDD
    dig = "".join(ch for ch in s if ch.isdigit())
    if len(dig) >= 8:
        return dig[:8]

    # DDMONYY e.g. 04JUN22
    s2 = s.replace("/", "").replace("-", "").strip()
    if len(s2) == 7 and s2[:2].isdigit() and s2[2:5].isalpha() and s2[5:7].isdigit():
        try:
            dt = datetime.strptime(s2.title(), "%d%b%y")
            return dt.strftime("%Y%m%d")
        except ValueError:
            pass

    return "00000000"



# ---------------- PROCESS ONE ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: process_one() – Processes a single PF row end-to-end: claim, parse, map, route, insert output, archive, and record statistics.
# ---------------------------------------------------------------------------------------------------
def process_one(
    con: pyodbc.Connection,
    map_rows: List[MapRow],
    out_char_cols: List[str],
    out_char_limits_map: Dict[str, int],
    stats_map: List[StatsMapRow],
) -> ProcessResult:
    """
    Processes one PFWIZREZ row.

    Returns a ProcessResult so the main loop can reconcile:
      INPUT rows claimed
        = ROUTED + NO_ROUTE + ERROR

      OUTPUT rows written
        should equal final routing destinations found.
    """
    pf = claim_one_row(con)
    if not pf:
        return ProcessResult(claimed=False, status="EMPTY")

    log(f"CLAIM rowid={pf.get(PF_ROWID_COL)} WHSOH={pf.get('WHSOH')}")

    archive_pf_text(pf)

    rowid = int(pf[PF_ROWID_COL])
    dr = cleanse(pf.get(PF_DR_COL)) or ""

    tags, tag_errs = parse_tags(dr)
    verbose_log("DR_SAMPLE=" + (dr[:200] if dr else "<empty>"))
    verbose_log("TAGS_FOUND=" + str(sorted([k for k in tags.keys() if k != "DR"])[:30]))
    if tag_errs:
        log("TAG_ERRS=" + str(tag_errs[:10]))

    pf[PF_DR_COL] = dr

    destids: List[str] = []
    written_ids: List[str] = []

    try:
        archive_pf_row(con, pf)

        destids, cfg2_by_dest = route(con, pf, tags)

        # No configured route is INFORMATION, not ERROR.
        # Mark the input row complete so it will not be repeatedly reclaimed.
        if not destids:
            no_route_log(
                f"INFO rowid={rowid} CNF={tags.get('CNF')!r} "
                f"No routing destination found - reservation skipped"
            )
            mark_pf(con, rowid, DONE)
            return ProcessResult(
                claimed=True,
                status="NO_ROUTE",
                destination_ids=(),
                written_ids=(),
            )

        verbose_log(f"ROUTE_SYS={pf.get('IHSNDL')!r} PUL={tags.get('PUL')!r}")
        verbose_log(f"ROUTE_DESTS={destids}")

        for destid in destids:
            cfg2 = cfg2_by_dest.get(destid, {})

            outrow: Dict[str, Any] = {}
            for m in map_rows:
                v = mapped_value(m, pf, tags, cfg2)
                if v is not None:
                    outrow[m.target] = v

            # Enforce routing destination.
            outrow["SY2_DESTID"] = destid

            # datetime2 columns.
            outrow["SY2_TMSAVE"] = now_stamp_dt()
            outrow["SY2_TMRECV"] = now_stamp_dt()

            # Remove mapped values so controlled defaults win.
            for k in (
                "OUTFTXD45", "OUT_TXD", "OUT_DATE", "OUT_TIME",
                "OUTCNF20", "OUTSEQ20", "SY2_STATUS"
            ):
                outrow.pop(k, None)

            # Keys / status.
            outrow["SY2_STATUS"] = "N"
            outrow["OUTCNF20"] = str(tags.get("CNF") or "")
            outrow["OUTSEQ20"] = str(tags.get("SEQ") or "0")

            # TXD date YYYYMMDD.
            txd8 = txd_to_yyyymmdd(pf.get("WHDATE"))
            if txd8 == "00000000":
                txd8 = txd_to_yyyymmdd(tags.get("TXD"))

            outrow["OUT_TXD"] = txd8

            # TXD time HHMMSS.
            tm_src = pf.get("IHTIME") or tags.get("TIM") or "000000"
            tm6 = "".join(ch for ch in str(tm_src) if ch.isdigit())[:6].ljust(6, "0")

            outrow["OUTFTXD45"] = f"{txd8}.{tm6}"

            if len(outrow["OUTFTXD45"]) != 15:
                log(
                    f"BAD OUTFTXD45='{outrow['OUTFTXD45']}' "
                    f"rowid={rowid} CNF={outrow['OUTCNF20']} "
                    f"SEQ={outrow['OUTSEQ20']}"
                )

            outrow["OUT_DUPCNT"] = next_dupcnt(
                con,
                destid,
                outrow["OUTFTXD45"],
                outrow["OUTCNF20"],
                outrow["OUTSEQ20"],
            )

            # PFHDR fallbacks.
            outrow.setdefault("OUT_DATE", txd8)
            outrow.setdefault("OUT_TIME", tm6)
            outrow.setdefault("OUT_LOCN8", pf.get("IHSNDL", "") or "")
            outrow.setdefault("OUT_LOCN", (pf.get("IHSNDL", "") or "")[:5])

            if FILL_MISSING_CHAR_WITH_BLANKS:
                for c in out_char_cols:
                    outrow.setdefault(c, "")

            # Enforce known short/long legacy compatibility fields.
            normalise_legacy_short_fields(outrow)

            # Final safety net for all SQL Server character columns.
            enforce_out_char_limits(
                outrow,
                out_char_limits_map,
                rowid=rowid,
                destid=destid,
            )

            insert_out(con, outrow)
            written_ids.append(destid)

            # Optional correlation trace for diagnosing downstream XmtFio issues.
            # Only written when LOG_XMTOUT_DIAGNOSTICS=True.
            log_xmto_diagnostic(rowid, outrow)

            if WRITE_XMTSTATS and stats_map:
                try:
                    insert_xmtstats(
                        con, stats_map, tags, pf, outrow, cfg2, destid
                    )
                except Exception as se:
                    log(
                        f"XMTSTATS insert failed "
                        f"CNF={outrow.get('OUTCNF20')} DEST={destid}: {se}"
                    )

        mark_pf(con, rowid, DONE)

        log(
            f"Processed rowid={rowid} dests={len(destids)} "
            f"wrote={len(written_ids)} tags={max(0, len(tags)-1)}"
        )

        return ProcessResult(
            claimed=True,
            status="ROUTED",
            destination_ids=tuple(destids),
            written_ids=tuple(written_ids),
        )

    except Exception as e:
        try:
            con.rollback()
        except Exception:
            pass

        mark_pf(con, rowid, ERROR)

        log(
            f"ERROR rowid={rowid} {type(e).__name__}: {e} "
            f"| dests={len(destids)} wrote={len(written_ids)}"
        )
        debug_log(
            f"DEBUG rowid={rowid} LAST_SQL={LAST_SQL[:1000]}"
        )

        return ProcessResult(
            claimed=True,
            status="ERROR",
            destination_ids=tuple(destids),
            written_ids=tuple(written_ids),
        )



# ---------------------------------------------------------------------------------------------------
#  Function: configured_odbc_driver() – Extracts configured ODBC driver name from the connection string.
# ---------------------------------------------------------------------------------------------------
def configured_odbc_driver() -> str:
    m = re.search(r"Driver=\{([^}]+)\}", CS, flags=re.IGNORECASE)
    return m.group(1) if m else "<unknown>"


# ---------------------------------------------------------------------------------------------------
#  Function: windows_identity() – Returns the Windows account running the process/service.
# ---------------------------------------------------------------------------------------------------
def windows_identity() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user



# ---------------------------------------------------------------------------------------------------
#  Function: sql_environment_info() – Returns SQL Server product and DB compatibility information.
# ---------------------------------------------------------------------------------------------------
def sql_environment_info(con: pyodbc.Connection) -> Dict[str, Any]:
    cur = con.cursor()

    product_version, product_level, edition = cur.execute("""
        SELECT
            CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)),
            CAST(SERVERPROPERTY('ProductLevel') AS nvarchar(128)),
            CAST(SERVERPROPERTY('Edition') AS nvarchar(256));
    """).fetchone()

    compatibility_level = cur.execute("""
        SELECT compatibility_level
        FROM sys.databases
        WHERE name = DB_NAME();
    """).fetchone()[0]

    major = 0
    try:
        major = int(str(product_version).split(".", 1)[0])
    except Exception:
        pass

    friendly = {
        13: "SQL Server 2016",
        14: "SQL Server 2017",
        15: "SQL Server 2019",
        16: "SQL Server 2022",
        17: "SQL Server 2025",
    }.get(major, "SQL Server")

    return {
        "product_version": str(product_version or ""),
        "product_level": str(product_level or ""),
        "edition": str(edition or ""),
        "compatibility_level": int(compatibility_level or 0),
        "friendly": friendly,
    }


# ---------------------------------------------------------------------------------------------------
#  Function: log_daily_summary() – Writes one concise operational summary for a processing day.
# ---------------------------------------------------------------------------------------------------
def log_daily_summary(
    summary_date: str,
    inputs: int,
    routed: int,
    no_route: int,
    errors: int,
    destinations: int,
    outputs: int,
) -> None:
    input_balance = inputs - (routed + no_route + errors)
    output_balance = outputs - destinations

    log("=" * 60)
    log(f"REZSERVET DAILY SUMMARY Date={summary_date}")
    log(
        f"Reservations={inputs} Routed={routed} "
        f"NoRoute={no_route} Errors={errors}"
    )
    log(
        f"DestinationsFound={destinations} "
        f"OutputRowsWritten={outputs}"
    )
    log(
        f"InputBalance={input_balance} "
        f"OutputBalance={output_balance}"
    )
    log("=" * 60)



# ---------------------------------------------------------------------------------------------------
#  Function: validate_required_database_objects() – Verifies core tables and required columns exist.
# ---------------------------------------------------------------------------------------------------
def validate_required_database_objects(con: pyodbc.Connection) -> None:
    # Only objects required for core routing/output processing are fatal.
    required_tables = [
        T_PF,
        T_OUT,
        T_CFG1,
        T_CFG2,
    ]

    # XMTSTATS is required only when statistics writing is enabled.
    if WRITE_XMTSTATS:
        required_tables.append(T_STATS)

    cur = con.cursor()

    missing_tables: List[str] = []
    for table_name in required_tables:
        exists = cur.execute(
            "SELECT CASE WHEN OBJECT_ID(?) IS NULL THEN 0 ELSE 1 END;",
            table_name,
        ).fetchone()[0]
        if not exists:
            missing_tables.append(table_name)

    if missing_tables:
        raise RuntimeError(
            "Startup validation failed - missing required table(s): "
            + ", ".join(missing_tables)
        )

    required_columns = {
        T_PF: [PF_ROWID_COL, PF_STAT_COL, PF_DR_COL, PF_INSNDL_COL, PF_IHSITE_COL],
        T_OUT: ["SY2_DESTID", "OUTCNF20", "OUTSEQ20", "OUT_DUPCNT"],
        T_CFG1: ["XMT_C1KEY", "XMT_C1DEST"],
        T_CFG2: ["XMT_C2KEY"],
    }

    missing_columns: List[str] = []

    for table_name, columns in required_columns.items():
        for column_name in columns:
            exists = cur.execute(
                """
                SELECT COUNT(*)
                FROM sys.columns
                WHERE object_id = OBJECT_ID(?)
                  AND name = ?;
                """,
                table_name,
                column_name,
            ).fetchone()[0]

            if not exists:
                missing_columns.append(f"{table_name}.{column_name}")

    if missing_columns:
        raise RuntimeError(
            "Startup validation failed - missing required column(s): "
            + ", ".join(missing_columns)
        )

    # Optional DB archive table:
    # archive_pf_row() is already non-fatal, so its absence must not prevent startup.
    archive_exists = cur.execute(
        "SELECT CASE WHEN OBJECT_ID(?) IS NULL THEN 0 ELSE 1 END;",
        T_AR1,
    ).fetchone()[0]

    if archive_exists:
        log(f"Optional DB archive table: {T_AR1} OK")
    else:
        log(
            f"WARNING Optional DB archive table {T_AR1} not found - "
            f"database archive copy disabled; text archive remains active"
        )

    log(
        f"Startup DB validation: OK "
        f"({len(required_tables)} required tables, "
        f"{sum(len(v) for v in required_columns.values())} required columns)"
    )


#-----------------------------------------------------------------------------------------------------------------
#
#   M A I N   D R I V E R     S E C T I O N   J   
#
#------------------------------------------------------------------------------------------------------------------    
# ---------------- MAIN ----------------
# ---------------------------------------------------------------------------------------------------
#  Function: main() – Main worker loop that repeatedly claims and processes rows until a stop signal is received.
# ---------------------------------------------------------------------------------------------------
def main() -> None:
    log(f"START REZSERVET Version={VERSION} Build={BUILD} RunID={RUN_ID}")
    log(f"BaseDir={BASE_DIR}")
    log(f"Shutdown flag (one-shot): {SHUTDOWN_FLAG}")
    log(f"Status flag (one-shot):   {STATUS_FLAG}")

    map_rows = load_map_ini_section_a(MAP_INI_PATH)
    stats_map = load_map_ini_section_b(MAP_INI_PATH)

    log(
        f"Configuration: xmtmaptag.ini OK "
        f"(Section-A={len(map_rows)}, Section-B={len(stats_map)})"
    )
    log("Configuration: db.ini OK")

    con = open_con()

    # Totals for the lifetime of this process.
    run_input = 0
    run_routed = 0
    run_no_route = 0
    run_error = 0
    run_destinations = 0
    run_outputs = 0

    # Daily operational totals. Reset automatically when the local date changes.
    daily_date = datetime.now().strftime("%Y-%m-%d")
    daily_input = 0
    daily_routed = 0
    daily_no_route = 0
    daily_error = 0
    daily_destinations = 0
    daily_outputs = 0

    try:
        db, user, server_name = con.cursor().execute(
            "SELECT DB_NAME(), SUSER_SNAME(), CAST(SERVERPROPERTY('ServerName') AS nvarchar(128))"
        ).fetchone()
        log(f"CONNECTED server={server_name} db={db} user={user}")

        validate_required_database_objects(con)

        out_char_cols = (
            out_char_columns(con) if FILL_MISSING_CHAR_WITH_BLANKS else []
        )

        # Always load XMTOUTFL character limits for the final insert guard.
        out_char_limits_map = out_char_limits(con)
        cfg1_count, cfg2_count = routing_config_counts(con)
        sql_info = sql_environment_info(con)

        log("-" * 60)
        log("REZSERVET Startup Summary")
        log("-" * 60)
        log(f"Version             {VERSION}")
        log(f"Build               {BUILD}")
        log(f"Base Directory      {BASE_DIR}")
        log(f"Server              {server_name}")
        log(f"Database            {db}")
        log(f"User                {user}")
        log(f"Execution Mode      {EXECUTION_MODE}")
        log(f"Windows Account     {windows_identity()}")
        log(f"Process ID          {os.getpid()}")
        log(
            f"SQL Server          {sql_info['friendly']} "
            f"{sql_info['product_version']} {sql_info['product_level']}"
        )
        log(f"SQL Edition         {sql_info['edition']}")
        log(f"DB Compatibility    {sql_info['compatibility_level']}")
        log(
            f"Python              {sys.version.split()[0]} "
            f"({platform.architecture()[0]})"
        )
        log(f"ODBC Driver         {configured_odbc_driver()}")
        log(f"Run ID              {RUN_ID}")
        log(f"Poll Interval       {SLEEP_SECS}s")
        log(f"Heartbeat Interval  {HEARTBEAT_SECS}s")
        log(f"SQL Login Timeout   {DB_TIMEOUT}s")
        log(f"XMTCFG1 (Routes)    {cfg1_count}")
        log(f"XMTCFG2 (Dests)     {cfg2_count}")
        log(f"XMTOUTFL Char Cols  {len(out_char_limits_map)}")
        log("Overflow Protect    ON")
        log("Legacy Normalise    ON")
        log(f"Dummy NoRoute       {DUMMY_NO_ROUTE_DEST} (no output)")
        log(
            "Logging             "
            f"Verbose={'ON' if VERBOSE_LOGGING else 'OFF'} "
            f"NoRoute={'ON' if LOG_NO_ROUTE else 'OFF'} "
            f"Debug={'ON' if DEBUG_LOGGING else 'OFF'}"
        )
        log(
            f"XMTOUT Diagnostics  "
            f"{'ON' if LOG_XMTOUT_DIAGNOSTICS else 'OFF'}"
        )
        log(
            f"Daily Summary       "
            f"{'ON' if DAILY_SUMMARY_ENABLED else 'OFF'}"
        )
        log("Daily Log File      Date-based rotation ON")
        startup_elapsed = time.perf_counter() - PROCESS_START_MONO
        log(f"Startup Time        {startup_elapsed:.2f}s")
        log("-" * 60)
        log("READY - waiting for reservations")
        log(f"Polling interval: {SLEEP_SECS} seconds")
        log("-" * 60)

        last_hb = 0.0

        while True:
            if should_stop():
                break

            if pop_flag(STATUS_FLAG):
                log(status_snapshot(con))

            # Reconciliation totals for this processing cycle.
            cycle_input = 0
            cycle_routed = 0
            cycle_no_route = 0
            cycle_error = 0
            cycle_destinations = 0
            cycle_outputs = 0

            # Per-destination reconciliation for this cycle.
            expected_by_dest: Dict[str, int] = {}
            written_by_dest: Dict[str, int] = {}

            while True:
                result = process_one(
                    con,
                    map_rows,
                    out_char_cols,
                    out_char_limits_map,
                    stats_map,
                )

                if not result.claimed:
                    break

                cycle_input += 1

                if result.status == "ROUTED":
                    cycle_routed += 1
                elif result.status == "NO_ROUTE":
                    cycle_no_route += 1
                elif result.status == "ERROR":
                    cycle_error += 1

                cycle_destinations += len(result.destination_ids)
                cycle_outputs += len(result.written_ids)

                for destid in result.destination_ids:
                    expected_by_dest[destid] = (
                        expected_by_dest.get(destid, 0) + 1
                    )

                for destid in result.written_ids:
                    written_by_dest[destid] = (
                        written_by_dest.get(destid, 0) + 1
                    )

                if should_stop():
                    break

            # Add this cycle to service-run totals.
            run_input += cycle_input
            run_routed += cycle_routed
            run_no_route += cycle_no_route
            run_error += cycle_error
            run_destinations += cycle_destinations
            run_outputs += cycle_outputs

            daily_input += cycle_input
            daily_routed += cycle_routed
            daily_no_route += cycle_no_route
            daily_error += cycle_error
            daily_destinations += cycle_destinations
            daily_outputs += cycle_outputs

            # INPUT must reconcile to ROUTED + NO_ROUTE + ERROR.
            input_balance = cycle_input - (
                cycle_routed + cycle_no_route + cycle_error
            )

            # Each final destination should produce one output row.
            output_balance = cycle_outputs - cycle_destinations

            # Only write reconciliation detail when this cycle actually processed rows.
            # This keeps idle polling cycles from filling the log with zero-value RECON entries.
            if cycle_input > 0:
                log(
                    "RECON "
                    f"Input={cycle_input} "
                    f"Routed={cycle_routed} "
                    f"NoRoute={cycle_no_route} "
                    f"Error={cycle_error} "
                    f"DestinationsFound={cycle_destinations} "
                    f"OutputRowsWritten={cycle_outputs} "
                    f"InputBalance={input_balance} "
                    f"OutputBalance={output_balance}"
                )

                # Always summarise no-route activity when it occurred in this cycle.
                # Individual rows are listed only when LOG_NO_ROUTE=True.
                if cycle_no_route > 0:
                    if LOG_NO_ROUTE:
                        log(
                            f"NO_ROUTE SUMMARY NoRoute={cycle_no_route} "
                            f"(individual reservations listed above)"
                        )
                    else:
                        log(
                            f"NO_ROUTE SUMMARY NoRoute={cycle_no_route} "
                            f"(set LOG_NO_ROUTE=True to list individual reservations)"
                        )

                if input_balance != 0:
                    log(
                        "WARNING RECON INPUT MISMATCH "
                        f"Input={cycle_input} "
                        f"Routed+NoRoute+Error="
                        f"{cycle_routed + cycle_no_route + cycle_error}"
                    )

                if output_balance != 0:
                    log(
                        "WARNING RECON OUTPUT MISMATCH "
                        f"DestinationsFound={cycle_destinations} "
                        f"OutputRowsWritten={cycle_outputs} "
                        f"Difference={output_balance}"
                    )

                    all_dests = sorted(
                        set(expected_by_dest) | set(written_by_dest)
                    )
                    for destid in all_dests:
                        expected = expected_by_dest.get(destid, 0)
                        written = written_by_dest.get(destid, 0)
                        if expected != written:
                            log(
                                "WARNING RECON DESTINATION MISMATCH "
                                f"DEST={destid} "
                                f"Expected={expected} "
                                f"Written={written} "
                                f"Difference={written - expected}"
                            )

                run_input_balance = run_input - (
                    run_routed + run_no_route + run_error
                )
                run_output_balance = run_outputs - run_destinations

                log(
                    "RECON_RUN "
                    f"Input={run_input} "
                    f"Routed={run_routed} "
                    f"NoRoute={run_no_route} "
                    f"Error={run_error} "
                    f"DestinationsFound={run_destinations} "
                    f"OutputRowsWritten={run_outputs} "
                    f"InputBalance={run_input_balance} "
                    f"OutputBalance={run_output_balance}"
                )

            current_date = datetime.now().strftime("%Y-%m-%d")
            if DAILY_SUMMARY_ENABLED and current_date != daily_date:
                log_daily_summary(
                    daily_date,
                    daily_input,
                    daily_routed,
                    daily_no_route,
                    daily_error,
                    daily_destinations,
                    daily_outputs,
                )

                daily_date = current_date
                daily_input = 0
                daily_routed = 0
                daily_no_route = 0
                daily_error = 0
                daily_destinations = 0
                daily_outputs = 0

            now = time.time()
            if now - last_hb >= HEARTBEAT_SECS:
                log(
                    f"HEARTBEAT ProcessedThisCycle={cycle_input} "
                    f"{status_snapshot(con)}"
                )
                last_hb = now

            if sleep_interruptible(SLEEP_SECS):
                break

    finally:
        try:
            con.close()
        except Exception:
            pass

        if DAILY_SUMMARY_ENABLED and (
            daily_input or daily_no_route or daily_error or daily_outputs
        ):
            log_daily_summary(
                daily_date,
                daily_input,
                daily_routed,
                daily_no_route,
                daily_error,
                daily_destinations,
                daily_outputs,
            )

        log(
            "FINAL_RECON "
            f"Input={run_input} "
            f"Routed={run_routed} "
            f"NoRoute={run_no_route} "
            f"Error={run_error} "
            f"DestinationsFound={run_destinations} "
            f"OutputRowsWritten={run_outputs} "
            f"InputBalance="
            f"{run_input - (run_routed + run_no_route + run_error)} "
            f"OutputBalance={run_outputs - run_destinations}"
        )
        log("END")


if __name__ == "__main__":
    # 2026-08-12 Moved from top of module to here and put under guard to end
    signal.signal(signal.SIGINT, lambda s, f: STOP_EVENT.set())  # Controlled CTRL-C redirect - do not change  
    main()

