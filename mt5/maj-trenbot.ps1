# Met à jour TrenBot dans MT5 : télécharge la dernière version depuis GitHub, la place dans
# MQL5\Experts et la compile. Lancé par MAJ-TrenBot.bat (double-clic).
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$url  = 'https://raw.githubusercontent.com/Leandre99/Trenbot/main/mt5/TrenBot.mq5'
$root = Join-Path $env:APPDATA 'MetaQuotes\Terminal'

function Read-Text($path) {
    # origin.txt et les journaux de MetaEditor peuvent être en UTF-16 : on enlève les caractères nuls
    return ([IO.File]::ReadAllText($path) -replace "`0", '').Trim()
}

if (-not (Test-Path $root)) { throw "MT5 introuvable : ouvre MT5 une fois, puis relance la mise à jour." }
$dirs = Get-ChildItem $root -Directory | Where-Object {
    (Test-Path (Join-Path $_.FullName 'MQL5\Experts')) -and (Test-Path (Join-Path $_.FullName 'origin.txt'))
}
if (-not $dirs) { throw "Dossier de données MT5 introuvable : ouvre MT5 une fois, puis relance la mise à jour." }

$tmp = Join-Path $env:TEMP 'TrenBot.mq5'
Write-Host "Téléchargement de la dernière version de TrenBot depuis GitHub..."
Invoke-WebRequest $url -OutFile $tmp -UseBasicParsing
Write-Host ("  {0:N0} octets reçus" -f (Get-Item $tmp).Length)

foreach ($d in $dirs) {
    $install = Read-Text (Join-Path $d.FullName 'origin.txt')
    $me = Join-Path $install 'metaeditor64.exe'
    if (-not (Test-Path $me)) { Write-Host "  (ignoré : pas de MetaEditor dans $install)"; continue }
    $dest = Join-Path $d.FullName 'MQL5\Experts\TrenBot.mq5'
    Copy-Item $tmp $dest -Force
    Write-Host "Compilation pour MT5 : $install"
    $log = [IO.Path]::ChangeExtension($dest, '.log')
    if (Test-Path $log) { Remove-Item $log -Force }
    Start-Process -FilePath $me -ArgumentList "/compile:`"$dest`"", '/log' -Wait -WindowStyle Hidden
    if (Test-Path $log) {
        $txt = Read-Text $log
        $res = ($txt -split "`r?`n" | Where-Object { $_ -match 'Result|error' }) -join "`n"
        Write-Host $res
        if ($txt -match 'Result:\s*0 errors') {
            Write-Host "OK : TrenBot est à jour. MT5 recharge le robot tout seul (sinon : F7 sur son graphique, puis OK)." -ForegroundColor Green
        } else {
            Write-Host "ERREUR de compilation : envoie cette fenêtre (capture) à Claude." -ForegroundColor Red
        }
    } else {
        Write-Host "Compilation lancée, mais pas de journal trouvé : vérifie dans MetaEditor (F7)." -ForegroundColor Yellow
    }
}
