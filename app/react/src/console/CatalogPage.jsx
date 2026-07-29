import { useState } from "react";
import { Database, GitBranch, Link2, Lock, Plug, RefreshCw } from "lucide-react";
import { CATALOG, CATALOG_HEALTH, MCP_TOOLS } from "./consoleData";
import { Card, SyntheticBadge, Tag } from "./ui";

const SRC_STATUS = {
  connected: { tone: "ok", label: "연결됨" },
  degraded: { tone: "warn", label: "지연" },
  pending: { tone: "slate", label: "연동 대기" },
};
const TOOL_STATUS = {
  ready: { tone: "ok", label: "ready" },
  review: { tone: "warn", label: "승인 대기" },
  blocked: { tone: "critical", label: "차단" },
};
const PII = { "높음": "critical", "중간": "warn", "없음": "slate" };

export function CatalogPage() {
  const [filter, setFilter] = useState("all");
  const sources = filter === "all" ? CATALOG : CATALOG.filter((s) => s.status === filter);

  return (
    <div className="wh-page" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="wh-meta-strip">
        {CATALOG_HEALTH.map((h) => (
          <div key={h.label}><span>{h.label}</span><b className="wh-num">{h.value}</b></div>
        ))}
        <div style={{ marginLeft: "auto" }}><SyntheticBadge /></div>
      </div>

      <Card
        title="사일로 데이터 소스"
        note="Agent가 조회할 수 있는 원천 시스템과 연결 상태"
        action={
          <div className="wh-tabs" style={{ border: 0, gap: 16 }}>
            {[["all", "전체"], ["connected", "연결됨"], ["degraded", "지연"], ["pending", "대기"]].map(([k, label]) => (
              <button key={k} className={filter === k ? "is-active" : ""} style={{ paddingBottom: 4, fontSize: 12 }} onClick={() => setFilter(k)}>
                {label}
              </button>
            ))}
          </div>
        }
        bodyClass="wh-card-body"
      >
        <div className="wh-grid wh-grid--3">
          {sources.map((s) => (
            <div key={s.id} className="wh-src">
              <div className="wh-src-head">
                <div>
                  <b><Database size={12} style={{ marginRight: 7, color: "#996b56" }} />{s.name}</b>
                  <small>{s.domain} · {s.kind}</small>
                </div>
                <Tag tone={SRC_STATUS[s.status].tone}><i className="wh-dot" />{SRC_STATUS[s.status].label}</Tag>
              </div>
              <div className="wh-src-rows">
                <div className="wh-src-row"><span>연결</span><code>{s.host}</code></div>
                <div className="wh-src-row"><span>동기화</span><div>{s.sync} · 최신 {s.freshness}</div></div>
                <div className="wh-src-row"><span>규모</span><div className="wh-num">{s.rows} rows</div></div>
                <div className="wh-src-row"><span>소유</span><div>{s.owner}</div></div>
                <div className="wh-src-row"><span>PII</span><div><Tag tone={PII[s.pii]}><Lock size={10} />{s.pii}</Tag></div></div>
                <div className="wh-src-row"><span>테이블</span><div className="wh-src-tables">{s.tables.map((t) => <i key={t}>{t}</i>)}</div></div>
                <div className="wh-src-row"><span>조인 키</span><div><code>{s.joins.join(" · ")}</code></div></div>
              </div>
            </div>
          ))}
        </div>
        {sources.length === 0 && <p className="wh-empty">해당 상태의 소스가 없습니다.</p>}
      </Card>

      <Card
        title="MCP Tool 레지스트리"
        note="Agent에 노출된 tool과 호출 권한 · 성능"
        action={<button className="wh-btn"><RefreshCw size={13} /> 상태 재조회</button>}
        bodyClass="wh-scroll"
      >
        <table className="wh-table">
          <thead>
            <tr>
              <th>Tool</th><th>서버</th><th>설명</th><th>인자</th><th>권한</th>
              <th className="wh-right">p95</th><th className="wh-right">24h 호출</th><th>상태</th>
            </tr>
          </thead>
          <tbody>
            {MCP_TOOLS.map((t) => (
              <tr key={t.name}>
                <td><span className="wh-mcp-name">{t.name}</span></td>
                <td>{t.server}</td>
                <td style={{ minWidth: 210 }}>{t.desc}</td>
                <td><code style={{ color: "#474e61", fontSize: 11 }}>{t.args}</code></td>
                <td>{t.scope.includes("write") ? <Tag tone="warn">{t.scope}</Tag> : <Tag>{t.scope}</Tag>}</td>
                <td className="wh-right wh-num">{t.p95}</td>
                <td className="wh-right wh-num">{t.calls24h.toLocaleString()}</td>
                <td><Tag tone={TOOL_STATUS[t.status].tone}>{TOOL_STATUS[t.status].label}</Tag></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="wh-grid wh-grid--2">
        <Card title="조인 경로" note="고객 단위 360 뷰를 만드는 키 연결">
          {[
            ["PMS guest_profile.guest_id", "CRM member.member_id", "고객 식별 통합"],
            ["PMS stay_folio.folio_no", "POS order_header.folio_no", "숙박-식음 결제 결합"],
            ["PMS stay_folio.folio_no", "CSD ticket.folio_no", "응대 이력 결합"],
            ["OTA review_normalized.property_code", "PMS property.code", "리뷰-시설 매핑"],
          ].map(([a, b, why]) => (
            <div key={a + b} className="wh-nba">
              <b style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "Consolas, monospace", fontSize: 11.5 }}>
                {a} <Link2 size={12} color="#996b56" /> {b}
              </b>
              <p>{why}</p>
            </div>
          ))}
        </Card>

        <Card title="연동 위험 · 다음 조치" note="카탈로그 품질 점검 결과">
          <div className="wh-nba">
            <b>CSD 티켓 배치 6시간 지연</b>
            <p>야간 배치가 실패해 응대 이력이 최신 상태가 아닙니다. 조치 완료율 지표가 실제보다 낮게 계산될 수 있습니다.</p>
            <small>담당 · 고객지원팀 / 데이터플랫폼</small>
          </div>
          <div className="wh-nba">
            <b>시설 IoT 스트림 연동 대기</b>
            <p>온도·엘리베이터 VOC의 물리적 원인 검증이 불가한 상태입니다. facility.sensor_read tool도 함께 차단되어 있습니다.</p>
            <small>담당 · 시설부</small>
          </div>
          <div className="wh-nba">
            <b>ticket.create 쓰기 권한 승인 필요</b>
            <p>Agent가 티켓을 생성하려면 쓰기 권한 승인이 필요합니다. 승인 전까지 사람이 확인 후 수동 생성합니다.</p>
            <small>담당 · 운영본부</small>
          </div>
          <p style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 7, color: "#999", fontSize: 11 }}>
            <Plug size={12} /> 연결 정보는 합성 값입니다. 실제 endpoint·credential은 저장하지 않습니다.
          </p>
        </Card>
      </div>

      <p style={{ display: "flex", alignItems: "center", gap: 7, color: "#999", fontSize: 11 }}>
        <GitBranch size={12} /> 카탈로그 변경은 데이터플랫폼 승인 후 반영됩니다.
      </p>
    </div>
  );
}
