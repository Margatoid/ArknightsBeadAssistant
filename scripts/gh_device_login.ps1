# -*- coding: utf-8 -*-
# GitHub 设备码登录脚本(PowerShell 5.1+)
# 通过 GitHub CLI 的公共 OAuth 应用执行标准 Device Flow:
#   1. 请求一次性代码并打开浏览器
#   2. 用户授权后自动轮询换取 token
#   3. 成功后将 token 写入 github_token.txt
# 本脚本被 登录GitHub.bat 调用, 也可在 PowerShell 中直接运行。

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$clientId = '178c6fc778ccc68e1d6a'   # GitHub CLI 公共 OAuth 应用 client_id
$scope = 'repo,gist,workflow,read:org'
$tokenFile = Join-Path $PSScriptRoot '..\github_token.txt'

Write-Host '正在请求一次性代码...' -ForegroundColor Cyan

# 1) 请求设备码
try {
    $resp = Invoke-RestMethod -Uri 'https://github.com/login/device/code' -Method Post -Body @{
        client_id = $clientId
        scope     = $scope
    } -Headers @{ Accept = 'application/json' }
} catch {
    Write-Host "请求设备码失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$deviceCode = $resp.device_code
$userCode   = $resp.user_code
$interval   = if ($resp.interval) { [int]$resp.interval } else { 5 }

Write-Host ''
Write-Host '==================================================' -ForegroundColor Yellow
Write-Host ' 你的【一次性代码】是: ' -NoNewline -ForegroundColor Yellow
Write-Host " $userCode " -NoNewline -ForegroundColor White -BackgroundColor DarkRed
Write-Host ''
Write-Host ' 浏览器已自动打开, 粘贴上方代码并点击 Authorize' -ForegroundColor Yellow
Write-Host '==================================================' -ForegroundColor Yellow
Write-Host ''

# 打开浏览器(优先 Chrome / Qoom Chrome)
$browser = $null
foreach ($cand in @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    'C:\Program Files\Qoom Chrome\chrome.exe')) {
    if (Test-Path $cand) { $browser = $cand; break }
}
if ($browser) {
    Start-Process $browser -ArgumentList $resp.verification_uri
} else {
    Start-Process $resp.verification_uri
}

# 2) 轮询等待用户授权(设备码 15 分钟内有效)
$tokenUri = 'https://github.com/login/oauth/access_token'
$deadline = (Get-Date).AddMinutes(14)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $interval
    try {
        $t = Invoke-RestMethod -Uri $tokenUri -Method Post -Body @{
            client_id  = $clientId
            device_code = $deviceCode
            grant_type = 'urn:ietf:params:oauth:grant-type:device_code'
        } -Headers @{ Accept = 'application/json' }
    } catch {
        Write-Host "请求异常: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
    if ($t.access_token) {
        Set-Content -Path $tokenFile -Value $t.access_token -Encoding ascii -NoNewline
        Write-Host ''
        Write-Host '==================================================' -ForegroundColor Green
        Write-Host ' 登录成功! Token 已保存, 可以关闭本窗口了' -ForegroundColor Green
        Write-Host '==================================================' -ForegroundColor Green
        exit 0
    }
    switch ($t.error) {
        'authorization_pending' { Write-Host '.' -NoNewline -ForegroundColor DarkGray; continue }
        'slow_down'             { $interval += 5; continue }
        'expired_token'         { Write-Host '设备码已过期, 请重新运行本脚本' -ForegroundColor Red; exit 1 }
        'access_denied'         { Write-Host '授权被拒绝' -ForegroundColor Red; exit 1 }
        default                 { Write-Host "未知错误: $($t.error)" -ForegroundColor Red; exit 1 }
    }
}
Write-Host '等待授权超时, 请重新运行本脚本' -ForegroundColor Red
exit 1
