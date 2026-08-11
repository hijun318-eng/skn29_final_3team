import { useState } from "react";
import { Database, ShieldCheck } from "lucide-react";
import { MetaStrip, SectionTitle, StatusBadge } from "../components/common/EnterpriseUi";
import {
  catalogSources,
  I3_DATA_CONTRACT_VERSION,
  I3_SCHEMA_VERSION,
  I3_SEED_VERSION,
} from "../data/catalogFixtures";

export function ConnectionsPage() {
  const [sourceId, setSourceId] = useState("all");
  const sources = sourceId === "all"
    ? catalogSources
    : catalogSources.filter((source) => source.sourceId === sourceId);

  return (
    <div className="page-content">
      <MetaStrip meta={{ synthetic: true, seed: I3_SEED_VERSION, schemaVersion: I3_SCHEMA_VERSION }} />
      <SectionTitle
        eyebrow="SOURCE CONFIGURATION"
        title="데이터 소스 연결 구성"
        description="원천별 DataHub·Trino 매핑과 ingestion 설정을 확인합니다. CONFIG_VALIDATED는 실시간 접속 성공이 아니라 연결 구성이 검증됐다는 의미입니다."
      />
      <div className="management-toolbar">
        <label className="scenario-picker">
          <span>source</span>
          <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
            <option value="all">전체 5개</option>
            {catalogSources.map((source) => <option value={source.sourceId} key={source.sourceId}>{source.sourceName}</option>)}
          </select>
        </label>
        <code>{I3_DATA_CONTRACT_VERSION}</code>
      </div>
      <section className="connection-grid">
        {sources.map((source) => (
          <article className="card connection-card" key={source.sourceId}>
            <header>
              <span className="vendor-icon"><Database size={21} /></span>
              <div><h3>{source.sourceName}</h3><p>{source.engine}</p></div>
              <StatusBadge status={source.ingestionStatus} />
            </header>
            <dl>
              <div><dt>source_id</dt><dd>{source.sourceId}</dd></div>
              <div><dt>Trino catalog</dt><dd>{source.catalog}</dd></div>
              <div><dt>DataHub URN</dt><dd>{source.datasetUrn}</dd></div>
              <div><dt>DataHub/Trino FQN</dt><dd>{source.fqn}</dd></div>
              <div><dt>catalog check FQN</dt><dd>{source.catalogCheckFqn}</dd></div>
              <div><dt>ingestion_id</dt><dd>{source.ingestionId}</dd></div>
              <div><dt>watermark UTC</dt><dd>{source.watermark}</dd></div>
              <div><dt>catalog SHA-256</dt><dd><code>{source.sha256}</code></dd></div>
            </dl>
            <footer><span><ShieldCheck size={13} />구성 검증 완료 · synthetic · read only</span></footer>
          </article>
        ))}
      </section>
    </div>
  );
}
