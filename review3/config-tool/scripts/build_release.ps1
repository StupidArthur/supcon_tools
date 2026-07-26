# DataFactory 发布构建脚本（todo.md §15.2）
#
# 流程：
# 1. 构建 DataFactoryService.exe
# 2. 对服务 EXE 执行 health smoke
# 3. 构建 config-tool.exe
# 4. 将服务复制到 config-tool.exe 同级
# 5. 创建 project/ 和 template/
# 6. 输出两个 EXE 的大小和 SHA256
#
# 用法：
#   cd review3/config-tool
#   .\scripts\build_release.ps1

param(
    [switch]$SkipServiceBuild,
    [switch]$SkipWailsBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigToolDir = Split-Path -Parent $ScriptDir
$Review3Dir = Split-Path -Parent $ConfigToolDir
$BuildBinDir = Join-Path $ConfigToolDir "build\bin"

Write-Host "=== DataFactory 发布构建 ===" -ForegroundColor Cyan
Write-Host "Config Tool 目录: $ConfigToolDir"
Write-Host "Review3 目录: $Review3Dir"
Write-Host ""

# 1. 构建 DataFactoryService.exe
if (-not $SkipServiceBuild) {
    Write-Host "[1/6] 构建 DataFactoryService.exe..." -ForegroundColor Yellow
    Push-Location $Review3Dir
    try {
        pyinstaller DataFactoryService.spec --noconfirm
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller 构建失败"
        }
        $ServiceExe = Join-Path $Review3Dir "dist\DataFactoryService.exe"
        if (-not (Test-Path $ServiceExe)) {
            throw "DataFactoryService.exe 未生成"
        }
        Write-Host "  DataFactoryService.exe 构建成功" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
} else {
    Write-Host "[1/6] 跳过 DataFactoryService.exe 构建" -ForegroundColor DarkGray
    $ServiceExe = Join-Path $Review3Dir "dist\DataFactoryService.exe"
}

# 2. Health smoke test（真实验证）
Write-Host "[2/6] 服务 health smoke test..." -ForegroundColor Yellow
if (-not (Test-Path $ServiceExe)) {
    throw "DataFactoryService.exe 不存在: $ServiceExe"
}

# 选择一个动态端口
$SmokePort = 18999
$SmokeProcess = $null
try {
    # 启动服务，设置无鉴权模式
    $env:DATAFACTORY_NO_AUTH = "1"
    $SmokeProcess = Start-Process -FilePath $ServiceExe `
        -ArgumentList "--service", "--api-host", "127.0.0.1", "--api-port", $SmokePort `
        -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $env:TEMP "df_smoke_stdout.log") `
        -RedirectStandardError (Join-Path $env:TEMP "df_smoke_stderr.log")

    Write-Host "  服务 PID: $($SmokeProcess.Id)"

    # 等待 /api/health 就绪（最多 15 秒）
    $HealthOk = $false
    $HealthDetail = ""
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/health" -Method GET -TimeoutSec 2
            if ($resp.ok -eq $true -and $resp.serviceState -eq "ready") {
                $HealthOk = $true
                $HealthDetail = "ok=$($resp.ok) protocolVersion=$($resp.protocolVersion) serviceState=$($resp.serviceState) runtimeState=$($resp.runtimeState)"
                break
            }
            $HealthDetail = "ok=$($resp.ok) serviceState=$($resp.serviceState)"
        } catch {
            $HealthDetail = "等待中... ($($_.Exception.Message))"
        }
    }

    if (-not $HealthOk) {
        $stderrLog = ""
        try { $stderrLog = Get-Content (Join-Path $env:TEMP "df_smoke_stderr.log") -Raw -ErrorAction Stop } catch {}
        throw "Health smoke 失败: 服务未在 15s 内就绪。详情: $HealthDetail`nstderr: $stderrLog"
    }

    Write-Host "  Health 验证通过: $HealthDetail" -ForegroundColor Green

    # 验证 protocolVersion
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/health" -Method GET -TimeoutSec 2
    if ($resp.protocolVersion -ne 1) {
        throw "protocolVersion 不匹配: 期望 1, 实际 $($resp.protocolVersion)"
    }

    # 请求 /api/service/shutdown
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/service/shutdown" -Method POST -TimeoutSec 5 -Body '{}' -ContentType 'application/json'
    } catch {
        # shutdown 可能导致连接断开，忽略
    }

    # 等待进程退出（最多 10 秒）
    $Exited = $SmokeProcess.WaitForExit(10000)
    if (-not $Exited) {
        Write-Host "  服务未在 10s 内退出，强制终止" -ForegroundColor Red
        $SmokeProcess.Kill()
        $SmokeProcess.WaitForExit(5000)
        throw "服务未在超时内退出"
    }

    Write-Host "  服务已正常退出 (exit code: $($SmokeProcess.ExitCode))" -ForegroundColor Green
}
finally {
    if ($SmokeProcess -and -not $SmokeProcess.HasExited) {
        try { $SmokeProcess.Kill() } catch {}
    }
    Remove-Item Env:\DATAFACTORY_NO_AUTH -ErrorAction SilentlyContinue
}

# 3. 构建 config-tool.exe
if (-not $SkipWailsBuild) {
    Write-Host "[3/6] 构建 config-tool.exe..." -ForegroundColor Yellow
    Push-Location $ConfigToolDir
    try {
        wails build
        if ($LASTEXITCODE -ne 0) {
            throw "Wails 构建失败"
        }
        Write-Host "  config-tool.exe 构建成功" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
} else {
    Write-Host "[3/6] 跳过 config-tool.exe 构建" -ForegroundColor DarkGray
}

# 4. 复制服务到 config-tool.exe 同级
Write-Host "[4/6] 复制 DataFactoryService.exe 到发布目录..." -ForegroundColor Yellow
$TargetServiceExe = Join-Path $BuildBinDir "DataFactoryService.exe"
Copy-Item -Path $ServiceExe -Destination $TargetServiceExe -Force
Write-Host "  已复制到: $TargetServiceExe" -ForegroundColor Green

# 5. 创建 project/ 和 template/
Write-Host "[5/6] 创建 project/ 和 template/ 目录..." -ForegroundColor Yellow
$ProjectDir = Join-Path $BuildBinDir "project"
$TemplateDir = Join-Path $BuildBinDir "template"
New-Item -ItemType Directory -Path $ProjectDir -Force | Out-Null
New-Item -ItemType Directory -Path $TemplateDir -Force | Out-Null
Write-Host "  已创建: $ProjectDir" -ForegroundColor Green
Write-Host "  已创建: $TemplateDir" -ForegroundColor Green

# 6. 输出 SHA256
Write-Host "[6/6] 计算 SHA256..." -ForegroundColor Yellow
$ConfigToolExe = Join-Path $BuildBinDir "config-tool.exe"

Write-Host ""
Write-Host "=== 构建结果 ===" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $ConfigToolExe) {
    $configToolInfo = Get-Item $ConfigToolExe
    $configToolHash = Get-FileHash $ConfigToolExe -Algorithm SHA256
    Write-Host "config-tool.exe:" -ForegroundColor White
    Write-Host "  路径: $ConfigToolExe"
    Write-Host "  大小: $($configToolInfo.Length) bytes ($([math]::Round($configToolInfo.Length / 1MB, 2)) MB)"
    Write-Host "  SHA256: $($configToolHash.Hash)"
} else {
    Write-Host "config-tool.exe: 未找到" -ForegroundColor Red
}

Write-Host ""

if (Test-Path $TargetServiceExe) {
    $serviceInfo = Get-Item $TargetServiceExe
    $serviceHash = Get-FileHash $TargetServiceExe -Algorithm SHA256
    Write-Host "DataFactoryService.exe:" -ForegroundColor White
    Write-Host "  路径: $TargetServiceExe"
    Write-Host "  大小: $($serviceInfo.Length) bytes ($([math]::Round($serviceInfo.Length / 1MB, 2)) MB)"
    Write-Host "  SHA256: $($serviceHash.Hash)"
} else {
    Write-Host "DataFactoryService.exe: 未找到" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 发布目录结构 ===" -ForegroundColor Cyan
Write-Host "build/bin/"
Write-Host "├── config-tool.exe"
Write-Host "├── DataFactoryService.exe"
Write-Host "├── project/"
Write-Host "└── template/"
Write-Host ""
Write-Host "构建完成！" -ForegroundColor Green