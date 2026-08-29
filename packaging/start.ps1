param([string]$InputFile='')
$ErrorActionPreference='Stop'
function Has($name) { Get-Command $name -ErrorAction SilentlyContinue }
try {
  if (-not (Has 'python')) { throw 'Python 3.11 or newer is required. Install it from python.org and select Add Python to PATH.' }
  if (-not (Has 'ffmpeg')) {
    if (Has 'winget') {
      & winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements --silent
      $env:Path="$([Environment]::GetEnvironmentVariable('Path','Machine'));$([Environment]::GetEnvironmentVariable('Path','User'))"
    }
    if (-not (Has 'ffmpeg')) { throw 'FFmpeg could not be installed automatically. Install FFmpeg and start the app again.' }
  }
  $venv=Join-Path $PSScriptRoot '.audiobook-venv'
  $py=Join-Path $venv 'Scripts\pythonw.exe'
  $pyConsole=Join-Path $venv 'Scripts\python.exe'
  if (-not (Test-Path $pyConsole)) { & python -m venv $venv }
  $old=$ErrorActionPreference; $ErrorActionPreference='Continue'; & $pyConsole -m pip show faster-whisper *> $null; $missing=$LASTEXITCODE -ne 0; $ErrorActionPreference=$old
  if ($missing) { & $pyConsole -m pip install "faster-whisper>=1.1,<2"; if ($LASTEXITCODE -ne 0) { throw 'The speech-recognition components could not be installed.' } }
  $app=Join-Path $PSScriptRoot 'audiobook_ui.py'
  if ($InputFile) { & $py $app $InputFile } else { & $py $app }
} catch {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show($_.Exception.Message,'Audiobook Maker could not start','OK','Error') | Out-Null
  exit 1
}
