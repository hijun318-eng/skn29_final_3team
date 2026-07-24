/**
 * SP-04 대화형 조회 화면
 * @see SensePlace_목업_v1.2.html — #sp04
 */

import { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout.tsx';
import { SyntheticTag } from '../components/Badge.tsx';
import { QA } from '../data/mockData.ts';
import type { QAPair } from '../data/mockData.ts';

/* ------------------------------------------------------------------ */
/*  차트 SVG                                                           */
/* ------------------------------------------------------------------ */

function ChartSvg({ bars, labels, unit }: { bars: number[]; labels?: string[]; unit?: string }) {
  const max = Math.max(...bars, 1);
  const w = 44;
  const gap = 14;
  const H = 120;
  const svgWidth = bars.length * (w + gap);

  return (
    <svg viewBox={`0 0 ${svgWidth} 150`} style={{ width: '100%', maxWidth: 360 }}>
      {bars.map((b, i) => {
        const h = (b / max) * H;
        const x = i * (w + gap);
        const y = H - h + 10;
        return (
          <g key={i}>
            <rect x={x} y={y} width={w} height={h} rx={4} fill="var(--brand)" />
            <text x={x + w / 2} y={y - 5} textAnchor="middle" fontSize={10} fill="#475569" fontWeight={600}>
              {b}{unit === '분' ? '분' : ''}
            </text>
            <text x={x + w / 2} y={145} textAnchor="middle" fontSize={9.5} fill="#94a3b8">
              {labels ? labels[i] : i + 1}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  채팅 메시지 타입                                                    */
/* ------------------------------------------------------------------ */

interface ChatBubble {
  id: string;
  role: 'user' | 'assistant' | 'typing' | 'error';
  text?: string;
  qa?: QAPair;
}

/* ------------------------------------------------------------------ */
/*  메인 화면                                                           */
/* ------------------------------------------------------------------ */

export default function ChatQueryPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatBubble[]>([]);
  const [input, setInput] = useState('');
  const [trayCount, setTrayCount] = useState(0);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const findAnswer = (q: string): QAPair | null => {
    for (const qa of QA) {
      if (qa.question === q) return qa;
    }
    return null;
  };

  const handleSubmit = useCallback((text: string) => {
    const q = text.trim();
    if (!q) return;

    const userBubble: ChatBubble = { id: `u-${Date.now()}`, role: 'user', text: q };
    const typingBubble: ChatBubble = { id: `t-${Date.now()}`, role: 'typing' };

    setMessages((prev) => {
      const cleared = prev.length === 0 ? [] : prev;
      return [...cleared, userBubble, typingBubble];
    });
    setInput('');
    setTimeout(scrollToBottom, 50);

    setTimeout(() => {
      setMessages((prev) => prev.filter((b) => b.role !== 'typing'));

      const answer = findAnswer(q);
      if (answer) {
        const bid = `b${Date.now()}`;
        const assistantBubble: ChatBubble = {
          id: bid,
          role: 'assistant',
          qa: answer,
        };
        setMessages((prev) => [...prev, assistantBubble]);
      } else {
        const errorBubble: ChatBubble = {
          id: `e-${Date.now()}`,
          role: 'error',
          text: q,
        };
        setMessages((prev) => [...prev, errorBubble]);
      }
      setTimeout(scrollToBottom, 50);
    }, 700);
  }, []);

  const handleTrayToggle = (add: boolean) => {
    setTrayCount((prev) => (add ? prev + 1 : Math.max(0, prev - 1)));
  };

  return (
    <Layout>
      <div className="frame-narrow" style={{ padding: '0 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '14px 4px' }}>
          <h3 style={{ fontSize: 15 }}>대화형 조회</h3>
          <SyntheticTag />
        </div>

        {/* 채팅 영역 */}
        <div style={{ minHeight: 360, display: 'flex', flexDirection: 'column', gap: 14, paddingBottom: 14 }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', padding: '34px 0', color: 'var(--muted)' }}>
              <div style={{ fontSize: 14, marginBottom: 16 }}>무엇이 궁금하신가요? 자연어로 물어보세요.</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, maxWidth: 560, margin: '0 auto' }}>
                {QA.map((qa) => (
                  <button key={qa.question} className="rec-card" onClick={() => handleSubmit(qa.question)}>
                    💬 {qa.question}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((bubble) => {
            if (bubble.role === 'user') {
              return (
                <div key={bubble.id} className="chat-user">
                  {bubble.text}
                </div>
              );
            }

            if (bubble.role === 'typing') {
              return (
                <div key={bubble.id} className="typing-indicator">
                  ● ● ●  분석 중…
                </div>
              );
            }

            if (bubble.role === 'error') {
              return (
                <div key={bubble.id} className="card chat-assistant">
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>이 질문은 아직 지원하지 않습니다.</div>
                  <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>아래 질문을 참고해 주세요:</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {QA.map((qa) => (
                      <button key={qa.question} className="btn sm" onClick={() => handleSubmit(qa.question)}>
                        {qa.question}
                      </button>
                    ))}
                  </div>
                </div>
              );
            }

            if (bubble.role === 'assistant' && bubble.qa) {
              return (
                <div key={bubble.id} className="card chat-assistant">
                  <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid var(--line)' }}>
                    <b style={{ color: 'var(--brand-2)' }}>{bubble.qa.intent}</b> · {bubble.qa.period} · {bubble.qa.place} · {bubble.qa.n}
                    <span style={{ float: 'right' }}><SyntheticTag /></span>
                  </div>
                  <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <ChartSvg bars={bubble.qa.bars} labels={bubble.qa.labels} unit={bubble.qa.unit} />
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
                    <span style={{ fontSize: 13.5, fontWeight: 600, flex: 1 }}>{bubble.qa.summary}</span>
                    <button className="btn sm" onClick={() => handleTrayToggle(true)}>＋ 담기</button>
                  </div>
                </div>
              );
            }

            return null;
          })}

          <div ref={chatEndRef} />
        </div>

        {/* 트레이 */}
        {trayCount > 0 && (
          <div
            style={{
              position: 'sticky',
              bottom: 64,
              display: 'flex',
              background: '#0f172a',
              color: '#fff',
              borderRadius: 10,
              padding: '10px 14px',
              fontSize: 13,
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 8,
            }}
          >
            <span>▣ 담긴 블록 <b>{trayCount}</b></span>
            <button
              className="btn sm"
              style={{ background: '#fff' }}
              onClick={() => navigate('/reports/editor')}
            >
              보고서에서 열기 →
            </button>
          </div>
        )}

        {/* 입력 바 */}
        <div style={{ position: 'sticky', bottom: 16, display: 'flex', gap: 8, background: 'var(--bg)', padding: '10px 0' }}>
          <input
            className="form-input"
            placeholder="질문 입력 (/ 로 포커스)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(input); }}
            style={{ flex: 1, padding: '12px 14px', borderRadius: 10, fontSize: 14 }}
          />
          <button className="btn primary" style={{ padding: '12px 22px' }} onClick={() => handleSubmit(input)}>
            전송
          </button>
        </div>
      </div>
    </Layout>
  );
}
