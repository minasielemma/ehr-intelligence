/**
 * EHR Ingestion, Cleaning & Job Management API service.
 */
import { apiRequest } from "./client.js";

export async function uploadEhrFile(formData, sync = true) {
    return await apiRequest(`/ingestion/upload?sync=${sync}`, {
        method: "POST",
        body: formData,
        headers: {}, // Let browser set multipart boundary
    });
}

export async function ingestJsonRecords(payload, sync = true) {
    return await apiRequest(`/ingestion/json?sync=${sync}`, {
        method: "POST",
        body: payload,
    });
}

export async function listIngestionJobs({ page = 1, pageSize = 20, status = "", sourceSystem = "" } = {}) {
    const params = new URLSearchParams();
    params.set("page", page);
    params.set("page_size", pageSize);
    if (status) params.set("status", status);
    if (sourceSystem) params.set("source_system", sourceSystem);

    return await apiRequest(`/ingestion/jobs?${params.toString()}`);
}

export async function getJobStatus(jobId) {
    return await apiRequest(`/ingestion/jobs/${encodeURIComponent(jobId)}`);
}

export async function getJobReport(jobId) {
    return await apiRequest(`/ingestion/jobs/${encodeURIComponent(jobId)}/report`);
}

export async function getJobRecords(jobId, { page = 1, pageSize = 50, status = "" } = {}) {
    const params = new URLSearchParams();
    params.set("page", page);
    params.set("page_size", pageSize);
    if (status) params.set("status", status);

    return await apiRequest(`/ingestion/jobs/${encodeURIComponent(jobId)}/records?${params.toString()}`);
}

export async function getJobPackageFiles(jobId) {
    return await apiRequest(`/ingestion/jobs/${encodeURIComponent(jobId)}/files`);
}
