# Start Cerebrum Blocks local dev stack (mock API + Vite frontend)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "Starting mock backend on http://localhost:8000 ..."
Start-Process -FilePath "python" -ArgumentList "dev/mock_backend.py" -WorkingDirectory $Root -WindowStyle Minimized

Start-Sleep -Seconds 2

Write-Host "Starting frontend on http://localhost:5173 ..."
Set-Location (Join-Path $Root "frontend")
npm run dev
