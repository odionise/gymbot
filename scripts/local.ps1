param(
    [ValidateSet('preview', 'telegram', 'status', 'stop')]
    [string]$Mode = 'preview'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$localEnv = Join-Path $projectRoot '.env.local'
$exampleEnv = Join-Path $projectRoot '.env.local.example'
$composeFile = Join-Path $projectRoot 'compose.local.yaml'

function Read-LocalValue([string]$Name) {
    if (-not (Test-Path -LiteralPath $localEnv)) { return '' }
    foreach ($line in [System.IO.File]::ReadAllLines($localEnv)) {
        if ($line -match "^$([regex]::Escape($Name))=(.*)$") { return $Matches[1] }
    }
    return ''
}

function Set-LocalValue([string]$Name, [string]$Value) {
    if ($Value.Contains("`n") -or $Value.Contains("`r")) { throw "Invalid value for $Name" }
    $lines = [System.Collections.Generic.List[string]]::new()
    $found = $false
    foreach ($line in [System.IO.File]::ReadAllLines($localEnv)) {
        if ($line -match "^$([regex]::Escape($Name))=") {
            $lines.Add("$Name=$Value")
            $found = $true
        } else {
            $lines.Add($line)
        }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($localEnv, $lines, [System.Text.UTF8Encoding]::new($false))
}

function Initialize-LocalEnv {
    if (Test-Path -LiteralPath $localEnv) { return }
    Copy-Item -LiteralPath $exampleEnv -Destination $localEnv
    $password = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant()
    $secret = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant()
    Set-LocalValue 'POSTGRES_PASSWORD' $password
    Set-LocalValue 'DATABASE_URL' "postgresql+psycopg://workout:${password}@db:5432/workout"
    Set-LocalValue 'WEBHOOK_SECRET' $secret
    Write-Host 'Создан .env.local с локальными случайными секретами.'
}

function Assert-Docker {
    $null = docker info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -eq 0) { $script:dockerContext = ''; return }
    $null = docker --context default info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -eq 0) { $script:dockerContext = 'default'; return }
    throw 'Docker Engine не запущен. Запустите Docker Desktop и повторите команду.'
}

function Invoke-Compose([string[]]$Arguments) {
    $contextArgs = if ($script:dockerContext) { @('--context', $script:dockerContext) } else { @() }
    & docker @contextArgs compose --env-file $localEnv -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Команда Docker Compose завершилась с ошибкой.' }
}

function Get-TelegramWebhook([string]$Token) {
    try {
        $response = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$Token/getWebhookInfo" -TimeoutSec 15
        if ($response.ok) { return [string]$response.result.url }
    } catch { }
    return ''
}

function Clear-LocalWebhook {
    $token = Read-LocalValue 'BOT_TOKEN'
    $url = Read-LocalValue 'PUBLIC_URL'
    if (-not $token -or $url -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') { return }
    if ((Get-TelegramWebhook $token) -ne "$url/telegram/webhook") { return }
    try {
        $null = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/deleteWebhook" -TimeoutSec 15
        Write-Host 'Тестовый webhook удалён из Telegram.'
    } catch {
        Write-Warning 'Не удалось удалить тестовый webhook. Проверьте подключение к Telegram.'
    }
}

function Wait-LocalHealth {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 3
            if ($response.ok) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Локальный API не ответил. Посмотрите логи: docker compose --env-file .env.local -f compose.local.yaml logs api web'
}

Push-Location -LiteralPath $projectRoot
try {
    Initialize-LocalEnv
    Assert-Docker

    switch ($Mode) {
        'preview' {
            Clear-LocalWebhook
            Invoke-Compose @('--profile', 'telegram', 'stop', 'tunnel')
            Set-LocalValue 'APP_ENV' 'development'
            Set-LocalValue 'BOT_TOKEN' ''
            Set-LocalValue 'PUBLIC_URL' 'http://localhost:8080'
            Set-LocalValue 'DEV_TELEGRAM_ID' '123456789'
            Invoke-Compose @('up', '-d', '--build', '--force-recreate', 'db', 'api', 'web')
            Wait-LocalHealth
            Write-Host 'Откройте http://localhost:8080 — это локальный просмотр с тестовым пользователем.'
        }
        'telegram' {
            $token = Read-LocalValue 'TELEGRAM_BOT_TOKEN'
            if (-not $token -or $token -eq 'replace-with-botfather-token') {
                throw 'Впишите токен отдельного тестового бота в TELEGRAM_BOT_TOKEN файла .env.local, затем повторите команду.'
            }
            Clear-LocalWebhook
            Set-LocalValue 'APP_ENV' 'development'
            Set-LocalValue 'BOT_TOKEN' ''
            Set-LocalValue 'PUBLIC_URL' 'http://localhost:8080'
            Set-LocalValue 'DEV_TELEGRAM_ID' '0'
            Invoke-Compose @('up', '-d', '--build', '--force-recreate', 'db', 'api', 'web')
            Wait-LocalHealth
            Invoke-Compose @('--profile', 'telegram', 'up', '-d', 'tunnel')
            $url = ''
            for ($attempt = 0; $attempt -lt 45; $attempt++) {
                $contextArgs = if ($script:dockerContext) { @('--context', $script:dockerContext) } else { @() }
                $logs = (& docker @contextArgs compose --env-file $localEnv -f $composeFile --profile telegram logs --no-color tunnel 2>&1) -join "`n"
                if ($logs -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
                    $url = $Matches[0]
                    break
                }
                Start-Sleep -Seconds 1
            }
            if (-not $url) { throw 'Туннель не выдал HTTPS-адрес. Посмотрите логи сервиса tunnel.' }
            Set-LocalValue 'APP_ENV' 'production'
            Set-LocalValue 'BOT_TOKEN' $token
            Set-LocalValue 'PUBLIC_URL' $url
            Invoke-Compose @('up', '-d', '--force-recreate', 'api')
            Wait-LocalHealth
            $registered = Get-TelegramWebhook $token
            if ($registered -ne "$url/telegram/webhook") {
                throw 'API доступен, но Telegram не подтвердил webhook. Проверьте логи api и tunnel.'
            }
            Write-Host "Mini App: $url"
            Write-Host 'Отправьте тестовому боту /start в личном чате и нажмите «Открыть тренировку».'
            Write-Host 'После перезапуска туннеля запустите этот режим ещё раз: адрес меняется.'
        }
        'status' {
            Invoke-Compose @('--profile', 'telegram', 'ps')
            Write-Host "Локальный адрес: http://localhost:8080"
            $url = Read-LocalValue 'PUBLIC_URL'
            if ($url -match '^https://[a-z0-9-]+\.trycloudflare\.com$') { Write-Host "Telegram Mini App: $url" }
        }
        'stop' {
            Clear-LocalWebhook
            Invoke-Compose @('--profile', 'telegram', 'down')
            Write-Host 'Контейнеры остановлены. Данные PostgreSQL сохранены.'
        }
    }
} finally {
    Pop-Location
}
