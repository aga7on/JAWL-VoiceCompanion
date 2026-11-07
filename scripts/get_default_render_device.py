from pycaw.pycaw import AudioUtilities, EDataFlow, ERole
from comtypes import CoInitialize, CoUninitialize

CoInitialize()
device_enumerator = AudioUtilities.GetDeviceEnumerator()
default_device = device_enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
print("Device ID:", default_device.GetId())
for d in AudioUtilities.GetAllDevices():
    if d.id == default_device.GetId():
        print("Default Multimedia Render Device:", d.FriendlyName)
CoUninitialize()
