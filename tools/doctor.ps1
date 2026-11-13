# Offline standalone doctor, ASCII source / Windows PowerShell 5.1.
param([switch]$Share, [string]$Run)
# DIAGNOSTICS_BEGIN
# ASCII source, Windows PowerShell 5.1 and PS7. No transcript or raw exception persistence.
$script:DiagVersion = 'ILSON-DIAG-1'
$script:DiagUtf8 = New-Object System.Text.UTF8Encoding($false)
function Test-IlsonDiagPath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'LOG_UNAVAILABLE' }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }; $current = $parent
    }
}
function New-IlsonDiagDirectory([string]$Path) {
    Test-IlsonDiagPath $Path
    if ($env:OS -eq 'Windows_NT') {
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        if (-not (Test-Path -LiteralPath $Path)) {
            $security = New-Object Security.AccessControl.DirectorySecurity
            $security.SetOwner($sid); $security.SetAccessRuleProtection($true, $false)
            $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            $security.AddAccessRule($rule)
            $directory = New-Object IO.DirectoryInfo($Path)
            $directory.Create($security)
        }
        $acl = Get-Acl -LiteralPath $Path
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'LOG_UNAVAILABLE' }
        foreach ($rule in $acl.Access) {
            if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'LOG_UNAVAILABLE' }
        }
    } else { [IO.Directory]::CreateDirectory($Path) | Out-Null }
}
function Write-IlsonDiagEvent([string]$Event, [string]$Step, [string]$Result, [string]$Reason, [bool]$Required=$true, $ExitCode=$null, [string]$Source='none', [string]$HostCode='none', $Http=$null, $Transport=$null) {
    if (-not $script:DiagAvailable) { return }
    # Callers pass fixed enums only. Refuse arbitrary strings at the persistence boundary.
    if ($Event -notin @('run-start','step-start','step-end','run-end') -or $Step -notmatch '^(bootstrap\.start|download\.installer|preflight\.(platform|arch)|runtime\.(python|node)|tools\.(brew|git|jq|gh|coreutils|python|node|claude|codex|aside|herdr|hc|tvly|vendor)(\.(download|execute))?|apps\.(orca|obsidian|tailscale|aside|herdr)|kit\.prepare|vault\.prepare|helper\.install|cli\.link|path\.persist|verify\.(absolute|current|new-window|simulated)|setup\.(stage|machine|jobs|web|telegram|auth-pending)|finish)$') { throw 'INVALID_EVENT' }
    if ($Result -notin @('ok','running','failed','skipped-with-reason') -or $Reason -notin @('STARTED','OK','REUSED_VERIFIED','DEPENDENCY_FAILED','PYTHON_TOO_OLD','RUNTIME_MISSING','WRONG_INSTALLER','UNSUPPORTED_OS','SMART_DASH','UNKNOWN_OPTION','COMMAND_CONFLICT','OUTSIDE_VAULT','DNS_FAILED','HTTP_FAILED','TIMEOUT','TLS_FAILED','DOWNLOAD_FAILED','EXECUTE_FAILED','VERIFY_FAILED','HASH_MISMATCH','USER_MODIFIED','PATH_MANUAL','AUTH_PENDING','USER_CONFIRMATION_REQUIRED','USER_DECLARED','DRY_RUN','NOT_APPLICABLE','NOT_SELECTED','INTERRUPTED','LOG_UNAVAILABLE','DETAIL_SUPPRESSED','CLOCK_UNVERIFIED')) { throw 'INVALID_EVENT' }
    if ($Source -notin @('none','native','curl','exception','installer','doctor')) { $Source='none' }
    if ($HostCode -notin @('none','custom_host','raw.githubusercontent.com','codeload.github.com','github.com','claude.ai','chatgpt.com','www.python.org','releases.herdr.dev','releases.aside.com')) { $HostCode='custom_host' }
    $now = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $ended = if ($Event -like '*-end') { $now } else { $null }
    $script:DiagSeq++
    $entry = [ordered]@{schema=1;run_id=$script:DiagRun;parent_run_id=$null;seq=$script:DiagSeq;installer_version=$script:DiagVersion;source_ref=$script:DiagVersion;edition=$script:DiagEdition;event=$Event;step_id=$Step;attempt=1;started_at=$now;ended_at=$ended;elapsed_ms=$null;result=$Result;reason_code=$Reason;required=$Required;exit_code=$ExitCode;exit_source=$Source;host=$HostCode;http_code=$Http;transport_code=$Transport;proxy=$script:DiagProxy;clock='unverified'}
    try {
        if ((Get-Item -LiteralPath $script:DiagFile).Length -gt 1MB) { throw 'LOG_UNAVAILABLE' }
        [IO.File]::AppendAllText($script:DiagFile, (($entry | ConvertTo-Json -Compress -Depth 4) + "`n"), $script:DiagUtf8)
    } catch { $script:DiagAvailable=$false; Write-Warning 'LOG_UNAVAILABLE' }
}
function Start-IlsonDiagnostics([string]$Edition, [bool]$Dry=$false) {
    $script:DiagAvailable=$false; $script:DiagDry=$Dry; $script:DiagEdition=$Edition; $script:DiagSeq=0; $script:DiagActive=$null
    if ($Dry) { Write-Output 'DIAGNOSTICS DRY_RUN'; return }
    try {
        $script:DiagRoot = if ($env:ILSON_DIAGNOSTICS_DIR) { $env:ILSON_DIAGNOSTICS_DIR } else { Join-Path $env:LOCALAPPDATA 'ilson-diagnostics' }
        New-IlsonDiagDirectory $script:DiagRoot
        New-IlsonDiagDirectory (Join-Path $script:DiagRoot 'runs')
        $script:DiagRun = [guid]::NewGuid().ToString('N')
        $folder = Join-Path (Join-Path $script:DiagRoot 'runs') $script:DiagRun
        New-IlsonDiagDirectory $folder
        $script:DiagFile = Join-Path $folder 'events.jsonl'
        [IO.File]::WriteAllText($script:DiagFile, '', $script:DiagUtf8)
        $script:DiagProxy = 'false'
        foreach ($key in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')) { if ([Environment]::GetEnvironmentVariable($key)) { $script:DiagProxy='true' } }
        if ($env:OS -eq 'Windows_NT') {
            # Query only a boolean, never persist PAC/proxy addresses or authentication.
            try { $proxy=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop; if ($proxy.ProxyEnable -or $proxy.AutoConfigURL) { $script:DiagProxy='true' } } catch { $script:DiagProxy='unknown' }
        }
        $script:DiagAvailable=$true
        Write-IlsonDiagEvent 'run-start' 'bootstrap.start' 'running' 'STARTED'
    } catch { Write-Warning 'LOG_UNAVAILABLE' }
}
function Start-IlsonStep([string]$Step, [bool]$Required=$true) {
    $script:DiagActive=$Step; $script:DiagRequired=$Required
    Write-IlsonDiagEvent 'step-start' $Step 'running' 'STARTED' $Required
}
function Stop-IlsonStep([string]$Step, [string]$Result='ok', [string]$Reason='OK', [bool]$Required=$true, $ExitCode=$null, [string]$Source='none', [string]$HostCode='none', $Http=$null, $Transport=$null) {
    Write-IlsonDiagEvent 'step-end' $Step $Result $Reason $Required $ExitCode $Source $HostCode $Http $Transport
    $script:DiagActive=$null
}
function Get-IlsonWebFailure($Failure) {
    $ex=$Failure.Exception; $http=$null; $reason='DOWNLOAD_FAILED'
    while ($ex -and $ex -isnot [Net.WebException] -and $ex.InnerException) { $ex=$ex.InnerException }
    if ($ex -is [Net.WebException]) {
        switch ($ex.Status.ToString()) {
            'NameResolutionFailure' { $reason='DNS_FAILED' }
            'ProxyNameResolutionFailure' { $reason='DNS_FAILED' }
            'Timeout' { $reason='TIMEOUT' }
            'TrustFailure' { $reason='TLS_FAILED' }
            'SecureChannelFailure' { $reason='TLS_FAILED' }
            'ProtocolError' { $reason='HTTP_FAILED' }
        }
        if ($ex.Response) { try { $http=[int]$ex.Response.StatusCode } catch { } }
    } elseif ($ex.Response) { try { $http=[int]$ex.Response.StatusCode; $reason='HTTP_FAILED' } catch { } }
    [pscustomobject]@{Reason=$reason;Http=$http}
}
function Invoke-IlsonStep([string]$Step, [scriptblock]$Action, [bool]$Required=$true) {
    Start-IlsonStep $Step $Required
    try {
        if ($script:DiagDry) { Stop-IlsonStep $Step 'skipped-with-reason' 'DRY_RUN' $Required; return }
        & $Action
        Stop-IlsonStep $Step 'ok' 'OK' $Required
    } catch {
        Stop-IlsonStep $Step 'failed' 'EXECUTE_FAILED' $Required $null 'exception'
        throw 'EXECUTE_FAILED'
    }
}
function Get-IlsonDownload([string]$Url, [string]$Step, [string]$OutFile='') {
    $hostCode='custom_host'; $uri=[uri]$Url
    if ($uri.Host -in @('raw.githubusercontent.com','codeload.github.com','github.com','claude.ai','chatgpt.com','www.python.org')) { $hostCode=$uri.Host }
    Start-IlsonStep $Step
    try {
        # Do not disable certificate validation or change TLS settings. TLS errors advise OS updates.
        $client=New-Object Net.WebClient
        try { $bytes=$client.DownloadData($Url) } finally { $client.Dispose() }
        if ($OutFile) { [IO.File]::WriteAllBytes($OutFile,$bytes) }
        Stop-IlsonStep $Step 'ok' 'OK' $true 0 'native' $hostCode 200
        if (-not $OutFile) { return ,$bytes }
    } catch {
        $failure=Get-IlsonWebFailure $_
        Stop-IlsonStep $Step 'failed' $failure.Reason $true $null 'exception' $hostCode $failure.Http
        if ($failure.Reason -eq 'TLS_FAILED') { Write-Warning 'TLS_FAILED: Check Windows updates and TLS 1.2 support. TLS policy unchanged.' }
        throw $failure.Reason
    }
}
function Complete-IlsonDiagnostics([int]$Code=0) {
    if ($script:DiagDry) { return 0 }
    if (-not $script:DiagAvailable) { return 3 }
    if ($script:DiagActive) { Stop-IlsonStep $script:DiagActive 'failed' 'INTERRUPTED' $script:DiagRequired; $Code=3 }
    $events=@([IO.File]::ReadAllLines($script:DiagFile) | ForEach-Object { $_ | ConvertFrom-Json })
    if (@($events | Where-Object { $_.event -eq 'step-end' -and $_.required -and $_.result -ne 'ok' -and $_.reason_code -notin @('DRY_RUN','NOT_APPLICABLE','NOT_SELECTED') }).Count -and $Code -eq 0) { $Code=1 }
    $result=if ($Code -eq 0) {'ok'} else {'failed'}
    $reason=if ($Code -eq 0) {'OK'} else {'EXECUTE_FAILED'}
    Write-IlsonDiagEvent 'run-end' 'finish' $result $reason $true $Code 'installer'
    $script:IlsonInstallExitCode=$Code
    Write-Output ('INSTALL_RESULT=' + $Code)
    Write-Output ('Current window: $env:Path=[Environment]::GetEnvironmentVariable(''Path'',''Machine'')+'';''+[Environment]::GetEnvironmentVariable(''Path'',''User''); ilson doctor --install --confirm-shell current --run ' + $script:DiagRun)
    Write-Output ('New window (user declaration): ilson doctor --install --confirm-shell new --run ' + $script:DiagRun)
    Write-Output ('Recovery: & "$env:LOCALAPPDATA\ilson-course\bin\ilson.cmd" doctor --install --run ' + $script:DiagRun)
    return $Code
}
# DIAGNOSTICS_END
function Invoke-IlsonDoctor {
    try {
        $root=if ($env:ILSON_DIAGNOSTICS_DIR) {$env:ILSON_DIAGNOSTICS_DIR} else {Join-Path $env:LOCALAPPDATA 'ilson-diagnostics'}
        Test-IlsonDiagPath $root
        if (-not (Test-Path -LiteralPath (Join-Path $root 'runs'))) { Write-Output 'NO_RUN: old irm|iex cannot observe failure before the first script byte.'; return 3 }
        if ($Run -and $Run -notmatch '^[a-f0-9]{32}$') { Write-Output 'INVALID_RUN'; return 2 }
        $folders=@(Get-ChildItem -LiteralPath (Join-Path $root 'runs') -Directory | Where-Object {$_.Name -match '^[a-f0-9]{32}$'} | Sort-Object LastWriteTimeUtc -Descending)
        $folder=if ($Run) {Join-Path (Join-Path $root 'runs') $Run} elseif ($folders.Count) {$folders[0].FullName} else {$null}
        if (-not $folder) { Write-Output 'NO_RUN'; return 3 }
        Test-IlsonDiagPath $folder
        $file=Join-Path $folder 'events.jsonl'; Test-IlsonDiagPath $file
        if ((Get-Item -LiteralPath $file).Length -gt 1MB) { throw 'LOG_UNAVAILABLE' }
        $events=@(); $damaged=$false
        foreach ($line in [IO.File]::ReadAllLines($file, $script:DiagUtf8)) { try {$events+=@($line | ConvertFrom-Json -ErrorAction Stop)} catch {$damaged=$true} }
        $ended=@($events | Where-Object {$_.event -eq 'run-end'})
        $failed=@($events | Where-Object {$_.event -eq 'step-end' -and $_.required -and $_.result -ne 'ok' -and $_.reason_code -notin @('DRY_RUN','NOT_APPLICABLE','NOT_SELECTED')})
        $code=if ($damaged -or -not $ended.Count) {3} elseif ($failed.Count -or $ended[-1].result -eq 'failed') {1} else {0}
        # Rebuild the summary from fixed codes. Never echo arbitrary fields from disk.
        $summary='Ilson offline install diagnostics; result=' + $code + '; current/new window require separate user confirmation.'
        Write-Output $summary
        if ($Share) {
            $dest=Join-Path $root 'share'; New-IlsonDiagDirectory $dest
            $reference='IL-' + [guid]::NewGuid().ToString('N').Substring(0,12).ToUpperInvariant()
            $output=Join-Path $dest ($reference+'.txt')
            $stream=[IO.File]::Open($output,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
            try {$bytes=$script:DiagUtf8.GetBytes($summary+"`nSend this reviewed file with its reference. Nothing uploaded.`n");$stream.Write($bytes,0,$bytes.Length)} finally {$stream.Dispose()}
            Write-Output ('Share reference: '+$reference+' (send the file too; no automatic upload)')
        }
        return $code
    } catch { Write-Output 'LOG_UNAVAILABLE'; return 3 }
}
$script:IlsonDoctorExitCode = @(Invoke-IlsonDoctor)
$script:IlsonDoctorExitCode | Write-Output
# Do not exit an interactive irm|iex caller. File mode can return an OS exit code.
if ($MyInvocation.MyCommand.Path) { exit [int]$script:IlsonDoctorExitCode[-1] }
