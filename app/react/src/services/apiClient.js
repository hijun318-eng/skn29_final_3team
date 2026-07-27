const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

export async function request(path, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, options);

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json();
}
