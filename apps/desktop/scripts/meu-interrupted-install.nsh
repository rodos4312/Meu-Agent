; Included ONLY by the unpublished CI failure fixture, never normal packages.
!macro customInstall
  IfFileExists "$TEMP\meu-native-interrupt.request" 0 meu_no_interrupt
  FileOpen $0 "$INSTDIR\resources\app.asar" w
  FileWrite $0 "Controlled incomplete Meu package"
  FileClose $0
  System::Call 'kernel32::GetCurrentProcessId() i .r0'
  FileOpen $1 "$TEMP\meu-native-interrupt.ready" w
  FileWrite $1 "$0"
  FileClose $1
  StrCpy $2 0
  meu_interrupt_wait:
    Sleep 250
    IntOp $2 $2 + 1
    IntCmp $2 240 meu_interrupt_abort meu_interrupt_wait meu_interrupt_abort
  meu_interrupt_abort:
    Abort "Controlled Meu installation interruption"
  meu_no_interrupt:
!macroend
