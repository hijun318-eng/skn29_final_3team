import { useEffect, useState } from "react";
import { AlertTriangle, Bell, Check, CheckCheck, Trash2 } from "lucide-react";
import { clearOperationAlerts, dismissOperationAlert, getOperationAlerts, operationAlertEvent } from "../../services/operationAlerts";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState(() => getOperationAlerts());
  const alertCount = alerts.length;

  useEffect(() => {
    const sync = (event) => {
      const nextAlerts = event.detail || getOperationAlerts();
      setAlerts(nextAlerts);
      if (nextAlerts.some((alert) => !alert.read)) setOpen(true);
    };
    const syncStorage = (event) => {
      if (event.key !== "senseplace.operation.alerts") return;
      const nextAlerts = getOperationAlerts();
      setAlerts(nextAlerts);
      if (nextAlerts.some((alert) => !alert.read)) setOpen(true);
    };
    window.addEventListener(operationAlertEvent, sync);
    window.addEventListener("storage", syncStorage);
    return () => { window.removeEventListener(operationAlertEvent, sync); window.removeEventListener("storage", syncStorage); };
  }, []);

  const openMenu = () => setOpen((current) => !current);

  const dismissAlert = (alertId) => {
    dismissOperationAlert(alertId);
    setAlerts(getOperationAlerts());
  };

  return <div className="notification-wrap">
    <button className={`icon-button ${alertCount ? "has-alerts" : ""}`} type="button" aria-label={`알림 ${alertCount}개`} aria-expanded={open} onClick={openMenu}><Bell size={20} />{alertCount > 0 && <b>{alertCount > 9 ? "9+" : alertCount}</b>}</button>
    {open && <section className="notification-panel" aria-label="실시간 운영 알림">
      <header><div><p>LIVE ALERTS</p><h2>실시간 운영 알림</h2></div>{alerts.length > 0 && <button type="button" onClick={() => { clearOperationAlerts(); setAlerts([]); }} aria-label="알림 모두 삭제"><Trash2 size={15} /></button>}</header>
      {alerts.length === 0 ? <div className="notification-empty"><CheckCheck size={22} /><b>새로운 위험 알림이 없습니다</b><span>모니터링에서 위험 요소가 감지되면 여기에 표시됩니다.</span></div> : <div className="notification-list">{alerts.map((alert) => <div className={`notification-item notification-item--${alert.severity}`} key={alert.id}><a href={`/monitoring?facility=${alert.facilityId}`}><span><AlertTriangle size={15} /></span><div><b>{alert.title}</b><small>{alert.message}</small><em>{new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit" }).format(new Date(alert.detectedAt))} 감지</em></div></a><button type="button" onClick={() => dismissAlert(alert.id)} aria-label={`${alert.title} 확인`}><Check size={14} />확인</button></div>)}</div>}
      <footer><a href="/monitoring">실시간 모니터링에서 확인</a></footer>
    </section>}
  </div>;
}
