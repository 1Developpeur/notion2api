param(
    [string]$BaseUrl = "http://127.0.0.1:8120",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8130,
    [string]$McpPath = "/mcp",
    [string]$AllowedHosts = "127.0.0.1:*,localhost:*,[::1]:*,0.0.0.0:*,notion2api-mcp.ptelectronics.net,notion2api-mcp.ptelectronics.net:*",
    [string]$AllowedOrigins = "http://127.0.0.1:*,http://localhost:*,http://[::1]:*,https://notion2api-mcp.ptelectronics.net,http://notion2api-mcp.ptelectronics.net,https://chatgpt.com,https://chat.openai.com",
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
$env:MCP_ALLOWED_HOSTS = $AllowedHosts
$env:MCP_ALLOWED_ORIGINS = $AllowedOrigins

python -m app.mcp_server --transport $Transport --base-url $BaseUrl --host $HostName --port $Port --mcp-path $McpPath
