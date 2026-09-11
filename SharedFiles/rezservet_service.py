import os
import sys
import servicemanager
import win32event
import win32service
import win32serviceutil

import rezservet


class RezServeTService(win32serviceutil.ServiceFramework):
    _svc_name_ = "REZSERVET"
    _svc_display_name_ = "West Pier REZSERVET"
    _svc_description_ = "Processes reservation records and routes them to configured destinations."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

        # Tell existing REZSERVET code to stop cleanly
        rezservet.STOP_EVENT.set()

        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("REZSERVET service starting")

        try:
            os.chdir(rezservet.BASE_DIR)
            rezservet.main()

        except Exception as exc:
            servicemanager.LogErrorMsg(
                f"REZSERVET service failed: {type(exc).__name__}: {exc}"
            )
            raise

        finally:
            servicemanager.LogInfoMsg("REZSERVET service stopped")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(RezServeTService)