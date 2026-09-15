// All the calls to the FastAPI backend live here, in one place.
// If the backend ever moves (different port, deployed somewhere), this
// is the only line you need to change.
const API_BASE = "http://127.0.0.1:8000";

/**
 * Fetch metrics + trade log + equity curve for one period ("tuning" or "test").
 * This is the main call the dashboard uses -- one request gets everything
 * needed to render that period's cards, charts, and table.
 */
export async function fetchPeriod(period) {
  const response = await fetch(`${API_BASE}/api/${period}`);
  if (!response.ok) {
    throw new Error(`Failed to load "${period}" data (HTTP ${response.status})`);
  }
  return response.json();
}
