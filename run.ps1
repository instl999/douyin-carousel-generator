# Windows 一键脚本
#   .\run.ps1 "楼盘名字里的暗号"
#   .\run.ps1 "第一次租房避坑" -Character 小圆 -Handle your_douyin_id
#   .\run.ps1 "测试主题" -Offline
param(
  [Parameter(Mandatory=$true, Position=0)][string]$Theme,
  [string]$Style = "",
  [string]$Character = "",
  [string]$Handle = "",
  [int]$Pages = 0,
  [switch]$Offline
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = "python"
if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" }

$cliArgs = @("-m", "dig", "run", "--theme", $Theme)
if ($Style)       { $cliArgs += @("--style", $Style) }
if ($Character)   { $cliArgs += @("--character", $Character) }
if ($Handle)      { $cliArgs += @("--handle", $Handle) }
if ($Pages -gt 0) { $cliArgs += @("--pages", "$Pages") }
if ($Offline)     { $cliArgs += "--offline" }

& $py @cliArgs
