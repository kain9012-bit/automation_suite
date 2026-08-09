; JB업무ON 설치 제거 훅
;
; 탐색기 우클릭 메뉴는 앱이 HKCU 아래에 직접 만든 키라서 설치 제거 프로그램이
; 알지 못한다. 그대로 두면 앱을 지운 뒤에도 메뉴가 남아 눌러도 아무 일이 없다.
; 앱은 키 이름을 항상 JBEduON. 으로 시작하게 만들므로 그 접두어만 찾아 지운다.
;
;   폴더:   HKCU\Software\Classes\Directory\shell\JBEduON.<도구ID>
;   파일:   HKCU\Software\Classes\SystemFileAssociations\.<확장자>\shell\JBEduON.<도구ID>
;
; 확장자 목록은 사용자가 무엇을 켰는지에 따라 달라지므로 미리 적어 둘 수 없다.
; 그래서 목록을 훑으면서 접두어가 맞는 것만 지운다.

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "탐색기 우클릭 메뉴를 정리하는 중..."

  ; 폴더 우클릭
  StrCpy $R0 0
  jbedu_dir_loop:
    EnumRegKey $R1 HKCU "Software\Classes\Directory\shell" $R0
    StrCmp $R1 "" jbedu_dir_done
    StrCpy $R2 $R1 8
    StrCmp $R2 "JBEduON." 0 jbedu_dir_next
      DeleteRegKey HKCU "Software\Classes\Directory\shell\$R1"
      ; 하나 지우면 뒤 항목이 앞으로 당겨지므로 번호를 올리지 않는다.
      Goto jbedu_dir_loop
    jbedu_dir_next:
    IntOp $R0 $R0 + 1
    Goto jbedu_dir_loop
  jbedu_dir_done:

  ; 확장자별 파일 우클릭
  StrCpy $R0 0
  jbedu_ext_loop:
    EnumRegKey $R1 HKCU "Software\Classes\SystemFileAssociations" $R0
    StrCmp $R1 "" jbedu_ext_done
    StrCpy $R3 0
    jbedu_shell_loop:
      EnumRegKey $R4 HKCU "Software\Classes\SystemFileAssociations\$R1\shell" $R3
      StrCmp $R4 "" jbedu_shell_done
      StrCpy $R2 $R4 8
      StrCmp $R2 "JBEduON." 0 jbedu_shell_next
        DeleteRegKey HKCU "Software\Classes\SystemFileAssociations\$R1\shell\$R4"
        Goto jbedu_shell_loop
      jbedu_shell_next:
      IntOp $R3 $R3 + 1
      Goto jbedu_shell_loop
    jbedu_shell_done:
    IntOp $R0 $R0 + 1
    Goto jbedu_ext_loop
  jbedu_ext_done:
!macroend
