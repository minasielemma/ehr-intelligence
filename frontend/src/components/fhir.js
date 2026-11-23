/**
 * HL7 FHIR R4 Bundles & Gatekeeper Conformance Component.
 * Lists persisted patient bundles, triggers normalization, and displays validation reports.
 */
import { listBundles, normalizePatient, normalizeJob } from "../api/fhir.js";
import { escapeHtml, formatDate, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { openFhirBundleModal, openFhirReportModal } from "./modals.js";
import { showToast } from "./toast.js";

let currentBundlePage = 1;
let bundlePageSize = 20;
let totalBundlePages = 1;
let currentBundleStatusFilter = "";

export async function loadStoredFhirBundles(page = 1) {
    currentBundlePage = page;
    const tbody = document.getElementById("fhir-bundles-table-body");
    const countBadge = document.getElementById("fhir-bundle-count-badge");

    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="p-8 text-center text-slate-400 text-xs">
                    ${iconSvg("spinner", "w-5 h-5 mx-auto text-[#389B98] mb-2")}
                    <span>Loading stored FHIR Bundles...</span>
                </td>
            </tr>
        `;
    }

    try {
        const data = await listBundles({
            page: currentBundlePage,
            pageSize: bundlePageSize,
            status: currentBundleStatusFilter,
        });

        totalBundlePages = data.total_pages || 1;

        if (countBadge) {
            countBadge.textContent = `${formatNumber(data.total)} Bundles`;
        }

        if (!data.items || data.items.length === 0) {
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="p-10 text-center text-slate-400 text-xs">
                            No stored FHIR Bundles found. Normalize a patient or job to populate.
                        </td>
                    </tr>
                `;
            }
            return;
        }

        const rowsHtml = data.items.map(b => {
            const badgeClass = getStatusBadgeClass(b.status);
            return `
                <tr class="hover:bg-slate-50 transition-colors">
                    <td class="px-4 py-3 font-mono font-bold text-xs text-[#389B98]">${escapeHtml(b.bundle_id)}</td>
                    <td class="px-4 py-3 font-mono font-bold text-xs text-slate-700">${escapeHtml(b.patient_mrn)}</td>
                    <td class="px-4 py-3 font-mono text-[11px] uppercase text-slate-500">${escapeHtml(b.bundle_type)}</td>
                    <td class="px-4 py-3 font-mono text-center text-slate-700 font-bold">v${b.version}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                            ${escapeHtml(b.status)}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-center font-mono font-bold text-slate-800">${b.resource_count}</td>
                    <td class="px-4 py-3 text-slate-500 font-mono text-[11px]">${formatDate(b.created_at)}</td>
                    <td class="px-4 py-3 text-right">
                        <div class="flex items-center justify-end space-x-1.5">
                            <button
                                onclick="openFhirBundleModal('${escapeHtml(b.bundle_id)}')"
                                class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-[#389B98]/10 text-[#389B98] hover:bg-[#389B98] hover:text-white transition-colors"
                            >
                                JSON
                            </button>
                            <button
                                onclick="openFhirReportModal('${escapeHtml(b.bundle_id)}')"
                                class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-600 hover:text-white border border-emerald-200 transition-colors"
                            >
                                Report
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        if (tbody) {
            tbody.innerHTML = rowsHtml;
        }
    } catch (err) {
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="p-8 text-center text-rose-600 text-xs">
                        Failed to load FHIR Bundles: ${escapeHtml(err.message || "Network or server error")}
                    </td>
                </tr>
            `;
        }
    }
}

export async function triggerPatientNormalization() {
    const input = document.getElementById("fhir-target-id-input");
    const bundleTypeSelect = document.getElementById("fhir-bundle-type-select");
    const patientId = input ? input.value.trim() : "";
    const bundleType = bundleTypeSelect ? bundleTypeSelect.value : "collection";

    if (!patientId) {
        showToast("warning", "Input Required", "Enter a Patient ID or MRN to normalize.");
        return;
    }

    try {
        showToast("info", "Normalization Started", `Normalizing patient ${patientId}...`, 3000);
        const res = await normalizePatient(patientId, bundleType);
        showToast("success", "Bundle Created", `FHIR Bundle ${res.bundle_id} (v${res.version}) saved with status ${res.validation_report.status}`);
        if (typeof window.invalidatePatientFhirCache === "function") {
            window.invalidatePatientFhirCache(patientId);
            if (res.patient_id) window.invalidatePatientFhirCache(res.patient_id);
        }
        loadStoredFhirBundles(1);
    } catch (err) {
        showToast("error", "Normalization Failed", err.message || "Could not normalize patient");
    }
}

export async function triggerJobNormalization() {
    const input = document.getElementById("fhir-target-id-input");
    const bundleTypeSelect = document.getElementById("fhir-bundle-type-select");
    const jobId = input ? input.value.trim() : "";
    const bundleType = bundleTypeSelect ? bundleTypeSelect.value : "collection";

    if (!jobId) {
        showToast("warning", "Input Required", "Enter an Ingestion Job UUID to batch normalize.");
        return;
    }

    try {
        showToast("info", "Batch Normalization", `Processing all patients for job ${jobId}...`, 3000);
        const results = await normalizeJob(jobId, bundleType);
        showToast("success", "Batch Complete", `Normalized ${results.length} patient bundles successfully.`);
        if (typeof window.invalidatePatientFhirCache === "function") {
            window.invalidatePatientFhirCache(null); // Invalidate all cached patient FHIR states
        }
        loadStoredFhirBundles(1);
    } catch (err) {
        showToast("error", "Batch Normalization Failed", err.message || "Could not normalize job");
    }
}

// Window bindings
window.loadStoredFhirBundles = loadStoredFhirBundles;
window.triggerPatientNormalization = triggerPatientNormalization;
window.triggerJobNormalization = triggerJobNormalization;
