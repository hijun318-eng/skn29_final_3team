import { useMemo, useState } from "react";
import { ArrowLeft, Bot, CheckCircle2, Clock3, DoorOpen, Sparkles, UsersRound, Wrench, X } from "lucide-react";
import { Sidebar } from "../components/layout/Sidebar";
import { HeaderUtilities } from "../components/layout/Header";

const TOWERS = {
  grand: { name: "그랜드 플레이스", shortName: "그랜드", floors: [5, 6, 7, 8, 9, 10, 11, 12], roomsPerFloor: 12 },
  vista: { name: "비스타 플레이스", shortName: "비스타", floors: [3, 4, 5, 6, 7, 8, 9, 10], roomsPerFloor: 10 },
};
const ROOM_TYPES = ["디럭스 리버뷰", "디럭스 마운틴뷰", "프리미어 스위트", "이그제큐티브 스위트"];
const ISSUES = [
  { type: "냉난방 고장", detail: "객실 에어컨이 작동하지 않아 실내 온도가 27도 이상 유지되고 있습니다.", severity: "높음", eta: "15분 이내" },
  { type: "온수 미공급", detail: "욕실 샤워 온수가 나오지 않아 프런트로 점검 요청이 접수되었습니다.", severity: "높음", eta: "20분 이내" },
  { type: "소음 민원", detail: "인접 객실 및 복도 소음으로 인한 수면 방해 민원이 접수되었습니다.", severity: "중간", eta: "10분 이내" },
  { type: "Wi-Fi 연결 불량", detail: "객실 내 Wi-Fi 연결이 반복적으로 끊기는 현상이 확인되었습니다.", severity: "낮음", eta: "10분 이내" },
];
const GUESTS = ["김O훈", "박O영", "이O민", "최O수", "정O아", "장O우", "조O진", "윤O현"];
const STATUS = { ok: "정상 운영", clean: "청소·점검중", issue: "이슈 발생" };
const FLOOR_STAFFING_META = { seed: "20260727", schemaVersion: "room-floor-staffing-v1" };
const FLOOR_STAFF = {
  grand: [
    { name: "최민지", role: "객실 매니저", floors: [5, 6, 7, 8], time: "09:00–18:00" },
    { name: "김하린", role: "하우스키핑", floors: [5, 6], time: "08:00–17:00" },
    { name: "박도윤", role: "하우스키핑", floors: [5, 6], time: "08:00–17:00" },
    { name: "이서준", role: "객실 정비", floors: [5, 6, 7], time: "09:00–18:00" },
    { name: "정유나", role: "하우스키핑", floors: [7, 8], time: "08:00–17:00" },
    { name: "한지호", role: "하우스키핑", floors: [7, 8], time: "08:00–17:00" },
    { name: "오세린", role: "객실 매니저", floors: [9, 10, 11, 12], time: "09:00–18:00" },
    { name: "윤가은", role: "하우스키핑", floors: [9, 10], time: "08:00–17:00" },
    { name: "송민재", role: "객실 정비", floors: [9, 10, 11], time: "09:00–18:00" },
    { name: "강수빈", role: "하우스키핑", floors: [11, 12], time: "08:00–17:00" },
    { name: "조현우", role: "하우스키핑", floors: [11, 12], time: "08:00–17:00" },
    { name: "임채원", role: "턴다운 서비스", floors: [10, 11, 12], time: "14:00–23:00" },
  ],
  vista: [
    { name: "한유진", role: "객실 매니저", floors: [3, 4, 5, 6], time: "09:00–18:00" },
    { name: "서지안", role: "하우스키핑", floors: [3, 4], time: "08:00–17:00" },
    { name: "김태윤", role: "하우스키핑", floors: [3, 4, 5], time: "08:00–17:00" },
    { name: "박소율", role: "객실 정비", floors: [4, 5, 6], time: "09:00–18:00" },
    { name: "윤서아", role: "하우스키핑", floors: [5, 6], time: "08:00–17:00" },
    { name: "신도현", role: "객실 매니저", floors: [7, 8, 9, 10], time: "09:00–18:00" },
    { name: "이예린", role: "하우스키핑", floors: [7, 8], time: "08:00–17:00" },
    { name: "최건우", role: "객실 정비", floors: [7, 8, 9], time: "09:00–18:00" },
    { name: "정다은", role: "하우스키핑", floors: [9, 10], time: "08:00–17:00" },
    { name: "문시우", role: "턴다운 서비스", floors: [8, 9, 10], time: "14:00–23:00" },
  ],
};

function seededRandom(seed) {
  const value = Math.sin(seed) * 10000;
  return value - Math.floor(value);
}

function buildRooms() {
  const rooms = [];
  let seed = 1;
  Object.entries(TOWERS).forEach(([towerId, tower]) => {
    tower.floors.forEach((floor) => {
      for (let number = 1; number <= tower.roomsPerFloor; number += 1) {
        seed += 1;
        const roomNo = `${floor}${String(number).padStart(2, "0")}`;
        const random = seededRandom(seed * 7.13);
        const status = random > 0.89 ? "issue" : random > 0.76 ? "clean" : "ok";
        const issue = status === "issue" ? ISSUES[Math.floor(seededRandom(seed * 2.3) * ISSUES.length)] : null;
        rooms.push({ id: `${towerId}-${roomNo}`, tower: towerId, floor, roomNo, type: ROOM_TYPES[Math.floor(seededRandom(seed * 3.7) * ROOM_TYPES.length)], status, issue, guest: status === "issue" ? GUESTS[Math.floor(seededRandom(seed * 5.1) * GUESTS.length)] : null, reportedAgo: status === "issue" ? Math.floor(seededRandom(seed * 4.4) * 40) + 3 : null });
      }
    });
  });
  return rooms;
}

const ROOMS = buildRooms();

export function RoomOperationsPage() {
  const params = new URLSearchParams(window.location.search);
  const initialTower = TOWERS[params.get("tower")] ? params.get("tower") : "grand";
  const initialFloor = Number(params.get("floor"));
  const [collapsed, setCollapsed] = useState(false);
  const [towerId, setTowerId] = useState(initialTower);
  const [floor, setFloor] = useState(TOWERS[initialTower].floors.includes(initialFloor) ? initialFloor : TOWERS[initialTower].floors[0]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [scenarioVisible, setScenarioVisible] = useState(false);
  const tower = TOWERS[towerId];
  const floorRooms = useMemo(() => ROOMS.filter((room) => room.tower === towerId && room.floor === floor), [towerId, floor]);
  const floorStaff = useMemo(() => FLOOR_STAFF[towerId].filter((staff) => staff.floors.includes(floor)), [towerId, floor]);
  const counts = useMemo(() => ({ ok: floorRooms.filter((room) => room.status === "ok").length, clean: floorRooms.filter((room) => room.status === "clean").length, issue: floorRooms.filter((room) => room.status === "issue").length }), [floorRooms]);
  const selectTower = (nextTower) => { setTowerId(nextTower); setFloor(TOWERS[nextTower].floors[0]); };
  const openRoom = (room) => { setSelectedRoom(room); setScenarioVisible(false); };
  const closeRoom = () => { setSelectedRoom(null); setScenarioVisible(false); };

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="workspace room-ops-workspace">
        <header className="top-header admin-page-header room-ops-page-header">
          <div className="headline"><p>ROOM OPERATIONS</p><h1>객실 운영 관제</h1><span>타워와 층별 객실 상태를 확인하고 운영 이슈에 대응합니다.</span></div>
          <HeaderUtilities />
        </header>

        <main className="room-ops-main">
          <a className="room-ops-back" href="/monitoring"><ArrowLeft size={14} /> 리조트 현황으로 돌아가기</a>
          <section className="room-ops-card card">
            <aside className="room-ops-sidebar">
              <div className="room-ops-sidebar-heading"><p>ROOM STATUS</p><h2>객실층 현황</h2></div>
              <div className="room-ops-towers" aria-label="호텔 선택">{Object.entries(TOWERS).map(([id, item]) => <button type="button" className={towerId === id ? "is-active" : ""} onClick={() => selectTower(id)} key={id}>{item.shortName}</button>)}</div>
              <div className="room-ops-floor-title">층별 현황</div>
              <nav className="room-ops-floors" aria-label="객실층 선택">{tower.floors.map((item) => { const issueCount = ROOMS.filter((room) => room.tower === towerId && room.floor === item && room.status === "issue").length; return <button type="button" className={floor === item ? "is-active" : ""} onClick={() => setFloor(item)} key={item}><span>{item}F</span>{issueCount > 0 && <b>{issueCount}</b>}</button>; })}</nav>
              <div className="room-ops-legend"><span><i className="ok" />정상 운영</span><span><i className="clean" />청소·점검중</span><span><i className="issue" />이슈 발생</span></div>
            </aside>

            <div className="room-ops-content">
              <header className="room-ops-header"><div><p>SELECTED FLOOR</p><h2><em>{tower.name}</em> · {floor}층</h2><span>객실 {tower.roomsPerFloor}개 · 실시간 상태 모니터링</span></div><b><i />LIVE · Synthetic</b></header>
              <section className="room-ops-stats" aria-label="객실 상태 요약">
                <article><DoorOpen size={18} /><span>전체 객실<strong>{floorRooms.length}</strong></span></article>
                <article className="ok"><CheckCircle2 size={18} /><span>정상 운영<strong>{counts.ok}</strong></span></article>
                <article className="clean"><Clock3 size={18} /><span>청소·점검중<strong>{counts.clean}</strong></span></article>
                <article className="issue"><Wrench size={18} /><span>이슈 발생<strong>{counts.issue}</strong></span></article>
              </section>
              <section className="room-floor-staff" aria-label={`${floor}층 근무 인원`}>
                <header><div><UsersRound size={17} /><span><b>{floor}층 근무 인원</b><small>여러 층 담당자는 각 담당 층에 중복 표시됩니다.</small></span></div><strong>{floorStaff.length}명 근무중</strong></header>
                <div>{floorStaff.map((staff) => <article key={`${towerId}-${floor}-${staff.name}`}><span className="room-floor-staff-avatar">{staff.name.slice(0, 1)}</span><div><b>{staff.name}</b><small>{staff.role} · {staff.time}</small><em>{staff.floors.map((item) => `${item}층`).join(" · ")} 담당</em></div><i>근무중</i></article>)}</div>
                <footer>Synthetic · seed {FLOOR_STAFFING_META.seed} · {FLOOR_STAFFING_META.schemaVersion}</footer>
              </section>
              <section className="room-ops-grid" aria-label={`${floor}층 객실 목록`}>{floorRooms.map((room) => <button type="button" className={`room-tile room-tile--${room.status}`} onClick={() => openRoom(room)} key={room.id}><i /><strong>{room.roomNo}</strong><span>{room.type}</span>{room.issue && <small>{room.issue.type}</small>}</button>)}</section>
            </div>
          </section>
        </main>
      </div>

      {selectedRoom && <div className="room-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeRoom(); }}><section className="room-modal" role="dialog" aria-modal="true" aria-labelledby="room-modal-title">
        <header><div><h2 id="room-modal-title">{selectedRoom.roomNo}호 <span className={selectedRoom.status}>{STATUS[selectedRoom.status]}</span></h2><p>{tower.name} · {selectedRoom.floor}층 · {selectedRoom.type}</p></div><button type="button" onClick={closeRoom} aria-label="객실 상세 닫기"><X size={18} /></button></header>
        <dl><div><dt>객실 번호</dt><dd>{selectedRoom.roomNo}</dd></div><div><dt>객실 타입</dt><dd>{selectedRoom.type}</dd></div>{selectedRoom.guest && <div><dt>투숙객</dt><dd>{selectedRoom.guest}</dd></div>}{selectedRoom.reportedAgo && <div><dt>접수 시간</dt><dd>{selectedRoom.reportedAgo}분 전</dd></div>}</dl>
        {selectedRoom.issue ? <><div className="room-issue-box"><b>{selectedRoom.issue.type} · 심각도 {selectedRoom.issue.severity}</b><p>{selectedRoom.issue.detail}</p></div><button className="room-ai-button" type="button" onClick={() => setScenarioVisible(true)}><Sparkles size={16} /> AI 대응 시나리오 생성</button>{scenarioVisible && <div className="room-scenario"><h3><Bot size={17} /> AI 생성 시나리오</h3><b>첫 응대 인사</b><p>불편을 드려 죄송합니다. 즉시 담당 직원을 보내 객실 상태를 확인하고 신속히 조치하겠습니다.</p><b>즉시 조치사항</b><ul><li>시설 담당자와 하우스키핑에 객실 상태를 즉시 공유합니다.</li><li>{selectedRoom.issue.eta} 방문 가능 여부를 확인해 투숙객에게 안내합니다.</li><li>조치가 지연되면 대체 객실 또는 고객 보상안을 검토합니다.</li></ul><div><Clock3 size={14} /> 예상 조치 완료 {selectedRoom.issue.eta}</div></div>}</> : <div className="room-normal-box"><CheckCircle2 size={18} /><div><b>{STATUS[selectedRoom.status]}</b><p>{selectedRoom.status === "clean" ? "하우스키핑 점검이 진행 중입니다." : "현재 접수된 운영 이슈가 없습니다."}</p></div></div>}
      </section></div>}
    </div>
  );
}
