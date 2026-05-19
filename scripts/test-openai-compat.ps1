function Read-ResponseText {
    param($Response)

    if ($null -eq $Response) {
        return ''
    }

    try {
        if ($Response -is [System.Net.Http.HttpResponseMessage]) {
            return $Response.Content.ReadAsStringAsync().Result
        }

        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) {
            return ''
        }
        try {
            $reader = [System.IO.StreamReader]::new($stream)
            return $reader.ReadToEnd()
        } finally {
            if ($reader) { $reader.Dispose() }
            $stream.Dispose()
        }
    } catch {
        return ''
    }
}

function Invoke-CompatRequest {
    param(
        [ValidateSet('GET', 'POST')]
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [string]$AuthKey = $ApiKey
    )

    $uri = "$BaseUrl$Path"
    $headers = @{ Accept = 'application/json' }
    if ($AuthKey) {
        $headers.Authorization = "Bearer $AuthKey"
    }

    $invokeParams = @{
        Uri         = $uri
        Method      = $Method
        Headers     = $headers
        ErrorAction = 'Stop'
    }

    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey('SkipHttpErrorCheck')) {
        $invokeParams.SkipHttpErrorCheck = $true
    }

    if ($Method -eq 'POST') {
        $invokeParams.ContentType = 'application/json'
        if ($null -ne $Body) {
            $invokeParams.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
        } else {
            $invokeParams.Body = '{}'
        }
    }

    try {
        $response = Invoke-WebRequest @invokeParams
        $bodyText = $response.Content
        return [pscustomobject]@{
            Ok         = $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
            StatusCode = [int]$response.StatusCode
            Text       = $bodyText
            Body       = Convert-ResponseBody -Text $bodyText
        }
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }

        $statusCode = [int]$response.StatusCode
        $bodyText = Read-ResponseText -Response $response
        return [pscustomobject]@{
            Ok         = $false
            StatusCode = $statusCode
            Text       = $bodyText
            Body       = Convert-ResponseBody -Text $bodyText
            Error      = $_.Exception.Message
        }
    }
}

function Assert-StatusCode {
    param(
        [string]$Name,
        [int]$Expected,
        $Result
    )

    $passed = $Result.StatusCode -eq $Expected
    $detail = "expected HTTP $Expected, got HTTP $($Result.StatusCode)"
    Write-TestResult -Name $Name -Passed $passed -Detail $detail
}

function Assert-JsonProperty {
    param(
        [string]$Name,
        $Value,
        [string]$Detail
    )

    $passed = $null -ne $Value -and ($Value -isnot [string] -or -not [string]::IsNullOrWhiteSpace($Value))
    Write-TestResult -Name $Name -Passed $passed -Detail $Detail
}

param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$ApiKey = $(if ($env:NOTION2API_KEY) { $env:NOTION2API_KEY } else { '' })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Failures = 0

function Write-TestResult {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail = ''
    )

    if ($Passed) {
        Write-Host "PASS  $Name" -ForegroundColor Green
        return
    }

    Write-Host "FAIL  $Name" -ForegroundColor Red
    if ($Detail) {
        Write-Host "      $Detail" -ForegroundColor DarkRed
    }
    $script:Failures++
}

function Convert-ResponseBody {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }

    try {
        return $Text | ConvertFrom-Json -Depth 20
    } catch {
        return $null
    }
}

function Read-ResponseText {
    param($Response)

    if ($null -eq $Response) {
        return ''
    }

    try {
        if ($Response -is [System.Net.Http.HttpResponseMessage]) {
            return $Response.Content.ReadAsStringAsync().Result
        }

        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) {
            return ''
        }
        try {
            $reader = [System.IO.StreamReader]::new($stream)
            return $reader.ReadToEnd()
        } finally {
            if ($reader) { $reader.Dispose() }
            $stream.Dispose()
        }
    } catch {
        return ''
    }
}

function Invoke-CompatRequest {
    param(
        [ValidateSet('GET', 'POST')]
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [string]$AuthKey = $ApiKey
    )

    $uri = "$BaseUrl$Path"
    $headers = @{ Accept = 'application/json' }
    if ($AuthKey) {
        $headers.Authorization = "Bearer $AuthKey"
    }

    $invokeParams = @{
        Uri         = $uri
        Method      = $Method
        Headers     = $headers
        ErrorAction = 'Stop'
    }

    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey('SkipHttpErrorCheck')) {
        $invokeParams.SkipHttpErrorCheck = $true
    }

    if ($Method -eq 'POST') {
        $invokeParams.ContentType = 'application/json'
        if ($null -ne $Body) {
            $invokeParams.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
        } else {
            $invokeParams.Body = '{}'
        }
    }

    try {
        $response = Invoke-WebRequest @invokeParams
        $bodyText = $response.Content
        return [pscustomobject]@{
            Ok         = $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
            StatusCode = [int]$response.StatusCode
            Text       = $bodyText
            Body       = Convert-ResponseBody -Text $bodyText
        }
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }

        $statusCode = [int]$response.StatusCode
        $bodyText = Read-ResponseText -Response $response
        return [pscustomobject]@{
            Ok         = $false
            StatusCode = $statusCode
            Text       = $bodyText
            Body       = Convert-ResponseBody -Text $bodyText
            Error      = $_.Exception.Message
        }
    }
}

function Assert-StatusCode {
    param(
        [string]$Name,
        [int]$Expected,
        $Result
    )

    $passed = $Result.StatusCode -eq $Expected
    $detail = "expected HTTP $Expected, got HTTP $($Result.StatusCode)"
    Write-TestResult -Name $Name -Passed $passed -Detail $detail
}

function Assert-JsonProperty {
    param(
        [string]$Name,
        $Value,
        [string]$Detail
    )

    $passed = $null -ne $Value -and ($Value -isnot [string] -or -not [string]::IsNullOrWhiteSpace($Value))
    Write-TestResult -Name $Name -Passed $passed -Detail $Detail
}

Write-Host "Testing OpenAI-compatible surface at $BaseUrl"
if (-not $ApiKey) {
    Write-Host 'Warning: NOTION2API_KEY is empty. /v1 checks may fail if the server requires auth.' -ForegroundColor Yellow
}

$health = Invoke-CompatRequest -Method GET -Path '/health' -AuthKey ''
Assert-StatusCode -Name '/health' -Expected 200 -Result $health

$healthz = Invoke-CompatRequest -Method GET -Path '/healthz' -AuthKey ''
Assert-StatusCode -Name '/healthz' -Expected 200 -Result $healthz

$models = Invoke-CompatRequest -Method GET -Path '/v1/models'
Assert-StatusCode -Name '/v1/models' -Expected 200 -Result $models
Write-TestResult -Name '/v1/models object=list' -Passed ($models.Body.object -eq 'list') -Detail 'expected OpenAI-style model list object'
Write-TestResult -Name '/v1/models data present' -Passed (($models.Body.data | Measure-Object).Count -gt 0) -Detail 'expected at least one model entry'

$chatBody = @{
    model    = 'custom:gpt-5.5'
    messages = @(
        @{
            role    = 'user'
            content = 'Say only: connected'
        }
    )
}
$chat = Invoke-CompatRequest -Method POST -Path '/v1/chat/completions' -Body $chatBody
Assert-StatusCode -Name '/v1/chat/completions' -Expected 200 -Result $chat
$chatContent = $chat.Body.choices[0].message.content
Assert-JsonProperty -Name '/v1/chat/completions message.content' -Value $chatContent -Detail 'expected choices[0].message.content to be present'

$responsesBody = @{
    model = 'custom:gpt-5.5'
    input = 'Say only: connected'
}
$responses = Invoke-CompatRequest -Method POST -Path '/v1/responses' -Body $responsesBody
Assert-StatusCode -Name '/v1/responses' -Expected 200 -Result $responses
$responseText = $responses.Body.output[0].content[0].text
if ([string]::IsNullOrWhiteSpace($responseText)) {
    $responseText = $responses.Body.output_text
}
Assert-JsonProperty -Name '/v1/responses output text' -Value $responseText -Detail 'expected output[0].content[0].text or output_text to be present'

$badKeyChat = Invoke-CompatRequest -Method POST -Path '/v1/chat/completions' -Body $chatBody -AuthKey 'definitely-wrong-key'
Write-TestResult -Name '/v1/chat/completions bad key status' -Passed ($badKeyChat.StatusCode -eq 401) -Detail "expected HTTP 401, got HTTP $($badKeyChat.StatusCode)"
Write-TestResult -Name '/v1/chat/completions bad key code' -Passed ($badKeyChat.Body.error.code -eq 'invalid_api_key') -Detail 'expected OpenAI-style invalid_api_key error'

$badKeyResponses = Invoke-CompatRequest -Method POST -Path '/v1/responses' -Body $responsesBody -AuthKey 'definitely-wrong-key'
Write-TestResult -Name '/v1/responses bad key status' -Passed ($badKeyResponses.StatusCode -eq 401) -Detail "expected HTTP 401, got HTTP $($badKeyResponses.StatusCode)"
Write-TestResult -Name '/v1/responses bad key code' -Passed ($badKeyResponses.Body.error.code -eq 'invalid_api_key') -Detail 'expected OpenAI-style invalid_api_key error'

Write-Host ''
if ($script:Failures -eq 0) {
    Write-Host 'All compatibility checks passed.' -ForegroundColor Green
} else {
    Write-Host "$script:Failures compatibility check(s) failed." -ForegroundColor Red
}

Pause
exit ([int]($script:Failures -gt 0))
>>>>>>> 8c45681 (feat: add read-only Notion chat-history sync)
