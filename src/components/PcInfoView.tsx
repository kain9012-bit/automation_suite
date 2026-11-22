import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AppWindow,
  Check,
  Copy,
  Cpu,
  HardDrive,
  Laptop,
  LoaderCircle,
  MemoryStick,
  Monitor,
  Network,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import {
  UNKNOWN,
  displayNote,
  driveLabel,
  driveLow,
  formatMemory,
  formatReadAt,
  formatSize,
  formatUptime,
  memoryPercent,
  pcInfo,
  pcInfoText,
  type PcInfo,
} from "../lib/pcinfo";
import "./pc-info.css";

/**
 * PC 정보(1.5.2): 사이드바 'PC 정보' 화면. 이 컴퓨터의 사양을 보여 준다.
 * 화면을 열 때와 [다시 읽기]를 누를 때만 읽는다(감시·자동 새로고침 없음).
 */

type Row = { label: string; value: ReactNode; mono?: boolean };

function Card({ icon: Icon, title, wide, children }: { icon: LucideIcon; title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section className={`pcinfo-card${wide ? " wide" : ""}`}>
      <h2>
        <span className="setting-icon">
          <Icon size={15} />
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Rows({ rows }: { rows: Row[] }) {
  return (
    <dl className="pcinfo-kv">
      {rows.map((row, i) => (
        <div key={i} className="pcinfo-row">
          <dt>{row.label}</dt>
          <dd className={row.mono ? "mono" : undefined}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Bar({ percent, warn }: { percent: number; warn?: boolean }) {
  return (
    <div className="pcinfo-bar">
      <i className={warn ? "is-warn" : undefined} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}

export function PcInfoView() {
  const [info, setInfo] = useState<PcInfo | null>(null);
  const [readAt, setReadAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<number | undefined>(undefined);

  const read = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setInfo(await pcInfo.read());
      setReadAt(new Date());
    } catch (e) {
      setError(`PC 정보를 읽지 못했습니다: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void read();
    return () => window.clearTimeout(copiedTimer.current);
  }, [read]);

  const copy = async () => {
    if (!info || !readAt) return;
    try {
      await pcInfo.copy(pcInfoText(info, readAt));
      setError("");
      setCopied(true);
      window.clearTimeout(copiedTimer.current);
      copiedTimer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch (e) {
      setError(String(e));
    }
  };

  const v = (s: string | null | undefined) => s || UNKNOWN;
  const pct = info ? memoryPercent(info) : null;

  return (
    <div className="pcinfo-view content-column">
      <div className="page-intro pcinfo-intro">
        <div>
          <span className="eyebrow">PC 정보</span>
          <h1>이 컴퓨터의 사양을 확인합니다.</h1>
          <p>이 화면을 열 때 한 번만 읽습니다. 읽은 내용은 PC 밖으로 보내지 않습니다.</p>
        </div>
        <div className="pcinfo-actions">
          <button className="secondary-button" onClick={() => void read()} disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}
            다시 읽기
          </button>
          <button className="primary-button" onClick={() => void copy()} disabled={!info || loading}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? "복사했습니다" : "전체 복사"}
          </button>
        </div>
      </div>

      {error && <p className="pcinfo-error">{error}</p>}

      {!info ? (
        loading && (
          <div className="pcinfo-loading">
            <LoaderCircle className="spin" size={18} />
            읽는 중…
          </div>
        )
      ) : (
        <>
          <div className="pcinfo-grid">
            <Card icon={Laptop} title="컴퓨터">
              <Rows
                rows={[
                  { label: "제조사", value: v(info.manufacturer) },
                  { label: "모델명", value: v(info.model) },
                  { label: "컴퓨터 이름", value: v(info.computerName), mono: !!info.computerName },
                ]}
              />
            </Card>
            <Card icon={AppWindow} title="Windows">
              <Rows
                rows={[
                  { label: "판", value: v(info.windows.name) },
                  {
                    label: "버전",
                    value: (
                      <>
                        {v(info.windows.version)}
                        {info.windows.build && <small>빌드 {info.windows.build}</small>}
                      </>
                    ),
                  },
                  { label: "켜진 지", value: formatUptime(info.uptimeSecs) },
                ]}
              />
            </Card>
            <Card icon={Cpu} title="CPU">
              <Rows
                rows={[
                  { label: "이름", value: v(info.cpu.name) },
                  {
                    label: "코어",
                    value: info.cpu.cores ? (
                      <>
                        {info.cpu.cores}코어<small>{info.cpu.threads ?? info.cpu.cores}스레드</small>
                      </>
                    ) : (
                      UNKNOWN
                    ),
                  },
                ]}
              />
            </Card>
            <Card icon={MemoryStick} title="메모리">
              <Rows
                rows={[
                  { label: "전체", value: info.memory.installed ? formatMemory(info.memory.installed) : UNKNOWN },
                  {
                    label: "사용 중",
                    value:
                      info.memory.used != null ? (
                        <>
                          {formatMemory(info.memory.used)}
                          {pct != null && <small>{pct}%</small>}
                          {pct != null && <Bar percent={pct} />}
                        </>
                      ) : (
                        UNKNOWN
                      ),
                  },
                ]}
              />
            </Card>
            <Card icon={HardDrive} title="디스크" wide>
              {info.drives.length === 0 ? (
                <p className="pcinfo-empty">읽은 디스크가 없습니다.</p>
              ) : (
                <div className="pcinfo-drives">
                  {info.drives.map((d) => {
                    const measured = d.kind !== "network" && d.total != null && d.free != null;
                    return (
                      <div className="pcinfo-drive" key={d.letter}>
                        <b>{d.letter}</b>
                        <div>
                          <div className="line">
                            <b>{driveLabel(d)}</b>
                            {measured ? (
                              <span>
                                {formatSize(d.total!)} 중 <em>{formatSize(d.free!)}</em> 남음
                              </span>
                            ) : (
                              <span>네트워크 드라이브 · 용량은 읽지 않음</span>
                            )}
                          </div>
                          {measured && <Bar percent={((d.total! - d.free!) / d.total!) * 100} warn={driveLow(d)} />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
            <Card icon={Monitor} title="그래픽·화면">
              <Rows
                rows={[
                  ...(info.gpus.length
                    ? info.gpus.map((g, i) => ({ label: info.gpus.length > 1 ? `그래픽 ${i + 1}` : "그래픽", value: g }))
                    : [{ label: "그래픽", value: UNKNOWN }]),
                  ...info.displays.map((d, i) => {
                    const note = displayNote(d);
                    return {
                      label: `화면 ${i + 1}`,
                      value: (
                        <>
                          {d.width} × {d.height}
                          {note && <small>{note}</small>}
                        </>
                      ),
                    };
                  }),
                ]}
              />
            </Card>
            <Card icon={Network} title="네트워크">
              {info.adapters.length === 0 ? (
                <p className="pcinfo-empty">연결된 네트워크가 없습니다.</p>
              ) : (
                <Rows
                  rows={info.adapters.flatMap((a) => [
                    { label: `${a.name} IP`, value: a.ipv4.join(", "), mono: true },
                    { label: `${a.name} MAC`, value: a.mac ?? UNKNOWN, mono: !!a.mac },
                  ])}
                />
              )}
            </Card>
          </div>
          {readAt && (
            <p className="pcinfo-foot">
              읽은 시각 {formatReadAt(readAt)} · 읽는 데 {(info.elapsedMs / 1000).toFixed(2)}초
            </p>
          )}
        </>
      )}
    </div>
  );
}
