; Atomic movement/rollback adapted from electron-builder uninstaller.nsh.
; Extended Windows paths apply to both operands, without changing install identity.
; The MIT License (MIT)
; Copyright (c) 2015 Loopline Systems
;
; Permission is hereby granted, free of charge, to any person obtaining a copy
; of this software and associated documentation files (the "Software"), to deal
; in the Software without restriction, including without limitation the rights
; to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
; copies of the Software, and to permit persons to whom the Software is
; furnished to do so, subject to the following conditions:
;
; The above copyright notice and this permission notice shall be included in all
; copies or substantial portions of the Software.
;
; THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
; IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
; FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
; AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
; LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
; OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
; SOFTWARE.

!ifndef MEU_LONG_PATH_UNINSTALL
!define MEU_LONG_PATH_UNINSTALL
!macro customHeader
!ifdef BUILD_UNINSTALLER
Var meuRemovalSource
Var meuRemovalBackup

Function un.meuExtendedPath
  Exch $R0
  Push $R1
  StrCpy $R1 $R0 4
  StrCmp $R1 "\\?\" done
  StrCpy $R1 $R0 2
  StrCmp $R1 "\\" unc
  StrCpy $R0 "\\?\$R0"
  Goto done
  unc:
    StrCpy $R0 $R0 "" 2
    StrCpy $R0 "\\?\UNC\$R0"
  done:
  Pop $R1
  Exch $R0
FunctionEnd

Function un.meuPrepareRemoval
  InitPluginsDir
  Push "$INSTDIR"
  Call un.meuExtendedPath
  Pop $meuRemovalSource
  Push "$PLUGINSDIR\old-install"
  Call un.meuExtendedPath
  Pop $meuRemovalBackup
  CreateDirectory "$meuRemovalBackup"
FunctionEnd

Function un.meuAtomicRMDir
  Exch $R0
  Push $R1
  Push $R2
  Push $R3

  StrCpy $R3 "$meuRemovalSource$R0\*.*"
  FindFirst $R1 $R2 $R3

  loop:
    StrCmp $R2 "" break

    StrCmp $R2 "." continue
    StrCmp $R2 ".." continue

    IfFileExists "$meuRemovalSource$R0\$R2\*.*" isDir isNotDir

    isDir:
      CreateDirectory "$meuRemovalBackup$R0\$R2"

      Push "$R0\$R2"
      Call un.meuAtomicRMDir
      Pop $R3

      ${if} $R3 != 0
        Goto done
      ${endIf}

      Goto continue

    isNotDir:
      ClearErrors
      Rename "$meuRemovalSource$R0\$R2" "$meuRemovalBackup$R0\$R2"

      # Ignore errors when renaming ourselves.
      StrCmp "$R0\$R2" "${UNINSTALL_FILENAME}" 0 +2
      ClearErrors

      IfErrors 0 +3
      StrCpy $R3 "$meuRemovalSource$R0\$R2"
      Goto done

    continue:
      FindNext $R1 $R2
      Goto loop

  break:
    StrCpy $R3 0

  done:
    FindClose $R1

    StrCpy $R0 $R3

    Pop $R3
    Pop $R2
    Pop $R1
    Exch $R0
FunctionEnd

Function un.meuRestoreFiles
  Exch $R0
  Push $R1
  Push $R2
  Push $R3

  StrCpy $R3 "$meuRemovalBackup$R0\*.*"
  FindFirst $R1 $R2 $R3

  loop:
    StrCmp $R2 "" break

    StrCmp $R2 "." continue
    StrCmp $R2 ".." continue

    IfFileExists "$meuRemovalSource$R0\$R2\*.*" isDir isNotDir

    isDir:
      CreateDirectory "$meuRemovalSource$R0\$R2"

      Push "$R0\$R2"
      Call un.meuRestoreFiles
      Pop $R3

      Goto continue

    isNotDir:
      Rename "$meuRemovalBackup$R0\$R2" "$meuRemovalSource$R0\$R2"

    continue:
      FindNext $R1 $R2
      Goto loop

  break:
    StrCpy $R0 0
    FindClose $R1

    Pop $R3
    Pop $R2
    Pop $R1
    Exch $R0
FunctionEnd


!endif
!macroend

!macro customRemoveFiles
  Call un.meuPrepareRemoval
  ${if} ${isUpdated}
    Push ""
    Call un.meuAtomicRMDir
    Pop $R0
    ${if} $R0 != 0
      DetailPrint "File is busy, aborting: $R0"
      Push ""
      Call un.meuRestoreFiles
      Pop $R0
      SetErrorLevel 2
      Abort `Can't replace "$INSTDIR"; original files restored.`
    ${endif}
  ${endif}
  SetOutPath $TEMP
  RMDir /r "$meuRemovalSource"
!macroend
!endif
