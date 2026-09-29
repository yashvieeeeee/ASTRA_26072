export const API_BASE_URL = import.meta.env.VITE_ASTRA_API_BASE_URL ?? "";
export const apiUrl = (path: string) => `${API_BASE_URL}${path}`;
/** Mock data is the safe default for the standalone Vite build. Set this to true
 * only when an unavailable live backend must be surfaced as an error. */
export const MOCK_DISABLED = import.meta.env.VITE_ASTRA_DISABLE_MOCK === "true";
export const shouldUseMock = () => !API_BASE_URL || !MOCK_DISABLED;
