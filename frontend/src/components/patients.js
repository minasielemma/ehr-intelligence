/**
 * Patient Directory & Management Component.
 * Allows searching, filtering, and paginating canonical patients.
 */
import { listPatients } from "../api/patients.js";
import { escapeHtml, formatDateShort, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { openPatientDrawer } from "./drawer.js";
import { showToast } from "./toast.js";

let currentPage = 1;
let pageSize = 20;
let totalPages = 1;
let currentSearchQuery = "";
let currentStatusFilter = "";
let currentSystemFilter = "";

export async function loadPatientsDirectory(page = 1) {
    currentPage = page;
    const container = document.getElementById("tab-content-patients");
    const tbody = document.getElementById("patients-table-body");
    const paginationInfo = document.getElementById("patients-pagination-info");
    const prevBtn = document.getElementById("patients-prev-page-btn");
    const nextBtn = document.getElementById("patients-next-page-btn");

    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="p-8 text-center text-slate-400 text-xs">
                    ${iconSvg("spinner", "w-5 h-5 mx-auto text-[#389B98] mb-2")}
                    <span>Loading patient directory...</span>
                </td>
            </tr>
        `;
    }

    try {
        const data = await listPatients({
            page: currentPage,
            pageSize,
            query: currentSearchQuery,
            sourceSystem: currentSystemFilter,
            reconciliationStatus: currentStatusFilter,
        });

        totalPages = data.total_pages || 1;

        if (paginationInfo) {
            const start = data.total > 0 ? (currentPage - 1) * pageSize + 1 : 0;
            const end = Math.min(currentPage * pageSize, data.total);
            paginationInfo.textContent = `Showing ${start}-${end} of ${formatNumber(data.total)} patients`;
        }

        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;

        if (!data.items || data.items.length === 0) {
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="p-10 text-center text-slate-400 text-xs">
                            No patients found matching the selected query and filters.
                        </td>
                    </tr>
                `;
            }
            return;
        }

        const rowsHtml = data.items.map(p => {
            const fullName = `${p.first_name || ""} ${p.last_name || ""}`.trim() || "Anonymous";
            const badgeClass = getStatusBadgeClass(p.reconciliation_status);
            const summaryBadge = p.has_summary
                ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">AI Summary</span>`
                : `<span class="text-[10px] text-slate-400">None</span>`;

            return `
                <tr class="hover:bg-slate-50 transition-colors cursor-pointer" onclick="openPatientDrawer('${escapeHtml(p.id)}')">
                    <td class="px-4 py-3 font-semibold text-slate-800">${escapeHtml(fullName)}</td>
                    <td class="px-4 py-3 font-mono font-bold text-xs text-[#389B98]">${escapeHtml(p.mrn)}</td>
                    <td class="px-4 py-3 capitalize text-slate-600">${escapeHtml(p.gender || "Unknown")}</td>
                    <td class="px-4 py-3 text-slate-500 font-mono text-[11px]">${escapeHtml(p.date_of_birth || "-")}</td>
                    <td class="px-4 py-3 text-slate-600">${escapeHtml(p.source_system)}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                            ${escapeHtml(p.reconciliation_status)}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-center">${summaryBadge}</td>
                    <td class="px-4 py-3 text-right">
                        <button class="px-3 py-1 bg-[#389B98]/10 hover:bg-[#389B98] text-[#389B98] hover:text-white rounded-lg text-xs font-semibold transition-colors">
                            View Profile
                        </button>
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
                        <div class="space-y-1">
                            <p class="font-medium">Failed to load patients: ${escapeHtml(err.message || "Network or server error")}</p>
                            <button onclick="loadPatientsDirectory(1)" class="mt-1 px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-[11px] font-semibold transition-colors">
                                Retry
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }
    }
}

export function handlePatientSearch(event) {
    if (event) event.preventDefault();
    const input = document.getElementById("patients-search-input");
    currentSearchQuery = input ? input.value.trim() : "";
    loadPatientsDirectory(1);
}

export function handlePatientFilterChange() {
    const statusSelect = document.getElementById("patients-status-filter");
    const systemSelect = document.getElementById("patients-system-filter");
    currentStatusFilter = statusSelect ? statusSelect.value : "";
    currentSystemFilter = systemSelect ? systemSelect.value : "";
    loadPatientsDirectory(1);
}

export function changePatientPage(delta) {
    const targetPage = currentPage + delta;
    if (targetPage >= 1 && targetPage <= totalPages) {
        loadPatientsDirectory(targetPage);
    }
}

// Window bindings
window.loadPatientsDirectory = loadPatientsDirectory;
window.handlePatientSearch = handlePatientSearch;
window.handlePatientFilterChange = handlePatientFilterChange;
window.changePatientPage = changePatientPage;
