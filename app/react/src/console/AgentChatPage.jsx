import { useEffect, useRef, useState } from "react";
import { ArrowUp, Check, Loader2, Paperclip, ShieldCheck, Sparkles } from "lucide-react";
import { AGENT_ANSWERS, AGENT_FALLBACK, AGENT_SUGGESTIONS, AGENT_THREADS } from "./consoleData";
import { RichText, SyntheticBadge, Tag } from "./ui";

const GREETING = {
  role: "agent",
  answer:
    "안녕하세요. 워커힐 VOC 운영 Agent입니다.\n고객 리뷰·설문·프론트 접수·운영 로그를 함께 조회해 이슈와 원인, 근거를 정리해 드립니다.\n\n무엇을 확인할까요?",
  bullets: [],
  evidence: [],
  steps: [],
  confidence: null,
};

function pickAnswer(q) {
  return AGENT_ANSWERS.find((a) => a.match.some((m) => q.includes(m))) ?? AGENT_FALLBACK;
}

export function AgentChatPage() {
  const [messages, setMessages] = useState([GREETING]);
  const [pending, setPending] = useState(null); // { question, answer, step }
  const [draft, setDraft] = useState("");
  const [thread, setThread] = useState(AGENT_THREADS[0].id);
  const streamRef = useRef(null);

  useEffect(() => {
    if (!pending) return;
    const total = pending.answer.steps.length;
    const t = setTimeout(() => {
      if (pending.step < total) {
        setPending((p) => p && { ...p, step: p.step + 1 });
        return;
      }
      setMessages((m) => [...m, { role: "user", text: pending.question }, { role: "agent", ...pending.answer }]);
      setPending(null);
    }, pending.step < total ? 620 : 380);
    return () => clearTimeout(t);
  }, [pending]);

  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending]);

  function send(text) {
    const q = text.trim();
    if (!q || pending) return;
    setDraft("");
    setPending({ question: q, answer: pickAnswer(q), step: 0 });
  }

  const lastEvidence = [...messages].reverse().find((m) => m.role === "agent" && m.evidence?.length);

  return (
    <div className="wh-chat">
      <aside className="wh-chat-side">
        <button className="wh-btn wh-btn--primary" style={{ width: "100%", justifyContent: "center", marginBottom: 22 }}>
          <Sparkles size={13} /> 새 대화
        </button>
        <h4>최근 대화</h4>
        {AGENT_THREADS.map((t) => (
          <button key={t.id} className={`wh-thread ${thread === t.id ? "is-active" : ""}`} onClick={() => setThread(t.id)}>
            <b>{t.title}</b>
            <small>{t.updated}{t.pinned ? " · 고정" : ""}</small>
          </button>
        ))}
      </aside>

      <div className="wh-chat-main">
        <div className="wh-stream" ref={streamRef}>
          {messages.map((m, i) =>
            m.role === "user" ? (
              <article key={i} className="wh-msg wh-msg--user">
                <div className="wh-msg-avatar">PJ</div>
                <div>
                  <div className="wh-msg-who"><b>박준희</b><span>CX 운영팀</span></div>
                  <div className="wh-bubble">{m.text}</div>
                </div>
              </article>
            ) : (
              <article key={i} className="wh-msg wh-msg--agent">
                <div className="wh-msg-avatar">WH</div>
                <div>
                  <div className="wh-msg-who">
                    <b>VOC AGENT</b>
                    {m.confidence != null && <Tag tone={m.confidence >= 70 ? "ok" : "warn"}>신뢰도 {m.confidence}%</Tag>}
                  </div>
                  <div className="wh-bubble">
                    <RichText text={m.answer} />
                    {m.bullets?.length > 0 && (
                      <ul>
                        {m.bullets.map((b) => <li key={b}>{b}</li>)}
                      </ul>
                    )}
                    {m.evidence?.length > 0 && (
                      <div style={{ marginTop: 12, color: "#999", fontSize: 11 }}>
                        근거
                        {m.evidence.map((e) => <span key={e.id} className="wh-cite">{e.id}</span>)}
                      </div>
                    )}
                  </div>
                  {m.steps?.length > 0 && (
                    <div className="wh-steps">
                      {m.steps.map((s) => (
                        <div key={s}><Check size={12} />{s}</div>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            ),
          )}

          {pending && (
            <>
              <article className="wh-msg wh-msg--user">
                <div className="wh-msg-avatar">PJ</div>
                <div>
                  <div className="wh-msg-who"><b>박준희</b><span>CX 운영팀</span></div>
                  <div className="wh-bubble">{pending.question}</div>
                </div>
              </article>
              <article className="wh-msg wh-msg--agent">
                <div className="wh-msg-avatar">WH</div>
                <div>
                  <div className="wh-msg-who"><b>VOC AGENT</b><span>분석 중</span></div>
                  <div className="wh-steps">
                    {pending.answer.steps.map((s, idx) => (
                      <div key={s} className={idx === pending.step ? "is-run" : ""} style={{ opacity: idx > pending.step ? 0.35 : 1 }}>
                        {idx < pending.step ? <Check size={12} /> : <Loader2 size={12} className={idx === pending.step ? "wh-spin" : ""} />}
                        {s}
                      </div>
                    ))}
                  </div>
                </div>
              </article>
            </>
          )}
        </div>

        <div className="wh-composer">
          <div className="wh-chips">
            {AGENT_SUGGESTIONS.map((s) => (
              <button key={s} className="wh-chip" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
          <div className="wh-composer-box">
            <textarea
              value={draft}
              placeholder="운영 이슈나 고객 VOC에 대해 질문하세요. Shift+Enter로 줄바꿈"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(draft);
                }
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button className="wh-btn wh-btn--ghost" title="첨부"><Paperclip size={14} /></button>
              <button className="wh-btn wh-btn--primary" disabled={!draft.trim() || !!pending} onClick={() => send(draft)}>
                <ArrowUp size={14} /> 전송
              </button>
            </div>
          </div>
          <p className="wh-composer-note">
            응답은 카탈로그에 연결된 소스만 사용하며 근거 ID를 함께 표시합니다. 합성 데이터 기반 데모입니다.
          </p>
        </div>
      </div>

      <aside className="wh-chat-aside">
        <h4>근거 패널</h4>
        {lastEvidence ? (
          lastEvidence.evidence.map((e) => (
            <div key={e.id} className="wh-ev">
              <div className="wh-ev-head"><b>{e.id} · {e.source}</b><small>{e.date}</small></div>
              <p>{e.label}</p>
              <div className="wh-ev-foot"><span>신뢰도</span><span className="wh-num">{e.conf}%</span></div>
              <div className="wh-bar"><i style={{ width: `${e.conf}%` }} /></div>
            </div>
          ))
        ) : (
          <p className="wh-empty">질문을 입력하면 답변에 사용된 원본 근거와 신뢰도가 이곳에 표시됩니다.</p>
        )}

        <h4 style={{ marginTop: 26 }}>사용 소스</h4>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Tag tone="slate">PMS</Tag><Tag tone="slate">POS</Tag><Tag tone="slate">CRM</Tag><Tag tone="slate">OTA 리뷰</Tag>
        </div>
        <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 7, color: "#666", fontSize: 11 }}>
          <ShieldCheck size={13} /> 개인정보 필드는 마스킹 후 조회됩니다.
        </div>
        <div style={{ marginTop: 16 }}><SyntheticBadge compact /></div>
      </aside>
    </div>
  );
}
