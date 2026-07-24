import { Activity, AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { FacilityMarker } from "./FacilityMarker";

export function HotelOperationMap({ facilities, selectedId, onSelect, simulated, timelineState }) {
  return (
    <div className={`operation-map ${simulated ? "is-simulating" : ""}`}>
      <div className="map-notice"><Info size={14} /><span><b>합성 데이터 기반 예상 시나리오</b> · 실제 호텔 운영 현황이나 정밀 예측 결과를 의미하지 않습니다.</span></div>
      {simulated && <div className="simulation-flag"><Activity size={14} /> SIMULATION · 합성 데이터 기반 예상 상태</div>}
      <div className="map-canvas" role="group" aria-label="호텔 시설 운영 상태 지도">
        <svg className="map-base" viewBox="0 0 900 560" aria-hidden="true">
          <defs>
            <pattern id="map-grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#ded8cf" strokeWidth=".6" opacity=".42" /></pattern>
            <filter id="soft-blur"><feGaussianBlur stdDeviation="13" /></filter>
            <filter id="building-shadow" x="-25%" y="-25%" width="150%" height="170%"><feDropShadow dx="0" dy="5" stdDeviation="5" floodColor="#46503d" floodOpacity=".16" /></filter>
            <linearGradient id="hotel-front" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#eee9df" /><stop offset="1" stopColor="#d8d0c3" /></linearGradient>
            <linearGradient id="hotel-side" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#c7b8a4" /><stop offset="1" stopColor="#a99a87" /></linearGradient>
            <linearGradient id="glass-front" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#c5d7d4" /><stop offset="1" stopColor="#8ba9a7" /></linearGradient>
          </defs>
          <rect width="900" height="560" rx="24" fill="#d8dfb0" />
          <path className="terrain terrain--hill" d="M0 0H900v145c-95-22-151-101-257-89C543 67 507 144 395 107 270 65 223 163 90 108 49 91 22 89 0 95Z" />
          <path className="terrain terrain--forest" d="M0 65c97-36 150 46 240 18 112-35 112 80 225 52 101-25 133 50 245 28 87-17 126 27 190-4V0H0Z" />
          <path className="terrain terrain--meadow" d="M0 128c92-31 161 37 259 23 86-13 157 10 246 48 122 53 221-6 395 47v196c-107 24-214-17-301 24-79 37-131 17-218-12-119-39-175 33-381-4Z" />
          <path className="river" d="M0 485c129-39 183 5 289 22 161 26 251-20 390-5 91 10 146 39 221 18v40H0Z" />
          <path className="riverside-road" d="M-25 467C95 434 177 454 259 478c88 26 155 28 221 2 82-33 154-28 229-5 78 24 137 15 216-20" />
          <path className="campus-road" d="M-15 276C47 260 78 215 126 190c58-30 111-18 160-5 50 13 88 0 129-25 54-32 99-38 151-15 54 23 78 62 133 61 60-1 85-47 142-57 58-10 100 26 154 53" />
          <path className="campus-road campus-road--lower" d="M-20 405C72 384 142 403 214 420c65 16 111 9 154-16 51-30 88-40 137-23 52 18 76 53 129 50 51-3 73-37 123-34 61 3 89 47 168 28" />
          <path className="campus-road campus-road--branch" d="M244 181c22 27 31 61 29 98-2 43 13 78 49 105" />
          <path className="campus-road campus-road--branch" d="M595 199c-17 34-20 65-6 93 12 25 39 40 70 48" />
          <ellipse cx="530" cy="323" rx={112 * timelineState.heat} ry={71 * timelineState.heat} className={`heat-zone heat-zone--${simulated && timelineState.status === "주의" ? "warning" : "danger"}`} filter="url(#soft-blur)" />
          <ellipse cx="225" cy="210" rx="55" ry="36" className="heat-zone heat-zone--warning" filter="url(#soft-blur)" />
          <ellipse cx="355" cy="385" rx="48" ry="31" className="heat-zone heat-zone--warning" filter="url(#soft-blur)" />
          <g className="map-trees">{Array.from({ length: 34 }, (_, index) => <circle key={index} cx={35 + ((index * 79) % 840)} cy={35 + ((index * 43) % 145)} r={8 + (index % 4) * 3} />)}</g>
          <g className="map-trees map-trees--lower">{Array.from({ length: 16 }, (_, index) => <circle key={index} cx={42 + ((index * 101) % 800)} cy={400 + ((index * 31) % 56)} r={7 + (index % 3) * 3} />)}</g>
          <g className="parking-deck" filter="url(#building-shadow)">
            <path className="parking-ground" d="M143 150l117-12 44 27-22 73-130 2-28-31Z" />
            {[0,1,2,3].map((n) => <path className="parking-bay" key={n} d={`M${157 + n * 29} 157l19-2 15 12-5 24-22 1-13-11Z`} />)}
            <g className="map-car map-car--orange"><rect x="169" y="165" width="25" height="11" rx="4" /><rect x="176" y="162" width="12" height="6" rx="2" /></g>
            <g className="map-car map-car--blue"><rect x="230" y="174" width="25" height="11" rx="4" /><rect x="237" y="171" width="12" height="6" rx="2" /></g>
          </g>
          <g className="resort-building resort-building--annex" filter="url(#building-shadow)">
            <path className="building-side" d="M292 244l64 8-5 39-61 4Z" /><path className="building-front" d="M259 230l33 14-2 51-35-15Z" /><path className="building-roof" d="M259 230l48-22 49 19-64 17Z" />
            <path className="roof-accent" d="M273 226l35-12 33 13-47 11Z" />
          </g>
          <g className="resort-building resort-building--main" filter="url(#building-shadow)">
            <path className="building-side" d="M475 280l142 12-7 72-137 6Z" /><path className="building-front" d="M385 296l90-16-2 90-86-10Z" /><path className="building-roof" d="M385 296l105-51 127 47-142 22Z" />
            <path className="roof-garden" d="M440 284l53-25 73 27-74 13Z" />
            {[0,1,2,3,4].map((n) => <path className="window-row" key={n} d={`M493 ${315 + n * 10}l96 1`} />)}
          </g>
          <g className="resort-building resort-building--hotel" filter="url(#building-shadow)">
            <path className="hotel-side" d="M420 330q56-27 101-1l-8 87q-43-19-94 6Z" /><path className="hotel-front" d="M325 352q48-36 95-22l-1 92q-47-9-91 17Z" /><path className="hotel-roof" d="M325 352q97-69 196-23-51 22-101 1-47-14-95 22Z" />
            {[0,1,2,3,4].map((n) => <path className="hotel-window-row" key={n} d={`M343 ${369 + n * 12}q35-18 64-13`} />)}
            <path className="hotel-entry" d="M367 409l27-8 1 22-27 10Z" />
          </g>
          <g className="resort-building resort-building--convention" filter="url(#building-shadow)">
            <path className="convention-side" d="M517 408l87 8-11 55-82 3Z" /><path className="convention-front" d="M438 424l79-16-6 66-73-10Z" /><path className="convention-roof" d="M438 424l86-42 80 34-87 19Z" />
            <path className="convention-glass" d="M452 432l50-10-3 39-47-6Z" />
          </g>
          <g className="resort-building resort-building--villa" filter="url(#building-shadow)">
            <path className="building-side" d="M684 207l68 5-7 50-65 3Z" /><path className="building-front" d="M626 219l58-12-4 58-51-8Z" /><path className="building-roof" d="M626 219l59-45 67 38-68 14Z" /><path className="roof-accent" d="M651 209l35-25 40 23-43 9Z" />
          </g>
          <g className="resort-building resort-building--lobby" filter="url(#building-shadow)">
            <path className="building-side" d="M746 368l71 8-6 48-68 2Z" /><path className="building-front" d="M682 382l64-14-3 58-59-8Z" /><path className="building-roof" d="M682 382l66-48 69 42-71 14Z" /><path className="lobby-glass" d="M696 388l37-8-2 34-35-5Z" />
          </g>
          <g className="map-labels"><text x="93" y="149">South Gate</text><text x="101" y="278">West Gate</text><text x="765" y="471">River Park</text><text x="734" y="135">Forest Zone</text></g>
          <g className="facility-leaders">
            {facilities.map((facility) => {
              const labelX = facility.labelX ?? facility.x;
              const labelY = facility.labelY ?? facility.y;
              const effectiveStatus = facility.id === "breakfast" && simulated ? "warning" : facility.status;
              return <g key={facility.id} className={`facility-leader facility-leader--${effectiveStatus}`}>
                <line x1={facility.x * 9} y1={facility.y * 5.6} x2={labelX * 9} y2={labelY * 5.6} />
                <circle cx={facility.x * 9} cy={facility.y * 5.6} r="7" />
                <circle className="facility-leader__center" cx={facility.x * 9} cy={facility.y * 5.6} r="3" />
              </g>;
            })}
          </g>
        </svg>
        {facilities.map((facility) => <FacilityMarker key={facility.id} facility={facility} selected={selectedId === facility.id} simulated={simulated} onSelect={onSelect} />)}
        <div className="map-legend" aria-label="운영 상태 범례">
          <span><CheckCircle2 size={13} /> 정상</span><span><AlertTriangle size={13} /> 주의</span><span><AlertCircle size={13} /> 위험</span>
        </div>
      </div>
      <ul className="facility-status-list" aria-label="시설별 운영 상태 목록">
        {facilities.map((facility) => <li key={facility.id}><button type="button" onClick={() => onSelect(facility.id)}><b>{facility.name}</b><span>{facility.id === "breakfast" && simulated ? "주의" : facility.statusLabel}</span><small>{facility.metric}</small></button></li>)}
      </ul>
    </div>
  );
}
