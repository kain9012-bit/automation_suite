# 배포와 자동 업데이트

JB업무ON은 두 가지를 따로 업데이트합니다.

| 대상 | 방식 | 서명키 |
|---|---|---|
| 앱 본체 | GitHub Releases에 올라간 `latest.json`을 확인해 새 설치본을 내려받아 교체 | `.signing/tauri.key` |
| 개별 도구 | 서명된 도구 카탈로그를 확인해 새 도구 추가·기존 도구 교체 | `.signing/tools_ed25519.key` |

앱을 다시 설치하지 않아도 도구만 바꿔 끼울 수 있도록 나눠 두었습니다.

---

## 처음 한 번만 하는 준비

GitHub 저장소에 서명키를 비밀값으로 등록해야 GitHub Actions가 설치본에 서명할 수 있습니다.
**개인키는 저장소에 올라가지 않습니다**(`.gitignore`로 제외). 잃어버리면 기존 설치본에
업데이트를 내려줄 수 없으니 별도로 백업해 두세요.

1. GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. 아래 두 개를 등록합니다.

| 이름 | 값 |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | `.signing\tauri.key` 파일 **내용 전체** |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `.signing\tauri.password` 파일 내용 |

파일 내용은 이렇게 복사하면 됩니다.

```powershell
Get-Content C:\work\automation_suite\.signing\tauri.key -Raw | Set-Clipboard
```

---

## 새 버전 배포하기

### 1. 버전 올리기

버전이 네 곳(`package.json`, `tauri.conf.json`, `Cargo.toml`, `Cargo.lock`)에 흩어져 있어
하나만 빠뜨리면 자동 업데이트가 조용히 동작하지 않습니다. 스크립트로 한 번에 맞춥니다.

```powershell
cd C:\work\automation_suite
powershell -ExecutionPolicy Bypass -File .\scripts\set_version.ps1 1.1.0
```

### 2. 커밋하고 태그 밀기

```powershell
git add -A
git commit -m "chore: 버전 1.1.0"
git tag v1.1.0
git push && git push --tags
```

태그를 밀면 GitHub Actions가 알아서 진행합니다.

1. 태그와 앱 버전이 같은지 확인 (다르면 여기서 멈춤)
2. Python sidecar를 PyInstaller로 새로 빌드
3. 프론트엔드 타입 검사 후 빌드
4. NSIS 설치본 빌드 및 서명
5. Releases에 설치본, `.sig`, `latest.json` 발행

진행 상황은 저장소의 **Actions** 탭에서 볼 수 있습니다. 10~20분쯤 걸립니다.

### 3. 확인

이미 설치된 앱은 시작 후 약 1.8초 뒤 백그라운드로 `latest.json`을 확인합니다.
새 버전이 있으면 내려받아 설치하고 앱을 다시 시작합니다.
설정 화면의 **앱 자동 업데이트 → 지금 확인**으로 즉시 확인할 수도 있습니다.

---

## 내 PC에서 직접 빌드하기

GitHub Actions를 쓰지 않고 설치본만 만들 때 씁니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

결과는 `src-tauri\target\release\bundle\nsis`에 생깁니다.

---

## 도구만 따로 업데이트하기 (지금은 쓰지 않음)

> **현재 이 기능은 꺼져 있습니다.** `update-config.json`의 `tools.catalog_url`이
> 비어 있어 앱이 카탈로그를 확인하지 않습니다. 의도한 상태입니다.
>
> 도구는 설치본 안에 함께 들어가므로, 도구를 고치거나 새로 추가해도
> 앱 업데이트만으로 전부 따라옵니다. 이 경로는 그 위에 얹는 선택 사항이고,
> 얻는 것은 다운로드 용량 절약뿐인데 서명키와 배포 절차가 하나 더 늘어납니다.
>
> 나중에 "HTML 도구만 자주 고치는데 매번 60MB를 받는 건 아깝다" 싶어지면
> 아래 절차를 마치고 주소를 채우면 그때 켜집니다. Rust 쪽 구현은 이미 되어 있습니다.

앱 본체를 건드리지 않고 도구를 추가하거나 교체하는 경로입니다.

### 1. 도구 패키지 만들기

```powershell
py -3.12 scripts\package_tool.py tools\qr_code_generator --base-url https://github.com/kain9012-bit/automation_suite/releases/download/tools
```

`tool-packages\` 아래에 ZIP과 카탈로그 항목이 만들어집니다.

### 2. 카탈로그 서명하기

여러 도구 항목을 모아 아래 형태의 JSON을 만든 뒤 서명합니다.

```json
{
  "schema_version": 1,
  "tools": [
    {
      "id": "qr_code_generator",
      "name": "QR 코드 생성",
      "version": "1.2.0",
      "url": "https://.../qr_code_generator-1.2.0.zip",
      "sha256": "…",
      "size": 12345
    }
  ]
}
```

```powershell
py -3.12 scripts\sign_tool_catalog.py tool-catalog.json --output tool-catalog.signed.json
```

### 3. 올리고 주소 연결하기

서명된 카탈로그와 ZIP을 릴리스 자산이나 공개 주소에 올린 뒤,
`update-config.json`의 `tools.catalog_url`에 카탈로그 주소를 적습니다.

앱은 시작할 때 카탈로그 서명을 검증하고, 처음 보는 ID는 자동 설치,
이미 있는 ID는 더 높은 버전일 때만 교체합니다. ZIP 내부 경로, 패키지 ID·버전,
SHA-256을 모두 확인하므로 중간에 바뀐 파일은 설치되지 않습니다.

---

## 알아두면 좋은 것

- **코드 서명 인증서가 없습니다.** 설치할 때 Windows SmartScreen 경고가 뜹니다.
  사용자는 `추가 정보 → 실행`을 눌러야 합니다. 상용 인증서를 사거나
  기관 인증서를 받아야 없앨 수 있습니다.
- **버전은 되돌릴 수 없습니다.** 업데이트는 더 높은 버전일 때만 동작하므로,
  1.1.0을 배포한 뒤 1.0.9를 올려도 아무도 받지 않습니다.
- **sidecar는 저장소에 없습니다.** 60MB라 `.gitignore`로 빼 두었고,
  배포할 때마다 GitHub Actions가 새로 만듭니다.
