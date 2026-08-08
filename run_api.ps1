# Serves the mobile snapshot (data/export/) over the network with CORS.
#
# Run:
#   .\run_api.ps1                  # http://0.0.0.0:8000/snapshot.json
#   .\run_api.ps1 -Token "secret"  # require Authorization: Bearer secret
#
# NOTE: For over-the-internet access, expose this behind HTTPS + auth
# (Tailscale is the easiest: phone and PC on the same tailnet). Do NOT expose
# it to the public internet with the default (no-token) settings.

param(
    [int]$Port = 8000,
    [string]$Bind = "0.0.0.0",
    [string]$Token = "",
    [switch]$Web
)

if ($Token) { $env:GESTOR_API_TOKEN = $Token }

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Serving mobile snapshot on http://$Bind`:$Port"
Write-Host "  Snapshot : /snapshot.json"
Write-Host "  Health   : /healthz"
if ($Web) { Write-Host "  Dashboard: /  (browser preview of app/web)" }
if ($Token) { Write-Host "  Token auth: ENABLED" }

& $py "src\export\server.py" --host $Bind --port $Port $(if ($Web) { "--web" })
