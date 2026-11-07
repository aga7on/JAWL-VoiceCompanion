@echo off
setlocal
set "VSROOT=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools"
if not exist "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" exit /b 2
call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
if not exist "%~dp0..\runtime\bin\process-loopback" mkdir "%~dp0..\runtime\bin\process-loopback"
pushd "%~dp0..\runtime\bin\process-loopback"
cl /nologo /std:c++17 /EHsc /O2 "%~dp0..\native\process_loopback.cpp" /Fe:process-loopback.exe /link ole32.lib runtimeobject.lib mmdevapi.lib
set "BUILD_RESULT=%errorlevel%"
popd
exit /b %BUILD_RESULT%
