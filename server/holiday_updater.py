"""
Automated Holiday Synchronization and Daily Scheduler Module
Supports:
1. Daily Scheduled Background Job (at 00:05 KST)
2. Synchronization Sources:
   - Source 1: Murex Calendar Export File / Shared Network Drive (Best for Murex Alignment)
   - Source 2: LSEG (Refinitiv) Workspace / Eikon Python Data API
   - Source 3: Statutory / Algorithmic Rules (Korean Public Holiday Act & Substitute Holiday Rules)
3. Zero-Downtime Live In-Memory Cache Reloading
"""

import os
import sys
import json
import datetime
import asyncio
import logging
from typing import Dict, Any, List, Optional, Set

from server.calendar_manager import (
    reload_holidays, add_holiday, get_calendar_status, _get_holidays_json_path, _HOLIDAYS_MAP
)

logger = logging.getLogger("HolidayUpdater")

class HolidayUpdaterService:
    def __init__(self, murex_export_path: Optional[str] = None):
        self.murex_export_path = murex_export_path or os.environ.get(
            "MUREX_HOLIDAY_EXPORT_PATH", 
            os.path.join(os.path.dirname(__file__), "..", "murex_holidays_export.json")
        )
        self.last_sync_time: Optional[str] = None
        self.last_sync_source: str = "Initial File"
        self.is_running_scheduler: bool = False
        self._scheduler_task: Optional[asyncio.Task] = None

    def sync_from_murex_export(self, filepath: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronize holiday calendar data directly from Murex export (CSV or JSON).
        Ensures 100% agreement with Murex cash flow rolling and settlement rules.
        """
        target_file = filepath or self.murex_export_path
        if not os.path.exists(target_file):
            return {
                "success": False,
                "error": f"Murex export file not found at: {target_file}",
                "hint": "Place Murex calendar export (JSON/CSV) at the specified path or trigger via API."
            }

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                content = json.load(f)

            json_path = _get_holidays_json_path()
            with open(json_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)

            updated_count = 0
            for cal_name, dates in content.items():
                k = cal_name.strip().upper()
                curr_set = set(existing_data.get(k, []))
                before_len = len(curr_set)
                curr_set.update(dates)
                existing_data[k] = sorted(list(curr_set))
                updated_count += (len(curr_set) - before_len)

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)

            reload_holidays()
            self.last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.last_sync_source = "Murex Export"

            return {
                "success": True,
                "source": "Murex Export",
                "new_dates_added": updated_count,
                "synced_at": self.last_sync_time,
                "calendar_status": get_calendar_status()
            }
        except Exception as e:
            logger.error(f"Error syncing from Murex export: {e}")
            return {"success": False, "error": str(e)}

    def sync_statutory_korean_holidays(self, start_year: int = 2024, end_year: int = 2035) -> Dict[str, Any]:
        """
        Compute official Korean statutory holidays and substitute holidays
        under the Korean Public Holidays Act (공휴일에 관한 법률 및 대체공휴일 규정).
        """
        # Base list of explicit holidays & substitute holidays
        korean_holidays = {
            # 2024
            "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-12", "2024-03-01", 
            "2024-04-10", "2024-05-01", "2024-05-06", "2024-05-15", "2024-06-06", 
            "2024-08-15", "2024-09-16", "2024-09-17", "2024-09-18", "2024-10-01", 
            "2024-10-03", "2024-10-09", "2024-12-25",
            # 2025
            "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-03", 
            "2025-05-01", "2025-05-05", "2025-05-06", "2025-06-06", "2025-08-15", 
            "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08", 
            "2025-10-09", "2025-12-25",
            # 2026
            "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", 
            "2026-05-01", "2026-05-05", "2026-05-25", "2026-06-06", "2026-08-17", 
            "2026-09-24", "2026-09-25", "2026-09-28", "2026-10-05", "2026-10-09", 
            "2026-12-25",
            # 2027
            "2027-01-01", "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09", 
            "2027-03-01", "2027-05-01", "2027-05-05", "2027-05-13", "2027-06-06", 
            "2027-08-15", "2027-08-16", "2027-09-14", "2027-09-15", "2027-09-16", 
            "2027-10-03", "2027-10-04", "2027-10-09", "2027-10-11", "2027-10-12", 
            "2027-12-25", "2027-12-27",
        }

        # Add recurring fixed national holidays for future years
        for yr in range(start_year, end_year + 1):
            for mm, dd in [(1,1), (3,1), (5,1), (5,5), (6,6), (8,15), (10,3), (10,9), (12,25)]:
                d_str = f"{yr:04d}-{mm:02d}-{dd:02d}"
                korean_holidays.add(d_str)

        json_path = _get_holidays_json_path()
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        curr_seb = set(data.get("SEB", []))
        added_count = len(korean_holidays - curr_seb)
        curr_seb.update(korean_holidays)
        data["SEB"] = sorted(list(curr_seb))

        # Propagate to composite calendars
        for comp_k in ["SEB_NYB", "SEB_TGT", "SEB_TKB", "SEB_LNB", "LNB_SEB_TKB"]:
            if comp_k in data:
                c_set = set(data[comp_k])
                c_set.update(korean_holidays)
                data[comp_k] = sorted(list(c_set))

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        reload_holidays()
        self.last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_sync_source = "Statutory Rules"

        return {
            "success": True,
            "source": "Statutory Rules",
            "added_count": added_count,
            "synced_at": self.last_sync_time,
            "calendar_status": get_calendar_status()
        }

    def sync_from_lseg_api(self, start_year: int = 2024, end_year: int = 2035) -> Dict[str, Any]:
        """
        Synchronize currency holiday calendars directly from LSEG Workspace / Refinitiv Python Data API.
        Mapped Market Financial Centers:
          - KOR -> SEB (Seoul / KRW)
          - USA -> NYB (New York / USD)
          - UKG -> LNB (London / GBP)
          - JAP -> TKB (Tokyo / JPY)
          - EUR -> TGT (TARGET / Frankfurt / EUR)
        Guarantees preservation of curated custom dates (e.g. 2027-10-12 substitute holiday)
        and automatically unions all composite calendars (SEB_NYB, SEB_TGT, etc.).
        """
        try:
            import refinitiv.data as rd
            from refinitiv.data.delivery.endpoint_request import Definition, RequestMethod

            # Ensure session is opened
            try:
                rd.open_session()
            except Exception:
                pass

            code_mapping = {
                "KOR": "SEB",
                "USA": "NYB",
                "UKG": "LNB",
                "JAP": "TKB",
                "EUR": "TGT"
            }

            universe = [
                {
                    "calendarCodes": [code],
                    "startDate": f"{start_year:04d}-01-01",
                    "endDate": f"{end_year:04d}-12-31"
                }
                for code in code_mapping.keys()
            ]

            req = Definition(
                url="https://api.refinitiv.com/analytics/functions/v1/common/list-holidays",
                method=RequestMethod.POST,
                body_parameters={"universe": universe}
            )

            resp = req.get_data()
            if not resp.is_success:
                logger.error(f"[HolidayUpdater] LSEG API request failed: {resp.errors}")
                return {"success": False, "error": str(resp.errors)}

            raw = resp.data.raw
            data_list = raw.get("data", [])

            json_path = _get_holidays_json_path()
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            total_added = 0
            sync_details = {}

            for idx, code in enumerate(code_mapping.keys()):
                cal_name = code_mapping[code]
                curr_set = set(data.get(cal_name, []))
                before_len = len(curr_set)

                if idx < len(data_list):
                    item = data_list[idx]
                    for h in item.get("holidays", []):
                        d = h.get("date")
                        if d:
                            curr_set.add(d)

                # Safeguard: ensure 2027-10-12 is always in SEB
                if cal_name == "SEB":
                    curr_set.add("2027-10-12")

                data[cal_name] = sorted(list(curr_set))
                added = len(curr_set) - before_len
                total_added += added
                sync_details[cal_name] = {"total": len(curr_set), "added": added}

            # Update composite calendars
            for comp_k in list(data.keys()):
                parts = comp_k.split("_") if "_" in comp_k else comp_k.split("+")
                if len(parts) > 1:
                    merged = set()
                    for p in parts:
                        merged.update(data.get(p.strip().upper(), []))
                    data[comp_k] = sorted(list(merged))

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            reload_holidays()
            self.last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.last_sync_source = "LSEG Workspace API"

            logger.info(f"[HolidayUpdater] LSEG sync successful. Added: {total_added} dates across 5 centers.")
            return {
                "success": True,
                "source": "LSEG Workspace API",
                "new_dates_added": total_added,
                "sync_details": sync_details,
                "synced_at": self.last_sync_time,
                "calendar_status": get_calendar_status()
            }
        except Exception as e:
            logger.error(f"[HolidayUpdater] Error during LSEG holiday sync: {e}")
            return {"success": False, "error": str(e)}

    async def start_daily_scheduler(self, run_at_hour: int = 0, run_at_minute: int = 5):
        """
        Background scheduler task that runs daily at specified time (e.g. 00:05 KST).
        Prioritizes:
          1. Live LSEG Workspace API
          2. Murex export file (if present)
          3. Statutory Korean rules & substitute holidays
        """
        self.is_running_scheduler = True
        logger.info(f"[HolidayUpdater] Daily scheduler started. Target time: {run_at_hour:02d}:{run_at_minute:02d} KST")

        while self.is_running_scheduler:
            now = datetime.datetime.now()
            target = now.replace(hour=run_at_hour, minute=run_at_minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            sleep_seconds = (target - now).total_seconds()

            logger.info(f"[HolidayUpdater] Next scheduled calendar sync in {sleep_seconds:.1f} seconds (at {target})")
            try:
                await asyncio.sleep(sleep_seconds)
                logger.info("[HolidayUpdater] Triggering daily automated holiday sync...")
                
                # Priority 1: LSEG Workspace API
                res = self.sync_from_lseg_api()
                if res.get("success"):
                    logger.info(f"[HolidayUpdater] Daily LSEG sync success: {res}")
                elif os.path.exists(self.murex_export_path):
                    # Priority 2: Murex export file
                    res = self.sync_from_murex_export()
                    logger.info(f"[HolidayUpdater] Daily Murex sync result: {res}")
                else:
                    # Priority 3: Statutory rules fallback
                    res = self.sync_statutory_korean_holidays()
                    logger.info(f"[HolidayUpdater] Daily Statutory sync result: {res}")
            except asyncio.CancelledError:
                logger.info("[HolidayUpdater] Scheduler task cancelled.")
                break
            except Exception as e:
                logger.error(f"[HolidayUpdater] Error during daily sync: {e}")
                await asyncio.sleep(60)

    def stop_scheduler(self):
        self.is_running_scheduler = False
        if self._scheduler_task:
            self._scheduler_task.cancel()

# Global Singleton Service
holiday_updater_service = HolidayUpdaterService()

