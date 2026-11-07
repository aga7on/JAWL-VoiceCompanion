from pycaw.pycaw import AudioUtilities
from comtypes import CoInitialize, CoUninitialize

CoInitialize()
devices = AudioUtilities.GetAllDevices()
for d in devices:
    print(f"Device: {d.FriendlyName} | state={d.state} | id={d.id}")
CoUninitialize()
