<#
.SYNOPSIS
  Download Piper binary and a sample French voice into third_party/piper.

.NOTES
  - Adjust URLs below to specific versions you want.
  - Run from repo root in PowerShell: `powershell -ExecutionPolicy Bypass -File scripts/setup_piper.ps1`
#>

param(
  [string]$PiperVersion = "v1.2.0",
  [string]$VoiceLang = "fr",
  [string]$VoiceName = "fr_FR-siwis-medium"
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path ".").Path
$tp = Join-Path $root "third_party"
$piperRoot = Join-Path $tp "piper"
$binDir = Join-Path $piperRoot "piper"
$modelsDir = Join-Path $piperRoot "models"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

# Piper Windows x64 binary (adjust tag/asset if needed)
$piperZip = Join-Path $tp "piper-win-x64.zip"
$piperUrl = "https://github.com/rhasspy/piper/releases/download/$PiperVersion/piper_windows_amd64.zip"

Write-Host "Downloading Piper from $piperUrl"
Invoke-WebRequest -Uri $piperUrl -OutFile $piperZip

Write-Host "Extracting Piper to $binDir"
Expand-Archive -Path $piperZip -DestinationPath $binDir -Force
Remove-Item $piperZip -Force

# Sample French voice (medium). Change to your preferred voice.
$voiceBase = "https://raw.githubusercontent.com/rhasspy/piper-voices/main/$VoiceLang/$($VoiceName.Split('-')[0])/$($VoiceName.Split('-')[1])/$($VoiceName.Split('-')[2])"
$onnxUrl = "$voiceBase/$VoiceName.onnx"
$jsonUrl = "$voiceBase/$VoiceName.onnx.json"
$onnxPath = Join-Path $modelsDir "$VoiceName.onnx"
$jsonPath = Join-Path $modelsDir "$VoiceName.onnx.json"

Write-Host "Downloading voice model: $VoiceName"
Invoke-WebRequest -Uri $onnxUrl -OutFile $onnxPath
Invoke-WebRequest -Uri $jsonUrl -OutFile $jsonPath

Write-Host "Done. Set these in your .env (or PATH):"
Write-Host "  PIPER_BIN=$binDir\\piper.exe"
Write-Host "  PIPER_MODEL=$onnxPath"

