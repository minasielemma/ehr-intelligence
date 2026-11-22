/**
 * Reusable Modals Component.
 * Implements:
 * 1. Record Deep Dive Modal
 * 2. FHIR Bundle JSON Viewer Modal
 * 3. FHIR Conformance & Validation Report Modal
 * 4. Ingestion Job Audit & Reconciliation Report Modal
 */
import { getBundleById, getBundleReport } from "../api/fhir.js";
import { getJobReport } from "../api/ingestion.js";
import { escapeHtml, formatDate, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { showToast } from "./toast.js";

let activeBundleJson = null;

// =============================================================================
// 1. Record Deep Dive Modal
// =============================================================================
export function openRecordModal(record) {
    const modal = document.getElementById("record-modal");
    if (!modal) return;

    document.getElementById("modal-record-id").textContent = record.id || "-";
    document.getElementById("modal-patient-id").textContent = record.patient_id || "Unassigned";
    document.getElementById("modal-fingerprint").textContent = (record.fingerprint || "-").substring(0, 16) + "...";
    document.getElementById("modal-record-date").textContent = formatDate(record.record_date || record.created_at);

    const badge = document.getElementById("modal-status-badge");
    badge.className = `px-2 py-0.5 rounded-full text-xs font-semibold border ${getStatusBadgeClass(record.status)}`;
    badge.textContent = record.status;

    document.getElementById("modal-cleaned-text").textContent = record.cleaned_text || "(No clinical narrative recorded)";

    // Render Structured Attribute Grid
    const structuredContainer = document.getElementById("modal-structured-payload");
    const rawPayloadWrapper = document.getElementById("modal-raw-payload-wrapper");
    const rawToggleBtn = document.getElementById("label-toggle-modal-raw");

    // Reset raw toggle to collapsed
    if (rawPayloadWrapper) rawPayloadWrapper.classList.add("hidden");
    if (rawToggleBtn) rawToggleBtn.textContent = "View Raw JSON";

    const payload = record.parsed_payload || {};
    const payloadEntries = Object.entries(payload);

    if (structuredContainer) {
        if (payloadEntries.length === 0) {
            structuredContainer.innerHTML = `<p class="text-xs text-slate-400 italic">No structured intermediate attributes present in this canonical record.</p>`;
        } else {
            structuredContainer.innerHTML = `
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
                    ${payloadEntries.map(([k, v]) => {
                        let displayVal = v;
                        let typeBadge = "STR";
                        if (typeof v === "object" && v !== null) {
                            displayVal = Array.isArray(v) 
                                ? v.map(item => (typeof item === "object" ? Object.values(item).join(" ") : item)).join(", ")
                                : Object.entries(v).map(([sk, sv]) => `${sk}: ${sv}`).join(", ");
                            typeBadge = Array.isArray(v) ? "ARR" : "OBJ";
                        } else if (typeof v === "number") {
                            typeBadge = "NUM";
                        } else if (typeof v === "boolean") {
                            typeBadge = "BOOL";
                        }

                        return `
                            <div class="p-2.5 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA] flex flex-col justify-between">
                                <div class="flex items-center justify-between mb-1">
                                    <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500 font-mono">${escapeHtml(k.replace(/_/g, " "))}</span>
                                    <span class="px-1.5 py-0.2 rounded text-[9px] font-bold font-mono bg-slate-200 text-slate-600">${typeBadge}</span>
                                </div>
                                <div class="text-xs font-medium text-slate-800 break-words font-sans">
                                    ${escapeHtml(String(displayVal))}
                                </div>
                            </div>
                        `;
                    }).join("")}
                </div>
            `;
        }
    }

    const payloadEl = document.getElementById("modal-parsed-payload");
    if (payloadEl) {
        payloadEl.textContent = JSON.stringify(payload, null, 2);
    }

    // Render Structured Validation Issues
    const errorsSec = document.getElementById("modal-errors-section");
    const errorsCards = document.getElementById("modal-errors-cards");
    const errors = record.validation_errors;

    if (errors && ((Array.isArray(errors) && errors.length > 0) || (typeof errors === "object" && Object.keys(errors).length > 0))) {
        if (errorsSec) errorsSec.classList.remove("hidden");
        if (errorsCards) {
            const errList = Array.isArray(errors) ? errors : Object.entries(errors).map(([k, v]) => ({ field: k, message: v }));
            errorsCards.innerHTML = errList.map((err, idx) => {
                const message = typeof err === "string" ? err : (err.message || err.error || JSON.stringify(err));
                const field = typeof err === "object" ? (err.field || err.loc || `Issue #${idx + 1}`) : `Error #${idx + 1}`;
                return `
                    <div class="p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs space-y-1">
                        <div class="flex items-center justify-between">
                            <span class="font-bold text-[#DE3449] flex items-center space-x-1">
                                <span class="w-1.5 h-1.5 rounded-full bg-[#DE3449]"></span>
                                <span>${escapeHtml(String(field))}</span>
                            </span>
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-[#DE3449]">CONFLICT</span>
                        </div>
                        <p class="text-rose-900 font-medium">${escapeHtml(String(message))}</p>
                    </div>
                `;
            }).join("");
        }
    } else {
        if (errorsSec) errorsSec.classList.add("hidden");
    }

    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
}

export function toggleModalRawPayload() {
    const rawPayloadWrapper = document.getElementById("modal-raw-payload-wrapper");
    const rawToggleBtn = document.getElementById("label-toggle-modal-raw");
    if (!rawPayloadWrapper || !rawToggleBtn) return;

    if (rawPayloadWrapper.classList.contains("hidden")) {
        rawPayloadWrapper.classList.remove("hidden");
        rawToggleBtn.textContent = "Hide Raw JSON";
    } else {
        rawPayloadWrapper.classList.add("hidden");
        rawToggleBtn.textContent = "View Raw JSON";
    }
}

export function closeRecordModal() {
    const modal = document.getElementById("record-modal");
    if (modal) modal.classList.add("hidden");
    document.body.style.overflow = "";
}


// =============================================================================
// 2. FHIR Bundle JSON Viewer Modal
// =============================================================================
export async function openFhirBundleModal(bundleId) {
    const modal = document.getElementById("fhir-bundle-modal");
    if (!modal) return;

    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";

    const titleEl = document.getElementById("fhir-modal-title");
    const jsonEl = document.getElementById("fhir-modal-json-content");

    titleEl.textContent = `HL7 FHIR R4 Bundle: ${bundleId}`;
    jsonEl.textContent = "Loading bundle payload from storage...";
    activeBundleJson = null;

    try {
        const bundle = await getBundleById(bundleId);
        activeBundleJson = bundle;
        jsonEl.textContent = JSON.stringify(bundle, null, 2);
    } catch (err) {
        jsonEl.textContent = `Error loading FHIR Bundle: ${err.message}`;
    }
}

export function closeFhirBundleModal() {
    const modal = document.getElementById("fhir-bundle-modal");
    if (modal) modal.classList.add("hidden");
    document.body.style.overflow = "";
    activeBundleJson = null;
}

export function downloadActiveFhirBundle() {
    if (!activeBundleJson) {
        showToast("warning", "No Bundle", "No active FHIR bundle loaded.");
        return;
    }
    const filename = `fhir-bundle-${activeBundleJson.id || "export"}.json`;
    const blob = new Blob([JSON.stringify(activeBundleJson, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast("success", "Download Started", `Downloaded ${filename}`);
}

export function copyActiveFhirBundle() {
    if (!activeBundleJson) return;
    navigator.clipboard.writeText(JSON.stringify(activeBundleJson, null, 2))
        .then(() => showToast("success", "Copied", "FHIR Bundle JSON copied to clipboard."))
        .catch(() => showToast("error", "Copy Failed", "Could not copy JSON to clipboard."));
}

// =============================================================================
// 3. FHIR Validation & Conformance Report Modal
// =============================================================================
export async function openFhirReportModal(bundleId) {
    const modal = document.getElementById("fhir-report-modal");
    if (!modal) return;

    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";

    const titleEl = document.getElementById("fhir-report-modal-title");
    const summaryCardsEl = document.getElementById("fhir-report-summary-cards");
    const issuesContainer = document.getElementById("fhir-report-issues-container");

    titleEl.textContent = `FHIR Conformance Report: ${bundleId}`;
    summaryCardsEl.innerHTML = `<div class="col-span-4 p-4 text-center text-slate-400">Loading validation report...</div>`;
    issuesContainer.innerHTML = "";

    try {
        const report = await getBundleReport(bundleId);

        const statusBadge = report.status === "VALID"
            ? `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">VALID CONFORMANCE</span>`
            : `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">${escapeHtml(report.status)}</span>`;

        summaryCardsEl.innerHTML = `
            <div class="bg-white p-3 rounded-xl border border-slate-200 text-center">
                <span class="text-[11px] text-slate-400 block font-medium">Resources</span>
                <span class="text-base font-bold text-slate-800">${report.total_resources || 0}</span>
            </div>
            <div class="bg-emerald-50/50 p-3 rounded-xl border border-emerald-200 text-center">
                <span class="text-[11px] text-emerald-600 block font-medium">Conforming</span>
                <span class="text-base font-bold text-emerald-700">${report.valid_resources || 0}</span>
            </div>
            <div class="bg-amber-50/50 p-3 rounded-xl border border-amber-200 text-center">
                <span class="text-[11px] text-amber-600 block font-medium">Warnings</span>
                <span class="text-base font-bold text-amber-700">${report.warning_count || 0}</span>
            </div>
            <div class="bg-rose-50/50 p-3 rounded-xl border border-rose-200 text-center">
                <span class="text-[11px] text-[#DE3449] block font-medium">Errors</span>
                <span class="text-base font-bold text-[#DE3449]">${report.error_count || 0}</span>
            </div>
        `;

        const issues = report.issues || [];
        if (issues.length === 0) {
            issuesContainer.innerHTML = `
                <div class="p-6 text-center text-xs text-emerald-600 bg-emerald-50/50 rounded-xl border border-emerald-200 flex items-center justify-center space-x-2">
                    ${iconSvg("check", "w-4 h-4 text-emerald-600")}
                    <span>All resources fully conform to HL7 FHIR R4 schema definitions and referential integrity constraints.</span>
                </div>
            `;
        } else {
            issuesContainer.innerHTML = issues.map(iss => {
                const isErr = iss.severity === "ERROR";
                const borderCol = isErr ? "border-rose-200 bg-rose-50/50" : "border-amber-200 bg-amber-50/50";
                const textCol = isErr ? "text-[#DE3449]" : "text-amber-700";
                return `
                    <div class="p-3.5 rounded-xl border ${borderCol} text-xs space-y-1">
                        <div class="flex items-center justify-between">
                            <span class="font-bold uppercase tracking-wider ${textCol} text-[10px]">${escapeHtml(iss.severity)}</span>
                            <span class="font-mono text-[10px] text-slate-500">${escapeHtml(iss.location || "Resource")}</span>
                        </div>
                        <p class="text-slate-800 font-medium">${escapeHtml(iss.description)}</p>
                        ${iss.recommendation ? `<p class="text-slate-500 text-[11px] italic">Recommendation: ${escapeHtml(iss.recommendation)}</p>` : ""}
                    </div>
                `;
            }).join("");
        }
    } catch (err) {
        summaryCardsEl.innerHTML = `<div class="col-span-4 p-4 text-center text-rose-600 text-xs">Error: ${escapeHtml(err.message)}</div>`;
    }
}

export function closeFhirReportModal() {
    const modal = document.getElementById("fhir-report-modal");
    if (modal) modal.classList.add("hidden");
    document.body.style.overflow = "";
}

// =============================================================================
// 4. Job Audit & Reconciliation Report Modal
// =============================================================================
export async function openJobReportModal(jobId) {
    const modal = document.getElementById("job-report-modal");
    if (!modal) return;

    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";

    const titleEl = document.getElementById("job-report-modal-title");
    const contentEl = document.getElementById("job-report-modal-content");

    titleEl.textContent = `Ingestion Audit Report: ${jobId}`;
    contentEl.innerHTML = `<div class="p-8 text-center text-slate-400 text-xs">Generating detailed audit & reconciliation report...</div>`;

    try {
        const report = await getJobReport(jobId);
        const j = report.job;

        const recSummaryHtml = Object.entries(report.reconciliation_summary || {}).map(([k, v]) => `
            <div class="p-2.5 bg-slate-50 rounded-lg border border-slate-200 text-center">
                <span class="text-[10px] uppercase font-bold text-slate-500 block">${escapeHtml(k)}</span>
                <span class="text-sm font-bold text-slate-800">${formatNumber(v)}</span>
            </div>
        `).join("");

        const domainSummaryHtml = Object.entries(report.domain_summary || {}).map(([k, v]) => `
            <div class="flex items-center justify-between py-1 text-xs border-b border-slate-100 last:border-0 font-mono">
                <span class="text-slate-600">${escapeHtml(k)}:</span>
                <span class="font-bold text-slate-800">${formatNumber(v)}</span>
            </div>
        `).join("");

        contentEl.innerHTML = `
            <div class="space-y-6">
                <!-- Summary Metrics -->
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div class="p-3 bg-white rounded-xl border border-slate-200 text-center">
                        <span class="text-slate-400 block text-[11px]">Total Records</span>
                        <span class="text-base font-bold text-slate-800">${formatNumber(j.total_records)}</span>
                    </div>
                    <div class="p-3 bg-emerald-50 rounded-xl border border-emerald-200 text-center">
                        <span class="text-emerald-600 block text-[11px]">Normalized</span>
                        <span class="text-base font-bold text-emerald-700">${formatNumber(j.successful_records)}</span>
                    </div>
                    <div class="p-3 bg-purple-50 rounded-xl border border-purple-200 text-center">
                        <span class="text-purple-600 block text-[11px]">Duplicates</span>
                        <span class="text-base font-bold text-purple-700">${formatNumber(j.duplicate_records)}</span>
                    </div>
                    <div class="p-3 bg-rose-50 rounded-xl border border-rose-200 text-center">
                        <span class="text-[#DE3449] block text-[11px]">Rejected</span>
                        <span class="text-base font-bold text-[#DE3449]">${formatNumber(j.rejected_records)}</span>
                    </div>
                </div>

                <!-- Reconciliation Breakdown -->
                <div class="bg-white p-4 rounded-xl border border-slate-200 space-y-3">
                    <h5 class="text-xs font-bold text-slate-700 uppercase tracking-wider">Patient Identity Reconciliation Summary</h5>
                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        ${recSummaryHtml || '<p class="text-xs text-slate-400">None</p>'}
                    </div>
                </div>

                <!-- Domain Records Breakdown -->
                <div class="bg-white p-4 rounded-xl border border-slate-200 space-y-3">
                    <h5 class="text-xs font-bold text-slate-700 uppercase tracking-wider">Domain Records Ingested</h5>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
                        ${domainSummaryHtml || '<p class="text-xs text-slate-400">No domain records</p>'}
                    </div>
                </div>

                <!-- Referential Integrity -->
                ${report.referential_integrity ? `
                    <div class="bg-white p-4 rounded-xl border border-slate-200 space-y-2 text-xs">
                        <h5 class="text-xs font-bold text-slate-700 uppercase tracking-wider">Referential Integrity Audit</h5>
                        <div class="flex items-center space-x-3">
                            <span class="px-2 py-0.5 rounded text-[11px] font-bold ${getStatusBadgeClass(report.referential_integrity.referential_integrity_status)}">
                                ${escapeHtml(report.referential_integrity.referential_integrity_status)}
                            </span>
                            <span class="text-slate-500">Evaluated ${formatNumber(report.referential_integrity.total_records_evaluated)} records</span>
                        </div>
                    </div>
                ` : ""}
            </div>
        `;
    } catch (err) {
        contentEl.innerHTML = `<div class="p-8 text-center text-xs text-rose-600">Failed to load audit report: ${escapeHtml(err.message)}</div>`;
    }
}

export function closeJobReportModal() {
    const modal = document.getElementById("job-report-modal");
    if (modal) modal.classList.add("hidden");
    document.body.style.overflow = "";
}

// Window bindings
window.openRecordModal = openRecordModal;
window.closeRecordModal = closeRecordModal;
window.toggleModalRawPayload = toggleModalRawPayload;
window.openFhirBundleModal = openFhirBundleModal;
window.closeFhirBundleModal = closeFhirBundleModal;
window.downloadActiveFhirBundle = downloadActiveFhirBundle;
window.copyActiveFhirBundle = copyActiveFhirBundle;
window.openFhirReportModal = openFhirReportModal;
window.closeFhirReportModal = closeFhirReportModal;
window.openJobReportModal = openJobReportModal;
window.closeJobReportModal = closeJobReportModal;

