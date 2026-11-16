Unicode true
; Match electron-builder: custom include precedes its common headers.
!ifdef MEU_FIXED
  !define BUILD_UNINSTALLER
  !include "${MEU_HELPER}"
!endif
!include LogicLib.nsh
!define UNINSTALL_FILENAME "fixture-uninstall.exe"
!ifdef MEU_FIXED
  !insertmacro customHeader
!else
  !include "${UPSTREAM_HELPER}"
!endif
Name "MEU isolated atomic-removal fixture"
OutFile "${BOOTSTRAP_OUT}"
RequestExecutionLevel user
SilentInstall silent
SilentUnInstall silent
Section
  WriteUninstaller "${FIXTURE_OUT}"
SectionEnd
Section "Uninstall"
  IfFileExists "$INSTDIR\fixture.guard" guarded
  SetErrorLevel 80
  Quit
  guarded:
  !ifdef MEU_FIXED
    !ifdef FULL_UNINSTALL
      !define isUpdated `1 == 0`
    !else
      !define isUpdated `1 == 1`
    !endif
    !insertmacro customRemoveFiles
    SetErrorLevel 0
  !else
    InitPluginsDir
    CreateDirectory "$PLUGINSDIR\old-install"
    Push ""
    Call un.atomicRMDir
    Pop $R0
    ${if} $R0 != 0
      Push ""
      Call un.restoreFiles
      Pop $R0
      SetErrorLevel 2
    ${else}
      SetErrorLevel 0
    ${endif}
  !endif
SectionEnd
