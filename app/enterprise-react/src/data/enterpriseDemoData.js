export const SYNTHETIC_META = {
  seed: "20260727",
  schemaVersion: "enterprise-demo-v1",
  label: "Synthetic demo data",
};

export const connections = [
  { name: "PMS Core", vendor: "PostgreSQL", catalog: "pms", domain: "예약·투숙", status: "connected", health: 99, records: "4.2M", owner: "객실운영팀", endpoint: "pms••••.internal", sync: "1분 전" },
  { name: "F&B POS Commerce", vendor: "MySQL", catalog: "pos", domain: "식음·구매", status: "connected", health: 96, records: "18.7M", owner: "F&B팀", endpoint: "pos••••.internal", sync: "3분 전" },
  { name: "Membership CRM", vendor: "SQL Server", catalog: "crm", domain: "고객·멤버십", status: "connected", health: 98, records: "620K", owner: "마케팅팀", endpoint: "crm••••.salesforce.com", sync: "5분 전" },
  { name: "Facility Operations", vendor: "ClickHouse", catalog: "facility", domain: "시설 운영", status: "delayed", health: 78, records: "2.1M", owner: "시설운영팀", endpoint: "facility••••.internal", sync: "41분 전" },
  { name: "Banquet & Revenue", vendor: "PostgreSQL", catalog: "banquet", domain: "연회·매출", status: "connected", health: 95, records: "340K", owner: "연회영업팀", endpoint: "banquet••••.internal", sync: "8분 전" },
];

export const dataProducts = [
  { product: "Reservation Fact", source: "PMS Core", catalog: "pms.reservation", domain: "예약", owner: "Revenue Strategy", freshness: "1분", quality: 98, sensitivity: "Internal", tool: "Federated Query" },
  { product: "Customer Golden Profile", source: "Customer CRM", catalog: "crm.customer_360", domain: "고객", owner: "CX Strategy", freshness: "5분", quality: 96, sensitivity: "Restricted", tool: "Customer 360" },
  { product: "Room Revenue Daily", source: "Finance ERP", catalog: "finance.room_revenue", domain: "매출", owner: "Finance", freshness: "8분", quality: 99, sensitivity: "Confidential", tool: "Federated Query" },
  { product: "POS Order Fact", source: "POS Commerce", catalog: "pos.orders", domain: "구매", owner: "F&B", freshness: "3분", quality: 94, sensitivity: "Internal", tool: "Federated Query" },
  { product: "VOC Sentiment", source: "VOC Platform", catalog: "voc.sentiment", domain: "고객경험", owner: "CX Strategy", freshness: "12분", quality: 91, sensitivity: "Restricted", tool: "Document Retrieval" },
  { product: "Demand Feature Set", source: "PMS + Finance", catalog: "mart.demand_features", domain: "예측", owner: "Data Science", freshness: "10분", quality: 97, sensitivity: "Internal", tool: "Forecast Model" },
];

export const mcpTools = [
  { name: "Federated Query Tool", category: "Data", version: "v1.4.2", health: "healthy", success: "98.7%", agents: "Data Agent", permission: "Read only", last: "1분 전" },
  { name: "Catalog Search Tool", category: "Metadata", version: "v1.2.0", health: "healthy", success: "99.4%", agents: "Orchestrator", permission: "All roles", last: "3분 전" },
  { name: "Ontology Traversal Tool", category: "Semantic", version: "v0.9.6", health: "healthy", success: "97.9%", agents: "Data Agent", permission: "Analyst+", last: "4분 전" },
  { name: "Document Retrieval Tool", category: "Knowledge", version: "v1.1.3", health: "healthy", success: "96.8%", agents: "Document Agent", permission: "Domain scoped", last: "8분 전" },
  { name: "Room Demand Forecast", category: "ML · ONNX", version: "v2.3.1", health: "healthy", success: "99.1%", agents: "Forecast Agent", permission: "Analyst+", last: "12분 전" },
  { name: "Report Generation Tool", category: "Document", version: "v1.0.8", health: "degraded", success: "92.4%", agents: "Strategy Agent", permission: "Manager+", last: "19분 전" },
];

export const customers = [
  { id: "CUS-84••12", name: "김*현", tier: "VIP Gold", stays: 8, revenue: "₩5,760,000", revisit: 78, sentiment: "긍정", issue: "조식 대기", last: "2026.07.18", room: "Grand Deluxe · River View" },
  { id: "CUS-22••91", name: "이*민", tier: "Silver", stays: 4, revenue: "₩2,840,000", revisit: 64, sentiment: "중립", issue: "없음", last: "2026.07.11", room: "Vista Deluxe" },
  { id: "CUS-73••08", name: "박*우", tier: "VIP Platinum", stays: 14, revenue: "₩12,460,000", revisit: 91, sentiment: "긍정", issue: "체크인 지연", last: "2026.07.23", room: "Grand Suite" },
];

export const agentSteps = [
  ["질문 해석", "완료", "매출 하락 원인과 기간 범위를 확인했습니다."],
  ["Catalog Search", "완료", "4개 데이터 제품을 선택했습니다."],
  ["Ontology Traversal", "완료", "Reservation → Stay → Revenue 관계를 확인했습니다."],
  ["Federated Query", "완료", "Trino로 3개 catalog를 연합 조회했습니다."],
  ["전략 생성", "완료", "근거와 한계를 포함한 제안을 생성했습니다."],
];
