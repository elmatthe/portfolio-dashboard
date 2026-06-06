; Custom NSIS hooks for Portfolio Dashboard.
; electron-builder auto-includes this file because it lives in the
; buildResources directory (directories.buildResources = ../assets) under the
; default name `installer.nsh`. It defines the optional macros electron-builder
; calls during install/uninstall.
;
; Item A4 — clean uninstall:
; The external tester reported that uninstalling and reinstalling did NOT return
; the app to a true first-run state (no re-prompt, still hung). The cause is that
; electron-builder's default uninstaller leaves the per-user data directory
; (%APPDATA%\Portfolio Dashboard) on disk, so a stale/corrupt profile survives
; the reinstall. This hook offers to remove that data on a genuine uninstall so
; the next install starts clean.
;
; Safety:
;  - Guarded by ${isUpdated}: during an in-place version upgrade we NEVER touch
;    user data (electron-builder runs the old uninstaller as part of updating).
;  - Defaults to "No" (keep data). Silent uninstalls (/S) also keep data (/SD IDNO).
;    The user must explicitly choose "Yes" to wipe their portfolio.
;  - $APPDATA in NSIS == %APPDATA% (C:\Users\<user>\AppData\Roaming), and
;    Electron's userData on Windows is %APPDATA%\${PRODUCT_NAME}, so the path
;    below matches exactly what the app writes at runtime.

!macro customUnInstall
  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "Also remove all your saved Portfolio Dashboard data?$\r$\n$\r$\nThis deletes every profile, all imported and manual transactions, settings, alerts, and cached prices.$\r$\n$\r$\nChoose No to keep your data for a future reinstall." \
      /SD IDNO IDYES PD_removeData IDNO PD_keepData
    PD_removeData:
      RMDir /r "$APPDATA\${PRODUCT_NAME}"
      Goto PD_doneData
    PD_keepData:
    PD_doneData:
  ${endIf}
!macroend
