from server import PromptServer  # type:ignore
import folder_paths  # type:ignore
import os
import threading
import time
import datetime


CATEGORY = "HotReload"


# ------------ Terminal ------------
class HotReload_Terminal:

    CATEGORY = CATEGORY

    @classmethod
    def INPUT_TYPES(s):
        return {"optional": {}}

    RETURN_TYPES = ()
    FUNCTION = "Func"

    def Func(self):
        pass


# file terminal checker
CHECKER_THREAD_NAME = "HotReload.LogFileChecker"


# func checker
def LogFileChecker(selfStamp):

    CheckedLine = 0
    CheckedDateSec = 0.0

    while True:
        try:

            # check for stop
            for thread in threading.enumerate():
                if thread.name == CHECKER_THREAD_NAME:
                    stamp = thread.__dict__.get("stamp")
                    if stamp > selfStamp:
                        return

            # check file
            port = PromptServer.instance.port if hasattr(PromptServer.instance, "port") else 8000

            logFilePath = os.path.join(folder_paths.get_user_directory(), f"comfyui_{port}.log")
            if os.path.isfile(logFilePath):
                fileDateSec = os.path.getmtime(logFilePath)
                if fileDateSec > CheckedDateSec + 0.1:
                    requareClear = CheckedLine == 0
                    CheckedDateSec = fileDateSec
                    resultText = ""
                    with open(logFilePath, "r") as file:
                        currentLine = 0
                        for line in file:
                            if currentLine > CheckedLine:
                                CheckedLine = currentLine
                                resultText += line + "\n"
                            currentLine += 1
                    PromptServer.instance.send_sync(
                        "/hotreload.terminal.log", {"text": resultText, "clear": requareClear}
                    )
        finally:
            # loop
            time.sleep(1)


# get current largest stamp
currentMaxStamp = 0
for thread in threading.enumerate():
    if thread.name == CHECKER_THREAD_NAME:
        stamp = thread.__dict__.get("stamp")
        currentMaxStamp = max(currentMaxStamp, stamp)

# start new checker
timestamp = max(int(datetime.datetime.now().timestamp()), currentMaxStamp + 1)
newThread = threading.Thread(target=LogFileChecker, name=CHECKER_THREAD_NAME, args=(timestamp,))
newThread.__dict__["stamp"] = timestamp
newThread.start()
