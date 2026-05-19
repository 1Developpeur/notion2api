param(
    [string]$CouncilRoot = "X:\Code\llm-council-plus",
    [int]$NotionPort = 8000,
    [int]$CouncilBackendPort = 8001,
    [int]$CouncilFrontendPort = 5173,
    [switch]$RefreshLogin,
    [switch]$NoBrowser,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$NotionRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$CouncilRootPath = Resolve-Path $CouncilRoot
$LogDir = Join-Path $NotionRoot "logs\launcher"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Get-Python {
    param([string]$Root)
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Stop-ProjectProcesses {
    $currentPid = $PID
    $notionPattern = [regex]::Escape($NotionRoot.Path)
    $councilPattern = [regex]::Escape($CouncilRootPath.Path)
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $currentPid -and
        $_.CommandLine -and
        (
            ($_.CommandLine -match $notionPattern -and $_.CommandLine -match "uvicorn.*app\.server") -or
            ($_.CommandLine -match $councilPattern -and $_.CommandLine -match "backend\.main|vite|npm run dev")
        )
    }

    foreach ($target in $targets) {
        Write-Host "Stopping PID $($target.ProcessId): $($target.CommandLine)"
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Set-EnvLine {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $lines = if (Test-Path $Path) { @(Get-Content -Path $Path) } else { @() }
    $updated = $false
    $newLines = foreach ($line in $lines) {
        if ($line.TrimStart().StartsWith("$Name=")) {
            $updated = $true
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) {
        $newLines += "$Name=$Value"
    }
    Set-Content -Path $Path -Value $newLines -Encoding UTF8
}

function Assert-NotionMode {
    $envFile = Join-Path $NotionRoot ".env"
    Set-EnvLine -Path $envFile -Name "APP_MODE" -Value "standard"
}

function Test-NotionLogin {
    $python = Get-Python -Root $NotionRoot
    Push-Location $NotionRoot
    try {
        & $python "login.py" "--check"
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

function Assert-NotionLogin {
    if (-not $RefreshLogin -and (Test-NotionLogin)) {
        Write-Step "Notion token is valid"
        return
    }

    Write-Step "Refreshing Notion login session"
    $python = Get-Python -Root $NotionRoot
    Push-Location $NotionRoot
    try {
        & $python "login.py" "--timeout" "300"
        if ($LASTEXITCODE -ne 0) {
            throw "Notion login did not complete successfully."
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-NotionLogin)) {
        throw "Notion token check still fails after login."
    }
}

function Get-NotionApiKey {
    $envFile = Join-Path $NotionRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            $line = $line.Trim()
            if ($line.StartsWith("API_KEY=")) {
                return $line.Substring(8).Trim().Trim('"').Trim("'")
            }
        }
    }
    return ""
}

function Ensure-NotionApiKey {
    $envFile = Join-Path $NotionRoot ".env"
    $apiKey = Get-NotionApiKey
    if ($apiKey) {
        Write-Step "Using existing API_KEY from .env file"
        return $apiKey
    }

    Write-Step "API_KEY not found in .env, generating a new one."
    # Generate a URL-safe random string
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $newApiKey = [System.Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

    Set-EnvLine -Path $envFile -Name "API_KEY" -Value $newApiKey
    Write-Host "  >> Added API_KEY=$newApiKey to $envFile"
    return $newApiKey
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Start-NotionApi {
    $python = Get-Python -Root $NotionRoot
    $out = Join-Path $LogDir "notion2api.out.log"
    $err = Join-Path $LogDir "notion2api.err.log"
    Remove-Item $out, $err -ErrorAction SilentlyContinue

    Write-Step "Starting Notion2API on http://127.0.0.1:$NotionPort"
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", "$NotionPort") `
        -WorkingDirectory $NotionRoot `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -WindowStyle Hidden | Out-Null
    Wait-HttpOk -Url "http://127.0.0.1:$NotionPort/health" -TimeoutSeconds 45
}

function Start-CouncilBackend {
    $python = Get-Python -Root $CouncilRootPath
    $out = Join-Path $LogDir "council-backend.out.log"
    $err = Join-Path $LogDir "council-backend.err.log"
    Remove-Item $out, $err -ErrorAction SilentlyContinue

    Write-Step "Starting LLM Council backend on http://127.0.0.1:$CouncilBackendPort"
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "backend.main") `
        -WorkingDirectory $CouncilRootPath `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -WindowStyle Hidden | Out-Null
    Wait-HttpOk -Url "http://127.0.0.1:$CouncilBackendPort/api/settings" -TimeoutSeconds 45
}

function Update-CouncilSettings {
    param(
        [string]$NotionApiKey
    )
    $settingsPath = Join-Path $CouncilRootPath "data\settings.json"
    $settingsDir = Split-Path $settingsPath -Parent
    if (-not (Test-Path $settingsDir)) {
        New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null
    }

    $settings = if (Test-Path $settingsPath) {
        try {
            Get-Content -Path $settingsPath -Raw | ConvertFrom-Json
        } catch {
            Write-Warning "Could not parse existing settings.json, starting fresh."
            [pscustomobject]@{}
        }
    } else {
        [pscustomobject]@{}
    }

    # Use Add-Member -Force for robust property creation/update
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_name" -Value "Notion2API" -Force
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_url" -Value "http://127.0.0.1:$NotionPort/v1" -Force
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_api_key" -Value $NotionApiKey -Force

    if ($null -eq $settings.enabled_providers) {
        $settings | Add-Member -MemberType NoteProperty -Name "enabled_providers" -Value ([pscustomobject]@{}) -Force
    }
    $settings.enabled_providers | Add-Member -MemberType NoteProperty -Name "custom" -Value $true -Force

    # Set preferred models
    $models = @(
        "custom:gpt-5.5",
        "custom:claude-opus4.7",
        "custom:gemini-3.1pro",
        "custom:kimi-2.6"
    )
    $settings | Add-Member -MemberType NoteProperty -Name "council_models" -Value $models -Force
    $settings | Add-Member -MemberType NoteProperty -Name "chairman_model" -Value "custom:claude-opus4.7" -Force

    # Save using [System.IO.File]::WriteAllText to avoid UTF-8 BOM issues (Python JSON loader fails with BOM)
    $json = $settings | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($settingsPath, $json)
}

function Start-CouncilFrontend {
    $frontendRoot = Join-Path $CouncilRootPath "frontend"
    $out = Join-Path $LogDir "council-frontend.out.log"
    $err = Join-Path $LogDir "council-frontend.err.log"
    Remove-Item $out, $err -ErrorAction SilentlyContinue

    Write-Step "Starting LLM Council frontend on http://127.0.0.1:$CouncilFrontendPort"
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$CouncilFrontendPort") `
        -WorkingDirectory $frontendRoot `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -WindowStyle Hidden | Out-Null
    Wait-HttpOk -Url "http://127.0.0.1:$CouncilFrontendPort/" -TimeoutSeconds 45
}

if ($Stop) {
    Write-Step "Stopping launcher-managed services"
    Stop-ProjectProcesses
    exit 0
}

Write-Step "Preparing Notion2API + LLM Council"
Assert-NotionMode
Assert-NotionLogin
$NotionApiKey = Ensure-NotionApiKey
Update-CouncilSettings -NotionApiKey $NotionApiKey

Stop-ProjectProcesses
Start-Sleep -Seconds 1
Start-NotionApi
Start-CouncilBackend
Start-CouncilFrontend

Write-Host ""
Write-Host "Ready:"
Write-Host "  Notion2API:        http://127.0.0.1:$NotionPort"
Write-Host "  LLM Council API:   http://127.0.0.1:$CouncilBackendPort"
Write-Host "  LLM Council UI:    http://127.0.0.1:$CouncilFrontendPort"
Write-Host "  Logs:              $LogDir"
Write-Host ""
Write-Host "Stop later with:"
Write-Host "  .\launch-council.bat -Stop"

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$CouncilFrontendPort/"
}
