param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$LauncherUrl = "http://127.0.0.1:8001",
    [string]$ApiKey = "",
    [string]$Model = "gpt-5.5"
)

$ErrorActionPreference = "Stop"
$script:Failures = 0
$BaseUrl = $BaseUrl.TrimEnd('/')
$LauncherUrl = $LauncherUrl.TrimEnd('/')

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ==="
}

function Resolve-ApiKey {
    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        return $ApiKey
    }

    try {
        $settings = Invoke-RestMethod -Uri "$LauncherUrl/api/settings/export" -Method GET
        if ($settings.custom_endpoint_api_key) {
            Write-Host "Using API key from launcher settings export."
            return [string]$settings.custom_endpoint_api_key
        }
    }
    catch {
        Write-Host "Launcher settings export not available at $LauncherUrl/api/settings/export. Continuing without API key."
    }

    return ""
}

function Get-AuthHeaders {
    param([string]$ResolvedApiKey)

    $headers = @{
        "X-Client-Type" = "CompatTest"
    }

    if (-not [string]::IsNullOrWhiteSpace($ResolvedApiKey)) {
        $headers["Authorization"] = "Bearer $ResolvedApiKey"
    }

    return $headers
}

function Invoke-CompatTest {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Path,
        [hashtable]$Headers = @{},
        [object]$Body = $null,
        [scriptblock]$Validate = $null
    )

    Write-Section $Name
    $uri = "$BaseUrl$Path"

    try {
        $params = @{
            Uri = $uri
            Method = $Method
            Headers = $Headers
        }

        if ($null -ne $Body) {
            $params.ContentType = "application/json"
            $params.Body = ($Body | ConvertTo-Json -Depth 20)
        }

        $result = Invoke-RestMethod @params

        if ($Validate) {
            & $Validate $result
        }

        Write-Host "PASS $Method $Path"
        $result | ConvertTo-Json -Depth 20
        return $result
    }
    catch {
        $script:Failures++
        Write-Host "FAIL $Method $Path"
        Write-Host $_.Exception.Message
        if ($_.ErrorDetails.Message) {
            Write-Host $_.ErrorDetails.Message
        }
        return $null
    }
}

$ResolvedApiKey = Resolve-ApiKey
$Headers = Get-AuthHeaders -ResolvedApiKey $ResolvedApiKey

Write-Host "Notion2API OpenAI compatibility test"
Write-Host "BaseUrl: $BaseUrl"
Write-Host "Model:   $Model"
Write-Host "API key: $(if ([string]::IsNullOrWhiteSpace($ResolvedApiKey)) { 'not set' } else { 'set' })"

Invoke-CompatTest `
    -Name "Health" `
    -Method GET `
    -Path "/health" `
    -Validate {
        param($r)
        if ($r.status -ne "ok") { throw "Expected status=ok from /health." }
    } | Out-Null

Invoke-CompatTest `
    -Name "Healthz alias" `
    -Method GET `
    -Path "/healthz" `
    -Validate {
        param($r)
        if ($r.status -ne "ok") { throw "Expected status=ok from /healthz." }
    } | Out-Null

Invoke-CompatTest `
    -Name "Models" `
    -Method GET `
    -Path "/v1/models" `
    -Headers $Headers `
    -Validate {
        param($r)
        if (-not $r.data) { throw "Expected a data array from /v1/models." }
    } | Out-Null

$ChatBody = @{
    model = $Model
    messages = @(
        @{
            role = "user"
            content = "Say only: connected"
        }
    )
    stream = $false
}

Invoke-CompatTest `
    -Name "Chat completions" `
    -Method POST `
    -Path "/v1/chat/completions" `
    -Headers $Headers `
    -Body $ChatBody `
    -Validate {
        param($r)
        $text = [string]$r.choices[0].message.content
        if ([string]::IsNullOrWhiteSpace($text)) { throw "Expected assistant text in choices[0].message.content." }
    } | Out-Null

$ResponsesBody = @{
    model = $Model
    input = "Say only: connected"
}

Invoke-CompatTest `
    -Name "Responses API" `
    -Method POST `
    -Path "/v1/responses" `
    -Headers $Headers `
    -Body $ResponsesBody `
    -Validate {
        param($r)
        if ($r.object -ne "response") { throw "Expected object=response." }
        if ([string]::IsNullOrWhiteSpace([string]$r.output_text)) { throw "Expected assistant text in output_text." }
        if (-not $r.output -or -not $r.output[0].content) { throw "Expected output[0].content response payload." }
    } | Out-Null

Write-Section "Summary"
if ($script:Failures -eq 0) {
    Write-Host "All compatibility checks passed."
}
else {
    Write-Host "$script:Failures compatibility check(s) failed."
}

Pause

if ($script:Failures -gt 0) {
    exit 1
}
exit 0
