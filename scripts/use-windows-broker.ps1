#requires -Version 7.0
# Dot-source in the ordinary PowerShell where Hiro runs. Does not elevate.
$env:PYTHONUTF8 = '1'
$env:HIRO_EXPLICIT_IDOL_STATE = '1'
$env:HIRO_DEVICE_BACKEND = 'hiro.platforms.windows.broker'
$env:HIRO_OCR_BACKEND = 'hiro.platforms.windows.ocr'
$env:HIRO_WINDOW_BACKEND = 'hiro.platforms.windows.window'
$env:HIRO_DECLINE_IDOL_SWITCH = '1'
# Retry a no-effect home entry only on a fresh confirmed home frame (3 clicks max).
$env:HIRO_WINDOWS_HOME_RETRY = '1'
# Keep numeric action HUD crops at native size for RapidOCR's text detector.
$env:HIRO_WINDOWS_HUD_NATIVE_SCALE = '1'
# Keep unsupported public lesson previews explicitly unknown.
$env:HIRO_PUBLIC_LESSON_FALLBACK = '1'
# Bounded shared fixed-counter selector for Step 2 and Step 3.
$env:HIRO_BOUNDED_SET_SELECTION = '1'
# Verify memory picker, selected cell, stable detail pages; skip covered rows.
$env:HIRO_MEMORY_SCAN_VERIFIED = '1'
$env:HIRO_WINDOWS_BROKER_STATE = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../reports/windows-broker/session.json'))
