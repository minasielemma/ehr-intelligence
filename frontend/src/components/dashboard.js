/**
 * Clinical Operations Overview Dashboard Component (Phase 4).
 * Fully API-driven from GET /api/v1/dashboard/stats and live system health.
 */
import { getDashboardStats, getSystemHealth } from "../api/dashboard.js";
import { escapeHtml, formatDate, formatDateShort, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { openPatientDrawer } from "./drawer.js";
import { showToast } from "./toast.js";

let autoRefreshInterval = null;
let isAutoRefreshEnabled = false;
let lastStatsData = null;

export async function loadDashboardOverview(force = false) {
    const container = document.getElementById("tab-content-dashboard");
    if (!container) return;

    if (!lastStatsData || force) {
        renderDashboardSkeleton(container);
    }

    try {
        const stats = await getDashboardStats();
        lastStatsData = stats;
        renderDashboardContent(container, stats);
    } catch (err) {
        renderDashboardError(container, err.message || "Failed to load dashboard statistics");
    }
}

function renderDashboardSkeleton(container) {
    container.innerHTML = `
        <div class="space-y-6">
            <!-- Header Skeleton -->
            <div class="flex items-center justify-between">
                <div class="space-y-1">
                    <div class="h-6 w-48 bg-slate-200 rounded animate-pulse"></div>
                    <div class="h-4 w-72 bg-slate-100 rounded animate-pulse"></div>
                </div>
                <div class="h-9 w-32 bg-slate-200 rounded-xl animate-pulse"></div>
            </div>

            <!-- KPI Cards Skeleton -->
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                ${Array(6).fill(0).map(() => `
                    <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm space-y-2">
                        <div class="h-3 w-20 bg-slate-100 rounded animate-pulse"></div>
                        <div class="h-7 w-16 bg-slate-200 rounded animate-pulse"></div>
                        <div class="h-2 w-24 bg-slate-100 rounded animate-pulse"></div>
                    </div>
                `).join("")}
            </div>

            <!-- Main Grid Skeleton -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="lg:col-span-2 bg-white rounded-2xl border border-slate-200 p-6 h-80 animate-pulse bg-slate-50"></div>
                <div class="bg-white rounded-2xl border border-slate-200 p-6 h-80 animate-pulse bg-slate-50"></div>
            </div>
        </div>
    `;
}

function renderDashboardError(container, message) {
    container.innerHTML = `
        <div class="bg-white border border-[#E5EAEA] rounded-2xl p-12 text-center space-y-4 shadow-sm">
            <div class="w-12 h-12 rounded-full bg-rose-50 text-[#DE3449] flex items-center justify-center mx-auto">
                ${iconSvg("close", "w-6 h-6")}
            </div>
            <div class="space-y-1">
                <h3 class="text-sm font-bold text-slate-800">Failed to Load Dashboard Analytics</h3>
                <p class="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">${escapeHtml(message)}</p>
            </div>
            <button
                onclick="loadDashboardOverview(true)"
                class="px-4 py-2 bg-[#389B98] hover:bg-[#287F7D] text-white text-xs font-semibold rounded-xl shadow-sm transition-colors inline-flex items-center space-x-1.5"
            >
                ${iconSvg("refresh", "w-3.5 h-3.5")}
                <span>Retry Loading</span>
            </button>
        </div>
    `;
}

function renderDashboardContent(container, data) {
    // KPI Cards data
    const kpis = [
        {
            title: "Total Patients",
            value: formatNumber(data.total_patients),
            desc: "Canonical Reconciled",
            color: "text-[#389B98]",
            bg: "bg-[#389B98]/10",
            icon: "patients",
        },
        {
            title: "Clinical Records",
            value: formatNumber(data.total_records),
            desc: "Cleaned & Ingested",
            color: "text-blue-600",
            bg: "bg-blue-50",
            icon: "explorer",
        },
        {
            title: "FHIR R4 Bundles",
            value: formatNumber(data.total_fhir_bundles),
            desc: "Validated Collections",
            color: "text-indigo-600",
            bg: "bg-indigo-50",
            icon: "fhir",
        },
        {
            title: "Normalized Resources",
            value: formatNumber(data.total_fhir_resources),
            desc: "Longitudinal Graph",
            color: "text-purple-600",
            bg: "bg-purple-50",
            icon: "fhir",
        },
        {
            title: "Semantic Vectors",
            value: formatNumber(data.active_vectors),
            desc: "ChromaDB Embeddings",
            color: "text-teal-600",
            bg: "bg-teal-50",
            icon: "search",
        },
        {
            title: "Ingestion Jobs",
            value: formatNumber(data.total_jobs),
            desc: "Executed Batches",
            color: "text-slate-700",
            bg: "bg-slate-100",
            icon: "jobs",
        },
    ];

    const kpiCardsHtml = kpis.map(kpi => `
        <div class="bg-white rounded-2xl border border-[#E5EAEA] p-4 shadow-sm hover:border-[#389B98]/40 transition-colors">
            <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider text-[11px]">${escapeHtml(kpi.title)}</span>
                <div class="p-1.5 rounded-lg ${kpi.bg} ${kpi.color}">
                    ${iconSvg(kpi.icon, "w-4 h-4")}
                </div>
            </div>
            <div class="text-2xl font-bold text-slate-800 mt-2 tracking-tight">${kpi.value}</div>
            <div class="text-[11px] text-slate-400 mt-1">${escapeHtml(kpi.desc)}</div>
        </div>
    `).join("");

    // Domain distribution bars
    const domainDistributionHtml = (data.domain_distribution || []).map(d => `
        <div class="space-y-1">
            <div class="flex items-center justify-between text-xs">
                <span class="font-medium text-slate-700">${escapeHtml(d.name)}</span>
                <span class="font-mono text-slate-500 font-bold">${formatNumber(d.count)} <span class="font-normal text-slate-400 text-[10px]">(${d.percentage}%)</span></span>
            </div>
            <div class="w-full bg-[#F7F9FA] rounded-full h-2 overflow-hidden border border-[#E5EAEA]">
                <div class="bg-[#389B98] h-full rounded-full transition-all duration-500" style="width: ${Math.min(d.percentage, 100)}%"></div>
            </div>
        </div>
    `).join("");

    // Recent Jobs Table rows
    const recentJobsRows = (data.recent_jobs || []).map(job => {
        const badgeClass = getStatusBadgeClass(job.status);
        const durationStr = job.duration_seconds !== null ? `${job.duration_seconds}s` : "-";
        return `
            <tr class="hover:bg-slate-50/70 transition-colors cursor-pointer" onclick="viewSpecificJob('${escapeHtml(job.id)}')">
                <td class="px-3.5 py-2.5 font-mono text-[11px] text-[#389B98] font-semibold truncate max-w-[120px]" title="${escapeHtml(job.id)}">
                    ${escapeHtml(job.id.substring(0, 8))}...
                </td>
                <td class="px-3.5 py-2.5 text-slate-700 font-medium">${escapeHtml(job.source_system)}</td>
                <td class="px-3.5 py-2.5 font-mono text-slate-500 uppercase text-[10px]">${escapeHtml(job.source_format)}</td>
                <td class="px-3.5 py-2.5 text-right font-mono font-bold text-slate-800">${formatNumber(job.total_records)}</td>
                <td class="px-3.5 py-2.5 text-center">
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                        ${escapeHtml(job.status)}
                    </span>
                </td>
                <td class="px-3.5 py-2.5 text-right font-mono text-slate-400 text-[10px]">${durationStr}</td>
            </tr>
        `;
    }).join("");

    // Recent Patients Table rows
    const recentPatientsRows = (data.recent_patients || []).map(p => {
        const fullName = `${p.first_name || ""} ${p.last_name || ""}`.trim() || "Anonymous";
        const badgeClass = getStatusBadgeClass(p.reconciliation_status);
        return `
            <tr class="hover:bg-slate-50/70 transition-colors cursor-pointer" onclick="openPatientDrawer('${escapeHtml(p.id)}')">
                <td class="px-3.5 py-2.5 font-semibold text-slate-800">${escapeHtml(fullName)}</td>
                <td class="px-3.5 py-2.5 font-mono text-xs text-[#389B98] font-bold">${escapeHtml(p.mrn)}</td>
                <td class="px-3.5 py-2.5 capitalize text-slate-600">${escapeHtml(p.gender || "Unknown")}</td>
                <td class="px-3.5 py-2.5 text-slate-500 font-mono text-[11px]">${escapeHtml(p.date_of_birth || "-")}</td>
                <td class="px-3.5 py-2.5 text-center">
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                        ${escapeHtml(p.reconciliation_status)}
                    </span>
                </td>
                <td class="px-3.5 py-2.5 text-right">
                    <button class="px-2.5 py-1 text-[11px] font-medium text-[#389B98] hover:text-white hover:bg-[#389B98] rounded-lg transition-colors border border-[#389B98]/30">
                        View
                    </button>
                </td>
            </tr>
        `;
    }).join("");

    container.innerHTML = `
        <div class="space-y-6">
            <!-- Header Bar -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-5 rounded-2xl border border-[#E5EAEA] shadow-sm">
                <div class="space-y-1">
                    <div class="flex items-center space-x-2">
                        <span class="w-2.5 h-2.5 rounded-full bg-[#389B98]"></span>
                        <h2 class="text-base font-bold text-slate-800 tracking-tight">Clinical Operations Command Center</h2>
                    </div>
                    <p class="text-xs text-slate-500">
                        Real-time clinical intelligence, FHIR R4 graph distribution, vector retrieval state, and patient identity reconciliation.
                    </p>
                </div>

                <div class="flex items-center space-x-3 text-xs">
                    <button
                        onclick="toggleAutoRefresh()"
                        id="btn-auto-refresh"
                        class="px-3 py-1.5 rounded-xl border border-[#E5EAEA] bg-[#F7F9FA] hover:bg-slate-100 text-slate-700 transition-colors flex items-center space-x-1.5 font-medium"
                    >
                        <span class="w-2 h-2 rounded-full ${isAutoRefreshEnabled ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}"></span>
                        <span>Auto-refresh ${isAutoRefreshEnabled ? 'ON' : 'OFF'}</span>
                    </button>
                    <button
                        onclick="loadDashboardOverview(true)"
                        class="px-3.5 py-1.5 bg-[#389B98] hover:bg-[#287F7D] text-white font-semibold rounded-xl transition-all shadow-sm flex items-center space-x-1.5"
                    >
                        ${iconSvg("refresh", "w-3.5 h-3.5")}
                        <span>Refresh Data</span>
                    </button>
                </div>
            </div>

            <!-- KPI Metric Cards Grid -->
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
                ${kpiCardsHtml}
            </div>

            <!-- Middle Section: Domain Breakdown & Recent Jobs -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Domain Breakdown Card -->
                <div class="bg-white rounded-2xl border border-[#E5EAEA] p-5 shadow-sm space-y-4">
                    <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                        <div class="flex items-center space-x-2">
                            <span class="p-1 rounded bg-[#389B98]/10 text-[#389B98]">
                                ${iconSvg("fhir", "w-4 h-4")}
                            </span>
                            <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Clinical Domain Distribution</h3>
                        </div>
                        <span class="text-[11px] text-slate-400 font-mono">${(data.domain_distribution || []).length} Domains</span>
                    </div>

                    <div class="space-y-3 max-h-80 overflow-y-auto pr-1">
                        ${domainDistributionHtml || '<p class="text-xs text-slate-400">No domain records found.</p>'}
                    </div>
                </div>

                <!-- Recent Ingestion Jobs Card -->
                <div class="lg:col-span-2 bg-white rounded-2xl border border-[#E5EAEA] p-5 shadow-sm space-y-4">
                    <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                        <div class="flex items-center space-x-2">
                            <span class="p-1 rounded bg-blue-50 text-blue-600">
                                ${iconSvg("jobs", "w-4 h-4")}
                            </span>
                            <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Recent Ingestion Batches</h3>
                        </div>
                        <button onclick="switchMainTab('jobs')" class="text-xs font-semibold text-[#389B98] hover:underline flex items-center space-x-1">
                            <span>View All Jobs</span>
                            <span>&rarr;</span>
                        </button>
                    </div>

                    <div class="overflow-x-auto max-h-80">
                        <table class="w-full text-left text-xs">
                            <thead class="bg-[#F7F9FA] text-slate-400 uppercase tracking-wider font-semibold border-b border-[#E5EAEA] text-[10px] sticky top-0">
                                <tr>
                                    <th class="px-3.5 py-2">Job ID</th>
                                    <th class="px-3.5 py-2">System</th>
                                    <th class="px-3.5 py-2">Format</th>
                                    <th class="px-3.5 py-2 text-right">Records</th>
                                    <th class="px-3.5 py-2 text-center">Status</th>
                                    <th class="px-3.5 py-2 text-right">Duration</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-100">
                                ${recentJobsRows || '<tr><td colspan="6" class="p-6 text-center text-slate-400">No jobs recorded yet.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Bottom Section: Recent Canonical Patients -->
            <div class="bg-white rounded-2xl border border-[#E5EAEA] p-5 shadow-sm space-y-4">
                <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div class="flex items-center space-x-2">
                        <span class="p-1 rounded bg-emerald-50 text-emerald-600">
                            ${iconSvg("patients", "w-4 h-4")}
                        </span>
                        <h3 class="text-xs font-bold text-slate-800 uppercase tracking-wider">Recently Ingested & Reconciled Patients</h3>
                    </div>
                    <button onclick="switchMainTab('patients')" class="text-xs font-semibold text-[#389B98] hover:underline flex items-center space-x-1">
                        <span>Open Patient Directory</span>
                        <span>&rarr;</span>
                    </button>
                </div>

                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs">
                        <thead class="bg-[#F7F9FA] text-slate-400 uppercase tracking-wider font-semibold border-b border-[#E5EAEA] text-[10px]">
                            <tr>
                                <th class="px-3.5 py-2">Patient Name</th>
                                <th class="px-3.5 py-2">MRN</th>
                                <th class="px-3.5 py-2">Gender</th>
                                <th class="px-3.5 py-2">Date of Birth</th>
                                <th class="px-3.5 py-2 text-center">Status</th>
                                <th class="px-3.5 py-2 text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            ${recentPatientsRows || '<tr><td colspan="6" class="p-6 text-center text-slate-400">No patients recorded yet.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

export function toggleAutoRefresh() {
    isAutoRefreshEnabled = !isAutoRefreshEnabled;
    if (isAutoRefreshEnabled) {
        autoRefreshInterval = setInterval(() => {
            loadDashboardOverview(false);
        }, 30000); // 30s auto-refresh
        showToast("info", "Auto-refresh Enabled", "Dashboard will refresh every 30 seconds.");
    } else {
        if (autoRefreshInterval) clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
        showToast("info", "Auto-refresh Disabled", "Dashboard auto-refresh stopped.");
    }
    const btn = document.getElementById("btn-auto-refresh");
    if (btn) {
        btn.innerHTML = `
            <span class="w-2 h-2 rounded-full ${isAutoRefreshEnabled ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}"></span>
            <span>Auto-refresh ${isAutoRefreshEnabled ? 'ON' : 'OFF'}</span>
        `;
    }
}

// Window bindings
window.loadDashboardOverview = loadDashboardOverview;
window.toggleAutoRefresh = toggleAutoRefresh;
