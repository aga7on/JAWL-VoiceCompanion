from pycaw.pycaw import AudioUtilities
from comtypes import CoInitialize, CoUninitialize

CoInitialize()
sessions = AudioUtilities.GetAllSessions()
print(f"Total audio sessions: {len(sessions)}")
for s in sessions:
    proc = s.Process
    name = proc.name() if proc else "System"
    print(f"Session process: {name} | volume={s.SimpleAudioVolume.GetMasterVolume()}")
CoUninitialize()
