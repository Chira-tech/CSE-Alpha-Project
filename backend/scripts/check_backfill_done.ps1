# Polled by the "CSE-Alpha-Backfill-DoneCheck" scheduled task every few
# minutes. Independent of any chat session — durable the same way
# backup_devdb.py's scheduled task is: it survives even if the session
# watching the backfill process gets cut off or the harness kills a
# foreground/background tool call.
$logFile = "C:\Users\USER\Documents\Claude Code Projects\CSE-Alpha-Project\backend\logs\backfill-financials-2026-08-22_153743.log"
$markerFile = "C:\Users\USER\Documents\Claude Code Projects\CSE-Alpha-Project\backend\logs\BACKFILL_COMPLETE.txt"

if (Test-Path $markerFile) {
    # Already recorded — nothing left to do, deregister so this stops firing.
    Unregister-ScheduledTask -TaskName "CSE-Alpha-Backfill-DoneCheck" -Confirm:$false -ErrorAction SilentlyContinue
    exit 0
}

if (Test-Path $logFile) {
    $done = Select-String -Path $logFile -Pattern '^Done\.' -Quiet -ErrorAction SilentlyContinue
    if ($done) {
        $lastLine = Get-Content $logFile -Tail 1
        "$(Get-Date -Format o)  $lastLine" | Out-File -Encoding utf8 $markerFile
        Unregister-ScheduledTask -TaskName "CSE-Alpha-Backfill-DoneCheck" -Confirm:$false -ErrorAction SilentlyContinue
    }
}
