/**
 * Centralized Fetch API Client for Ony(e) EHR Intelligence Platform.
 * Provides unified request handling, authentication, timeout control,
 * signal cancellation, and standardized error normalization.
 */

const DEFAULT_API_PREFIX = "/api/v1";
const DEFAULT_TIMEOUT_MS = 30000;

export class ApiError extends Error {
    constructor(message, status = 500, details = null) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.details = details;
    }
}

export function getApiKey() {
    return sessionStorage.getItem("ehr_api_key") || "dev-test-key";
}

export function setApiKey(key) {
    if (key) {
        sessionStorage.setItem("ehr_api_key", key);
    } else {
        sessionStorage.removeItem("ehr_api_key");
    }
}

/**
 * Universal API request wrapper
 * @param {string} endpoint - API path (e.g. '/dashboard/stats' or '/search')
 * @param {Object} options - Fetch options (method, headers, body, signal, timeout)
 * @returns {Promise<any>} Parsed response data
 */
export async function apiRequest(endpoint, options = {}) {
    const fullUrl = `${DEFAULT_API_PREFIX}${endpoint}`;

    const headers = {
        "X-API-Key": getApiKey(),
        ...options.headers,
    };

    // If body is object and not FormData, stringify to JSON
    let body = options.body;
    if (body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob)) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(body);
    }

    const timeoutMs = options.timeout || DEFAULT_TIMEOUT_MS;
    const controller = new AbortController();
    const activeSignal = options.signal || controller.signal;

    const timeoutId = setTimeout(() => {
        controller.abort(new Error(`Request timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    try {
        const response = await fetch(fullUrl, {
            ...options,
            headers,
            body,
            signal: activeSignal,
        });

        clearTimeout(timeoutId);

        if (response.status === 204) {
            return null;
        }

        const contentType = response.headers.get("content-type") || "";
        const isJson = contentType.includes("application/json");

        if (!response.ok) {
            let errorMsg = `API request failed with status ${response.status}`;
            let details = null;
            if (isJson) {
                try {
                    const errData = await response.json();
                    details = errData;
                    if (typeof errData.error_message === "string" && errData.error_message.trim()) {
                        errorMsg = errData.error_message.trim();
                    } else if (typeof errData.detail === "string" && errData.detail.trim()) {
                        errorMsg = errData.detail.trim();
                    } else if (Array.isArray(errData.detail) && errData.detail.length > 0) {
                        errorMsg = errData.detail.map(d => {
                            if (typeof d === "string") return d;
                            const loc = Array.isArray(d.loc) ? d.loc.filter(l => l !== "body").join(".") : "";
                            const msg = d.msg || d.message || JSON.stringify(d);
                            return loc ? `${loc}: ${msg}` : msg;
                        }).join("; ");
                    } else if (typeof errData.message === "string" && errData.message.trim()) {
                        errorMsg = errData.message.trim();
                    } else if (errData.error) {
                        errorMsg = typeof errData.error === "string" ? errData.error : (errData.error.message || JSON.stringify(errData.error));
                    }
                } catch {
                    // Ignore JSON parsing errors for error body
                }
            } else {
                try {
                    const txt = await response.text();
                    if (txt && txt.trim()) errorMsg = txt.trim();
                } catch {
                    // Ignore text errors
                }
            }
            throw new ApiError(errorMsg, response.status, details);
        }

        if (isJson) {
            return await response.json();
        }
        return await response.text();
    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === "AbortError") {
            throw err;
        }
        if (err instanceof ApiError) {
            throw err;
        }
        throw new ApiError(err.message || "Network connectivity failure", 0, null);
    }
}
