/**
 * Patient Detail Drawer Component (Phase 5.3).
 * Renders comprehensive patient information, evidence-grounded AI clinical summaries,
 * linked FHIR R4 resources, and longitudinal clinical records.
 */
import { getPatientDetail, getPatientFhirResources, getPatientRecords } from "../api/patients.js";
import { getPatientSummary, generatePatientSummary, regeneratePatientSummaryAsync, getSummaryTaskStatus, invalidateSummaryCache } from "../api/summarization.js";
import { normalizePatient } from "../api/fhir.js";
import { showToast } from "./toast.js";
import { escapeHtml, formatDate, formatDateShort, formatNumber, getStatusBadgeClass } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";

let currentActivePatientId = null;
let drawerRequestEpoch = 0; // Monotonically increasing epoch to prevent race condition clobbering
let currentActiveTab = "summary"; // 'summary' | 'fhir' | 'records' | 'demographics'
let cachedPatientDetail = null;
let cachedFhirState = { patientId: null, resources: null, fetchedAt: null, filter: "ALL" };
let cachedSummary = null;
let cachedRecords = null;
let activeSummaryTask = null; // { taskId, patientId, status, startedAt }
let summaryPollTimer = null;
let lastSummaryTaskError = null;


export async function openPatientDrawer(patientId) {
    if (!patientId) return;

    const requestEpoch = ++drawerRequestEpoch;
    currentActivePatientId = patientId;
    currentActiveTab = "summary";
    cachedPatientDetail = null;
    cachedFhirState = { patientId: null, resources: null, fetchedAt: null, filter: "ALL" };
    cachedSummary = null;
    cachedRecords = null;
    lastSummaryTaskError = null;

    if (summaryPollTimer) {
        clearInterval(summaryPollTimer);
        summaryPollTimer = null;
    }
    activeSummaryTask = null;

    const drawerEl = document.getElementById("patient-detail-drawer");
    const backdropEl = document.getElementById("patient-drawer-backdrop");

    if (!drawerEl || !backdropEl) return;

    backdropEl.classList.remove("hidden");
    drawerEl.classList.remove("translate-x-full");

    // Prevent background scrolling
    document.body.style.overflow = "hidden";

    // Set initial loading skeleton and reset tabs
    renderDrawerSkeleton();

    try {
        // Fetch patient details and linked FHIR resources in parallel
        const [detail, fhirRes] = await Promise.all([
            getPatientDetail(patientId),
            getPatientFhirResources(patientId).catch(() => []),
        ]);

        // Guard against race conditions: if a newer patient was opened, drop this stale response
        if (drawerRequestEpoch !== requestEpoch) {
            return;
        }

        // Canonical patient ID resolution from backend detail
        if (detail && detail.id) {
            currentActivePatientId = detail.id;
        }

        cachedPatientDetail = detail;
        cachedFhirState = {
            patientId: currentActivePatientId,
            resources: Array.isArray(fhirRes) ? fhirRes : [],
            fetchedAt: new Date(),
            filter: "ALL",
        };

        renderDrawerHeader(detail);
        await switchDrawerTab(currentActiveTab);
    } catch (err) {
        if (drawerRequestEpoch !== requestEpoch) return;
        renderDrawerError(err.message || "Failed to load patient clinical profile");
    }
}

export function closePatientDrawer() {
    drawerRequestEpoch++;
    currentActivePatientId = null;
    cachedPatientDetail = null;
    cachedFhirState = { patientId: null, resources: null, fetchedAt: null, filter: "ALL" };
    cachedSummary = null;
    cachedRecords = null;

    const drawerEl = document.getElementById("patient-detail-drawer");
    const backdropEl = document.getElementById("patient-drawer-backdrop");

    if (drawerEl) drawerEl.classList.add("translate-x-full");
    if (backdropEl) backdropEl.classList.add("hidden");
    document.body.style.overflow = "";

    if (summaryPollTimer) {
        clearInterval(summaryPollTimer);
        summaryPollTimer = null;
    }
    activeSummaryTask = null;

    // Clear drawer body and headers so next open doesn't flash stale data
    const bodyEl = document.getElementById("drawer-content-body");
    const titleEl = document.getElementById("drawer-patient-name");
    const metaEl = document.getElementById("drawer-patient-meta");
    if (bodyEl) bodyEl.innerHTML = "";
    if (titleEl) titleEl.textContent = "Patient Detail Deep Dive";
    if (metaEl) metaEl.innerHTML = "";
}


function renderDrawerSkeleton() {
    const titleEl = document.getElementById("drawer-patient-name");
    const metaEl = document.getElementById("drawer-patient-meta");
    const bodyEl = document.getElementById("drawer-content-body");

    if (titleEl) titleEl.textContent = "Loading Patient Profile...";
    if (metaEl) metaEl.innerHTML = `<span class="inline-block w-48 h-3.5 bg-slate-200 rounded animate-pulse"></span>`;

    // Reset tab button highlight to summary
    const tabs = ["summary", "fhir", "records", "demographics"];
    tabs.forEach(t => {
        const btn = document.getElementById(`drawer-tab-btn-${t}`);
        if (!btn) return;
        if (t === "summary") {
            btn.className = "px-3 sm:px-4 py-2 sm:py-2.5 border-b-2 border-[#389B98] text-[#389B98] flex items-center space-x-1.5 transition-colors whitespace-nowrap";
        } else {
            btn.className = "px-3 sm:px-4 py-2 sm:py-2.5 border-b-2 border-transparent text-slate-500 hover:text-slate-700 flex items-center space-x-1.5 transition-colors whitespace-nowrap";
        }
    });

    if (bodyEl) {
        bodyEl.innerHTML = `
            <div class="p-6 space-y-6">
                <div class="grid grid-cols-4 gap-3">
                    <div class="h-16 bg-slate-100 rounded-xl animate-pulse"></div>
                    <div class="h-16 bg-slate-100 rounded-xl animate-pulse"></div>
                    <div class="h-16 bg-slate-100 rounded-xl animate-pulse"></div>
                    <div class="h-16 bg-slate-100 rounded-xl animate-pulse"></div>
                </div>
                <div class="h-48 bg-slate-100 rounded-xl animate-pulse"></div>
                <div class="h-32 bg-slate-100 rounded-xl animate-pulse"></div>
            </div>
        `;
    }
}

function renderDrawerHeader(detail) {
    const titleEl = document.getElementById("drawer-patient-name");
    const metaEl = document.getElementById("drawer-patient-meta");

    let fullName = `${detail.first_name || ""} ${detail.middle_name || ""} ${detail.last_name || ""}`.trim() || "Anonymous Patient";
    if (fullName.toUpperCase().includes("UNRESOLVED PATIENT") || fullName.toUpperCase() === "UNRESOLVED") {
        fullName = "Unresolved Patient Record";
    } else if (fullName === fullName.toUpperCase() && fullName.length > 3) {
        fullName = fullName.split(/\s+/).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");
    }

    if (titleEl) {
        titleEl.textContent = fullName;
    }

    if (metaEl) {
        const badgeClass = getStatusBadgeClass(detail.reconciliation_status);
        metaEl.innerHTML = `
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500 mt-1">
                <span class="font-mono font-bold text-slate-700">MRN: ${escapeHtml(detail.mrn)}</span>
                <span>•</span>
                <span>Gender: <strong class="capitalize text-slate-700">${escapeHtml(detail.gender || "Unknown")}</strong></span>
                <span>•</span>
                <span>DOB: <strong class="text-slate-700">${escapeHtml(detail.date_of_birth || "-")}</strong></span>
                <span>•</span>
                <span>System: <strong class="text-slate-700">${escapeHtml(detail.source_system)}</strong></span>
                <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeClass}">
                    ${escapeHtml(detail.reconciliation_status)}
                </span>
            </div>
        `;
    }
}

function extractCleanSummaryText(s) {
    if (!s) return "";
    let text = s.clinical_summary || s.summary || s.narrative || "";
    if (typeof text !== "string") {
        text = "";
    }
    text = text.trim();

    // If text looks like serialized JSON, parse it and extract the narrative
    if (text.startsWith("{") && text.endsWith("}")) {
        try {
            const parsed = JSON.parse(text);
            text = parsed.clinical_summary || parsed.summary || parsed.narrative || "";
        } catch (e) {
            text = "";
        }
    }

    // Strip any <untrusted_clinical_note...> or XML tags
    if (text.includes("<untrusted_clinical_note") || text.includes("</untrusted_clinical_note>")) {
        text = text.replace(/<\/?untrusted_clinical_note[^>]*>/gi, "");
    }
    // Strip <br> or <br/> tags
    if (text.includes("<br")) {
        text = text.replace(/<br\s*\/?>/gi, " ");
    }
    // Strip any other HTML/XML tags
    text = text.replace(/<\/?[a-zA-Z0-9_\-]+[^>]*>/gi, " ");

    // CRITICAL: Strip leading < or trailing >
    text = text.replace(/^[<«‹\s]+/, "").replace(/[>»›\s]+$/, "").trim();

    // Clean raw ingestion headers without destroying clinical narrative
    text = text.replace(/(?:Bed assignment id|Admission id|History id):\s*[\w\-]+[;,]?\s*/gi, " ");
    text = text.replace(/\s+/g, " ").trim();

    // If still empty, compose a fluid narrative from available clinical fields
    if (!text) {
        const parts = [];
        if (s.chief_concern) parts.push(`Presenting concern: ${s.chief_concern}.`);
        if (s.key_diagnoses && s.key_diagnoses.length > 0) {
            const diagList = Array.isArray(s.key_diagnoses) ? s.key_diagnoses.join(", ") : s.key_diagnoses;
            parts.push(`Documented diagnoses include ${diagList}.`);
        }
        if (s.flagged_anomalies && s.flagged_anomalies.length > 0) {
            const anomList = Array.isArray(s.flagged_anomalies) ? s.flagged_anomalies.join(", ") : s.flagged_anomalies;
            parts.push(`Flagged clinical findings: ${anomList}.`);
        }
        text = parts.join(" ") || "Clinical documentation recorded. Longitudinal evaluation in progress.";
    }

    // Ensure leading angle brackets and whitespace are fully stripped
    text = text.replace(/^[<«‹\s]+/, "").replace(/[>»›\s]+$/, "").trim();

    // Enforce strictly under 200 words
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length >= 200) {
        text = words.slice(0, 195).join(" ") + "...";
    }
    return text;
}

function renderDrawerError(message) {
    const bodyEl = document.getElementById("drawer-content-body");
    if (!bodyEl) return;
    console.warn("Drawer loading notice:", message);
    bodyEl.innerHTML = `
        <div class="p-8 text-center space-y-3">
            <div class="w-12 h-12 rounded-full bg-slate-100 text-[#389B98] flex items-center justify-center mx-auto">
                ${iconSvg("sparkles", "w-6 h-6")}
            </div>
            <h4 class="text-sm font-bold text-slate-800">Patient Clinical Record</h4>
            <p class="text-xs text-slate-500 max-w-sm mx-auto leading-relaxed">Clinical profile details are being synchronized.</p>
            <button onclick="openPatientDrawer('${escapeHtml(currentActivePatientId)}')" class="mt-2 px-4 py-2 bg-[#389B98] text-white rounded-lg text-xs font-semibold hover:bg-[#287F7D] transition-colors">
                Refresh View
            </button>
        </div>
    `;
}

export async function switchDrawerTab(tab) {
    currentActiveTab = tab;
    const tabs = ["summary", "fhir", "records", "demographics"];
    tabs.forEach(t => {
        const btn = document.getElementById(`drawer-tab-btn-${t}`);
        if (!btn) return;
        if (t === tab) {
            btn.className = "px-3 sm:px-4 py-2 sm:py-2.5 text-xs font-semibold border-b-2 border-[#389B98] text-[#389B98] flex items-center space-x-1.5 transition-colors whitespace-nowrap";
        } else {
            btn.className = "px-3 sm:px-4 py-2 sm:py-2.5 text-xs font-medium text-slate-500 hover:text-slate-700 border-b-2 border-transparent flex items-center space-x-1.5 transition-colors whitespace-nowrap";
        }
    });

    const bodyEl = document.getElementById("drawer-content-body");
    if (!bodyEl) return;

    if (tab === "summary") {
        await renderDrawerSummaryTab(bodyEl);
    } else if (tab === "fhir") {
        await renderDrawerFhirTab(bodyEl);
    } else if (tab === "records") {
        await renderDrawerRecordsTab(bodyEl);
    } else if (tab === "demographics") {
        renderDrawerDemographicsTab(bodyEl);
    }
}

// -----------------------------------------------------------------------------
// Drawer Tab 1: AI Clinical Summary
// -----------------------------------------------------------------------------
async function renderDrawerSummaryTab(container) {
    container.innerHTML = `
        <div class="p-6 space-y-4">
            <div class="h-8 bg-slate-100 rounded-lg animate-pulse"></div>
            <div class="h-32 bg-slate-100 rounded-lg animate-pulse"></div>
            <div class="h-24 bg-slate-100 rounded-lg animate-pulse"></div>
        </div>
    `;

    try {
        // If no in-memory active task, check if the server has a background task in progress
        if (!activeSummaryTask) {
            try {
                const taskStatus = await getSummaryTaskStatus(currentActivePatientId);
                if (taskStatus && (taskStatus.status === "PENDING" || taskStatus.status === "PROCESSING")) {
                    activeSummaryTask = {
                        taskId: taskStatus.task_id,
                        patientId: currentActivePatientId,
                        status: taskStatus.status,
                        startedAt: taskStatus.started_at ? new Date(taskStatus.started_at).getTime() : Date.now(),
                    };
                    startSummaryStatusPolling(currentActivePatientId, taskStatus.task_id);
                } else if (taskStatus && taskStatus.status === "COMPLETED" && taskStatus.summary) {
                    cachedSummary = taskStatus.summary;
                } else if (taskStatus && taskStatus.status === "FAILED") {
                    lastSummaryTaskError = taskStatus.error_message || taskStatus.message || null;
                }
            } catch (err) {
                // Not found or no task, proceed normally
            }
        }

        if (!cachedSummary) {
            try {
                cachedSummary = await getPatientSummary(currentActivePatientId);
            } catch (err) {
                if (err.status === 404) {
                    cachedSummary = null;
                } else {
                    throw err;
                }
            }
        }

        const isTaskRunning = activeSummaryTask && (activeSummaryTask.status === "PENDING" || activeSummaryTask.status === "PROCESSING");
        const activeTaskBanner = isTaskRunning ? `
            <div class="bg-gradient-to-r from-[#389B98]/10 via-[#389B98]/5 to-transparent p-4 rounded-xl border border-[#389B98]/30 space-y-2.5">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2.5">
                        <div class="w-6 h-6 rounded-lg bg-[#389B98] text-white flex items-center justify-center animate-spin">
                            ${iconSvg("spinner", "w-3.5 h-3.5")}
                        </div>
                        <div>
                            <h5 class="text-xs font-bold text-slate-800">AI Clinical Synthesis in Progress (Async Background Worker)</h5>
                            <p class="text-[11px] text-slate-500">Synthesizing longitudinal records, evaluating evidence, and generating structured narrative...</p>
                        </div>
                    </div>
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-white text-[#389B98] border border-[#389B98]/30">
                        ${escapeHtml(activeSummaryTask.taskId || "active-task")}
                    </span>
                </div>
                <div class="w-full bg-slate-200/60 rounded-full h-1.5 overflow-hidden">
                    <div class="bg-[#389B98] h-1.5 rounded-full animate-pulse w-3/4"></div>
                </div>
                <div class="flex items-center justify-between text-[11px] text-slate-500 font-medium">
                    <span class="flex items-center space-x-1.5">
                        <span class="w-2 h-2 rounded-full bg-amber-500 animate-ping"></span>
                        <span>Status: ${escapeHtml(activeSummaryTask.status || "PROCESSING")}</span>
                    </span>
                    <span id="async-elapsed-time">Elapsed: ${Math.floor((Date.now() - (activeSummaryTask.startedAt || Date.now())) / 1000)}s</span>
                </div>
            </div>
        ` : "";

        if (!cachedSummary) {
            if (isTaskRunning) {
                container.innerHTML = `
                    <div class="p-6 space-y-6">
                        ${activeTaskBanner}
                        <div class="p-8 text-center space-y-3 bg-[#F7F9FA] rounded-xl border border-[#E5EAEA]">
                            <p class="text-xs text-slate-500">
                                Generating initial evidence-grounded clinical overview for this patient. This view will update automatically once synthesis is complete.
                            </p>
                        </div>
                    </div>
                `;
                return;
            }

            const errorBanner = lastSummaryTaskError ? `
                <div class="p-4 bg-rose-50 border border-rose-200/90 rounded-xl text-xs text-rose-800 flex items-start space-x-3 text-left max-w-lg mx-auto">
                    <div class="mt-0.5 text-rose-600 flex-shrink-0">
                        ${iconSvg("close", "w-4 h-4")}
                    </div>
                    <div class="space-y-1.5 flex-1">
                        <span class="font-bold text-rose-900 block text-xs">Summary Generation Notice</span>
                        <p class="text-[11px] text-rose-700 leading-relaxed m-0 font-medium">${escapeHtml(lastSummaryTaskError)}</p>
                        ${lastSummaryTaskError.toLowerCase().includes("fhir") ? `
                            <button
                                onclick="switchDrawerTab('fhir')"
                                class="mt-1 px-3 py-1 bg-white border border-rose-300 text-rose-800 hover:bg-rose-100 rounded-lg text-[11px] font-semibold transition-colors inline-flex items-center space-x-1"
                            >
                                <span>Switch to FHIR Tab to Normalize</span>
                                <span>&rarr;</span>
                            </button>
                        ` : ""}
                    </div>
                </div>
            ` : "";

            // Empty state: No summary generated yet
            container.innerHTML = `
                <div class="p-8 text-center space-y-4">
                    <div class="w-14 h-14 rounded-2xl bg-[#389B98]/10 text-[#389B98] flex items-center justify-center mx-auto">
                        ${iconSvg("sparkles", "w-7 h-7")}
                    </div>
                    <div class="space-y-1">
                        <h4 class="text-sm font-bold text-slate-800">No AI Clinical Summary Available</h4>
                        <p class="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
                            Generate an evidence-grounded clinical overview synthesized directly from this patient's validated longitudinal records and FHIR R4 observations.
                        </p>
                    </div>
                    ${errorBanner}
                    <div>
                        <button
                            id="btn-generate-summary"
                            onclick="triggerDrawerSummaryGeneration(false)"
                            class="px-4 py-2.5 bg-[#389B98] hover:bg-[#287F7D] text-white rounded-xl text-xs font-semibold shadow-sm transition-all inline-flex items-center space-x-2"
                        >
                            ${iconSvg("sparkles", "w-4 h-4")}
                            <span>Generate AI Clinical Summary</span>
                        </button>
                    </div>
                </div>
            `;
            return;
        }

        // Render AI Clinical Summary: Pure text under 200 words (no JSON or structured data cards)
        const s = cachedSummary;
        const confidenceLevel = typeof s.confidence === "object" ? s.confidence.level : s.confidence;
        const confidenceBadge = confidenceLevel === "high"
            ? `<span class="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span>High Confidence</span></span>`
            : `<span class="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200"><span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span><span>Moderate Confidence</span></span>`;

        const summaryText = extractCleanSummaryText(s).trim();
        const wordCount = summaryText ? summaryText.split(/\s+/).filter(Boolean).length : 0;

        const regenerateBtn = isTaskRunning ? `
            <button
                disabled
                class="px-3 py-1.5 text-xs font-medium text-slate-400 bg-slate-100 border border-slate-200 rounded-xl flex items-center space-x-1.5 cursor-not-allowed"
                title="Regeneration is in progress in background worker"
            >
                <div class="w-3 h-3 border-2 border-slate-400 border-t-transparent rounded-full animate-spin"></div>
                <span>Regenerating...</span>
            </button>
        ` : `
            <button
                id="btn-regenerate-summary"
                onclick="triggerDrawerSummaryRegeneration()"
                class="px-3 py-1.5 text-xs font-semibold text-slate-700 hover:text-[#389B98] bg-white border border-[#E5EAEA] hover:border-[#389B98] rounded-xl shadow-2xs hover:shadow-xs transition-all flex items-center space-x-1.5"
                title="Regenerate clinical narrative summary"
            >
                ${iconSvg("refresh", "w-3.5 h-3.5")}
                <span>Regenerate</span>
            </button>
        `;

        container.innerHTML = `
            <div class="p-6 space-y-4">
                ${activeTaskBanner}

                <!-- Action & Confidence Bar -->
                <div class="flex items-center justify-between bg-[#F7F9FA] p-3 rounded-xl border border-[#E5EAEA]">
                    <div class="flex items-center space-x-2">
                        ${confidenceBadge}
                        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-white text-slate-600 border border-slate-200">
                            ${wordCount} words
                        </span>
                        <span class="text-[11px] text-slate-400">Generated ${formatDate(s.generated_at)}</span>
                        ${isTaskRunning ? `<span class="text-[11px] text-[#389B98] font-medium">• Refreshing</span>` : ""}
                    </div>
                    <div>
                        ${regenerateBtn}
                    </div>
                </div>

                <!-- Chief Clinical Concern -->
                ${s.chief_concern ? `
                    <div class="bg-white p-4 rounded-xl border border-[#E5EAEA] shadow-sm space-y-1.5">
                        <h5 class="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center space-x-1.5">
                            <span class="w-2 h-2 rounded-full bg-[#389B98]"></span>
                            <span>Chief Clinical Concern</span>
                        </h5>
                        <p class="text-xs text-slate-800 leading-relaxed font-medium">
                            ${escapeHtml(s.chief_concern)}
                        </p>
                    </div>
                ` : ""}

                <!-- Uniform Clinical Narrative Card -->
                <div class="bg-white p-5 rounded-xl border border-[#E5EAEA] shadow-sm space-y-3">
                    <div class="flex items-center justify-between border-b border-slate-100 pb-2.5">
                        <div class="flex items-center space-x-2">
                            <span class="w-2 h-2 rounded-full bg-indigo-500"></span>
                            <h5 class="font-bold text-slate-800 uppercase tracking-wider text-[11px]">
                                Clinical Narrative Summary
                            </h5>
                        </div>
                        <span class="text-[10px] font-mono text-slate-400">
                            Under 200 words
                        </span>
                    </div>

                    <div class="bg-[#F7F9FA] rounded-lg p-3.5 border border-slate-100 text-xs text-slate-800 font-sans leading-relaxed">
                        <p class="m-0 text-xs text-slate-800 font-normal leading-relaxed">${escapeHtml(summaryText)}</p>
                    </div>
                </div>

                <!-- Key Diagnoses & Anomalies -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <!-- Key Active Diagnoses -->
                    <div class="bg-white p-4 rounded-xl border border-[#E5EAEA] shadow-sm space-y-2">
                        <h5 class="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center space-x-1.5">
                            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
                            <span>Key Active Diagnoses</span>
                        </h5>
                        ${renderStringOrList(s.key_diagnoses)}
                    </div>

                    <!-- Flagged Anomalies & Risks -->
                    <div class="bg-white p-4 rounded-xl border border-[#E5EAEA] shadow-sm space-y-2">
                        <h5 class="text-xs font-bold uppercase tracking-wider text-[#DE3449] flex items-center space-x-1.5">
                            <span class="w-2 h-2 rounded-full bg-[#DE3449]"></span>
                            <span>Flagged Anomalies & Out-of-Range Labs</span>
                        </h5>
                        ${renderStringOrList(s.flagged_anomalies, true)}
                    </div>
                </div>

                <!-- Recent Diagnostic Records -->
                ${renderDiagnosticRecordsSummary(s.recent_diagnostic_records)}

                <!-- Evidence Grounding & FHIR Sources -->
                ${s.source_references && s.source_references.length > 0 ? `
                    <div class="bg-white p-4 rounded-xl border border-[#E5EAEA] shadow-sm space-y-2">
                        <h5 class="text-xs font-bold uppercase tracking-wider text-slate-500">Evidentiary Grounding References</h5>
                        <div class="flex flex-wrap gap-1.5">
                            ${s.source_references.map(ref => `
                                <span class="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono text-[11px] border border-slate-200">
                                    ${escapeHtml(ref)}
                                </span>
                            `).join("")}
                        </div>
                    </div>
                ` : ""}

                <!-- Clinical Decision Support Disclaimer -->
                <div class="p-3.5 bg-amber-50/60 rounded-xl border border-amber-200/60 text-[11px] text-amber-800 space-y-1">
                    <p class="font-medium">${escapeHtml(s.disclaimer || "AI-generated clinical synthesis for decision support only. Not a clinical decision. Verify with primary EHR documentation.")}</p>
                    ${s.model_metadata ? `
                        <div class="text-[10px] text-amber-700/80 font-mono">
                            Model: ${escapeHtml(s.model_metadata.model || "Local LLM")} | Provider: ${escapeHtml(s.model_metadata.provider || "ollama")}
                        </div>
                    ` : ""}
                </div>
            </div>
        `;
    } catch (err) {
        console.error("Summary tab load failure:", err);
        const isNotFound = (err.status === 404) || (err.message && err.message.toLowerCase().includes("not found")) || (err.message && err.message.toLowerCase().includes("no clinical summary"));
        if (isNotFound) {
            container.innerHTML = `
                <div class="p-8 text-center space-y-4">
                    <div class="w-14 h-14 rounded-2xl bg-[#389B98]/10 text-[#389B98] flex items-center justify-center mx-auto">
                        ${iconSvg("sparkles", "w-7 h-7")}
                    </div>
                    <div class="space-y-1">
                        <h4 class="text-sm font-bold text-slate-800">No AI Clinical Summary Available</h4>
                        <p class="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
                            Synthesize an evidence-grounded clinical narrative under 200 words from this patient's validated longitudinal records and FHIR R4 observations.
                        </p>
                    </div>
                    <div>
                        <button
                            id="btn-generate-summary"
                            onclick="triggerDrawerSummaryGeneration(false)"
                            class="px-4 py-2.5 bg-[#389B98] hover:bg-[#287F7D] text-white rounded-xl text-xs font-semibold shadow-sm transition-all inline-flex items-center space-x-2"
                        >
                            ${iconSvg("sparkles", "w-4 h-4")}
                            <span>Generate AI Clinical Summary</span>
                        </button>
                    </div>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="p-8 text-center text-xs text-rose-600 space-y-3">
                    <div class="w-10 h-10 rounded-full bg-rose-50 text-[#DE3449] flex items-center justify-center mx-auto">
                        ${iconSvg("close", "w-6 h-6")}
                    </div>
                    <p class="font-medium">Failed to retrieve clinical summary: ${escapeHtml(err.message)}</p>
                    <button onclick="renderDrawerSummaryTab(document.getElementById('drawer-content-body'))" class="px-3.5 py-1.5 bg-[#389B98] text-white rounded-lg text-xs font-semibold hover:bg-[#287F7D] transition-colors">
                        Retry Loading
                    </button>
                </div>
            `;
        }
    }
}

function formatClinicalItem(item) {
    if (!item) return "-";
    if (typeof item === "string") return item;
    if (typeof item === "object") {
        if (item.display || item.name || item.code || item.test_name) {
            const title = item.display || item.name || item.code || item.test_name;
            const val = item.value !== undefined ? ` (${item.value} ${item.unit || ""})`.trim() : "";
            return `${title}${val}`;
        }
        return Object.entries(item).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? formatClinicalItem(v) : v}`).join(", ");
    }
    return String(item);
}

function renderDiagnosticRecordsSummary(diag) {
    if (!diag || typeof diag !== "object") return "";

    const lab = Array.isArray(diag.laboratory) ? diag.laboratory : [];
    const imaging = Array.isArray(diag.imaging) ? diag.imaging : [];
    const other = Array.isArray(diag.other) ? diag.other : [];

    const totalCount = lab.length + imaging.length + other.length;
    if (totalCount === 0) return "";

    return `
        <div class="bg-white p-4 rounded-xl border border-[#E5EAEA] shadow-sm space-y-3">
            <h5 class="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center justify-between">
                <span>Recent Diagnostic & Laboratory Studies</span>
                <span class="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">${totalCount} findings</span>
            </h5>

            <!-- Laboratory Findings -->
            ${lab.length > 0 ? `
                <div class="space-y-1.5">
                    <div class="flex items-center space-x-1.5 text-[11px] font-bold text-slate-700">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#389B98]"></span>
                        <span>Laboratory Observations (${lab.length})</span>
                    </div>
                    <div class="grid grid-cols-1 gap-1.5">
                        ${lab.map(item => `
                            <div class="p-2.5 bg-slate-50/80 border border-slate-200/80 rounded-lg text-xs flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                    <span class="px-1.5 py-0.5 rounded bg-[#389B98]/10 text-[#389B98] font-bold font-mono text-[9px]">LAB</span>
                                    <span class="font-medium text-slate-800">${escapeHtml(formatClinicalItem(item))}</span>
                                </div>
                                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">Grounded</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            ` : ""}

            <!-- Imaging Studies -->
            ${imaging.length > 0 ? `
                <div class="space-y-1.5">
                    <div class="flex items-center space-x-1.5 text-[11px] font-bold text-slate-700">
                        <span class="w-1.5 h-1.5 rounded-full bg-purple-500"></span>
                        <span>Imaging & Radiology (${imaging.length})</span>
                    </div>
                    <div class="grid grid-cols-1 gap-1.5">
                        ${imaging.map(item => `
                            <div class="p-2.5 bg-purple-50/50 border border-purple-200/80 rounded-lg text-xs flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                    <span class="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-bold font-mono text-[9px]">RAD</span>
                                    <span class="font-medium text-slate-800">${escapeHtml(formatClinicalItem(item))}</span>
                                </div>
                                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-100 text-purple-700">Report</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            ` : ""}

            <!-- Other Physiological Measurements & Vitals -->
            ${other.length > 0 ? `
                <div class="space-y-1.5">
                    <div class="flex items-center space-x-1.5 text-[11px] font-bold text-slate-700">
                        <span class="w-1.5 h-1.5 rounded-full bg-blue-500"></span>
                        <span>Vitals & Physiological Findings (${other.length})</span>
                    </div>
                    <div class="grid grid-cols-1 gap-1.5">
                        ${other.map(item => `
                            <div class="p-2.5 bg-blue-50/40 border border-blue-200/80 rounded-lg text-xs flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                    <span class="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-bold font-mono text-[9px]">VIT</span>
                                    <span class="font-medium text-slate-800">${escapeHtml(formatClinicalItem(item))}</span>
                                </div>
                                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">Observed</span>
                            </div>
                        `).join("")}
                    </div>
                </div>
            ` : ""}
        </div>
    `;
}

function renderStringOrList(data, isAlert = false) {
    if (!data || (Array.isArray(data) && data.length === 0)) {
        return `<p class="text-xs text-slate-400 italic">None noted or documented.</p>`;
    }
    if (typeof data === "string") {
        return `<p class="text-xs text-slate-700 leading-relaxed font-medium">${escapeHtml(data)}</p>`;
    }
    if (Array.isArray(data)) {
        return `
            <ul class="space-y-1.5">
                ${data.map(item => {
                    const text = formatClinicalItem(item);
                    return `
                        <li class="text-xs text-slate-700 flex items-start space-x-2">
                            <span class="text-${isAlert ? '[#DE3449]' : '[#389B98]'} font-bold mt-0.5">•</span>
                            <span class="leading-relaxed font-medium">${escapeHtml(text)}</span>
                        </li>
                    `;
                }).join("")}
            </ul>
        `;
    }
    if (typeof data === "object") {
        return `
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                ${Object.entries(data).map(([k, v]) => `
                    <div class="p-2 bg-slate-50 rounded-lg border border-slate-200/70 text-xs">
                        <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500 block">${escapeHtml(k.replace(/_/g, ' '))}</span>
                        <span class="text-slate-800 font-medium">${escapeHtml(typeof v === 'object' ? formatClinicalItem(v) : String(v))}</span>
                    </div>
                `).join("")}
            </div>
        `;
    }
    return `<p class="text-xs text-slate-700 leading-relaxed font-medium">${escapeHtml(String(data))}</p>`;
}


export function startSummaryStatusPolling(patientId, taskId) {
    if (summaryPollTimer) {
        clearInterval(summaryPollTimer);
        summaryPollTimer = null;
    }

    const pollInterval = 1500; // 1.5s
    const maxPollTime = 90000; // 90s timeout
    const startTime = Date.now();

    summaryPollTimer = setInterval(async () => {
        // If patient changed or drawer closed, abort polling
        if (currentActivePatientId !== patientId) {
            clearInterval(summaryPollTimer);
            summaryPollTimer = null;
            return;
        }

        const elapsedEl = document.getElementById("async-elapsed-time");
        if (elapsedEl) {
            const elapsedSec = Math.floor((Date.now() - startTime) / 1000);
            elapsedEl.textContent = `Elapsed: ${elapsedSec}s`;
        }

        if (Date.now() - startTime > maxPollTime) {
            clearInterval(summaryPollTimer);
            summaryPollTimer = null;
            activeSummaryTask = null;
            showToast("warning", "Inference In Progress", "The background worker is still processing. Check back in a moment.");
            if (currentActiveTab === "summary") {
                await switchDrawerTab("summary");
            }
            return;
        }

        try {
            const statusResp = await getSummaryTaskStatus(patientId, taskId);
            if (statusResp.status === "COMPLETED" && statusResp.summary) {
                clearInterval(summaryPollTimer);
                summaryPollTimer = null;
                activeSummaryTask = null;
                cachedSummary = statusResp.summary;
                const durText = statusResp.duration_seconds ? ` in ${statusResp.duration_seconds}s` : "";
                showToast("success", "Summary Regenerated", `Fresh evidence-grounded summary is ready${durText}.`);
                if (currentActiveTab === "summary") {
                    await switchDrawerTab("summary");
                }
            } else if (statusResp.status === "FAILED") {
                clearInterval(summaryPollTimer);
                summaryPollTimer = null;
                activeSummaryTask = null;
                lastSummaryTaskError = statusResp.error_message || statusResp.message || "Clinical summary generation encountered an error.";
                showToast("error", "Summary Generation Failed", lastSummaryTaskError, 9000);
                if (currentActiveTab === "summary") {
                    await switchDrawerTab("summary");
                }
            }
        } catch (err) {
            // Transient network glitch during polling tick
            console.warn("Summary status polling tick error:", err);
        }
    }, pollInterval);
}

export async function triggerDrawerSummaryRegeneration() {
    if (!currentActivePatientId) return;

    try {
        lastSummaryTaskError = null;
        const res = await regeneratePatientSummaryAsync(currentActivePatientId);
        activeSummaryTask = {
            taskId: res.task_id,
            patientId: currentActivePatientId,
            status: res.status || "PROCESSING",
            startedAt: Date.now(),
        };

        showToast("info", "Regeneration Scheduled", "Synthesizing fresh clinical summary in background worker...", 3500);
        await switchDrawerTab("summary");
        startSummaryStatusPolling(currentActivePatientId, res.task_id);
    } catch (err) {
        lastSummaryTaskError = err.message || (err.details && (err.details.error_message || err.details.detail)) || "Failed to trigger background summary regeneration";
        showToast("error", "Summary Regeneration Failed", lastSummaryTaskError, 9000);
        await switchDrawerTab("summary");
    }
}

export async function triggerDrawerSummaryGeneration(forceRefresh = false) {
    if (forceRefresh) {
        return await triggerDrawerSummaryRegeneration();
    }

    if (!currentActivePatientId) return;

    const btn = document.getElementById("btn-generate-summary");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `${iconSvg("spinner", "w-4 h-4 mr-1.5")} <span>Scheduling Async Inference...</span>`;
    }

    try {
        lastSummaryTaskError = null;
        showToast("info", "Inference Triggered", "Synthesizing clinical summary in background worker...", 3500);
        const res = await generatePatientSummary(currentActivePatientId, false, false);
        if (res.task_id) {
            activeSummaryTask = {
                taskId: res.task_id,
                patientId: currentActivePatientId,
                status: res.status || "PROCESSING",
                startedAt: Date.now(),
            };
            await switchDrawerTab("summary");
            startSummaryStatusPolling(currentActivePatientId, res.task_id);
        } else {
            cachedSummary = res;
            showToast("success", "Summary Ready", "Clinical summary successfully generated.");
            await switchDrawerTab("summary");
        }
    } catch (err) {
        lastSummaryTaskError = err.message || (err.details && (err.details.error_message || err.details.detail)) || "Failed to generate AI summary";
        showToast("error", "Summary Generation Failed", lastSummaryTaskError, 9000);
        await switchDrawerTab("summary");
    }
}


function renderFhirResourceAttributes(r) {
    const raw = r.raw_resource || {};
    const details = r.details || {};
    const chips = [];

    // Concept / Code
    const coding = raw.code?.coding?.[0] || {};
    if (coding.code) {
        const sys = coding.system ? coding.system.split("/").pop().toUpperCase() : "CODE";
        chips.push({ label: sys, value: `${coding.code}${coding.display ? ` - ${coding.display}` : ""}` });
    }

    // Category
    const cat = raw.category?.[0]?.coding?.[0]?.display || raw.category?.[0]?.text || details.category;
    if (cat) {
        chips.push({ label: "Category", value: cat });
    }

    // Value / Quantity
    if (raw.valueQuantity) {
        chips.push({ label: "Measurement", value: `${raw.valueQuantity.value ?? ""} ${raw.valueQuantity.unit ?? ""}`.trim() });
    } else if (raw.valueString) {
        chips.push({ label: "Observation", value: raw.valueString });
    }

    // Clinical / Verification status
    const clinStatus = raw.clinicalStatus?.coding?.[0]?.code || details.clinical_status;
    if (clinStatus) {
        chips.push({ label: "Clinical Status", value: clinStatus });
    }
    const verStatus = raw.verificationStatus?.coding?.[0]?.code || details.verification_status;
    if (verStatus) {
        chips.push({ label: "Verification", value: verStatus });
    }

    // Severity
    const severity = raw.severity?.coding?.[0]?.display || raw.severity?.coding?.[0]?.code || details.severity;
    if (severity) {
        chips.push({ label: "Severity", value: severity });
    }

    // Conclusion / Note
    const conclusion = raw.conclusion || details.conclusion;
    if (conclusion) {
        chips.push({ label: "Impression", value: conclusion });
    }

    // Encounter
    const encounterRef = raw.encounter?.reference || details.encounter_id;
    if (encounterRef) {
        chips.push({ label: "Encounter", value: encounterRef });
    }

    if (chips.length === 0) return "";

    return `
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 bg-[#F7F9FA] rounded-lg p-2.5 border border-slate-100">
            ${chips.map(c => `
                <div class="text-[11px] leading-tight">
                    <span class="text-slate-400 font-medium">${escapeHtml(c.label)}:</span>
                    <span class="text-slate-700 font-semibold ml-1">${escapeHtml(c.value)}</span>
                </div>
            `).join("")}
        </div>
    `;
}

function renderDrawerRecordContent(rec) {
    const hasCleanedText = rec.cleaned_text && rec.cleaned_text.trim();
    const payload = rec.parsed_payload || {};
    const entries = Object.entries(payload);

    let narrativeHtml = "";
    if (hasCleanedText) {
        const cleanedNarrative = rec.cleaned_text.replace(/<\/?untrusted_clinical_note[^>]*>/gi, '').replace(/<br\s*\/?>/gi, ' ').replace(/^[<«‹\s]+/, '').replace(/[>»›\s]+$/, '').trim();
        narrativeHtml = `
            <div class="bg-[#F7F9FA] rounded-lg p-3 text-xs text-slate-800 font-sans leading-relaxed border border-slate-100">
                <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1">Cleaned Clinical Narrative</span>
                <p class="m-0">${escapeHtml(cleanedNarrative)}</p>
            </div>
        `;
    }

    let payloadHtml = "";
    if (entries.length > 0) {
        payloadHtml = `
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 bg-[#F7F9FA] rounded-lg p-2.5 border border-slate-100">
                ${entries.slice(0, 6).map(([k, v]) => {
                    let displayVal = v;
                    if (typeof v === "object" && v !== null) {
                        displayVal = Array.isArray(v) 
                            ? v.map(item => (typeof item === "object" ? Object.values(item).join(" ") : item)).join(", ")
                            : Object.entries(v).map(([sk, sv]) => `${sk}: ${sv}`).join(", ");
                    }
                    return `
                        <div class="text-xs">
                            <span class="text-slate-400 font-medium block text-[10px] uppercase font-mono">${escapeHtml(k.replace(/_/g, " "))}</span>
                            <span class="text-slate-800 font-semibold break-words">${escapeHtml(String(displayVal))}</span>
                        </div>
                    `;
                }).join("")}
            </div>
        `;
    }

    const errors = rec.validation_errors;
    let errorsHtml = "";
    if (errors && ((Array.isArray(errors) && errors.length > 0) || (typeof errors === "object" && Object.keys(errors).length > 0))) {
        errorsHtml = `
            <div class="px-2.5 py-1.5 bg-rose-50 border border-rose-200 rounded-lg text-[11px] text-[#DE3449] font-medium flex items-center space-x-1.5">
                <span class="w-1.5 h-1.5 rounded-full bg-[#DE3449]"></span>
                <span>Ingestion validation alert: Conflict flagged during canonical reconciliation.</span>
            </div>
        `;
    }

    return `
        <div class="space-y-2">
            ${narrativeHtml}
            ${payloadHtml}
            ${errorsHtml}
            ${entries.length > 0 ? `
                <details class="text-xs pt-1">
                    <summary class="cursor-pointer text-[11px] font-medium text-[#389B98] hover:underline flex items-center space-x-1 select-none">
                        <span>Inspect Raw Source Payload</span>
                    </summary>
                    <pre class="mt-2 bg-[#F7F9FA] border border-[#E5EAEA] rounded-lg p-3 text-[11px] font-mono text-slate-800 overflow-x-auto max-h-40 leading-relaxed">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
                </details>
            ` : ""}
        </div>
    `;
}

// -----------------------------------------------------------------------------
// Drawer Tab 2: Linked FHIR Resources
// -----------------------------------------------------------------------------
async function renderDrawerFhirTab(container, forceRefresh = false) {
    const activePatientId = currentActivePatientId;
    if (!activePatientId) return;

    const isCurrent = cachedFhirState.patientId === activePatientId && cachedFhirState.resources !== null;

    if (!isCurrent || forceRefresh) {
        container.innerHTML = `
            <div class="p-6 space-y-4">
                <div class="flex items-center justify-between">
                    <div class="h-4 w-40 bg-slate-200 rounded animate-pulse"></div>
                    <div class="h-6 w-24 bg-slate-200 rounded animate-pulse"></div>
                </div>
                <div class="h-24 bg-slate-100 rounded-xl animate-pulse"></div>
                <div class="h-24 bg-slate-100 rounded-xl animate-pulse"></div>
                <div class="h-24 bg-slate-100 rounded-xl animate-pulse"></div>
            </div>
        `;

        try {
            const freshRes = await getPatientFhirResources(activePatientId);
            // Guard against patient switch during async network fetch
            if (currentActivePatientId !== activePatientId) return;

            cachedFhirState = {
                patientId: activePatientId,
                resources: Array.isArray(freshRes) ? freshRes : [],
                fetchedAt: new Date(),
                filter: cachedFhirState.filter || "ALL",
            };
        } catch (err) {
            if (currentActivePatientId !== activePatientId) return;
            container.innerHTML = `
                <div class="p-8 text-center text-xs text-rose-600 space-y-3">
                    <div class="w-10 h-10 rounded-full bg-rose-50 text-[#DE3449] flex items-center justify-center mx-auto">
                        ${iconSvg("close", "w-6 h-6")}
                    </div>
                    <p class="font-medium">Failed to retrieve linked FHIR resources: ${escapeHtml(err.message)}</p>
                    <button onclick="refreshDrawerFhirResources(false)" class="px-3.5 py-1.5 bg-[#389B98] text-white rounded-lg text-xs font-semibold hover:bg-[#287F7D] transition-colors">
                        Retry Loading
                    </button>
                </div>
            `;
            return;
        }
    }

    const allResources = cachedFhirState.resources || [];
    const activeFilter = cachedFhirState.filter || "ALL";

    // Category count statistics
    const counts = {
        ALL: allResources.length,
        Observation: allResources.filter(r => r.resource_type === "Observation").length,
        Condition: allResources.filter(r => r.resource_type === "Condition").length,
        DiagnosticReport: allResources.filter(r => r.resource_type === "DiagnosticReport").length,
        DocumentReference: allResources.filter(r => r.resource_type === "DocumentReference").length,
        Encounter: allResources.filter(r => r.resource_type === "Encounter").length,
        Patient: allResources.filter(r => r.resource_type === "Patient").length,
    };

    const filteredResources = activeFilter === "ALL"
        ? allResources
        : allResources.filter(r => r.resource_type === activeFilter);

    const fetchedTimeStr = cachedFhirState.fetchedAt
        ? cachedFhirState.fetchedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
        : "Just now";

    if (allResources.length === 0) {
        container.innerHTML = `
            <div class="p-8 text-center space-y-4">
                <div class="w-14 h-14 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
                    ${iconSvg("fhir", "w-7 h-7")}
                </div>
                <div class="space-y-1">
                    <h4 class="text-sm font-bold text-slate-800">No Normalized FHIR R4 Bundle Found</h4>
                    <p class="text-xs text-slate-500 max-w-sm mx-auto leading-relaxed">
                        Transform this patient's reconciled records into an HL7 FHIR R4 Bundle with referential graph assembly and schema conformance.
                    </p>
                </div>
                <div class="flex flex-wrap items-center justify-center gap-2 pt-2">
                    <button
                        onclick="triggerDrawerFhirNormalization()"
                        class="px-4 py-2.5 bg-[#389B98] hover:bg-[#287F7D] text-white rounded-xl text-xs font-semibold shadow-sm transition-all inline-flex items-center space-x-2"
                    >
                        ${iconSvg("fhir", "w-4 h-4")}
                        <span>Normalize Patient to FHIR R4</span>
                    </button>
                    <button
                        onclick="refreshDrawerFhirResources(false)"
                        class="px-4 py-2.5 bg-white border border-[#E5EAEA] hover:border-[#389B98] text-slate-700 rounded-xl text-xs font-semibold shadow-2xs hover:shadow-xs transition-all inline-flex items-center space-x-2"
                    >
                        ${iconSvg("refresh", "w-4 h-4")}
                        <span>Check for Updates</span>
                    </button>
                </div>
            </div>
        `;
        return;
    }

    const cardsHtml = filteredResources.map((r) => {
        let typeBadgeClass = "bg-slate-100 text-slate-700 border-slate-200";
        if (r.resource_type === "Observation") typeBadgeClass = "bg-blue-50 text-blue-700 border-blue-200";
        else if (r.resource_type === "Condition") typeBadgeClass = "bg-rose-50 text-rose-700 border-rose-200";
        else if (r.resource_type === "DiagnosticReport") typeBadgeClass = "bg-purple-50 text-purple-700 border-purple-200";
        else if (r.resource_type === "Patient") typeBadgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
        else if (r.resource_type === "DocumentReference") typeBadgeClass = "bg-teal-50 text-teal-700 border-teal-200";
        else if (r.resource_type === "Encounter") typeBadgeClass = "bg-amber-50 text-amber-700 border-amber-200";

        const rawJsonEscaped = escapeHtml(JSON.stringify(r.raw_resource || r.details, null, 2));

        return `
            <div class="bg-white rounded-xl border border-[#E5EAEA] p-4 shadow-sm hover:border-[#389B98] transition-colors space-y-3">
                <div class="flex items-start justify-between gap-3">
                    <div class="space-y-1">
                        <div class="flex items-center space-x-2">
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold font-mono border ${typeBadgeClass}">
                                ${escapeHtml(r.resource_type)}
                            </span>
                            <span class="text-xs font-mono text-slate-400">ID: ${escapeHtml(r.id)}</span>
                        </div>
                        <h5 class="text-xs font-bold text-slate-800 leading-snug">
                            ${escapeHtml(r.title)}
                        </h5>
                    </div>

                    <div class="text-right flex-shrink-0">
                        ${r.status ? `
                            <span class="px-2 py-0.5 rounded text-[10px] font-medium uppercase font-mono ${getStatusBadgeClass(r.status)}">
                                ${escapeHtml(r.status)}
                            </span>
                        ` : ""}
                        ${r.date ? `<div class="text-[10px] text-slate-400 font-mono mt-1">${formatDateShort(r.date)}</div>` : ""}
                    </div>
                </div>

                <!-- Structured Clinical Attributes Chips -->
                ${renderFhirResourceAttributes(r)}

                <!-- Expandable JSON Raw View -->
                <details class="text-xs border-t border-slate-100 pt-2">
                    <summary class="cursor-pointer text-[11px] font-medium text-[#389B98] hover:underline flex items-center space-x-1 select-none">
                        <span>View Raw FHIR JSON</span>
                    </summary>
                    <pre class="mt-2 bg-[#F7F9FA] border border-[#E5EAEA] rounded-lg p-3 text-[11px] font-mono text-slate-800 overflow-x-auto max-h-48 leading-relaxed">${rawJsonEscaped}</pre>
                </details>
            </div>
        `;
    }).join("");

    container.innerHTML = `
        <div class="p-6 space-y-4">
            <!-- Header with Live Sync Status & Actions -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 bg-white p-3.5 rounded-xl border border-[#E5EAEA] shadow-2xs">
                <div class="flex items-center space-x-2.5">
                    <span class="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        <span>Live Synced: ${fetchedTimeStr}</span>
                    </span>
                    <span class="text-xs font-mono font-bold text-slate-600">
                        ${allResources.length} Total Resources
                    </span>
                </div>
                <div class="flex items-center space-x-2 self-end sm:self-auto">
                    <button
                        id="btn-refresh-fhir"
                        onclick="refreshDrawerFhirResources(false)"
                        class="px-3 py-1.5 text-xs font-semibold text-slate-700 hover:text-[#389B98] bg-slate-50 hover:bg-white border border-[#E5EAEA] hover:border-[#389B98] rounded-xl transition-all flex items-center space-x-1.5 cursor-pointer"
                        title="Fetch latest linked FHIR resources from database"
                    >
                        ${iconSvg("refresh", "w-3.5 h-3.5")}
                        <span>Refresh State</span>
                    </button>
                    <button
                        id="btn-normalize-fhir"
                        onclick="triggerDrawerFhirNormalization()"
                        class="px-3 py-1.5 text-xs font-semibold text-white bg-[#389B98] hover:bg-[#287F7D] rounded-xl transition-all flex items-center space-x-1.5 shadow-2xs cursor-pointer"
                        title="Re-assemble and validate HL7 FHIR R4 Bundle"
                    >
                        ${iconSvg("fhir", "w-3.5 h-3.5")}
                        <span>Re-Normalize</span>
                    </button>
                </div>
            </div>

            <!-- Filter Pills -->
            <div class="flex flex-wrap items-center gap-1.5 text-xs">
                <button
                    onclick="filterDrawerFhirResources('ALL')"
                    class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'ALL' ? 'bg-[#389B98] text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
                >
                    All (${counts.ALL})
                </button>
                ${counts.Observation > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('Observation')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'Observation' ? 'bg-blue-600 text-white' : 'bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200'}"
                    >
                        Observations (${counts.Observation})
                    </button>
                ` : ""}
                ${counts.Condition > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('Condition')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'Condition' ? 'bg-rose-600 text-white' : 'bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200'}"
                    >
                        Conditions (${counts.Condition})
                    </button>
                ` : ""}
                ${counts.DiagnosticReport > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('DiagnosticReport')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'DiagnosticReport' ? 'bg-purple-600 text-white' : 'bg-purple-50 text-purple-700 hover:bg-purple-100 border border-purple-200'}"
                    >
                        Reports (${counts.DiagnosticReport})
                    </button>
                ` : ""}
                ${counts.DocumentReference > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('DocumentReference')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'DocumentReference' ? 'bg-teal-600 text-white' : 'bg-teal-50 text-teal-700 hover:bg-teal-100 border border-teal-200'}"
                    >
                        Documents (${counts.DocumentReference})
                    </button>
                ` : ""}
                ${counts.Encounter > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('Encounter')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'Encounter' ? 'bg-amber-600 text-white' : 'bg-amber-50 text-amber-700 hover:bg-amber-100 border border-amber-200'}"
                    >
                        Encounters (${counts.Encounter})
                    </button>
                ` : ""}
                ${counts.Patient > 0 ? `
                    <button
                        onclick="filterDrawerFhirResources('Patient')"
                        class="px-2.5 py-1 rounded-lg font-semibold transition-colors cursor-pointer ${activeFilter === 'Patient' ? 'bg-emerald-600 text-white' : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200'}"
                    >
                        Patient (${counts.Patient})
                    </button>
                ` : ""}
            </div>

            <!-- Resource Cards -->
            <div class="space-y-3">
                ${cardsHtml || `
                    <div class="p-8 text-center text-xs text-slate-400 bg-white rounded-xl border border-[#E5EAEA]">
                        No resources matching category "${escapeHtml(activeFilter)}".
                    </div>
                `}
            </div>
        </div>
    `;
}

export async function refreshDrawerFhirResources(silent = false) {
    if (!currentActivePatientId) return;

    const btn = document.getElementById("btn-refresh-fhir");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `${iconSvg("spinner", "w-3.5 h-3.5 animate-spin")} <span>Refreshing...</span>`;
    }

    try {
        const bodyEl = document.getElementById("drawer-content-body");
        if (bodyEl && currentActiveTab === "fhir") {
            await renderDrawerFhirTab(bodyEl, true);
        } else {
            const freshRes = await getPatientFhirResources(currentActivePatientId);
            cachedFhirState = {
                patientId: currentActivePatientId,
                resources: Array.isArray(freshRes) ? freshRes : [],
                fetchedAt: new Date(),
                filter: cachedFhirState.filter || "ALL",
            };
        }
        if (!silent) {
            showToast("success", "FHIR State Updated", "Linked FHIR resources are up to date.");
        }
    } catch (err) {
        showToast("error", "Refresh Failed", err.message || "Failed to refresh FHIR resources");
    } finally {
        if (btn) {
            btn.disabled = false;
        }
    }
}

export function filterDrawerFhirResources(filterType) {
    cachedFhirState.filter = filterType;
    const bodyEl = document.getElementById("drawer-content-body");
    if (bodyEl && currentActiveTab === "fhir") {
        renderDrawerFhirTab(bodyEl, false);
    }
}

export function invalidatePatientFhirCache(patientId) {
    if (cachedFhirState.patientId === patientId || !patientId) {
        cachedFhirState = { patientId: null, resources: null, fetchedAt: null, filter: "ALL" };
    }
}

export async function triggerDrawerFhirNormalization() {
    if (!currentActivePatientId) return;

    const btn = document.getElementById("btn-normalize-fhir");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `${iconSvg("spinner", "w-3.5 h-3.5 animate-spin")} <span>Normalizing...</span>`;
    }

    try {
        showToast("info", "Normalization Triggered", "Normalizing patient records into FHIR R4 Bundle...", 3000);
        await normalizePatient(currentActivePatientId, "collection");
        showToast("success", "Normalization Complete", "Patient successfully normalized to validated FHIR R4 Bundle.");
        await refreshDrawerFhirResources(true);
    } catch (err) {
        showToast("error", "Normalization Failed", err.message || "Failed to normalize patient to FHIR");
    } finally {
        if (btn) {
            btn.disabled = false;
        }
    }
}

// -----------------------------------------------------------------------------
// Drawer Tab 3: Longitudinal Records
// -----------------------------------------------------------------------------
async function renderDrawerRecordsTab(container) {
    container.innerHTML = `
        <div class="p-6 space-y-3">
            <div class="h-16 bg-slate-100 rounded-lg animate-pulse"></div>
            <div class="h-16 bg-slate-100 rounded-lg animate-pulse"></div>
            <div class="h-16 bg-slate-100 rounded-lg animate-pulse"></div>
        </div>
    `;

    try {
        if (!cachedRecords) {
            cachedRecords = await getPatientRecords(currentActivePatientId, { page: 1, pageSize: 50 });
        }

        const records = cachedRecords.items || [];
        if (records.length === 0) {
            container.innerHTML = `
                <div class="p-8 text-center text-xs text-slate-400">
                    No longitudinal clinical records found for this patient.
                </div>
            `;
            return;
        }

        const itemsHtml = records.map(rec => {
            const statusClass = getStatusBadgeClass(rec.status);
            return `
                <div class="bg-white rounded-xl border border-[#E5EAEA] p-4 shadow-sm space-y-3">
                    <div class="flex items-center justify-between text-xs border-b border-slate-100 pb-2">
                        <div class="flex items-center space-x-2">
                            <span class="font-mono font-bold text-slate-700">${escapeHtml(rec.record_type)}</span>
                            <span class="text-slate-400 font-mono text-[11px] truncate max-w-xs">ID: ${escapeHtml(rec.id)}</span>
                        </div>
                        <div class="flex items-center space-x-2">
                            <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${statusClass}">
                                ${escapeHtml(rec.status)}
                            </span>
                            <span class="text-[11px] text-slate-400 font-mono">${formatDateShort(rec.record_date || rec.created_at)}</span>
                        </div>
                    </div>
                    ${renderDrawerRecordContent(rec)}
                </div>
            `;
        }).join("");

        container.innerHTML = `
            <div class="p-6 space-y-3">
                <div class="text-xs font-bold text-slate-700 border-b border-[#E5EAEA] pb-2">
                    Longitudinal Clinical Records (${cachedRecords.total})
                </div>
                ${itemsHtml}
            </div>
        `;
    } catch (err) {
        console.error("Records loading failure:", err);
        container.innerHTML = `
            <div class="p-8 text-center text-xs text-rose-600 space-y-2">
                <p>Failed to load records: ${escapeHtml(err.message)}</p>
                <button onclick="switchDrawerTab('records')" class="px-3 py-1 bg-slate-100 hover:bg-slate-200 rounded text-slate-700 font-semibold">
                    Retry
                </button>
            </div>
        `;
    }
}

// -----------------------------------------------------------------------------
// Drawer Tab 4: Demographics & Identifiers
// -----------------------------------------------------------------------------
function renderDrawerDemographicsTab(container) {
    const d = cachedPatientDetail;
    if (!d) return;

    container.innerHTML = `
        <div class="p-6 space-y-6 text-xs text-slate-700">
            <!-- Basic Demographics -->
            <div class="bg-white p-5 rounded-xl border border-[#E5EAEA] shadow-sm space-y-4">
                <h5 class="font-bold text-slate-800 uppercase tracking-wider text-[11px] border-b border-slate-100 pb-2">
                    Canonical Demographic Information
                </h5>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <span class="text-slate-400 block text-[11px]">First Name</span>
                        <span class="font-semibold text-slate-800">${escapeHtml(d.first_name || "-")}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[11px]">Last Name</span>
                        <span class="font-semibold text-slate-800">${escapeHtml(d.last_name || "-")}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[11px]">Date of Birth</span>
                        <span class="font-semibold text-slate-800">${escapeHtml(d.date_of_birth || "-")}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[11px]">Administrative Gender</span>
                        <span class="font-semibold text-slate-800 capitalize">${escapeHtml(d.gender || "Unknown")}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[11px]">Medical Record Number (MRN)</span>
                        <span class="font-mono font-bold text-[#389B98]">${escapeHtml(d.mrn)}</span>
                    </div>
                    <div>
                        <span class="text-slate-400 block text-[11px]">Issuing Source System</span>
                        <span class="font-semibold text-slate-800">${escapeHtml(d.source_system)}</span>
                    </div>
                </div>
            </div>

            <!-- External Identifiers -->
            <div class="bg-white p-5 rounded-xl border border-[#E5EAEA] shadow-sm space-y-3">
                <h5 class="font-bold text-slate-800 uppercase tracking-wider text-[11px] border-b border-slate-100 pb-2">
                    External System Identifiers (${(d.identifiers || []).length})
                </h5>
                ${(d.identifiers && d.identifiers.length > 0) ? `
                    <div class="space-y-2">
                        ${d.identifiers.map(ident => `
                            <div class="flex items-center justify-between p-2.5 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA] font-mono text-[11px]">
                                <div>
                                    <span class="text-slate-400">${escapeHtml(ident.identifier_type)}:</span>
                                    <span class="font-bold text-slate-800 ml-1">${escapeHtml(ident.value)}</span>
                                </div>
                                <span class="text-slate-500 text-[10px]">${escapeHtml(ident.issuing_authority)}</span>
                            </div>
                        `).join("")}
                    </div>
                ` : `<p class="text-slate-400 italic">No external auxiliary identifiers mapped.</p>`}
            </div>

            <!-- Domain Counts Summary -->
            <div class="bg-white p-5 rounded-xl border border-[#E5EAEA] shadow-sm space-y-3">
                <h5 class="font-bold text-slate-800 uppercase tracking-wider text-[11px] border-b border-slate-100 pb-2">
                    Clinical Data Breakdown
                </h5>
                <div class="grid grid-cols-3 gap-2 text-center">
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Observations</span>
                        <div class="text-base font-bold text-slate-800 mt-0.5">${formatNumber(d.domain_counts.observations)}</div>
                    </div>
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Conditions</span>
                        <div class="text-base font-bold text-slate-800 mt-0.5">${formatNumber(d.domain_counts.conditions)}</div>
                    </div>
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Diagnostic Reports</span>
                        <div class="text-base font-bold text-slate-800 mt-0.5">${formatNumber(d.domain_counts.diagnostic_reports)}</div>
                    </div>
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Encounters</span>
                        <div class="text-base font-bold text-slate-800 mt-0.5">${formatNumber(d.domain_counts.encounters)}</div>
                    </div>
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Documents</span>
                        <div class="text-base font-bold text-slate-800 mt-0.5">${formatNumber(d.domain_counts.document_references)}</div>
                    </div>
                    <div class="p-3 bg-[#F7F9FA] rounded-lg border border-[#E5EAEA]">
                        <span class="text-[10px] text-slate-500 uppercase font-bold">Total Records</span>
                        <div class="text-base font-bold text-[#389B98] mt-0.5">${formatNumber(d.domain_counts.total_clinical_records)}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// Make functions accessible globally for inline handlers
window.openPatientDrawer = openPatientDrawer;
window.closePatientDrawer = closePatientDrawer;
window.switchDrawerTab = switchDrawerTab;
window.triggerDrawerSummaryGeneration = triggerDrawerSummaryGeneration;
window.triggerDrawerSummaryRegeneration = triggerDrawerSummaryRegeneration;
window.triggerDrawerFhirNormalization = triggerDrawerFhirNormalization;
window.refreshDrawerFhirResources = refreshDrawerFhirResources;
window.filterDrawerFhirResources = filterDrawerFhirResources;
window.invalidatePatientFhirCache = invalidatePatientFhirCache;


