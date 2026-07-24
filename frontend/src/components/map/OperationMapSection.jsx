import { useEffect, useMemo, useState } from "react";
import { HotelOperationMap } from "./HotelOperationMap";
import { facilities, facilityDetails, timeline } from "./operationMapData";
import { FacilityDetailPanel } from "../simulation/FacilityDetailPanel";
import { getLiveVocEvents, liveVocEvent, liveVocStorageKey } from "../../services/liveVoc";

export function OperationMapSection() {
  const requestedFacility = new URLSearchParams(window.location.search).get("facility");
  const [selectedId, setSelectedId] = useState(() => facilities.some((facility) => facility.id === requestedFacility) ? requestedFacility : "breakfast");
  const [liveVocEvents, setLiveVocEvents] = useState(() => getLiveVocEvents());
  const latestVocByFacility = useMemo(() => {
    const latest = new Map();
    liveVocEvents.forEach((event) => { if (!latest.has(event.facilityId)) latest.set(event.facilityId, event); });
    return latest;
  }, [liveVocEvents]);
  const liveFacilities = useMemo(() => facilities.map((facility) => {
    const voc = latestVocByFacility.get(facility.id);
    if (!voc) return facility;
    const vocStatus = voc.rating <= 2 ? "danger" : voc.rating === 3 ? "warning" : facility.status;
    return { ...facility, status: vocStatus, statusLabel: vocStatus === "danger" ? "위험" : vocStatus === "warning" ? "주의" : facility.statusLabel, metric: `신규 VOC ${voc.rating}점` };
  }), [latestVocByFacility]);
  const selectedFacility = liveFacilities.find((facility) => facility.id === selectedId) || liveFacilities[0];
  const selectedVoc = latestVocByFacility.get(selectedFacility.id);
  const selectedDetail = selectedVoc ? { ...facilityDetails[selectedFacility.id], recentVoc: selectedVoc.comment, facts: [`고객 모바일 VOC ${selectedVoc.rating}점 실시간 접수`, ...(selectedVoc.photos?.length ? [`첨부 사진 ${selectedVoc.photos.length}장 · ${selectedVoc.photos.map((photo) => photo.name).join(", ")}`] : []), ...(selectedVoc.reasons.length ? [`선택 항목 · ${selectedVoc.reasons.join(" · ")}`] : []), ...facilityDetails[selectedFacility.id].facts].slice(0, 4) } : facilityDetails[selectedFacility.id];
  const simulated = false;
  const result = timeline[0];

  useEffect(() => {
    const syncVoc = (event) => setLiveVocEvents(event.detail || getLiveVocEvents());
    const syncStorage = (event) => { if (event.key === liveVocStorageKey) setLiveVocEvents(getLiveVocEvents()); };
    window.addEventListener(liveVocEvent, syncVoc);
    window.addEventListener("storage", syncStorage);
    return () => { window.removeEventListener(liveVocEvent, syncVoc); window.removeEventListener("storage", syncStorage); };
  }, []);

  return (
    <section className="operation-map-card card" aria-labelledby="operation-map-title">
      <header className="operation-map-header">
        <div><p>OPERATION MAP</p><h2 id="operation-map-title">호텔 실시간 운영 맵</h2><span>시설을 선택해 운영 상태와 대응 시나리오를 확인하세요.</span></div>
        <div className="map-meta"><span>2026.07.21 08:30 기준</span><b>Synthetic</b></div>
      </header>
      <div className="operation-map-layout">
        <div className="map-column">
          <HotelOperationMap facilities={liveFacilities} selectedId={selectedId} onSelect={setSelectedId} simulated={simulated} timelineState={result} />
        </div>
        <FacilityDetailPanel facility={selectedFacility} detail={selectedDetail} simulated={simulated} />
      </div>
    </section>
  );
}
