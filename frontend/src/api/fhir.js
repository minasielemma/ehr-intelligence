/**
 * HL7 FHIR R4 Normalization, Bundles, and Conformance Validation API service.
 */
import { apiRequest } from "./client.js";

export async function listBundles({ page = 1, pageSize = 50, status = "" } = {}) {
    const params = new URLSearchParams();
    params.set("page", page);
    params.set("page_size", pageSize);
    if (status) params.set("status", status);

    return await apiRequest(`/fhir/bundles?${params.toString()}`);
}

export async function getBundleById(bundleId) {
    return await apiRequest(`/fhir/bundles/${encodeURIComponent(bundleId)}`);
}

export async function getBundleReport(bundleId) {
    return await apiRequest(`/fhir/bundles/${encodeURIComponent(bundleId)}/report`);
}

export async function getPatientBundles(patientId, latest = true) {
    return await apiRequest(`/fhir/bundles/patient/${encodeURIComponent(patientId)}?latest=${latest}`);
}

export async function normalizePatient(patientId, bundleType = "collection") {
    return await apiRequest(`/fhir/normalize/patient/${encodeURIComponent(patientId)}?bundle_type=${bundleType}&save_to_store=true`, {
        method: "POST",
    });
}

export async function normalizeJob(jobId, bundleType = "collection") {
    return await apiRequest(`/fhir/normalize/job/${encodeURIComponent(jobId)}?bundle_type=${bundleType}&save_to_store=true`, {
        method: "POST",
    });
}

export async function validateFhirPayload(resource, patientIdentifier = null) {
    return await apiRequest("/fhir/validate", {
        method: "POST",
        body: {
            resource,
            patient_identifier: patientIdentifier,
        },
    });
}
