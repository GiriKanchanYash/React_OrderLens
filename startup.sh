#!/usr/bin/env bash
# Azure App Service (Linux, native Python runtime) startup for the Order
# Lens FastAPI backend.
#
# The container filesystem outside /home is reset on every cold start and
# every scale-out instance, so ODBC Driver 18 for SQL Server (required by
# pyodbc) has to be (re)installed here rather than once - this script runs
# as root on every boot, which is exactly what Microsoft's own guidance for
# pyodbc on native App Service Linux relies on:
# https://learn.microsoft.com/troubleshoot/azure/general/connect-sql-database-source-code
set -e
 
if ! command -v odbcinst >/dev/null 2>&1 || ! odbcinst -q -d | grep -qi "ODBC Driver 18"; then
    echo "Installing ODBC Driver 18 for SQL Server..."
    apt-get update -qq
    apt-get install -y -qq curl gnupg apt-transport-https unixodbc unixodbc-dev > /dev/null
    curl -sSL https://packages.microsoft.com/keys/microsoft.asc | apt-key add - > /dev/null 2>&1
    curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y -qq msodbcsql18 > /dev/null
else
    echo "ODBC Driver 18 already present, skipping install."
fi
 
cd /home/site/wwwroot
if [ -f "/home/site/wwwroot/antenv/bin/activate" ]; then
    source /home/site/wwwroot/antenv/bin/activate
else
    python -m pip install --upgrade pip -q
    pip install -r requirements.txt -q
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"