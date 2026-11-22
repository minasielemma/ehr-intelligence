/**
 * Ingestion Jobs Lifecycle & Management Component.
 * Lists all historical and active batch ingestion jobs with real-time status.
 */
import { listIngestionJobs, getJobStatus, getJobReport, getJobRecords } from "../api/ingestion.js";
import { escapeHtml, formatDate, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { openJobReportModal } from "./modals.js";
import { showToast } from "./toast.js";

let currentJobPage = 1;
let jobPageSize = 15;
let totalJobPages = 1;
let currentJobStatusFilter = "";
let activeSelectedJobId = null;
let activePollingInterval = null;

export async function loadIngestionJobsList(page = 1) {
    currentJobPage = page;
    const tbody = document.getElementById("jobs-table-body");
    const paginationInfo = document.getElementById("jobs-pagination-info");
    const prevBtn = document.getElementById("jobs-prev-page-btn");
    const nextBtn = document.getElementById("jobs-next-page-btn");

    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="p-8 text-center text-slate-400 text-xs">
                    ${iconSvg("spinner", "w-5 h-5 mx-auto text-[#389B98] mb-2")}
                    <span>Loading ingestion jobs...</span>
                </td>
            </tr>
        `;
    }

    try {
        const data = await listIngestionJobs({
            page: currentJobPage,
            pageSize: jobPageSize,
            status: currentJobStatusFilter,
        });

        totalJobPages = data.total_pages || 1;

        if (paginationInfo) {
            const start = data.total > 0 ? (currentJobPage - 1) * jobPageSize + 1 : 0;
            const end = Math.min(currentJobPage * jobPageSize, data.total);
            paginationInfo.textContent = `Showing ${start}-${end} of ${formatNumber(data.total)} jobs`;
        }

        if (prevBtn) prevBtn.disabled = currentJobPage <= 1;
        if (nextBtn) nextBtn.disabled = currentJobPage >= totalJobPages;

        if (!data.items || data.items.length === 0) {
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" class="p-10 text-center text-slate-400 text-xs">
                            No ingestion jobs found.
                        </td>
                    </tr>
                `;
            }
            return;
        }

        const rowsHtml = data.items.map(job => {
            const badgeClass = getStatusBadgeClass(job.status);
            const durationStr = job.duration_seconds !== null ? `${job.duration_seconds}s` : "-";
            const isSelected = activeSelectedJobId === job.job_id;

            return `
                <tr
                    class="hover:bg-slate-50 transition-colors cursor-pointer ${isSelected ? 'bg-[#389B98]/5 border-l-4 border-[#389B98]' : ''}"
                    onclick="viewSpecificJob('${escapeHtml(job.job_id)}')"
                >
                    <td class="px-4 py-3 font-mono font-bold text-xs text-[#389B98]">${escapeHtml(job.job_id)}</td>
                    <td class="px-4 py-3 font-medium text-slate-800">${escapeHtml(job.source_system)}</td>
                    <td class="px-4 py-3 font-mono text-[11px] uppercase text-slate-500">${escapeHtml(job.source_format)}</td>
                    <td class="px-4 py-3 text-right font-mono font-bold text-slate-800">${formatNumber(job.total_records)}</td>
                    <td class="px-4 py-3 text-right font-mono text-emerald-600 font-bold">${formatNumber(job.successful_records)}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                            ${escapeHtml(job.status)}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-right font-mono text-slate-500 text-[11px]">${formatDate(job.created_at)}</td>
                </tr>
            `;
        }).join("");

        if (tbody) {
            tbody.innerHTML = rowsHtml;
        }

        // Auto select first job if none selected
        if (!activeSelectedJobId && data.items.length > 0) {
            updateJobDetailsCard(data.items[0]);
        }
    } catch (err) {
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="p-8 text-center text-rose-600 text-xs">
                        Failed to load jobs: ${escapeHtml(err.message)}
                    </td>
                </tr>
            `;
        }
    }
}

export async function viewSpecificJob(jobId) {
    activeSelectedJobId = jobId;
    try {
        const job = await getJobStatus(jobId);
        updateJobDetailsCard(job);

        // Highlight selected row
        loadIngestionJobsList(currentJobPage);

        // If job is processing, poll for completion
        if (job.status === "PROCESSING" || job.status === "PENDING") {
            startJobPolling(jobId);
        } else {
            stopJobPolling();
        }
    } catch (err) {
        showToast("error", "Job Lookup Error", err.message || "Failed to load job details");
    }
}

function updateJobDetailsCard(job) {
    if (!job) return;
    activeSelectedJobId = job.job_id;

    const idEl = document.getElementById("card-job-id");
    const badgeEl = document.getElementById("card-job-status-badge");
    const formatEl = document.getElementById("card-job-format");
    const systemEl = document.getElementById("card-job-system");
    const durationEl = document.getElementById("card-job-duration");

    const totalEl = document.getElementById("metric-total");
    const successEl = document.getElementById("metric-success");
    const dupEl = document.getElementById("metric-duplicates");
    const confEl = document.getElementById("metric-conflicts");
    const warnEl = document.getElementById("metric-warnings");
    const rejEl = document.getElementById("metric-rejected");

    if (idEl) idEl.textContent = job.job_id;
    if (badgeEl) {
        badgeEl.className = `px-2.5 py-0.5 rounded-full text-xs font-semibold border ${getStatusBadgeClass(job.status)}`;
        badgeEl.textContent = job.status;
    }
    if (formatEl) formatEl.textContent = job.source_format.toUpperCase();
    if (systemEl) systemEl.textContent = job.source_system;
    if (durationEl) durationEl.textContent = job.duration_seconds !== null ? `${job.duration_seconds}s` : "-";

    if (totalEl) totalEl.textContent = formatNumber(job.total_records);
    if (successEl) successEl.textContent = formatNumber(job.successful_records);
    if (dupEl) dupEl.textContent = formatNumber(job.duplicate_records);
    if (confEl) confEl.textContent = formatNumber(job.conflict_records);
    if (warnEl) warnEl.textContent = formatNumber(job.warning_records);
    if (rejEl) rejEl.textContent = formatNumber(job.rejected_records);
}

function startJobPolling(jobId) {
    stopJobPolling();
    activePollingInterval = setInterval(async () => {
        try {
            const job = await getJobStatus(jobId);
            updateJobDetailsCard(job);
            if (job.status !== "PROCESSING" && job.status !== "PENDING") {
                stopJobPolling();
                loadIngestionJobsList(currentJobPage);
                showToast("success", "Job Completed", `Batch job ${jobId} finished with status ${job.status}`);
            }
        } catch {
            stopJobPolling();
        }
    }, 2500);
}

function stopJobPolling() {
    if (activePollingInterval) {
        clearInterval(activePollingInterval);
        activePollingInterval = null;
    }
}

export function handleJobFilterChange() {
    const select = document.getElementById("jobs-status-filter");
    currentJobStatusFilter = select ? select.value : "";
    loadIngestionJobsList(1);
}

export function changeJobPage(delta) {
    const target = currentJobPage + delta;
    if (target >= 1 && target <= totalJobPages) {
        loadIngestionJobsList(target);
    }
}

export function viewCurrentJobReport() {
    if (!activeSelectedJobId) {
        showToast("warning", "Select Job", "Please select a job first.");
        return;
    }
    openJobReportModal(activeSelectedJobId);
}

export function viewCurrentJobRecords() {
    if (!activeSelectedJobId) {
        showToast("warning", "Select Job", "Please select a job first.");
        return;
    }
    // Switch to explorer tab and filter by this job
    window.switchMainTab("explorer");
    window.loadRecordsForJob(activeSelectedJobId);
}

export function lookupJobByIdInput() {
    const input = document.getElementById("lookup-job-id");
    const jobId = input ? input.value.trim() : "";
    if (!jobId) {
        showToast("warning", "Input Required", "Enter an ingestion job UUID.");
        return;
    }
    viewSpecificJob(jobId);
}

// Window bindings
window.loadIngestionJobsList = loadIngestionJobsList;
window.viewSpecificJob = viewSpecificJob;
window.handleJobFilterChange = handleJobFilterChange;
window.changeJobPage = changeJobPage;
window.viewCurrentJobReport = viewCurrentJobReport;
window.viewCurrentJobRecords = viewCurrentJobRecords;
window.lookupJobByIdInput = lookupJobByIdInput;
