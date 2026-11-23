/**
 * Canonical Records & Audit Explorer Component.
 * Inspects parsed intermediate representations, dosage preservation, and append-only audit trails.
 */
import { getJobRecords, getJobReport, listIngestionJobs } from "../api/ingestion.js";
import { escapeHtml, formatDate, formatNumber, getStatusBadgeClass, formatClinicalSummaryPreview } from "../utils/formatters.js";

import { iconSvg } from "../utils/icons.js";
import { openRecordModal } from "./modals.js";
import { showToast } from "./toast.js";

let currentExplorerJobId = null;
let currentExplorerPage = 1;
let explorerPageSize = 25;
let totalExplorerPages = 1;
let currentExplorerStatusFilter = "";
let cachedRecordsMap = new Map();

export async function loadRecordsForJob(jobId, page = 1) {
    currentExplorerJobId = jobId;
    currentExplorerPage = page;
    const tbody = document.getElementById("records-table-body");
    const paginationInfo = document.getElementById("records-pagination-info");
    const prevBtn = document.getElementById("records-prev-page-btn");
    const nextBtn = document.getElementById("records-next-page-btn");

    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="p-8 text-center text-slate-400 text-xs">
                    ${iconSvg("spinner", "w-5 h-5 mx-auto text-[#389B98] mb-2")}
                    <span>Loading canonical clinical records...</span>
                </td>
            </tr>
        `;
    }

    try {
        const data = await getJobRecords(jobId, {
            page: currentExplorerPage,
            pageSize: explorerPageSize,
            status: currentExplorerStatusFilter,
        });

        totalExplorerPages = data.total_pages || 1;
        cachedRecordsMap.clear();

        if (paginationInfo) {
            const start = data.total > 0 ? (currentExplorerPage - 1) * explorerPageSize + 1 : 0;
            const end = Math.min(currentExplorerPage * explorerPageSize, data.total);
            paginationInfo.textContent = `Showing records ${start}-${end} of ${formatNumber(data.total)}`;
        }

        if (prevBtn) prevBtn.disabled = currentExplorerPage <= 1;
        if (nextBtn) nextBtn.disabled = currentExplorerPage >= totalExplorerPages;

        if (!data.items || data.items.length === 0) {
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="p-10 text-center text-slate-400 text-xs">
                            No records found for job ${jobId} with status filter '${currentExplorerStatusFilter || 'ALL'}'.
                        </td>
                    </tr>
                `;
            }
            return;
        }

        const rowsHtml = data.items.map((rec, idx) => {
            cachedRecordsMap.set(rec.id, rec);
            const badgeClass = getStatusBadgeClass(rec.status);
            const previewText = formatClinicalSummaryPreview(rec);

            return `
                <tr class="hover:bg-slate-50 transition-colors cursor-pointer" onclick="openRecordDeepDive('${escapeHtml(rec.id)}')">
                    <td class="px-4 py-3 font-mono font-bold text-xs text-[#389B98] truncate max-w-[140px]">${escapeHtml(rec.id)}</td>
                    <td class="px-4 py-3 font-mono text-slate-700">${escapeHtml(rec.patient_id || "Unassigned")}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                            ${escapeHtml(rec.status)}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-slate-500 font-mono text-[11px]">${formatDate(rec.record_date || rec.created_at)}</td>
                    <td class="px-4 py-3 text-slate-600 font-mono text-[11px] truncate max-w-xs">${escapeHtml(previewText)}</td>
                    <td class="px-4 py-3 text-right">
                        <button class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-[#389B98]/10 text-[#389B98] hover:bg-[#389B98] hover:text-white transition-colors">
                            Inspect
                        </button>
                    </td>
                </tr>
            `;
        }).join("");

        if (tbody) {
            tbody.innerHTML = rowsHtml;
        }

        // Also load audit trail for this job
        loadAuditTrailForJob(jobId);
    } catch (err) {
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="p-8 text-center text-rose-600 text-xs">
                        Error loading records: ${escapeHtml(err.message || "Network or server error")}
                    </td>
                </tr>
            `;
        }
    }
}

export async function loadInitialExplorerData() {
    if (currentExplorerJobId) {
        loadRecordsForJob(currentExplorerJobId, 1);
        return;
    }
    // Fetch latest job to auto-populate explorer
    try {
        const jobs = await listIngestionJobs({ page: 1, pageSize: 1 });
        if (jobs.items && jobs.items.length > 0) {
            loadRecordsForJob(jobs.items[0].job_id, 1);
        } else {
            const tbody = document.getElementById("records-table-body");
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="p-10 text-center text-slate-400 text-xs">
                            No ingestion jobs exist yet. Ingest an EHR file or direct JSON payload to begin inspecting canonical records.
                        </td>
                    </tr>
                `;
            }
        }
    } catch {
        // Ignore fallback errors
    }
}

async function loadAuditTrailForJob(jobId) {
    const auditTbody = document.getElementById("audit-table-body");
    const countBadge = document.getElementById("audit-count-badge");
    if (!auditTbody) return;

    try {
        const report = await getJobReport(jobId);
        const audits = report.recent_audit_events || [];

        if (countBadge) {
            countBadge.textContent = `${audits.length} Audits`;
        }

        if (audits.length === 0) {
            auditTbody.innerHTML = `
                <tr>
                    <td colspan="6" class="p-6 text-center text-slate-400 text-xs">
                        No audit events recorded for this job.
                    </td>
                </tr>
            `;
            return;
        }

        const rowsHtml = audits.map(a => `
            <tr class="hover:bg-slate-50 transition-colors font-mono text-[11px]">
                <td class="px-3.5 py-2 font-bold text-slate-700">${escapeHtml(a.field_name || "-")}</td>
                <td class="px-3.5 py-2 text-slate-500">${escapeHtml(a.original_value || "-")}</td>
                <td class="px-3.5 py-2 text-emerald-600 font-semibold">${escapeHtml(a.normalized_value || "-")}</td>
                <td class="px-3.5 py-2 text-slate-600">${escapeHtml(a.transformation_applied || "-")}</td>
                <td class="px-3.5 py-2 text-slate-500">${escapeHtml(a.component || "-")}</td>
                <td class="px-3.5 py-2 text-slate-400">${escapeHtml(a.reason || "-")}</td>
            </tr>
        `).join("");

        auditTbody.innerHTML = rowsHtml;
    } catch {
        auditTbody.innerHTML = `<tr><td colspan="6" class="p-4 text-center text-slate-400 text-xs">Audit log unavailable</td></tr>`;
    }
}

export function openRecordDeepDive(recordId) {
    const record = cachedRecordsMap.get(recordId);
    if (record) {
        openRecordModal(record);
    }
}

export function handleExplorerStatusFilterChange() {
    const select = document.getElementById("explorer-status-filter");
    currentExplorerStatusFilter = select ? select.value : "";
    if (currentExplorerJobId) {
        loadRecordsForJob(currentExplorerJobId, 1);
    }
}

export function changeExplorerRecordPage(delta) {
    const target = currentExplorerPage + delta;
    if (target >= 1 && target <= totalExplorerPages && currentExplorerJobId) {
        loadRecordsForJob(currentExplorerJobId, target);
    }
}

// Window bindings
window.loadRecordsForJob = loadRecordsForJob;
window.loadInitialExplorerData = loadInitialExplorerData;
window.openRecordDeepDive = openRecordDeepDive;
window.handleExplorerStatusFilterChange = handleExplorerStatusFilterChange;
window.changeExplorerRecordPage = changeExplorerRecordPage;
