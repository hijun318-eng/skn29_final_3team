import { useMemo, useState } from "react";
import { HotelOperationMap } from "./HotelOperationMap";
import { facilities, facilityDetails, responseOptions, timeline } from "./operationMapData";
import { FacilityDetailPanel } from "../simulation/FacilityDetailPanel";
import { SimulationControls } from "../simulation/SimulationControls";

export function OperationMapSection() {
  const [selectedId, setSelectedId] = useState("breakfast");
  const [simulated, setSimulated] = useState(false);
  const [selectedOptions, setSelectedOptions] = useState(["staff", "seats"]);
  const [timeIndex, setTimeIndex] = useState(3);
  const [memo, setMemo] = useState("");
  const [decision, setDecision] = useState(null);
  const selectedFacility = facilities.find((facility) => facility.id === selectedId) || facilities[0];
  const result = simulated ? timeline[timeIndex] : timeline[0];
  const cost = useMemo(() => responseOptions.filter((option) => selectedOptions.includes(option.id)).reduce((sum, option) => sum + option.cost, 0), [selectedOptions]);

  const toggleOption = (id) => setSelectedOptions((current) => current.includes(id) ? current.filter((optionId) => optionId !== id) : [...current, id]);
  const changeMode = (nextMode) => { setSimulated(nextMode); if (!nextMode) setTimeIndex(0); else if (timeIndex === 0) setTimeIndex(3); setDecision(null); };
  const makeDecision = (label) => {
    const messages = {
      승인: "대응안이 실행 후보로 등록되었습니다. 실제 운영 조치는 자동 실행되지 않습니다.",
      보류: "추가 현장 확인이 필요한 상태로 저장되었습니다.",
      반려: "선택한 대응안이 실행 후보에서 제외되었습니다.",
    };
    setDecision({ label, message: messages[label], type: label === "승인" ? "approved" : label === "보류" ? "held" : "rejected", time: new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit" }).format(new Date()) });
  };

  return (
    <section className="operation-map-card card" aria-labelledby="operation-map-title">
      <header className="operation-map-header">
        <div><p>OPERATION MAP</p><h2 id="operation-map-title">호텔 실시간 운영 맵</h2><span>시설을 선택해 운영 상태와 대응 시나리오를 확인하세요.</span></div>
        <div className="map-meta"><span>2026.07.21 08:30 기준</span><b>Synthetic</b></div>
      </header>
      <div className="operation-map-layout">
        <div className="map-column">
          <HotelOperationMap facilities={facilities} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); setMemo(""); setDecision(null); }} simulated={simulated} timelineState={result} />
          <SimulationControls simulated={simulated} onModeChange={changeMode} timeline={timeline} timeIndex={timeIndex} onTimeChange={setTimeIndex} />
        </div>
        <FacilityDetailPanel facility={selectedFacility} detail={facilityDetails[selectedFacility.id]} options={responseOptions} selectedOptions={selectedOptions} onToggleOption={toggleOption} simulated={simulated} result={result} cost={cost} memo={memo} onMemoChange={setMemo} decision={decision} onDecision={makeDecision} />
      </div>
    </section>
  );
}
