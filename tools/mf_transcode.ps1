# Windows-native audio transcode via Media Foundation (no ffmpeg needed).
# Run with Windows PowerShell 5.1:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File mf_transcode.ps1 ...
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Dest,
    [switch]$AsWav,
    [ValidateSet('Low', 'Medium', 'High')][string]$Quality = 'Low',
    [int]$Bitrate = 64000,
    [int]$Channels = 1,
    [int]$SampleRate = 0
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskOp = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskOp.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Transcoding.MediaTranscoder, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.MediaProperties.MediaEncodingProfile, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.MediaProperties.AudioEncodingQuality, Windows.Media, ContentType = WindowsRuntime] | Out-Null

$srcFile = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path -LiteralPath $Source).Path)) ([Windows.Storage.StorageFile])
$destDir = Split-Path -Parent $Dest
$destName = Split-Path -Leaf $Dest
$folder = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($destDir)) ([Windows.Storage.StorageFolder])
$dstFile = Await ($folder.CreateFileAsync($destName, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])

$q = [Windows.Media.MediaProperties.AudioEncodingQuality]::$Quality
if ($AsWav) {
    $profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateWav($q)
    if ($SampleRate -gt 0) { $profile.Audio.SampleRate = $SampleRate }
    if ($Channels -gt 0) { $profile.Audio.ChannelCount = $Channels }
}
else {
    $profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateM4a($q)
    if ($Bitrate -gt 0) { $profile.Audio.Bitrate = $Bitrate }
    if ($Channels -gt 0) { $profile.Audio.ChannelCount = $Channels }
}

$transcoder = New-Object Windows.Media.Transcoding.MediaTranscoder
$prep = Await ($transcoder.PrepareFileTranscodeAsync($srcFile, $dstFile, $profile)) ([Windows.Media.Transcoding.PrepareTranscodeResult])

if (-not $prep.CanTranscode) {
    Write-Output "FAIL canTranscode=false reason=$($prep.FailureReason)"
    exit 2
}

# TranscodeAsync is IAsyncOperationWithProgress; PowerShell cannot project that generic
# into AsTask reliably, so drive it by polling the output file until it settles.
$null = $prep.TranscodeAsync()
$last = -1
$stable = 0
for ($i = 0; $i -lt 1200; $i++) {
    Start-Sleep -Milliseconds 250
    $len = if (Test-Path $Dest) { (Get-Item $Dest).Length } else { 0 }
    if ($len -gt 0 -and $len -eq $last) { $stable++ } else { $stable = 0 }
    $last = $len
    if ($stable -ge 6) { break }
}
if (-not (Test-Path $Dest)) { Write-Output "FAIL no output"; exit 3 }
Write-Output "OK size=$((Get-Item $Dest).Length) seconds=$([math]::Round($i * 0.25, 1))"
