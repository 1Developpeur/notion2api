param(
    [string]$BaseUrl = "http://127.0.0.1:8120",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8130,
    [string]$McpPath = "/mcp",
    [ValidateSet("streamable-http", "stdio", "sse")]
    [string]$Transport = "streamable-http"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:MCP_NOTION2API_BASE_URL = $BaseUrl
$env:MCP_HOST = $HostName
$env:MCP_PORT = [string]$Port
$env:MCP_PATH = $McpPath

python -m app.mcp_server --transport $Transport --base-url $BaseUrl --host $HostName --port $Port --mcp-path $McpPath
