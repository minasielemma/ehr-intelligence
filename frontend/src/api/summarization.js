/**
 * AI Clinical Summarization API service.
 */
import { apiRequest } from "./client.js";

export async function getPatientSummary(patientId) {
    return await apiRequest(`/ai/summary/${encodeURIComponent(patientId)}`);
}

export async function generatePatientSummary(patientId, forceRefresh = false, sync = true) {
    return await apiRequest(`/ai/summarize/patient/${encodeURIComponent(patientId)}?force_refresh=${forceRefresh}&sync=${sync}`, {
        method: "POST",
    });
}

/**
 * Asynchronously triggers clinical summary regeneration in a background worker.
 * Returns 202 Accepted with task metadata immediately.
 */
export async function regeneratePatientSummaryAsync(patientId, bundleId = null) {
    let url = `/ai/summarize/patient/${encodeURIComponent(patientId)}/regenerate`;
    if (bundleId) {
        url += `?bundle_id=${encodeURIComponent(bundleId)}`;
    }
    return await apiRequest(url, {
        method: "POST",
    });
}

/**
 * Polls the current status and result of an asynchronous summary generation/regeneration task.
 */
export async function getSummaryTaskStatus(patientId, taskId = null) {
    let url = `/ai/summarize/status/${encodeURIComponent(patientId)}`;
    if (taskId) {
        url += `?task_id=${encodeURIComponent(taskId)}`;
    }
    return await apiRequest(url);
}

export async function invalidateSummaryCache(patientId) {
    return await apiRequest(`/ai/cache/${encodeURIComponent(patientId)}`, {
        method: "DELETE",
    });
}

export async function getLlmHealth() {
    return await apiRequest("/ai/health");
}

