/** API idempotency·trace에 사용할 암호학적 UUID를 생성하는 유틸리티 모듈이다. */
/** 브라우저 암호학 난수만 사용해 RFC 4122 v4 식별자를 만들며 비암호학적 대체값을 사용하지 않는다. */
export function createUuid() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}
