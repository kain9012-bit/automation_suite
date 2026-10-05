; JB업무ON 설치 훅
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

; 업데이트 설치는 파일을 덮어쓰기만 하고, 새 버전에서 없어진 파일은 지우지 않는다.
; 그래서 도구를 하나 빼도 예전에 깔린 manifest.json 이 그대로 남아 앱 목록에
; 계속 나타난다. 설치 전에 도구 폴더를 비워, 새 설치본에 든 것만 남게 한다.
;
; 사용자가 따로 받은 도구는 여기가 아니라 AppData 에 들어가므로 영향이 없다.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "이전 버전의 도구 폴더를 정리하는 중..."
  RMDir /r "$INSTDIR\_up_\tools"
  RMDir /r "$INSTDIR\tools"
!macroend

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

; 문서 검색(1.4.4~) 색인 지우기
;
; 색인은 %LOCALAPPDATA%\kr.go.jbe.automation-suite\docsearch 에 있고 수백 MB 가 될 수 있다.
; 설치 제거 화면의 '애플리케이션 데이터 삭제하기'를 누르지 않아도 이 폴더만은 지운다.
; (설정·따로 받은 도구는 그 칸을 눌렀을 때만 지워진다. 그대로 둔다.)
;
; 업데이트 때는 절대 지우지 않는다. 그래서 두 가지를 모두 확인한다.
;   1) 앱의 자동 업데이트는 설치 파일을 /UPDATE 로 실행한다(board_update.rs).
;      이때 $UpdateMode = 1 이다.
;   2) 사용자가 새 설치 파일을 직접 실행해 '이전 버전 제거 후 설치'를 고르면, 설치 파일이
;      이전 제거 프로그램을 "uninstall.exe _?=설치폴더" 로 실행한다(/UPDATE 없음).
;      _?= 로 실행된 제거 프로그램은 임시 폴더로 복사되지 않고 설치 폴더에서 그대로 돈다
;      (NSIS 설명서 3.2.2). 즉 $EXEDIR = $INSTDIR 이다.
;      제어판·설정에서 제거하면 임시 폴더로 복사된 뒤 돌므로 $EXEDIR 가 $INSTDIR 와 다르다.
; 그래서 '/UPDATE 가 아니고, 임시 폴더로 복사되어 도는 제거'일 때만 지운다.

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
    ; $INSTDIR 끝에 \ 가 붙어 있어도 같게 비교한다(대소문자는 가리지 않음).
    StrCpy $R5 $INSTDIR 1 -1
    ${If} $R5 == "\"
      StrCpy $R5 $INSTDIR -1
    ${Else}
      StrCpy $R5 $INSTDIR
    ${EndIf}
    ${If} $EXEDIR != $R5
      SetShellVarContext current
      DetailPrint "문서 검색 색인을 지우는 중..."
      RMDir /r "$LOCALAPPDATA\kr.go.jbe.automation-suite\docsearch"
    ${EndIf}
  ${EndIf}
!macroend
