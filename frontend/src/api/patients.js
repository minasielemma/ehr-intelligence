/**
 * Patient directory & clinical detail API service.
 */
import { apiRequest } from "./client.js";

export async function listPatients({ page = 1, pageSize = 20, query = "", sourceSystem = "", reconciliationStatus = "" } = {}) {
    const params = new URLSearchParams();
    params.set("page", page);
    params.set("page_size", pageSize);
    if (query) params.set("query", query);
    if (sourceSystem) params.set("source_system", sourceSystem);
    if (reconciliationStatus) params.set("reconciliation_status", reconciliationStatus);

    return await apiRequest(`/patients?${params.toString()}`);
}

export async function getPatientDetail(patientId) {
    return await apiRequest(`/patients/${encodeURIComponent(patientId)}`);
}

export async function getPatientRecords(patientId, { page = 1, pageSize = 20, status = "" } = {}) {
    const params = new URLSearchParams();
    params.set("page", page);
    params.set("page_size", pageSize);
    if (status) params.set("status", status);

    return await apiRequest(`/patients/${encodeURIComponent(patientId)}/records?${params.toString()}`);
}

export async function getPatientFhirResources(patientId) {
    return await apiRequest(`/patients/${encodeURIComponent(patientId)}/fhir-resources`);
}
