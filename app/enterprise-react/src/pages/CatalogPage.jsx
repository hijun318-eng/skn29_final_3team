import { useMemo, useState } from "react";
import { Database, Network, Search, TableProperties } from "lucide-react";
import { MetaStrip, SectionTitle, StatusBadge } from "../components/common/EnterpriseUi";
import {
  catalogSources,
  I3_DATA_CONTRACT_VERSION,
  I3_SCHEMA_VERSION,
  I3_SEED_VERSION,
} from "../data/catalogFixtures";

export function CatalogPage({ onManageConnections }) {
  const [search, setSearch] = useState("");
  const sources = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return catalogSources;
    return catalogSources.filter((source) => [
      source.sourceId, source.sourceName, source.domain, source.engine, source.fqn,
    ].some((value) => value.toLowerCase().includes(query)));
  }, [search]);

  return (
    <div className="page-content catalog-overview">
      <MetaStrip meta={{ synthetic: true, seed: I3_SEED_VERSION, schemaVersion: I3_SCHEMA_VERSION }} />
      <section className="card federation-card">
        <SectionTitle
          eyebrow={I3_DATA_CONTRACT_VERSION}
          title="5개 합성 데이터 원천 Catalog"
          description="R2 I3 fixture의 source·engine·DataHub URN·Trino FQN·watermark를 그대로 표시합니다."
          action={<button className="secondary" onClick={onManageConnections}>연결 상세</button>}
        />
        <div className="catalog-metrics" aria-label="R2 I3 카탈로그 요약">
          <span><small>logical source</small><b>{catalogSources.length}</b><em>fixture 제공값</em></span>
          <span><small>engine</small><b>{new Set(catalogSources.map((source) => source.engine)).size}</b><em>PostgreSQL 포함 4종</em></span>
          <span><small>schema</small><b>{I3_SCHEMA_VERSION}</b><em>synthetic</em></span>
          <span><small>seed</small><b>{I3_SEED_VERSION}</b><em>deterministic</em></span>
        </div>
        <div className="source-stack">
          {catalogSources.map((source) => (
            <article key={source.sourceId}>
              <span><Database size={15} /></span>
              <div><b>{source.sourceName}</b><small>{source.domain} · {source.engine}</small></div>
              <em>{source.catalog}</em>
            </article>
          ))}
        </div>
      </section>

      <section className="card source-status-card">
        <SectionTitle
          eyebrow="DATAHUB → TRINO TRACE"
          title="원천 자산과 ingestion 상태"
          description="검색은 현재 I3 fixture 안에서만 수행하며 상태를 연결 성공으로 재판정하지 않습니다."
        />
        <label className="search-box">
          <Search size={14} />
          <input aria-label="카탈로그 검색" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="source, engine, FQN 검색" />
        </label>
        <div className="data-table source-status-table">
          <div className="table-row table-head">
            <span>source</span><span>engine</span><span>ingestion</span><span>status</span>
            <span>rows</span><span>watermark UTC</span><span>asset</span>
          </div>
          {sources.map((source) => (
            <div className="table-row" key={source.sourceId}>
              <span><b>{source.sourceName}</b><small>{source.sourceId}</small></span>
              <span>{source.engine}</span>
              <span><code>{source.ingestionId}</code></span>
              <span><StatusBadge status={source.ingestionStatus} /></span>
              <span>{source.rowCount}</span>
              <span>{source.watermark}</span>
              <span><TableProperties size={13} /> <code>{source.fqn}</code><small>check {source.catalogCheckFqn} · {source.datasetUrn}</small></span>
            </div>
          ))}
        </div>
        {!sources.length && <p className="evidence-empty">일치하는 I3 source가 없습니다.</p>}
        <p className="catalog-contract-note"><Network size={13} />{I3_DATA_CONTRACT_VERSION} · schema {I3_SCHEMA_VERSION} · seed {I3_SEED_VERSION}</p>
      </section>
    </div>
  );
}
