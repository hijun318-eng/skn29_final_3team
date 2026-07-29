const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export async function request(path, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = null;
    }
    throw new Error(errorData?.error?.message || `API request failed: ${response.status}`);
  }

  return response.json();
}

export async function apiGet(path) {
  return request(path, { method: "GET" });
}

export async function apiPost(path, body) {
  return request(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}
