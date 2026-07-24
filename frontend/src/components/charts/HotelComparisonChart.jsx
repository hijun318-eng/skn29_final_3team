import { Building2, CircleAlert, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HOTEL_COMPARISON_DATA, HOTEL_COMPARISON_INSIGHTS, HOTEL_COMPARISON_META } from "./hotelComparisonData";

function ComparisonTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = HOTEL_COMPARISON_DATA.find((item) => item.shortName === label);
  if (!row) return null;
  return <div className="hotel-comparison-tooltip"><b>{row.hotel}</b><span>부정 VOC <strong>{row.negativeRate}%</strong></span><span>평균 대기 <strong>{row.waitMinutes}분</strong></span><span>만족도 <strong>{row.satisfaction} / 5</strong></span><span>조치 완료율 <strong>{row.resolutionRate}%</strong></span><small>{row.issue}</small></div>;
}

export function HotelComparisonChart() {
  return <section className="hotel-comparison card" aria-labelledby="hotel-comparison-title">
    <header className="hotel-comparison__header">
      <div><p>HOTEL BENCHMARK</p><h2 id="hotel-comparison-title">호텔별 VOC·운영 성과 비교</h2><span>같은 기간과 기준으로 호텔별 부정 VOC, 대기시간과 만족도를 비교합니다.</span></div>
      <div className="hotel-comparison__meta"><b>{HOTEL_COMPARISON_META.label}</b><span>{HOTEL_COMPARISON_META.schemaVersion} · seed {HOTEL_COMPARISON_META.seed}</span><small>{HOTEL_COMPARISON_META.period}</small></div>
    </header>
    <div className="hotel-comparison__body">
      <div className="hotel-comparison__chart" role="img" aria-label="호텔별 부정 VOC 비율, 평균 대기시간, 고객 만족도 비교 차트">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={HOTEL_COMPARISON_DATA} margin={{ top: 16, right: 12, bottom: 4, left: -18 }}>
            <CartesianGrid stroke="#eee9e2" strokeDasharray="4 4" vertical={false} />
            <XAxis dataKey="shortName" tick={{ fill: "#686d76", fontSize: 11 }} axisLine={false} tickLine={false} dy={9} />
            <YAxis yAxisId="metric" domain={[0, 35]} tick={{ fill: "#84878d", fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis yAxisId="score" orientation="right" domain={[0, 5]} tickCount={6} tick={{ fill: "#84878d", fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip content={<ComparisonTooltip />} />
            <Legend verticalAlign="top" align="right" height={35} iconSize={8} wrapperStyle={{ fontSize: 10, color: "#626771" }} />
            <Bar yAxisId="metric" name="부정 VOC 비율(%)" dataKey="negativeRate" fill="#b65b54" radius={[5, 5, 0, 0]} maxBarSize={34} />
            <Bar yAxisId="metric" name="평균 대기(분)" dataKey="waitMinutes" fill="#c7a36b" radius={[5, 5, 0, 0]} maxBarSize={34} />
            <Line yAxisId="score" name="만족도(5점)" dataKey="satisfaction" type="monotone" stroke="#243754" strokeWidth={2.5} dot={{ r: 4, fill: "#fff", strokeWidth: 2 }} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="hotel-comparison__insights">
        {HOTEL_COMPARISON_INSIGHTS.slice(0, 2).map((insight) => <article className={`comparison-insight comparison-insight--${insight.tone}`} key={insight.title}>
          <span>{insight.tone === "positive" ? <TrendingUp size={16} /> : <CircleAlert size={16} />}</span>
          <div><small>{insight.title}</small><b>{insight.hotel}</b><p>{insight.summary}</p></div>
        </article>)}
        <a href="/reports"><Building2 size={15} />호텔별 비교 인사이트 보고서 보기</a>
      </div>
    </div>
  </section>;
}
