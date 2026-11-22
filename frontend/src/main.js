/**
 * Ony(e) EHR Intelligence Platform - Root Application Entry Point.
 * Modernized ES Module Architecture.
 */

import { checkSystemHealth, switchMainTab } from "./components/navigation.js";
import { loadDashboardOverview } from "./components/dashboard.js";
import { setupSearchListeners } from "./components/search.js";
import { setupIngestionListeners } from "./components/ingestion.js";
import { closePatientDrawer } from "./components/drawer.js";
import {
    closeRecordModal,
    closeFhirBundleModal,
    closeFhirReportModal,
    closeJobReportModal,
} from "./components/modals.js";

// Make sure global handlers are bound
import "./components/drawer.js";
import "./components/modals.js";
import "./components/dashboard.js";
import "./components/search.js";
import "./components/patients.js";
import "./components/ingestion.js";
import "./components/jobs.js";
import "./components/fhir.js";
import "./components/explorer.js";

document.addEventListener("DOMContentLoaded", () => {
    // 1. Initial health monitoring & periodic check
    checkSystemHealth();
    setInterval(checkSystemHealth, 20000);

    // 2. Setup interaction listeners
    setupSearchListeners();
    setupIngestionListeners();

    // 3. Global Escape key listener for closing modals and drawer
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closePatientDrawer();
            closeRecordModal();
            closeFhirBundleModal();
            closeFhirReportModal();
            closeJobReportModal();
        }
    });

    // 4. Initial Tab from URL hash or default to 'dashboard'
    const initialHash = window.location.hash.replace("#", "").trim();
    if (initialHash && ["dashboard", "search", "patients", "ingest", "jobs", "explorer", "fhir"].includes(initialHash)) {
        switchMainTab(initialHash);
    } else {
        switchMainTab("dashboard");
    }
});
