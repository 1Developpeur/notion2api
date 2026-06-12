param(
    [string]$CouncilRoot = "",
    [int]$NotionPort = 8000,
    [int]$CouncilBackendPort = 8001,
    [int]$CouncilFrontendPort = 5173,
    [string]$CouncilRepoUrl = "https://github.com/jacob-bd/the-ai-counsel.git",
    [string]$CouncilBranch = "main",
    [switch]$NoSync,
    [switch]$RefreshLogin,
    [switch]$NoBrowser,
    [switch]$NoPause,
    [switch]$SetupOnly,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$NotionRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = if ($env:NOTION2API_LAUNCHER_LOG_DIR) { $env:NOTION2API_LAUNCHER_LOG_DIR } else { Join-Path $NotionRoot "logs\launcher" }
$StateFile = Join-Path $LogDir "launcher-state.json"
$RestartNotionFlag = Join-Path $LogDir "restart-notion.flag"
$EventLogPath = Join-Path $LogDir "launcher-events.log"
$EventLogMaxBytes = 1048576

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
    Write-LauncherEvent $Message
}

function Write-LauncherEvent {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    $line = "[$timestamp] $Message"
    if (Test-Path $EventLogPath) {
        $item = Get-Item $EventLogPath
        if ($item.Length -ge $EventLogMaxBytes) {
            Move-Item -LiteralPath $EventLogPath -Destination (Join-Path $LogDir "launcher-events.$(Get-Date -Format 'yyyyMMdd-HHmmss').log") -Force
        }
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($EventLogPath, $line + [Environment]::NewLine, $utf8NoBom)
}

function Normalize-ProxyBypassEnvironment {
    foreach ($name in @("NO_PROXY", "no_proxy")) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not $value) { continue }
        $entries = @($value -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notin @("::1", "::1/128") })
        if ($entries.Count -gt 0) {
            [Environment]::SetEnvironmentVariable($name, ($entries -join ","), "Process")
        } else {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
    }
}

function Get-Python {
    param([string]$Root)
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }
    return "python"
}

function Get-Sha256Hash {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash
}

function Test-PythonModules {
    param([string]$Python, [string[]]$Modules)
    if (-not $Modules -or $Modules.Count -eq 0) { return $true }
    $missing = @()
    foreach ($module in $Modules) {
        $oldValue = $env:N2API_PY_MODULE
        $env:N2API_PY_MODULE = $module
        try {
            & $Python -c "import importlib.util, os, sys; m=os.environ.get('N2API_PY_MODULE',''); sys.exit(0 if m and importlib.util.find_spec(m) else 1)" *> $null
            if ($LASTEXITCODE -ne 0) { $missing += $module }
        } finally {
            if ($null -eq $oldValue) { Remove-Item Env:N2API_PY_MODULE -ErrorAction SilentlyContinue } else { $env:N2API_PY_MODULE = $oldValue }
        }
    }
    if ($missing.Count -eq 0) { return $true }
    Write-Step "Missing Python modules: $($missing -join ', ')"
    return $false
}

function Get-PyprojectDependencies {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return @() }
    $content = Get-Content -Raw -Path $Path
    $match = [regex]::Match($content, '(?ms)^dependencies\s*=\s*\[(?<deps>.*?)\r?\n\s*\]')
    if (-not $match.Success) {
        $match = [regex]::Match($content, '(?ms)^dependencies\s*=\s*\[(?<deps>.*?)\]')
    }
    if (-not $match.Success) { return @() }
    $deps = @()
    foreach ($line in ($match.Groups['deps'].Value -split "`r?`n")) {
        $clean = ($line -replace '#.*$', '').Trim().TrimEnd(',').Trim()
        if (-not $clean) { continue }
        $depMatch = [regex]::Match($clean, '^["''](?<dep>.*?)["'']$')
        if ($depMatch.Success) { $deps += $depMatch.Groups['dep'].Value }
    }
    return $deps
}

function Initialize-PythonRequirements {
    param(
        [string]$Root,
        [string]$Label,
        [string[]]$RequiredModules = @()
    )
    $requirementsPath = Join-Path $Root "requirements.txt"
    $pyprojectPath = Join-Path $Root "pyproject.toml"
    $hasRequirements = Test-Path $requirementsPath
    $hasPyproject = Test-Path $pyprojectPath
    if (-not $hasRequirements -and -not $hasPyproject) {
        Write-Step "$Label requirements.txt or pyproject.toml not found; skipping Python dependency sync"
        return
    }
    $venvDir = Join-Path $Root ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating $Label Python virtual environment"
        & python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Failed to create Python virtual environment for $Label" }
    }
    $python = Get-Python -Root $Root
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $python -m pip --version *> $null
    $pipExitCode = $LASTEXITCODE
    $ErrorActionPreference = $oldErrorActionPreference
    if ($pipExitCode -ne 0) {
        Write-Step "$Label Python environment has no pip; bootstrapping pip"
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $python -m ensurepip --upgrade *> $null
        $ensurePipExitCode = $LASTEXITCODE
        $ErrorActionPreference = $oldErrorActionPreference
        if ($ensurePipExitCode -ne 0) {
            Write-Step "$Label Python environment could not bootstrap pip; recreating virtual environment"
            Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue
            & python -m venv $venvDir
            if ($LASTEXITCODE -ne 0) { throw "Failed to recreate Python virtual environment for $Label" }
            $python = Get-Python -Root $Root
        }
    }
    if ($hasRequirements) {
        $dependencySource = $requirementsPath
        $installArgs = @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath)
        $installLabel = "$Label Python requirements"
    } else {
        $dependencySource = $pyprojectPath
        $deps = @(Get-PyprojectDependencies -Path $pyprojectPath)
        if ($deps.Count -eq 0) { throw "$Label pyproject.toml does not contain a parseable dependencies list" }
        $installArgs = @("-m", "pip", "install", "--disable-pip-version-check") + $deps
        $installLabel = "$Label Python project dependencies"
    }
    $dependencyHash = Get-Sha256Hash -Path $dependencySource
    $markerPath = Join-Path $Root ".notion2council-requirements.sha256"
    $markerHash = if (Test-Path $markerPath) { (Get-Content -Path $markerPath -Raw).Trim() } else { "" }
    if ((Test-PythonModules -Python $python -Modules $RequiredModules) -and $markerHash -eq $dependencyHash) {
        Write-Step "$installLabel are current"
        return
    }
    Write-Step "Installing $installLabel"
    & $python @installArgs
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies for $Label" }
    Set-Content -Path $markerPath -Value $dependencyHash -Encoding ASCII
    if (-not (Test-PythonModules -Python $python -Modules $RequiredModules)) {
        throw "$Label Python dependencies installed, but required modules are still unavailable"
    }
}

function Initialize-NodeRequirements {
    param([string]$Root, [string]$Label)
    if (-not (Test-Path (Join-Path $Root "package.json"))) { return }
    if (Test-Path (Join-Path $Root "node_modules")) {
        Write-Step "$Label node_modules are present"
        return
    }
    Push-Location $Root
    try {
        if (Test-Path (Join-Path $Root "package-lock.json")) {
            Write-Step "Running npm ci for $Label"
            & npm ci
            if ($LASTEXITCODE -eq 0) { return }
            Write-Warning "npm ci failed for $Label; falling back to npm install"
        }
        Write-Step "Running npm install for $Label"
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Node dependencies for $Label" }
    } finally {
        Pop-Location
    }
}

function Set-EnvLine {
    param([string]$Path, [string]$Name, [string]$Value)
    $lines = if (Test-Path $Path) { @(Get-Content -Path $Path) } else { @() }
    $updated = $false
    $changed = $false
    $newLines = foreach ($line in $lines) {
        if ($line.TrimStart().StartsWith("$Name=")) {
            $updated = $true
            if ($line -cne "$Name=$Value") { $changed = $true }
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) {
        $newLines += "$Name=$Value"
        $changed = $true
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $newLines, $utf8NoBom)
    return $changed
}

function Get-EnvLineValue {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path $Path)) { return "" }
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("#") -or -not $trimmed.StartsWith("$Name=")) { continue }
        return $trimmed.Substring($Name.Length + 1).Trim('"').Trim("'")
    }
    return ""
}

function New-ApiKey {
    $bytes = [byte[]]::new(32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Initialize-NotionApiKey {
    $envPath = Join-Path $NotionRoot ".env"
    $existing = Get-EnvLineValue -Path $envPath -Name "API_KEY"
    if ($existing) {
        Write-Step "Notion2API API key is configured"
        return $existing
    }
    $generated = "n2api_" + (New-ApiKey)
    Set-EnvLine -Path $envPath -Name "API_KEY" -Value $generated | Out-Null
    Set-Content -Path $RestartNotionFlag -Value "api-key-generated" -Encoding UTF8
    Write-Step "Generated Notion2API API key"
    return $generated
}

function ConvertTo-EnvBool {
    param($Value)
    if ($Value -eq $true -or "$Value".ToLowerInvariant() -eq "true" -or "$Value" -eq "1") { return "true" }
    return "false"
}

function Initialize-NotionMode {
    $envPath = Join-Path $NotionRoot ".env"
    $changed = $false
    $changed = (Set-EnvLine -Path $envPath -Name "APP_MODE" -Value "standard") -or $changed
    $changed = (Set-EnvLine -Path $envPath -Name "HOST" -Value "127.0.0.1") -or $changed
    if ($changed) {
        Set-Content -Path $RestartNotionFlag -Value "notion-env-changed" -Encoding UTF8
        Write-Step "Notion2API local mode settings changed; restart will apply them"
    }
}

function Test-NotionLogin {
    $python = Get-Python -Root $NotionRoot
    Push-Location $NotionRoot
    try {
        $null = & $python "login.py" "--check"
        return ($LASTEXITCODE -eq 0)
    } finally { Pop-Location }
}

function Initialize-NotionLogin {
    if (-not (Test-Path (Join-Path $NotionRoot "login.py"))) { throw "Notion2API checkout does not contain login.py" }
    if (-not $RefreshLogin -and (Test-NotionLogin)) {
        Write-Step "Notion token is valid"
        return
    }
    Write-Step "Refreshing Notion login session"
    $python = Get-Python -Root $NotionRoot
    Push-Location $NotionRoot
    try {
        & $python "login.py" "--timeout" "300"
        if ($LASTEXITCODE -ne 0) { throw "Notion login failed" }
    } finally { Pop-Location }
}

function Get-State {
    if (-not (Test-Path $StateFile)) { return [pscustomobject]@{} }
    try { return Get-Content -Path $StateFile -Raw | ConvertFrom-Json } catch { return [pscustomobject]@{} }
}

function Save-State {
    param($State)
    $json = $State | ConvertTo-Json -Depth 12
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($StateFile, $json + [Environment]::NewLine, $utf8NoBom)
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    taskkill.exe /PID $ProcessId /T /F *> $null
}

function Stop-ManagedServices {
    $state = Get-State
    foreach ($service in @($state.councilFrontend, $state.councilBackend, $state.notion)) {
        if ($service -and $service.pid) {
            Write-Step "Stopping $($service.name) (PID $($service.pid))"
            Stop-ProcessTree -ProcessId ([int]$service.pid)
        }
    }
    Remove-Item $StateFile -ErrorAction SilentlyContinue
}

function Get-ListeningProcessId {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return 0
}

function Test-ProcessCommandLineContains {
    param([int]$ProcessId, [string]$Needle)
    if ($ProcessId -le 0 -or -not $Needle) { return $false }
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId"
        if (-not $proc -or -not $proc.CommandLine) { return $false }
        return ($proc.CommandLine -match [regex]::Escape($Needle))
    } catch {
        return $false
    }
}

function Test-StateServiceRoot {
    param($Service, [string]$ExpectedRoot)
    if (-not $Service -or -not $Service.root -or -not $ExpectedRoot) { return $false }
    return ([string]$Service.root).TrimEnd('\') -ieq ([string]$ExpectedRoot).TrimEnd('\')
}

function Test-PortInUse {
    param([int]$Port)
    return [bool](Get-ListeningProcessId -Port $Port)
}

function Find-FreePort {
    param([int]$PreferredPort)
    $port = $PreferredPort
    while (Test-PortInUse -Port $port) { $port++ }
    return $port
}

function Test-HttpOk {
    param(
        [string]$Url,
        [string]$ExpectedContent = "",
        [string]$ExpectedTitle = "",
        [string]$BearerToken = ""
    )
    try {
        $headers = @{}
        if ($BearerToken) { $headers["Authorization"] = "Bearer $BearerToken" }
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $headers -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) { return $false }
        $body = [string]$response.Content
        if ($ExpectedContent -and $body -notmatch [regex]::Escape($ExpectedContent)) { return $false }
        if ($ExpectedTitle -and $body -notmatch [regex]::Escape($ExpectedTitle)) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 45,
        [string]$ExpectedContent = "",
        [string]$BearerToken = ""
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-HttpOk -Url $Url -ExpectedContent $ExpectedContent -BearerToken $BearerToken) { return }
        Start-Sleep -Milliseconds 750
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Url"
}

function Resolve-CouncilRoot {
    if ($CouncilRoot) { return (Resolve-Path $CouncilRoot).Path }
    if ($env:NOTION2API_COUNCIL_ROOT) { return (Resolve-Path $env:NOTION2API_COUNCIL_ROOT).Path }
    $candidates = @(
        "X:\Code\the-ai-counsel-main-test",
        "X:\Code\the-ai-counsel-electron-test",
        "X:\Code\llm-council-plus",
        (Join-Path $NotionRoot "vendor\the-ai-counsel")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
    }
    return (Join-Path $NotionRoot "vendor\the-ai-counsel")
}

function Initialize-CouncilRepo {
    param([string]$Path)
    if ($NoSync) {
        Write-Step "Council repo sync disabled"
        return
    }
    if (Test-Path $Path) {
        if (-not (Test-Path (Join-Path $Path ".git"))) {
            Write-Step "Council path exists but is not a git checkout; skipping sync: $Path"
            return
        }
        $dirty = git -C $Path status --porcelain
        if ($dirty) {
            Write-Warning "Council checkout has uncommitted changes; skipping sync for safety: $Path"
            return
        }
        Write-Step "Refreshing Council repo from origin/$CouncilBranch"
        git -C $Path fetch --quiet origin $CouncilBranch
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not fetch origin/$CouncilBranch; using existing Council checkout"
            return
        }
        $currentBranch = (git -C $Path rev-parse --abbrev-ref HEAD).Trim()
        if ($currentBranch -ne $CouncilBranch) {
            Write-Step "Checking out Council branch $CouncilBranch"
            git -C $Path checkout -f $CouncilBranch
            if ($LASTEXITCODE -ne 0) { throw "Failed to checkout $CouncilBranch in $Path" }
        }
        git -C $Path pull --quiet --ff-only origin $CouncilBranch
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not fast-forward Council repo; using existing checkout"
        }
        return
    }
    $parent = Split-Path $Path -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Write-Step "Cloning Council repo to $Path"
    git clone --quiet --branch $CouncilBranch $CouncilRepoUrl $Path
    if ($LASTEXITCODE -ne 0) { throw "Failed to clone Council repo" }
}

function Start-NotionApi {
    param($State, [string]$NotionApiKey)
    $healthUrl = "http://127.0.0.1:$NotionPort/health"
    $pidToStop = Get-ListeningProcessId -Port $NotionPort
    if ($pidToStop -and (Test-HttpOk -Url $healthUrl -ExpectedContent "ok")) {
        $stateMatchesRoot = Test-StateServiceRoot -Service $State.notion -ExpectedRoot $NotionRoot
        $processMatchesRoot = Test-ProcessCommandLineContains -ProcessId $pidToStop -Needle $NotionRoot
        if (-not $stateMatchesRoot -and -not $processMatchesRoot) {
            Write-Warning "Port $NotionPort is serving Notion2API from an untracked checkout; choosing another port."
            $script:NotionPort = Find-FreePort -PreferredPort ($NotionPort + 1)
        } else {
        $keyMatches = $true
        if ($NotionApiKey) {
            $keyMatches = Test-HttpOk -Url "http://127.0.0.1:$NotionPort/v1/models" -BearerToken $NotionApiKey
        }
        if (Test-Path $RestartNotionFlag) {
            Write-Step "Restarting Notion2API due to launcher flag"
            Stop-ProcessTree -ProcessId $pidToStop
            Start-Sleep -Seconds 1
            Remove-Item $RestartNotionFlag -ErrorAction SilentlyContinue
        } elseif (-not $keyMatches) {
            Write-Step "Restarting Notion2API to apply current API key"
            Stop-ProcessTree -ProcessId $pidToStop
            Start-Sleep -Seconds 1
        } else {
            Write-Step "Reusing Notion2API on http://127.0.0.1:$NotionPort"
            $State | Add-Member -MemberType NoteProperty -Name notion -Value ([pscustomobject]@{ name="Notion2API"; pid=$pidToStop; port=$NotionPort; url="http://127.0.0.1:$NotionPort"; root=$NotionRoot }) -Force
            return $State
        }
        }
    }
    Remove-Item $RestartNotionFlag -ErrorAction SilentlyContinue
    if (Test-PortInUse -Port $NotionPort) { $script:NotionPort = Find-FreePort -PreferredPort $NotionPort }
    $python = Get-Python -Root $NotionRoot
    Write-Step "Starting Notion2API on http://127.0.0.1:$NotionPort"
    $process = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", "$NotionPort") `
        -WorkingDirectory $NotionRoot `
        -RedirectStandardOutput (Join-Path $LogDir "notion2api.out.log") `
        -RedirectStandardError (Join-Path $LogDir "notion2api.err.log") `
        -WindowStyle Hidden -PassThru
    Wait-HttpOk -Url "http://127.0.0.1:$NotionPort/health" -ExpectedContent "ok" -TimeoutSeconds 60
    $State | Add-Member -MemberType NoteProperty -Name notion -Value ([pscustomobject]@{ name="Notion2API"; pid=$process.Id; port=$NotionPort; url="http://127.0.0.1:$NotionPort"; root=$NotionRoot }) -Force
    return $State
}

function Start-CouncilBackend {
    param($State, [string]$NotionApiKey)
    $settingsUrl = "http://127.0.0.1:$CouncilBackendPort/api/settings"
    $pidToStop = Get-ListeningProcessId -Port $CouncilBackendPort
    if ($pidToStop -and (Test-HttpOk -Url $settingsUrl -ExpectedContent "council_models")) {
        $stateMatchesRoot = Test-StateServiceRoot -Service $State.councilBackend -ExpectedRoot $CouncilRootPath
        $processMatchesRoot = Test-ProcessCommandLineContains -ProcessId $pidToStop -Needle $CouncilRootPath
        if ($stateMatchesRoot -or $processMatchesRoot) {
            Write-Step "Reusing AI Counsel backend on http://127.0.0.1:$CouncilBackendPort"
            $State | Add-Member -MemberType NoteProperty -Name councilBackend -Value ([pscustomobject]@{ name="AI Counsel backend"; pid=$pidToStop; port=$CouncilBackendPort; url="http://127.0.0.1:$CouncilBackendPort"; root=$CouncilRootPath }) -Force
            return $State
        }
        Write-Warning "Port $CouncilBackendPort is serving an untracked AI Counsel backend; choosing another port."
        $script:CouncilBackendPort = Find-FreePort -PreferredPort ($CouncilBackendPort + 1)
    }
    if (Test-PortInUse -Port $CouncilBackendPort) { $script:CouncilBackendPort = Find-FreePort -PreferredPort $CouncilBackendPort }
    $python = Get-Python -Root $CouncilRootPath
    Write-Step "Starting AI Counsel backend on http://127.0.0.1:$CouncilBackendPort"
    $oldShutdown = $env:LLM_COUNCIL_ENABLE_SHUTDOWN
    $oldFrontend = $env:FRONTEND_HOST
    $oldN2Base = $env:NOTION2API_BASE_URL
    $oldN2Key = $env:NOTION2API_API_KEY
    $env:LLM_COUNCIL_ENABLE_SHUTDOWN = "1"
    $env:FRONTEND_HOST = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:3000,http://localhost:3000"
    $env:NOTION2API_BASE_URL = "http://127.0.0.1:$NotionPort/v1"
    $env:NOTION2API_API_KEY = $NotionApiKey
    try {
        $process = Start-Process -FilePath $python `
            -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "$CouncilBackendPort") `
            -WorkingDirectory $CouncilRootPath `
            -RedirectStandardOutput (Join-Path $LogDir "council-backend.out.log") `
            -RedirectStandardError (Join-Path $LogDir "council-backend.err.log") `
            -WindowStyle Hidden -PassThru
    } finally {
        $env:LLM_COUNCIL_ENABLE_SHUTDOWN = $oldShutdown
        $env:FRONTEND_HOST = $oldFrontend
        $env:NOTION2API_BASE_URL = $oldN2Base
        $env:NOTION2API_API_KEY = $oldN2Key
    }
    Wait-HttpOk -Url "http://127.0.0.1:$CouncilBackendPort/api/settings" -ExpectedContent "council_models" -TimeoutSeconds 60
    $State | Add-Member -MemberType NoteProperty -Name councilBackend -Value ([pscustomobject]@{ name="AI Counsel backend"; pid=$process.Id; port=$CouncilBackendPort; url="http://127.0.0.1:$CouncilBackendPort"; root=$CouncilRootPath }) -Force
    return $State
}

function Ensure-ObjectProperty {
    param($Object, [string]$Name, $DefaultValue)
    if (-not $Object.PSObject.Properties[$Name]) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $DefaultValue -Force
    }
}

function Set-CouncilSettings {
    param([string]$NotionApiKey)
    $exportUrl = "http://127.0.0.1:$CouncilBackendPort/api/settings/export"
    $importUrl = "http://127.0.0.1:$CouncilBackendPort/api/settings/import"
    $settings = $null
    try {
        $settings = Invoke-RestMethod -Method Get -Uri $exportUrl -TimeoutSec 10
    } catch {
        Write-Warning "Failed to export AI Counsel settings: $($_.Exception.Message). Creating minimal payload."
        $settings = [pscustomobject]@{
            enabled_providers = [pscustomobject]@{}
            direct_provider_toggles = [pscustomobject]@{}
            council_models = @()
            execution_mode = "full"
        }
    }
    Ensure-ObjectProperty -Object $settings -Name "enabled_providers" -DefaultValue ([pscustomobject]@{})
    Ensure-ObjectProperty -Object $settings -Name "direct_provider_toggles" -DefaultValue ([pscustomobject]@{})
    $expectedUrl = "http://127.0.0.1:$NotionPort/v1"

    # Prefer the dedicated Notion2API provider when present, but keep custom endpoint
    # fields synchronized for older AI Counsel checkouts.
    $settings.enabled_providers | Add-Member -MemberType NoteProperty -Name "notion2api" -Value $true -Force
    $settings.enabled_providers | Add-Member -MemberType NoteProperty -Name "custom" -Value $true -Force
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_name" -Value "Notion2API" -Force
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_url" -Value $expectedUrl -Force
    $settings | Add-Member -MemberType NoteProperty -Name "custom_endpoint_api_key" -Value $NotionApiKey -Force
    $settings | Add-Member -MemberType NoteProperty -Name "model_timeout_seconds" -Value 300 -Force

    $json = $settings | ConvertTo-Json -Depth 20
    Invoke-RestMethod -Method Post -Uri $importUrl -ContentType "application/json" -Body $json -TimeoutSec 20 | Out-Null
    $verified = Invoke-RestMethod -Method Get -Uri $exportUrl -TimeoutSec 10
    if (-not $verified.enabled_providers) { throw "AI Counsel settings import did not preserve enabled_providers" }
    Write-Step "AI Counsel provider settings synchronized"

    $testUrl = "http://127.0.0.1:$CouncilBackendPort/api/settings/test-custom-endpoint"
    $testBody = [ordered]@{ name="Notion2API"; url=$expectedUrl; api_key=$NotionApiKey } | ConvertTo-Json
    try {
        $response = Invoke-RestMethod -Method Post -Uri $testUrl -ContentType "application/json" -Body $testBody -TimeoutSec 30
        if ($response.error) { Write-Warning "Provider smoke test warning: $($response.error)" } else { Write-Step "Provider smoke test successful" }
    } catch {
        Write-Warning "Provider smoke test warning: $($_.Exception.Message)"
    }
}

function Start-CouncilFrontend {
    param($State)
    $allowedPorts = @($CouncilFrontendPort, 5173, 5174, 3000) | Select-Object -Unique
    foreach ($candidate in $allowedPorts) {
        if ((Test-HttpOk -Url "http://127.0.0.1:$candidate/" -ExpectedTitle "LLM Council") -or (Test-HttpOk -Url "http://127.0.0.1:$candidate/" -ExpectedTitle "The AI Counsel")) {
            $frontendPid = Get-ListeningProcessId -Port $candidate
            $stateMatchesRoot = Test-StateServiceRoot -Service $State.councilFrontend -ExpectedRoot $CouncilRootPath
            $processMatchesRoot = Test-ProcessCommandLineContains -ProcessId $frontendPid -Needle $CouncilRootPath
            if ($stateMatchesRoot -or $processMatchesRoot) {
                $script:CouncilFrontendPort = $candidate
                Write-Step "Reusing AI Counsel frontend on port $candidate"
                $State | Add-Member -MemberType NoteProperty -Name councilFrontend -Value ([pscustomobject]@{ name="AI Counsel frontend"; pid=$frontendPid; port=$candidate; url="http://127.0.0.1:$candidate"; root=$CouncilRootPath }) -Force
                return $State
            }
            Write-Warning "Port $candidate is serving an untracked AI Counsel frontend; not reusing it."
        }
    }
    $frontendRoot = Join-Path $CouncilRootPath "frontend"
    Initialize-NodeRequirements -Root $frontendRoot -Label "AI Counsel frontend"
    $envLocalPath = Join-Path $frontendRoot ".env.local"
    $envLocalLines = @(
        "VITE_API_URL=http://127.0.0.1:$CouncilBackendPort",
        "VITE_ENABLE_LOCAL_SHUTDOWN=true"
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envLocalPath, $envLocalLines, $utf8NoBom)
    if (Test-PortInUse -Port $CouncilFrontendPort) { $script:CouncilFrontendPort = Find-FreePort -PreferredPort $CouncilFrontendPort }
    Write-Step "Starting AI Counsel frontend on http://127.0.0.1:$CouncilFrontendPort"
    $process = Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$CouncilFrontendPort") `
        -WorkingDirectory $frontendRoot `
        -RedirectStandardOutput (Join-Path $LogDir "council-frontend.out.log") `
        -RedirectStandardError (Join-Path $LogDir "council-frontend.err.log") `
        -WindowStyle Hidden -PassThru
    Wait-HttpOk -Url "http://127.0.0.1:$CouncilFrontendPort/" -TimeoutSeconds 60
    $State | Add-Member -MemberType NoteProperty -Name councilFrontend -Value ([pscustomobject]@{ name="AI Counsel frontend"; pid=$process.Id; port=$CouncilFrontendPort; url="http://127.0.0.1:$CouncilFrontendPort"; root=$CouncilRootPath }) -Force
    return $State
}

Normalize-ProxyBypassEnvironment

if ($Stop) {
    Stop-ManagedServices
    exit 0
}

$CouncilRootPath = Resolve-CouncilRoot
Initialize-CouncilRepo -Path $CouncilRootPath
$CouncilRootPath = (Resolve-Path $CouncilRootPath).Path

Write-Step "Preparing Notion2API + AI Counsel"
Initialize-PythonRequirements -Root $NotionRoot -Label "Notion2API" -RequiredModules @("cloudscraper", "fastapi", "uvicorn", "dotenv", "slowapi", "websocket")
Initialize-PythonRequirements -Root $CouncilRootPath -Label "AI Counsel" -RequiredModules @("fastapi", "uvicorn", "dotenv", "httpx", "pydantic")
Initialize-NotionMode
Initialize-NotionLogin
$NotionApiKey = Initialize-NotionApiKey

if ($SetupOnly) {
    Write-Host "Setup complete"
    exit 0
}

$state = Get-State
$state = Start-NotionApi -State $state -NotionApiKey $NotionApiKey
$state = Start-CouncilBackend -State $state -NotionApiKey $NotionApiKey
Set-CouncilSettings -NotionApiKey $NotionApiKey
$state = Start-CouncilFrontend -State $state
Save-State -State $state

Write-Host ""
Write-Host "Ready:"
Write-Host "  Notion2API:        http://127.0.0.1:$NotionPort"
Write-Host "  AI Counsel API:    http://127.0.0.1:$CouncilBackendPort"
Write-Host "  AI Counsel UI:     http://127.0.0.1:$CouncilFrontendPort"
Write-Host "  Council root:      $CouncilRootPath"
Write-Host "  Logs:              $LogDir"
Write-Host ""
Write-Host "Stop later with:"
Write-Host "  .\launch-council.bat -Stop"
Write-Host ""

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$CouncilFrontendPort/" }
if (-not $env:GITHUB_ACTIONS -and -not $NoPause) { Pause }