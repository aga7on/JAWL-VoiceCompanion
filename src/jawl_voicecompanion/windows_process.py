"""Create a worker inside its Windows Job before its first instruction.

Uses documented STARTUPINFOEX/JOB_LIST (Windows10+), never a suspended orphan
or a process-wide monkeypatch of subprocess. DEVNULL remains the default;
``pipe_stdio=True`` opts into owned binary stdin/stdout pipes.
"""
from __future__ import annotations

import ctypes
import io
from ctypes import wintypes as w
import math
import os
import subprocess
import sys
import threading


class _Startup(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                *[(name, w.DWORD) for name in ('x', 'y', 'cx', 'cy', 'chars_x', 'chars_y', 'fill', 'flags')],
                ('show', w.WORD), ('reserved_bytes', w.WORD), ('reserved_data', ctypes.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class _StartupEx(ctypes.Structure):
    _fields_ = [('startup', _Startup), ('attributes', ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class _Security(ctypes.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', w.BOOL)]


def _kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'InitializeProcThreadAttributeList': ([ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
        'UpdateProcThreadAttribute': ([ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
        'DeleteProcThreadAttributeList': ([ctypes.c_void_p], None),
        'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(_Security), w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        'CreatePipe': ([ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.POINTER(_Security), w.DWORD], w.BOOL),
        'SetHandleInformation': ([w.HANDLE, w.DWORD, w.DWORD], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                            ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(_StartupEx), ctypes.POINTER(_ProcessInfo)], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


class WindowsJobProcess:
    """Handle-owned subset of Popen used by RuntimeSupervisor."""
    def __init__(self, api, handle, pid, args, streams=None):
        self._lock = threading.Lock()
        self._api, self.pid, self.args, self.returncode = api, pid, args, None
        if streams is not None:
            self.stdin, self.stdout, self.stderr = streams
        self._handle = handle  # last: a partial constructor must not close factory's handle

    def poll(self):
        with self._lock:
            if self.returncode is None:
                result = self._api.WaitForSingleObject(self._handle, 0)
                if result == 258:  # WAIT_TIMEOUT; a real exit259 is not STILL_ACTIVE
                    return None
                if result != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
                code = w.DWORD()
                if not self._api.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.returncode = int(code.value)
            return self.returncode

    def wait(self, timeout=None):
        if self.poll() is not None:
            return self.returncode
        milliseconds = 0xFFFFFFFF if timeout is None else min(0xFFFFFFFE, max(0, math.ceil(timeout * 1000)))
        result = self._api.WaitForSingleObject(self._handle, milliseconds)
        if result == 258:
            raise subprocess.TimeoutExpired(self.args, timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is not None:
            return
        if not self._api.TerminateProcess(self._handle, 1):
            error = ctypes.get_last_error()
            if self.poll() is None:
                raise ctypes.WinError(error)

    kill = terminate

    def __del__(self):
        try:
            for name in ('stdin', 'stdout'):
                stream = getattr(self, name, None)
                if stream is not None:
                    stream.close()
            self._api.CloseHandle(self._handle)
        except Exception:
            pass


def _environment(env):
    if env is None:
        return None
    entries, seen = [], {}
    for key, value in env.items():
        key, value = os.fsdecode(key), os.fsdecode(value)
        if not key or '=' in key or '\0' in key or '\0' in value:
            raise OSError('invalid worker environment')  # never echo a credential value
        if key.casefold() in seen:
            if seen[key.casefold()] != value:
                raise OSError('conflicting worker environment aliases')
            continue
        seen[key.casefold()] = value
        entries.append((key, value))
    return ctypes.create_unicode_buffer('\0'.join(key + '=' + value for key, value in
                                                 sorted(entries, key=lambda pair: pair[0].casefold())) + '\0\0')


def create_job_process(command, job, *, cwd=None, env=None, pipe_stdio=False, bufsize=0):
    if sys.platform != 'win32' or not job:
        raise OSError('atomic Windows Job creation unavailable')
    job_handles = tuple(job) if isinstance(job, (tuple, list)) else (job,)
    if not job_handles or any(not handle for handle in job_handles):
        raise OSError('atomic Windows Job creation unavailable')
    args = [os.fsdecode(part) for part in command]
    if not args or any('\0' in part for part in args):
        raise OSError('invalid worker command')
    environment = _environment(env)
    api = _kernel()
    size = ctypes.c_size_t()
    api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    if not size.value or ctypes.get_last_error() != 122:  # expected insufficient-buffer sizing call
        raise ctypes.WinError(ctypes.get_last_error())
    memory = ctypes.create_string_buffer(size.value)
    attributes = ctypes.cast(memory, ctypes.c_void_p)
    initialized, null, info = False, None, _ProcessInfo()
    child_handles, parent_handles, streams, transferred = [], [], [], False

    def valid(handle):
        return handle is not None and handle != 0 and handle != w.HANDLE(-1).value

    def close_handle(handle):
        if valid(handle):
            api.CloseHandle(handle)

    def pipe_stream(handle, mode, flags):
        import msvcrt
        descriptor = msvcrt.open_osfhandle(int(handle), flags | os.O_BINARY)
        # open_osfhandle transfers ownership to the CRT on success.
        parent_handles.remove(handle)
        try:
            return io.open(descriptor, mode, buffering=bufsize)
        except BaseException:
            os.close(descriptor)
            raise

    try:
        if not api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        initialized = True
        security = _Security(ctypes.sizeof(_Security), None, True)
        null = api.CreateFileW('NUL', 0xC0000000, 3, ctypes.byref(security), 3, 0x80, None)
        if not valid(null):
            raise ctypes.WinError(ctypes.get_last_error())

        if pipe_stdio:
            stdin_read, stdin_write = w.HANDLE(), w.HANDLE()
            stdout_read, stdout_write = w.HANDLE(), w.HANDLE()
            for index, (read_end, write_end) in enumerate(((stdin_read, stdin_write),
                                                            (stdout_read, stdout_write))):
                if not api.CreatePipe(ctypes.byref(read_end), ctypes.byref(write_end),
                                      ctypes.byref(security), 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                if index == 0:
                    child_handles.append(read_end.value)
                    parent_handles.append(write_end.value)
                else:
                    parent_handles.append(read_end.value)
                    child_handles.append(write_end.value)
            # The parent's endpoints must never enter the child's inherited handle set.
            for parent_end in (stdin_write.value, stdout_read.value):
                if not api.SetHandleInformation(parent_end, 1, 0):  # HANDLE_FLAG_INHERIT
                    raise ctypes.WinError(ctypes.get_last_error())
            child_stdin_handle, child_stdout_handle = stdin_read.value, stdout_write.value
            inherited = (w.HANDLE * 3)(child_stdin_handle, child_stdout_handle, null)
        else:
            inherited = (w.HANDLE * 1)(null)
        jobs = (w.HANDLE * len(job_handles))(*(int(handle) for handle in job_handles))
        # Only child stdio and NUL are inherited, never parent pipe ends or Jobs.
        for key, value in ((0x20002, inherited), (0x2000D, jobs)):
            if not api.UpdateProcThreadAttribute(attributes, 0, key, ctypes.cast(value, ctypes.c_void_p),
                                                  ctypes.sizeof(value), None, None):
                raise ctypes.WinError(ctypes.get_last_error())
        startup = _StartupEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.startup.stdin = child_stdin_handle if pipe_stdio else null
        startup.startup.stdout = child_stdout_handle if pipe_stdio else null
        startup.startup.stderr = null
        startup.attributes = attributes
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        flags = 0x80000 | 0x400 | 0x8000000  # EXTENDED_STARTUPINFO, UNICODE_ENV, NO_WINDOW
        if not api.CreateProcessW(None, line, None, None, True, flags, environment,
                                  os.fsdecode(cwd) if cwd is not None else None,
                                  ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if pipe_stdio:
            for index, handle in enumerate(child_handles):
                close_handle(handle)
                child_handles[index] = None
            streams.append(pipe_stream(parent_handles[0], 'wb', os.O_WRONLY))
            streams.append(pipe_stream(parent_handles[0], 'rb', os.O_RDONLY))
            streams.append(None)
        process = WindowsJobProcess(api, info.process, int(info.pid), command,
                                    tuple(streams) if pipe_stdio else None)
        info.process = None  # ownership transferred; descendants already born inside Job
        transferred = True
        return process
    finally:
        if info.thread:
            api.CloseHandle(info.thread)
        if info.process:
            api.TerminateProcess(info.process, 1)
            api.WaitForSingleObject(info.process, 2000)
            api.CloseHandle(info.process)
        if not transferred:
            for stream in streams:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
        for handle in child_handles:
            close_handle(handle)
        for handle in parent_handles:
            close_handle(handle)
        if initialized:
            api.DeleteProcThreadAttributeList(attributes)
        if null is not None and null != w.HANDLE(-1).value:
            api.CloseHandle(null)
