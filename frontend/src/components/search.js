/**
 * Clinical Semantic Search & AI Summary Retrieval Component (Phase 5).
 * Connects directly to POST /search with configurable debounce, AbortController
 * cancellation, structured result cards, and one-click Patient Detail Drawer integration.
 */
import { searchClinicalRecords } from "../api/search.js";
import { escapeHtml, formatDate, formatNumber } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { openPatientDrawer } from "./drawer.js";
import { showToast } from "./toast.js";

let activeAbortController = null;
let debounceTimer = null;
const DEBOUNCE_DELAY_MS = 350;

export function setupSearchListeners() {
    const searchInput = document.getElementById("search-query-input");
    const searchForm = document.getElementById("semantic-search-form");

    if (searchInput) {
        // Real-time search with debounce
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim();
            if (debounceTimer) clearTimeout(debounceTimer);

            if (query.length === 0) {
                renderSearchEmptyState("Enter a clinical query above to search patients, FHIR observations, and AI summaries.");
                hideSearchMetrics();
                return;
            }

            debounceTimer = setTimeout(() => {
                executeClinicalSearch();
            }, DEBOUNCE_DELAY_MS);
        });

        // Keyboard shortcut: '/' focuses search input
        window.addEventListener("keydown", (e) => {
            if (e.key === "/" && document.activeElement !== searchInput && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
                e.preventDefault();
                searchInput.focus();
                searchInput.select();
            }
        });
    }

    if (searchForm) {
        searchForm.addEventListener("submit", (e) => {
            e.preventDefault();
            if (debounceTimer) clearTimeout(debounceTimer);
            executeClinicalSearch();
        });
    }
}

export async function executeClinicalSearch() {
    const searchInput = document.getElementById("search-query-input");
    const resourceFilter = document.getElementById("search-filter-resource");
    const patientFilter = document.getElementById("search-filter-patient");
    const dateFromInput = document.getElementById("search-filter-date-from");
    const dateToInput = document.getElementById("search-filter-date-to");
    const topKSelect = document.getElementById("search-filter-top-k");
    const submitBtn = document.getElementById("search-submit-btn");
    const resultsContainer = document.getElementById("search-results-container");

    const query = searchInput ? searchInput.value.trim() : "";
    if (!query) {
        renderSearchEmptyState("Please enter a clinical concept, symptom, medication, or diagnosis to search.");
        return;
    }

    // Cancel obsolete pending request
    if (activeAbortController) {
        activeAbortController.abort();
    }
    activeAbortController = new AbortController();

    const filters = {
        query,
        resourceType: resourceFilter ? resourceFilter.value : null,
        patientId: patientFilter && patientFilter.value.trim() ? patientFilter.value.trim() : null,
        dateFrom: dateFromInput && dateFromInput.value ? dateFromInput.value : null,
        dateTo: dateToInput && dateToInput.value ? dateToInput.value : null,
        topK: topKSelect ? parseInt(topKSelect.value, 10) : 5,
    };

    // Show loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `${iconSvg("spinner", "w-4 h-4 text-white")} <span class="ml-1.5">Searching...</span>`;
    }
    renderSearchSkeleton(resultsContainer);

    try {
        const startTime = performance.now();
        const data = await searchClinicalRecords({
            ...filters,
            signal: activeAbortController.signal,
        });
        const elapsedMs = Math.round(performance.now() - startTime);

        renderSearchResults(data, filters, elapsedMs);
    } catch (err) {
        if (err.name === "AbortError") {
            // Superseded by newer keystroke, do not display error
            return;
        }
        console.error("Search error:", err);
        renderSearchError(resultsContainer, err.message || "Semantic search request failed");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>Search</span> ${iconSvg("search", "w-3.5 h-3.5 ml-1")}`;
        }
    }
}

function cleanSnippetText(text) {
    if (!text) return "";
    let clean = String(text).trim();
    if (clean.startsWith("{") && clean.endsWith("}")) {
        try {
            const parsed = JSON.parse(clean);
            clean = parsed.clinical_summary || parsed.summary || parsed.snippet || Object.values(parsed).find(v => typeof v === "string") || clean;
        } catch (e) {}
    }
    if (clean.includes("<untrusted_clinical_note") || clean.includes("</untrusted_clinical_note>")) {
        clean = clean.replace(/<\/?untrusted_clinical_note[^>]*>/gi, "");
    }
    if (clean.includes("<br")) {
        clean = clean.replace(/<br\s*\/?>/gi, " ");
    }
    if (clean.includes("<") && clean.includes(">")) {
        clean = clean.replace(/<[^>]+>/g, " ");
    }
    // Clean raw ingestion header prefixes without destroying clinical narrative
    clean = clean.replace(/(?:Bed assignment id|Admission id|History id):\s*[\w\-]+[;,]?\s*/gi, " ");
    clean = clean.replace(/\s+/g, " ").trim();
    clean = clean.replace(/^[<«‹\s]+/, "").replace(/[>»›\s]+$/, "").trim();

    const words = clean.split(/\s+/).filter(Boolean);
    if (words.length >= 200) {
        clean = words.slice(0, 195).join(" ") + "...";
    }
    return clean;
}

function renderSearchSkeleton(container) {
    if (!container) return;
    container.innerHTML = `
        <div class="space-y-4">
            ${Array(3).fill(0).map(() => `
                <div class="bg-white border border-[#E5EAEA] rounded-2xl p-5 shadow-sm space-y-3 animate-pulse">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-2">
                            <div class="h-4 w-16 bg-slate-200 rounded"></div>
                            <div class="h-4 w-24 bg-slate-200 rounded"></div>
                            <div class="h-4 w-32 bg-slate-100 rounded"></div>
                        </div>
                        <div class="h-5 w-20 bg-slate-200 rounded-full"></div>
                    </div>
                    <div class="h-14 bg-slate-100 rounded-xl"></div>
                </div>
            `).join("")}
        </div>
    `;
}

function renderSearchError(container, message) {
    if (!container) return;
    container.innerHTML = `
        <div class="bg-white border border-[#E5EAEA] rounded-2xl p-8 text-center space-y-3 shadow-sm">
            <div class="w-10 h-10 rounded-full bg-rose-50 text-[#DE3449] flex items-center justify-center mx-auto">
                ${iconSvg("close", "w-5 h-5")}
            </div>
            <h4 class="text-xs font-bold text-slate-800">Search Failed</h4>
            <p class="text-xs text-slate-500 max-w-sm mx-auto leading-relaxed">${escapeHtml(message)}</p>
            <button
                onclick="executeClinicalSearch()"
                class="px-3.5 py-1.5 bg-[#389B98] text-white rounded-lg text-xs font-semibold hover:bg-[#287F7D] transition-colors"
            >
                Try Again
            </button>
        </div>
    `;
}

function renderSearchEmptyState(message) {
    const container = document.getElementById("search-results-container");
    if (!container) return;
    container.innerHTML = `
        <div class="bg-white border border-[#E5EAEA] rounded-2xl p-10 text-center space-y-2 shadow-sm">
            <div class="w-10 h-10 rounded-full bg-[#389B98]/10 text-[#389B98] flex items-center justify-center mx-auto">
                ${iconSvg("search", "w-5 h-5")}
            </div>
            <div class="text-xs font-semibold text-slate-700">${escapeHtml(message)}</div>
            <p class="text-[11px] text-slate-400">Powered by Sentence Transformers and ChromaDB HNSW Index.</p>
        </div>
    `;
}

function hideSearchMetrics() {
    const metricsBar = document.getElementById("search-metrics-bar");
    if (metricsBar) metricsBar.classList.add("hidden");
}

function renderSearchResults(data, filters, elapsedMs) {
    const container = document.getElementById("search-results-container");
    const metricsBar = document.getElementById("search-metrics-bar");
    const countEl = document.getElementById("search-results-count");
    const latencyEl = document.getElementById("search-results-latency");
    const filterTagsEl = document.getElementById("search-active-filter-tags");

    if (metricsBar) metricsBar.classList.remove("hidden");
    if (countEl) countEl.textContent = `${data.count || 0} distinct clinical record${data.count === 1 ? '' : 's'} retrieved`;
    if (latencyEl) latencyEl.textContent = `Retrieved in ${(data.took_ms || elapsedMs).toFixed(1)} ms`;

    // Active filter tags
    if (filterTagsEl) {
        const badges = [];
        if (filters.resourceType) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-[#389B98]/10 text-[#389B98] border border-[#389B98]/20 text-[10px] font-mono">Type: ${escapeHtml(filters.resourceType)}</span>`);
        }
        if (filters.patientId) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-[10px] font-mono">Patient: ${escapeHtml(filters.patientId)}</span>`);
        }
        if (filters.dateFrom || filters.dateTo) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200 text-[10px] font-mono">Date: [${escapeHtml(filters.dateFrom || 'start')} to ${escapeHtml(filters.dateTo || 'end')}]</span>`);
        }
        filterTagsEl.innerHTML = badges.join(" ");
    }

    if (!data.results || data.results.length === 0) {
        if (container) {
            container.innerHTML = `
                <div class="bg-white border border-[#E5EAEA] rounded-2xl p-10 text-center space-y-2 shadow-sm">
                    <div class="text-xs font-semibold text-slate-700">No clinical records matched this query and filter criteria</div>
                    <p class="text-xs text-slate-400">Try broadening your search term or clearing the active filters.</p>
                </div>
            `;
        }
        return;
    }

    // Results Cards with Phase 5.3 Deep Dive click action
    const cardsHtml = data.results.map((item, idx) => {
        const pct = Math.round(item.score * 100);
        let scoreBadgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
        let barColor = "bg-[#389B98]";

        if (pct < 60) {
            scoreBadgeClass = "bg-amber-50 text-amber-700 border-amber-200";
            barColor = "bg-amber-500";
        } else if (pct < 75) {
            scoreBadgeClass = "bg-teal-50 text-teal-700 border-teal-200";
            barColor = "bg-[#389B98]";
        }

        const isSummary = item.source === "ai_summary";
        const sourceBadge = isSummary
            ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">AI Summary</span>`
            : `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">FHIR Resource</span>`;

        let typeBadgeClass = "bg-slate-100 text-slate-700 border-slate-200";
        if (item.resource_type === "Observation") typeBadgeClass = "bg-blue-50 text-blue-700 border-blue-200";
        else if (item.resource_type === "Condition") typeBadgeClass = "bg-rose-50 text-rose-700 border-rose-200";
        else if (item.resource_type === "DiagnosticReport") typeBadgeClass = "bg-purple-50 text-purple-700 border-purple-200";
        else if (item.resource_type === "ClinicalSummary") typeBadgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";

        return `
            <div
                class="bg-white rounded-2xl border border-[#E5EAEA] hover:border-[#389B98] p-4 sm:p-5 shadow-sm hover:shadow-md transition-all cursor-pointer space-y-3 group"
                onclick="openPatientDrawer('${escapeHtml(item.patient_id)}')"
                title="Click to view comprehensive patient profile, AI summary, and linked FHIR resources"
            >
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b border-slate-100 pb-3">
                    <div class="flex flex-wrap items-center gap-1.5 sm:gap-2">
                        <span class="text-xs font-mono font-bold text-slate-400">#${idx + 1}</span>
                        <span class="px-2 py-0.5 rounded text-[11px] sm:text-xs font-bold font-mono border ${typeBadgeClass}">
                            ${escapeHtml(item.resource_type)}
                        </span>
                        ${sourceBadge}
                        <span class="text-xs text-slate-600">
                            Patient: <strong class="text-[#389B98] font-mono group-hover:underline">${escapeHtml(item.patient_id)}</strong>
                        </span>
                        <span class="hidden sm:inline text-slate-300">|</span>
                        <span class="text-xs text-slate-400 font-mono text-[11px] truncate max-w-[140px] sm:max-w-[220px]" title="${escapeHtml(item.record_id)}">
                            ID: ${escapeHtml(item.record_id)}
                        </span>
                    </div>

                    <div class="flex items-center space-x-3 self-end sm:self-auto flex-shrink-0">
                        <div class="text-right">
                            <span class="px-2.5 py-1 rounded-lg text-xs font-mono font-bold border ${scoreBadgeClass}">
                                ${pct}% Relevance
                            </span>
                            <div class="w-20 sm:w-24 bg-slate-100 h-1.5 rounded-full mt-1.5 overflow-hidden ml-auto">
                                <div class="${barColor} h-full rounded-full" style="width: ${pct}%"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Record Timestamp -->
                <div class="flex items-center space-x-2 text-xs text-slate-400 font-mono text-[11px]">
                    <svg class="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span>Record Timestamp: <strong class="text-slate-600 font-normal">${formatDate(item.date)}</strong></span>
                </div>

                <!-- Clinical Text Snippet -->
                <div class="bg-[#F7F9FA] border border-[#E5EAEA] rounded-xl p-3.5 text-xs text-slate-700 leading-relaxed font-sans">
                    <p class="m-0">${escapeHtml(cleanSnippetText(item.snippet))}</p>
                </div>

                <!-- Footer Hint -->
                <div class="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                    <span class="text-[#389B98] font-medium group-hover:underline flex items-center space-x-1">
                        <span>Inspect Patient & Linked FHIR Graph</span>
                        <span>&rarr;</span>
                    </span>
                    <span class="text-slate-400">Click card for patient drawer</span>
                </div>
            </div>
        `;
    }).join("");

    if (container) {
        container.innerHTML = cardsHtml;
    }
}

export function applySampleSearch(query) {
    const searchInput = document.getElementById("search-query-input");
    if (searchInput) {
        searchInput.value = query;
        searchInput.focus();
        executeClinicalSearch();
    }
}

export function clearSearchInput() {
    const searchInput = document.getElementById("search-query-input");
    if (searchInput) {
        searchInput.value = "";
        searchInput.focus();
        renderSearchEmptyState("Enter a clinical query above to search patients, FHIR observations, and AI summaries.");
        hideSearchMetrics();
    }
}

export function resetSearchFilters() {
    const resourceFilter = document.getElementById("search-filter-resource");
    const patientFilter = document.getElementById("search-filter-patient");
    const dateFromInput = document.getElementById("search-filter-date-from");
    const dateToInput = document.getElementById("search-filter-date-to");
    const topKSelect = document.getElementById("search-filter-top-k");

    if (resourceFilter) resourceFilter.value = "";
    if (patientFilter) patientFilter.value = "";
    if (dateFromInput) dateFromInput.value = "";
    if (dateToInput) dateToInput.value = "";
    if (topKSelect) topKSelect.value = "5";

    showToast("info", "Filters Cleared", "Search filters have been reset to defaults.");
    executeClinicalSearch();
}

// Window bindings
window.executeClinicalSearch = executeClinicalSearch;
window.applySampleSearch = applySampleSearch;
window.clearSearchInput = clearSearchInput;
window.resetSearchFilters = resetSearchFilters;
