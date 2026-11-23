/**
 * Ony(e) EHR Intelligence Platform - Root Application Entry Point.
 * Modernized 2026 SaaS ES Module Architecture.
 */

import { checkSystemHealth, switchMainTab, initSidebarState, closeMobileNav } from "./components/navigation.js";
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
    // 1. Initialize responsive sidebar preference
    initSidebarState();

    // 2. Initial health monitoring & periodic check
    checkSystemHealth();
    setInterval(checkSystemHealth, 20000);

    // 3. Setup interaction listeners
    setupSearchListeners();
    setupIngestionListeners();

    // 4. Global Escape key listener for closing modals, drawers, and mobile nav
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeMobileNav();
            closePatientDrawer();
            closeRecordModal();
            closeFhirBundleModal();
            closeFhirReportModal();
            closeJobReportModal();
        }
    });

    // 5. Auto close mobile nav drawer when resizing to desktop/laptop breakpoint
    window.addEventListener("resize", () => {
        if (window.innerWidth >= 1024) {
            closeMobileNav();
        }
    });

    // 6. Handle hash changes dynamically
    window.addEventListener("hashchange", () => {
        const hash = window.location.hash.replace("#", "").trim();
        if (["dashboard", "search", "patients", "ingest", "jobs", "explorer", "fhir"].includes(hash)) {
            switchMainTab(hash);
        }
    });

    // 7. Initial Tab from URL hash or default to 'dashboard'
    const initialHash = window.location.hash.replace("#", "").trim();
    if (initialHash && ["dashboard", "search", "patients", "ingest", "jobs", "explorer", "fhir"].includes(initialHash)) {
        switchMainTab(initialHash);
    } else {
        switchMainTab("dashboard");
    }
});
