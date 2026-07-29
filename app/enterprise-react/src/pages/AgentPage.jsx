import { useEffect, useState } from "react";
import {
  Check,
  MessageSquareText,
  Plus,
  Send,
  Sparkles,
  TableProperties,
} from "lucide-react";
import { MetaStrip, SectionTitle } from "../components/common/EnterpriseUi";
import { agentSteps as _fallbackSteps, dataProducts as _fallbackProducts } from "../data/enterpriseDemoData";
import { apiGet } from "../services/apiClient";

const agentSteps = [..._fallbackSteps];
const dataProducts = [..._fallbackProducts];
let _agentLoaded = false;

const RECENT_ANALYSES = [
  "지난달 객실 매출 하락 원인",
  "다음 30일 객실 수요",
  "프로모션 효과 분석",
  "VIP 고객 재방문 요인",
];

export function AgentPage() {
  const [question, setQuestion] = useState("");
  const [sent, setSent] = useState(false);
  const [, setRefresh] = useState(0);

  useEffect(() => {
    if (_agentLoaded) return;
    _agentLoaded = true;
    Promise.all([
      apiGet("/agent/workflow/").catch(() => null),
      apiGet("/data-products/").catch(() => null),
    ]).then(([workflow, products]) => {
      if (workflow?.data?.length) {
        agentSteps.splice(0, agentSteps.length, ...workflow.data);
      }
      if (products?.data?.length) {
        dataProducts.splice(0, dataProducts.length, ...products.data);
      }
      setRefresh((n) => n + 1);
    });
  }, []);

  const submitQuestion = (event) => {
    event.preventDefault();
    if (question.trim()) setSent(true);
  };

  return (
    <div className="chat-layout">
      <aside className="chat-history">
        <button className="new-chat"><Plus size={16} />새 분석</button>
        <p>RECENT</p>
        {RECENT_ANALYSES.map((item, index) => (
          <button className={index === 0 ? "selected" : ""} key={item}>
            <MessageSquareText size={15} />
            <span>{item}<small>{index === 0 ? "방금 전" : `${index + 1}일 전`}</small></span>
          </button>
        ))}
      </aside>

      <main className="chat-main">
        <MetaStrip />
        <div className="conversation">
          <div className="message message--user">
            <div className="avatar small">J</div>
            <div>
              <b>사용자</b>
              <p>지난달 객실 매출이 하락한 원인을 분석하고 다음 달 대응 전략을 제안해줘.</p>
            </div>
          </div>
          <div className="message message--agent">
            <span className="agent-avatar"><Sparkles size={17} /></span>
            <div>
              <b>Analysis Agent <em>분석 완료</em></b>
              <p>지난달 객실 매출은 전월 대비 <strong>6.8% 감소</strong>했습니다. 주된 영향은 주중 OCC 하락과 해외 OTA 채널의 취소율 증가입니다.</p>
              <div className="fact-grid">
                <article><small>확인된 사실</small><strong>-6.8%</strong><span>객실 매출 MoM</span></article>
                <article><small>주요 원인</small><strong>-7.2%p</strong><span>주중 OCC</span></article>
                <article><small>예측</small><strong>+4.3%p</strong><span>전략 적용 OCC</span></article>
              </div>
              <div className="answer-section">
                <h3>전략 제안 <span>관리자 검토 필요</span></h3>
                <ol>
                  <li><b>주중 패키지 재구성</b><p>조식과 late checkout을 결합한 직접 예약 패키지를 우선 노출합니다.</p></li>
                  <li><b>취소 위험 선제 대응</b><p>lead time 21일 이상 OTA 예약에 재확인 메시지를 적용합니다.</p></li>
                </ol>
              </div>
            </div>
          </div>
          {sent && (
            <div className="message message--user">
              <div className="avatar small">J</div>
              <div><b>사용자</b><p>{question}</p></div>
            </div>
          )}
        </div>
        <form className="chat-input" onSubmit={submitQuestion}>
          <input
            value={question}
            onChange={(event) => {
              setQuestion(event.target.value);
              setSent(false);
            }}
            placeholder="기업 데이터에 대해 질문하세요..."
          />
          <button aria-label="질문 전송"><Send size={17} /></button>
          <small>Agent 결과는 의사결정 참고용이며 자동 실행되지 않습니다.</small>
        </form>
      </main>

      <aside className="evidence-panel">
        <SectionTitle eyebrow="TRACEABILITY" title="분석 근거" />
        <div className="execution-list">
          {agentSteps.map(([name, status, text], index) => (
            <article key={name}>
              <span>{index + 1}</span>
              <div><b>{name}<em><Check size={11} />{status}</em></b><small>{text}</small></div>
            </article>
          ))}
        </div>
        <div className="evidence-block">
          <h3>사용 데이터 제품</h3>
          {dataProducts.slice(0, 4).map((item) => (
            <span key={item.product}>
              <TableProperties size={13} />{item.product}<small>{item.freshness} 전</small>
            </span>
          ))}
        </div>
        <div className="evidence-block">
          <h3>실행 정보</h3>
          <dl>
            <div><dt>Query engine</dt><dd>Trino</dd></div>
            <div><dt>Scanned</dt><dd>1.28M rows</dd></div>
            <div><dt>Elapsed</dt><dd>2.4 sec</dd></div>
            <div><dt>ML model</dt><dd>ONNX v2.3.1</dd></div>
          </dl>
        </div>
      </aside>
    </div>
  );
}
