import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const data = [
  { date: "6/30", total: 332, negative: 104, wait: 31 },
  { date: "7/2", total: 358, negative: 112, wait: 30 },
  { date: "7/4", total: 401, negative: 130, wait: 34 },
  { date: "7/6", total: 376, negative: 118, wait: 28 },
  { date: "7/8", total: 429, negative: 147, wait: 32 },
  { date: "7/10", total: 388, negative: 121, wait: 24 },
  { date: "7/13", total: 361, negative: 109, wait: 26 },
];

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return <div className="chart-tooltip"><b>2026년 {label}</b><span>전체 VOC <strong>{payload[0]?.value}건</strong></span><span>부정 VOC <strong>{payload[1]?.value}건</strong></span><span>대기시간 <strong>{payload[2]?.value}분</strong></span></div>;
}

export function VocTrendChart() {
  return (
    <article className="card chart-card">
      <div className="section-heading">
        <div><p>2026년 6월 30일 ~ 7월 13일 · 일별 추이</p><h2>VOC 및 운영 지표 변화</h2></div>
      </div>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 8, bottom: 4, left: -18 }}>
            <CartesianGrid stroke="#eee9e2" strokeDasharray="4 4" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "#7b7e85", fontSize: 12 }} axisLine={false} tickLine={false} dy={10} />
            <YAxis yAxisId="left" tick={{ fill: "#7b7e85", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis yAxisId="right" orientation="right" tick={{ fill: "#7b7e85", fontSize: 12 }} axisLine={false} tickLine={false} unit="분" />
            <Tooltip content={<ChartTooltip />} />
            <Legend verticalAlign="top" align="right" height={42} iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 12, color: "#5f626a" }} />
            <Line yAxisId="left" name="전체 VOC" type="monotone" dataKey="total" stroke="#1e2b45" strokeWidth={3} dot={{ r: 3, fill: "#fff", strokeWidth: 2 }} />
            <Line yAxisId="left" name="부정 VOC" type="monotone" dataKey="negative" stroke="#8c6a43" strokeWidth={3} dot={{ r: 3, fill: "#fff", strokeWidth: 2 }} />
            <Line yAxisId="right" name="대기시간(분)" type="monotone" dataKey="wait" stroke="#bfa27a" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3, fill: "#fff", strokeWidth: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-insight"><span>AI INSIGHT</span>체크인 대기시간과 부정 VOC가 같은 방향으로 움직였습니다. 인력 배치와 시스템 처리시간을 우선 점검하세요.</div>
    </article>
  );
}
