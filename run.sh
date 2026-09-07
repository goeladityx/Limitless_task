#!/usr/bin/env bash
# ============================================================================
#  One file. Run it and the console opens.
#
#  Installs the three dependencies, starts Postgres, builds the schema, loads
#  both companies, runs every test, then serves the site. If any test fails it
#  stops without serving anything, because a demo that opens on a wrong number
#  is worse than one that does not open.
# ============================================================================
set -u
cd "$(dirname "$0")"

say()  { printf '  %s\n' "$*"; }
die()  { printf '\n  [x] %s\n\n' "$*"; exit 1; }

echo
echo "  ============================================================"
echo "    Pellet Console"
echo "  ============================================================"
echo

# ---------------------------------------------------------------- python
PY=$(command -v python3 || command -v python) || die "Python is not installed. This needs 3.11 or later."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "This needs Python 3.11 or later. You have $("$PY" --version)."
say "[1/5] $("$PY" --version)"

# nothing else may already be on the port, or we would build for two minutes and
# only then find there is nowhere to listen
"$PY" -c "import socket,sys; s=socket.socket(); r=s.connect_ex(('127.0.0.1',8000)); s.close(); sys.exit(1 if r==0 else 0)" \
  || die "Something is already using port 8000 on this machine, so the console
      would have nowhere to listen. Close it and run this again. To find
      out what it is:
          lsof -i :8000"

# ---------------------------------------------------------------- dependencies
#  Into a virtual environment inside the repo, never into their system Python.
#  Homebrew and every Debian since 12 refuse the second one outright (PEP 668),
#  and that is the likeliest way this script dies on somebody else's machine. It
#  also means running this leaves nothing behind on their python.
say "[2/5] Installing dependencies"
[ -d .venv ] || "$PY" -m venv .venv >/dev/null 2>&1 || say "      no venv module here, using $PY as it is"
for c in .venv/bin/python .venv/Scripts/python.exe; do
  [ -x "$c" ] && PY="$PWD/$c" && break
done
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
  || "$PY" -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt \
  || die "Could not install the dependencies. It needs three: psycopg, fastapi and uvicorn.
      Try this and read the error:
          $PY -m pip install -r requirements.txt"

# ---------------------------------------------------------------- database
export DATABASE_URL="${DATABASE_URL:-postgresql://pellet_app:pellet_app@localhost:5432/pellet}"
export ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/pellet}"

say "[3/5] Looking for Postgres"
if ! "$PY" db/wait.py >/dev/null 2>&1; then
  command -v docker >/dev/null 2>&1 || die "No Postgres is running and Docker is not installed.

      Either start Docker and run this again, or point this at a Postgres you
      already have by exporting two variables first:

        export DATABASE_URL=postgresql://pellet_app:pellet_app@HOST:PORT/pellet
        export ADMIN_DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/pellet"
  say "      none found, starting one in Docker"
  docker compose up -d 2>/dev/null \
    || { command -v docker-compose >/dev/null 2>&1 && docker-compose up -d; } \
    || die "Docker is installed but would not start the database.
      Is the Docker daemon running? Check with:  docker compose up -d"
  say "      waiting for it to accept connections"
  "$PY" db/wait.py 90 >/dev/null 2>&1 \
    || die "Postgres did not accept connections within ninety seconds.
      Check what it is doing with:  docker compose logs db"
fi
say "      connected"

# ---------------------------------------------------------------- build and test
say "[4/5] Building the data and running every test"
echo
"$PY" setup.py || die "Something did not pass, so nothing has been served. That is on
      purpose: a demo that opens on a wrong number is worse than one that
      does not open. The failure is printed above."

# ---------------------------------------------------------------- serve
echo
say "[5/5] Serving"
echo
echo "  ------------------------------------------------------------"
echo "    Open   http://localhost:8000"
echo "    Stop   press Ctrl+C"
echo "  ------------------------------------------------------------"
echo
( sleep 2; (command -v open >/dev/null && open http://localhost:8000) \
        || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) ) >/dev/null 2>&1 &
exec "$PY" -m uvicorn app.api:app --host 127.0.0.1 --port 8000
