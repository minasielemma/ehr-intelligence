/**
 * Top Navigation & System Health Monitoring Component.
 * Employs Ony(e) branding colors, tab transitions, and live dependency monitoring.
 */
import { getSystemHealth } from "../api/dashboard.js";
import { loadDashboardOverview } from "./dashboard.js";
import { loadPatientsDirectory } from "./patients.js";
import { loadIngestionJobsList } from "./jobs.js";
import { loadInitialExplorerData } from "./explorer.js";
import { loadStoredFhirBundles } from "./fhir.js";

const ALL_TABS = ["dashboard", "search", "patients", "ingest", "jobs", "explorer", "fhir"];

export async function checkSystemHealth() {
    const backendStatusEl = document.getElementById("backend-status");
    const backendIndicatorEl = document.getElementById("backend-indicator");
    const vectorStatusEl = document.getElementById("vector-status");
    const vectorIndicatorEl = document.getElementById("vector-indicator");

    try {
        const data = await getSystemHealth();

        if (backendIndicatorEl && backendStatusEl) {
            backendIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
            backendStatusEl.textContent = `Online (${data.environment || "dev"})`;
        }

        if (vectorIndicatorEl && vectorStatusEl) {
            if (data.services && data.services.vector_store) {
                const vs = data.services.vector_store;
                if (vs.status === "healthy") {
                    vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
                    vectorStatusEl.textContent = "Connected";
                } else {
                    vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
                    vectorStatusEl.textContent = vs.status;
                }
            }
        }
    } catch {
        if (backendIndicatorEl && backendStatusEl) {
            backendIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-[#DE3449]";
            backendStatusEl.textContent = "Offline";
        }
        if (vectorIndicatorEl && vectorStatusEl) {
            vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-slate-400";
            vectorStatusEl.textContent = "Unreachable";
        }
    }
}

export function switchMainTab(tab) {
    if (!ALL_TABS.includes(tab)) tab = "dashboard";

    ALL_TABS.forEach(t => {
        const btn = document.getElementById(`tab-btn-${t}`);
        const content = document.getElementById(`tab-content-${t}`);
        if (!btn || !content) return;

        if (t === tab) {
            btn.className = "tab-button border-b-2 border-[#389B98] text-[#389B98] pb-3 flex items-center space-x-2 font-semibold transition-colors";
            content.classList.remove("hidden");

            // Lazy load tab data on entry
            if (t === "dashboard") {
                loadDashboardOverview(false);
            } else if (t === "patients") {
                loadPatientsDirectory(1);
            } else if (t === "jobs") {
                loadIngestionJobsList(1);
            } else if (t === "explorer") {
                loadInitialExplorerData();
            } else if (t === "fhir") {
                loadStoredFhirBundles(1);
            }
        } else {
            btn.className = "tab-button border-b-2 border-transparent text-slate-500 hover:text-slate-800 pb-3 flex items-center space-x-2 font-medium transition-colors";
            content.classList.add("hidden");
        }
    });

    // Update URL hash without reload
    window.location.hash = tab;
}

// Window bindings
window.switchMainTab = switchMainTab;
