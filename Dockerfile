FROM python:3.11-slim

# --- ODBC Driver 18 for SQL Server + unixODBC (required by pyodbc) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg apt-transport-https unixodbc unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY orderlens_metadata.yaml ./orderlens_metadata.yaml

EXPOSE 8000

# Azure Web App for Containers routes to whatever port WEBSITES_PORT is set
# to in App Settings -- set that to 8000 to match this.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
