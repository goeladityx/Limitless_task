@echo off
REM ============================================================================
REM  One file. Double click it and the console opens.
REM
REM  Installs the three dependencies, starts Postgres, builds the schema, loads
REM  both companies, runs every test, then serves the site and opens a browser.
REM  If any test fails it stops without serving anything, because a demo that
REM  opens on a wrong number is worse than one that does not open.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Pellet Console

echo.
echo   ============================================================
echo     Pellet Console
echo   ============================================================
echo.

REM ---------------------------------------------------------------- python
where python >nul 2>&1
if errorlevel 1 goto nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 goto oldpython
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [1/5] Python %PYVER%

REM  nothing else may already be on the port, or we would build for two minutes
REM  and only then find there is nowhere to listen
python -c "import socket,sys; s=socket.socket(); r=s.connect_ex(('127.0.0.1',8000)); s.close(); sys.exit(1 if r==0 else 0)" >nul 2>&1
if errorlevel 1 goto portbusy

REM ---------------------------------------------------------------- dependencies
REM  Into a virtual environment inside the repo, never into their system Python.
REM  It leaves their machine as it found it, and it survives a Python that will
REM  not be written to.
echo   [2/5] Installing dependencies
set PY=python
if not exist ".venv\Scripts\python.exe" python -m venv .venv >nul 2>&1
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto nodeps

REM ---------------------------------------------------------------- database
if "%DATABASE_URL%"=="" set DATABASE_URL=postgresql://pellet_app:pellet_app@localhost:5432/pellet
if "%ADMIN_DATABASE_URL%"=="" set ADMIN_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pellet

echo   [3/5] Looking for Postgres
%PY% db\wait.py >nul 2>&1
if not errorlevel 1 goto dbready

REM  nothing listening, so start one in Docker
where docker >nul 2>&1
if errorlevel 1 goto nodb
echo         none found, starting one in Docker
docker compose up -d
if not errorlevel 1 goto dbwait
REM  older installs still have it as a separate command
where docker-compose >nul 2>&1
if errorlevel 1 goto dockerfailed
docker-compose up -d
if errorlevel 1 goto dockerfailed
:dbwait
echo         waiting for it to accept connections
%PY% db\wait.py 90 >nul 2>&1
if errorlevel 1 goto dbtimeout

:dbready
echo         connected

REM ---------------------------------------------------------------- build and test
echo   [4/5] Building the data and running every test
echo.
%PY% setup.py
if errorlevel 1 goto testsfailed

REM ---------------------------------------------------------------- serve
echo.
echo   [5/5] Serving
echo.
echo   ------------------------------------------------------------
echo     Open   http://localhost:8000
echo     Stop   press Ctrl+C in this window
echo   ------------------------------------------------------------
echo.
start "" http://localhost:8000
%PY% -m uvicorn app.api:app --host 127.0.0.1 --port 8000
goto done

REM ---------------------------------------------------------------- failures
:nopython
echo   [x] Python is not on your PATH.
echo       Install Python 3.11 or later from python.org, tick
echo       "Add python.exe to PATH" during setup, and run this again.
goto stop

:oldpython
echo   [x] This needs Python 3.11 or later.
python --version
goto stop

:portbusy
echo.
echo   [x] Something is already using port 8000 on this machine, so the
echo       console would have nowhere to listen. Close it and run this
echo       again. To find out what it is:
echo           netstat -ano ^| findstr :8000
goto stop

:nodeps
echo.
echo   [x] Could not install the dependencies. It needs three: psycopg,
echo       fastapi and uvicorn. Try this and read the error:
echo           python -m pip install -r requirements.txt
goto stop

:nodb
echo.
echo   [x] No Postgres is running and Docker is not installed.
echo.
echo       Either start Docker Desktop and run this again, or point this
echo       at a Postgres you already have by setting two variables first:
echo.
echo         set DATABASE_URL=postgresql://pellet_app:pellet_app@HOST:PORT/pellet
echo         set ADMIN_DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/pellet
goto stop

:dockerfailed
echo.
echo   [x] Docker is installed but would not start the database.
echo       Is Docker Desktop actually running? Check with:
echo           docker compose up -d
goto stop

:dbtimeout
echo.
echo   [x] Postgres did not accept connections within ninety seconds.
echo       Check what it is doing with:
echo           docker compose logs db
goto stop

:testsfailed
echo.
echo   [x] Something did not pass, so nothing has been served. That is on
echo       purpose: a demo that opens on a wrong number is worse than one
echo       that does not open. The failure is printed above.
goto stop

:stop
echo.
pause
endlocal
exit /b 1

:done
endlocal
