@echo off
setlocal
if "%EPOCROOT%"=="" set EPOCROOT=\Symbian\8.1a\S60_2nd_FP3\
set PATH=C:%EPOCROOT%epoc32\tools;C:%EPOCROOT%epoc32\gcc\bin;C:\Perl\bin;%PATH%
cd /d %~dp0group
call bldmake bldfiles
if errorlevel 1 exit /b 1
call abld build armi urel
if errorlevel 1 exit /b 1
echo Output: C:%EPOCROOT%epoc32\release\armi\urel\abtesrv.dll
