import { useState } from "react";
import { HotelOperationMap } from "./HotelOperationMap";
import { facilities, facilityDetails, timeline } from "./operationMapData";
import { FacilityDetailPanel } from "../simulation/FacilityDetailPanel";
import { SimulationControls } from "../simulation/SimulationControls";

export function OperationMapSection() {
  const requestedFacility = new URLSearchParams(window.location.search).get("facility");
  const [selectedId, setSelectedId] = useState(() => facilities.some((facility) => facility.id === requestedFacility) ? requestedFacility : "breakfast");
  const [simulated, setSimulated] = useState(false);
  const [timeIndex, setTimeIndex] = useState(3);
  const selectedFacility = facilities.find((facility) => facility.id === selectedId) || facilities[0];
  const result = simulated ? timeline[timeIndex] : timeline[0];

  const changeMode = (nextMode) => { setSimulated(nextMode); if (!nextMode) setTimeIndex(0); else if (timeIndex === 0) setTimeIndex(3); };

  return (
    <section className="operation-map-card card" aria-labelledby="operation-map-title">
      <header className="operation-map-header">
        <div><p>OPERATION MAP</p><h2 id="operation-map-title">호텔 실시간 운영 맵</h2><span>시설을 선택해 운영 상태와 대응 시나리오를 확인하세요.</span></div>
        <div className="map-meta"><span>2026.07.21 08:30 기준</span><b>Synthetic</b></div>
      </header>
      <div className="operation-map-layout">
        <div className="map-column">
          <HotelOperationMap facilities={facilities} selectedId={selectedId} onSelect={setSelectedId} simulated={simulated} timelineState={result} />
          <SimulationControls simulated={simulated} onModeChange={changeMode} timeline={timeline} timeIndex={timeIndex} onTimeChange={setTimeIndex} />
        </div>
        <FacilityDetailPanel facility={selectedFacility} detail={facilityDetails[selectedFacility.id]} simulated={simulated} />
      </div>
    </section>
  );
}
