// Windows process-tree loopback. PCM16 stereo 44.1 kHz is written to stdout;
// diagnostics and readiness go to stderr. No audio file is created.
// Uses the Windows application loopback API illustrated by Microsoft's
// Windows-classic-samples/Samples/ApplicationLoopback (MIT license).
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

using Microsoft::WRL::ComPtr;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;
using Microsoft::WRL::ClassicCom;
using Microsoft::WRL::FtmBase;

class Activation final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, FtmBase,
                                               IActivateAudioInterfaceCompletionHandler> {
public:
    HANDLE ready = nullptr;
    HRESULT result = E_FAIL;
    ComPtr<IAudioClient> client;
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* operation) override {
        HRESULT activation = E_FAIL;
        ComPtr<IUnknown> instance;
        result = operation->GetActivateResult(&activation, &instance);
        if (SUCCEEDED(result)) result = activation;
        if (SUCCEEDED(result)) result = instance.As(&client);
        SetEvent(ready);
        return S_OK;
    }
};

static bool write_all(HANDLE out, const BYTE* data, DWORD size) {
    while (size) {
        DWORD written = 0;
        if (!WriteFile(out, data, size, &written, nullptr) || !written) return false;
        data += written;
        size -= written;
    }
    return true;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    wchar_t* end = nullptr;
    const unsigned long pid = std::wcstoul(argv[1], &end, 10);
    if (!pid || !end || *end) return 2;
    HANDLE target = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!target) { std::fprintf(stderr, "target unavailable\n"); return 3; }
    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HANDLE samples = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!ready || !samples || !stop) return 3;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 3;
    auto callback = Microsoft::WRL::Make<Activation>();
    if (!callback) return 3;
    callback->ready = ready;
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    PROPVARIANT prop{};
    prop.vt = VT_BLOB;
    prop.blob.cbSize = sizeof(params);
    prop.blob.pBlobData = reinterpret_cast<BYTE*>(&params);
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient),
                                     &prop, callback.Get(), &operation);
    if (FAILED(hr) || WaitForSingleObject(ready, 15000) != WAIT_OBJECT_0 || FAILED(callback->result)) {
        std::fprintf(stderr, "activation failed\n"); return 3;
    }
    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 2;
    format.nSamplesPerSec = 44100;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 4;
    format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;
    ComPtr<IAudioCaptureClient> capture;
    hr = callback->client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
        0, 0, &format, nullptr);
    if (SUCCEEDED(hr)) hr = callback->client->GetService(IID_PPV_ARGS(&capture));
    if (SUCCEEDED(hr)) hr = callback->client->SetEventHandle(samples);
    if (SUCCEEDED(hr)) hr = callback->client->Start();
    if (FAILED(hr)) { std::fprintf(stderr, "capture initialization failed\n"); return 3; }
    // Fixed handshake separates initialization failures from a silent stream.
    const BYTE header[] = {'J','A','W','L','P','C','M','1'};
    if (!write_all(GetStdHandle(STD_OUTPUT_HANDLE), header, sizeof(header))) return 4;
    std::fprintf(stderr, "ready 44100 2 s16le\n");
    std::fflush(stderr);
    std::thread([stop]() {
        char command;
        DWORD read = 0;
        while (ReadFile(GetStdHandle(STD_INPUT_HANDLE), &command, 1, &read, nullptr) && read && command != 'q') {}
        SetEvent(stop);
    }).detach();
    HANDLE events[] = {samples, stop, target};
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    bool success = true;
    while (WaitForMultipleObjects(3, events, FALSE, INFINITE) == WAIT_OBJECT_0) {
        UINT32 frames = 0;
        while (SUCCEEDED(capture->GetNextPacketSize(&frames)) && frames) {
            BYTE* data = nullptr;
            DWORD flags = 0;
            hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) { success = false; break; }
            DWORD size = frames * format.nBlockAlign;
            std::vector<BYTE> silence;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) { silence.resize(size); data = silence.data(); }
            const bool written = data && write_all(out, data, size);
            capture->ReleaseBuffer(frames);
            if (!written) { success = false; break; }
        }
        if (!success) break;
    }
    callback->client->Stop();
    CloseHandle(target); CloseHandle(samples); CloseHandle(ready);
    // The stdin reader is process-lifetime; let process exit reclaim its event.
    return success ? 0 : 4;
}
