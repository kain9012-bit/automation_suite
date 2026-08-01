import { Download, FolderCog, RefreshCw, ShieldCheck } from "lucide-react";

export function SettingsView({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="settings-view content-column">
      <div className="page-intro">
        <span className="eyebrow">환경 설정</span>
        <h1>앱과 도구를 관리합니다.</h1>
        <p>
          사용자 설정과 추가 도구는 LocalAppData에 보관되어 앱 업데이트 후에도
          유지됩니다.
        </p>
      </div>
      <section className="settings-card">
        <div className="setting-icon">
          <FolderCog size={20} />
        </div>
        <div>
          <strong>도구 레지스트리</strong>
          <p>기본 도구와 자동 설치된 도구 패키지를 다시 검색합니다.</p>
        </div>
        <button className="secondary-button" onClick={onRefresh}>
          <RefreshCw size={15} />
          새로고침
        </button>
      </section>
      <section className="settings-card">
        <div className="setting-icon">
          <Download size={20} />
        </div>
        <div>
          <strong>자동 업데이트</strong>
          <p>서명된 앱 버전과 신규 도구 패키지를 자동으로 확인합니다.</p>
        </div>
        <label className="switch">
          <input type="checkbox" defaultChecked />
          <span />
        </label>
      </section>
      <section className="settings-card">
        <div className="setting-icon">
          <ShieldCheck size={20} />
        </div>
        <div>
          <strong>로컬 처리 우선</strong>
          <p>사용자가 선택한 파일은 외부 서버로 전송하지 않습니다.</p>
        </div>
        <span className="status-chip">사용 중</span>
      </section>
    </div>
  );
}
