/**
 * Clinical Semantic Search & Vector Retrieval API service.
 */
import { apiRequest } from "./client.js";

/**
 * Natural language semantic search across clinical records and AI summaries.
 * Submits query to POST /search (or /api/v1/search).
 */
export async function searchClinicalRecords({
    query,
    resourceType = null,
    patientId = null,
    dateFrom = null,
    dateTo = null,
    topK = 5,
    signal = null,
} = {}) {
    const payload = {
        query: query.trim(),
        resource_type: resourceType || undefined,
        patient_id: patientId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        top_k: Number(topK) || 5,
    };

    return await apiRequest("/search", {
        method: "POST",
        body: payload,
        signal,
    });
}
