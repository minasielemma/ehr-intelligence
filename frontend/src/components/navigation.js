/**
 * Navigation, App Shell & System Health Monitoring Component.
 * Supports modern 2026 SaaS layout:
 * - Collapsible Desktop & Tablet Sidebar
 * - Off-Canvas Mobile Navigation Drawer
 * - Top App Header with dynamic breadcrumbs & health pills
 * - Preserves all existing tab routes and lazy data loading
 */
import { getSystemHealth } from "../api/dashboard.js";
import { loadDashboardOverview } from "./dashboard.js";
import { loadPatientsDirectory } from "./patients.js";
import { loadIngestionJobsList } from "./jobs.js";
import { loadInitialExplorerData } from "./explorer.js";
import { loadStoredFhirBundles } from "./fhir.js";

export const ALL_TABS = ["dashboard", "search", "patients", "ingest", "jobs", "explorer", "fhir"];

export const TAB_METADATA = {
    dashboard: {
        title: "Clinical Overview Dashboard",
        shortTitle: "Dashboard",
        description: "Real-time clinical intelligence, FHIR R4 graph distribution & patient reconciliation",
        badge: "Live Telemetry"
    },
    search: {
        title: "Clinical Semantic Search & AI Summaries",
        shortTitle: "Semantic Search",
        description: "Dense vector retrieval across longitudinal records, lab reports, and AI clinical summaries",
        badge: "Dense HNSW"
    },
    patients: {
        title: "Canonical Patient Directory",
        shortTitle: "Patients",
        description: "Reconciled patient demographics, longitudinal timeline, and clinical records",
        badge: "Reconciled"
    },
    ingest: {
        title: "Ingest & Clean EHR Data",
        shortTitle: "Ingest Data",
        description: "Multi-domain CSV, JSON, and archive ingestion with dosage and vitals preservation",
        badge: "100MB Max"
    },
    jobs: {
        title: "Ingestion Batches & Lifecycle",
        shortTitle: "Batches",
        description: "Historical batch execution metrics, anomaly logs, and reconciliation audits",
        badge: "Batches"
    },
    explorer: {
        title: "Canonical Records & Ingestion Audit",
        shortTitle: "Records Audit",
        description: "Inspect parsed intermediate schemas, unit conversions, and append-only audit trail",
        badge: "Append-Only"
    },
    fhir: {
        title: "HL7 FHIR R4 Bundles & Conformance",
        shortTitle: "FHIR R4",
        description: "Connected FHIR R4 Bundle normalization, SQLite persistence, and validation reports",
        badge: "Gatekeeper"
    }
};

/**
 * System Health polling and status indicators updater.
 */
export async function checkSystemHealth() {
    const backendStatusEls = document.querySelectorAll(".backend-status-text");
    const backendIndicatorEls = document.querySelectorAll(".backend-indicator-dot");
    const vectorStatusEls = document.querySelectorAll(".vector-status-text");
    const vectorIndicatorEls = document.querySelectorAll(".vector-indicator-dot");

    // Also support original element IDs for backwards compatibility
    const oldBackendStatus = document.getElementById("backend-status");
    const oldBackendIndicator = document.getElementById("backend-indicator");
    const oldVectorStatus = document.getElementById("vector-status");
    const oldVectorIndicator = document.getElementById("vector-indicator");

    try {
        const data = await getSystemHealth();
        const envText = data.environment || "dev";

        const setHealthy = (indicators, texts, statusText) => {
            indicators.forEach(el => {
                el.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-sm";
            });
            texts.forEach(el => {
                el.textContent = statusText;
            });
        };

        setHealthy(backendIndicatorEls, backendStatusEls, `Online (${envText})`);
        if (oldBackendIndicator && oldBackendStatus) {
            oldBackendIndicator.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
            oldBackendStatus.textContent = `Online (${envText})`;
        }

        if (data.services && data.services.vector_store) {
            const vs = data.services.vector_store;
            if (vs.status === "healthy") {
                setHealthy(vectorIndicatorEls, vectorStatusEls, "Connected");
                if (oldVectorIndicator && oldVectorStatus) {
                    oldVectorIndicator.className = "w-2.5 h-2.5 rounded-full bg-emerald-500";
                    oldVectorStatus.textContent = "Connected";
                }
            } else {
                vectorIndicatorEls.forEach(el => el.className = "w-2.5 h-2.5 rounded-full bg-amber-500");
                vectorStatusEls.forEach(el => el.textContent = vs.status);
                if (oldVectorIndicator && oldVectorStatus) {
                    oldVectorIndicator.className = "w-2.5 h-2.5 rounded-full bg-amber-500";
                    oldVectorStatus.textContent = vs.status;
                }
            }
        }
    } catch {
        const setOffline = (indicators, texts, statusText) => {
            indicators.forEach(el => {
                el.className = "w-2.5 h-2.5 rounded-full bg-[#DE3449]";
            });
            texts.forEach(el => {
                el.textContent = statusText;
            });
        };

        setOffline(backendIndicatorEls, backendStatusEls, "Offline");
        if (oldBackendIndicator && oldBackendStatus) {
            oldBackendIndicator.className = "w-2.5 h-2.5 rounded-full bg-[#DE3449]";
            oldBackendStatus.textContent = "Offline";
        }

        vectorIndicatorEls.forEach(el => el.className = "w-2.5 h-2.5 rounded-full bg-slate-400");
        vectorStatusEls.forEach(el => el.textContent = "Unreachable");
        if (oldVectorIndicator && oldVectorStatus) {
            oldVectorIndicator.className = "w-2.5 h-2.5 rounded-full bg-slate-400";
            oldVectorStatus.textContent = "Unreachable";
        }
    }
}

/**
 * Switches the active main section/tab with smooth transitions and lazy loading.
 * Synchronizes desktop sidebar, mobile drawer, and top header breadcrumb.
 */
export function switchMainTab(tab) {
    if (!ALL_TABS.includes(tab)) tab = "dashboard";

    ALL_TABS.forEach(t => {
        const content = document.getElementById(`tab-content-${t}`);
        const sidebarBtn = document.getElementById(`sidebar-btn-${t}`);
        const mobileBtn = document.getElementById(`mobile-btn-${t}`);
        const legacyBtn = document.getElementById(`tab-btn-${t}`);

        const isActive = t === tab;

        // 1. Content Visibility
        if (content) {
            if (isActive) {
                content.classList.remove("hidden");
                content.classList.add("animate-in", "fade-in", "duration-200");
            } else {
                content.classList.add("hidden");
                content.classList.remove("animate-in", "fade-in", "duration-200");
            }
        }

        // 2. Sidebar Navigation Items
        if (sidebarBtn) {
            if (isActive) {
                sidebarBtn.className = "sidebar-nav-item group flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold bg-[#389B98]/10 text-[#389B98] border border-[#389B98]/20 transition-all shadow-xs";
                sidebarBtn.setAttribute("aria-current", "page");
            } else {
                sidebarBtn.className = "sidebar-nav-item group flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-all border border-transparent";
                sidebarBtn.removeAttribute("aria-current");
            }
        }

        // 3. Mobile Navigation Drawer Items
        if (mobileBtn) {
            if (isActive) {
                mobileBtn.className = "flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-semibold bg-[#389B98]/10 text-[#389B98] border border-[#389B98]/20 transition-all";
                mobileBtn.setAttribute("aria-current", "page");
            } else {
                mobileBtn.className = "flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-all border border-transparent";
                mobileBtn.removeAttribute("aria-current");
            }
        }

        // 4. Legacy Tab Buttons (if present)
        if (legacyBtn) {
            if (isActive) {
                legacyBtn.className = "tab-button border-b-2 border-[#389B98] text-[#389B98] pb-1.5 flex items-center space-x-2 whitespace-nowrap font-semibold transition-colors";
            } else {
                legacyBtn.className = "tab-button border-b-2 border-transparent text-slate-500 hover:text-slate-800 pb-1.5 flex items-center space-x-2 whitespace-nowrap font-medium transition-colors";
            }
        }
    });

    // 5. Update Header Breadcrumb and Section Title
    const meta = TAB_METADATA[tab] || TAB_METADATA.dashboard;
    const headerTitleEl = document.getElementById("header-section-title");
    const headerBadgeEl = document.getElementById("header-section-badge");
    const headerDescEl = document.getElementById("header-section-desc");

    if (headerTitleEl) headerTitleEl.textContent = meta.title;
    if (headerBadgeEl) headerBadgeEl.textContent = meta.badge;
    if (headerDescEl) headerDescEl.textContent = meta.description;

    // 6. Close Mobile Drawer after navigation
    closeMobileNav();

    // 7. Lazy load tab data on initial or explicit navigation
    if (tab === "dashboard") {
        loadDashboardOverview(false);
    } else if (tab === "patients") {
        loadPatientsDirectory(1);
    } else if (tab === "jobs") {
        loadIngestionJobsList(1);
    } else if (tab === "explorer") {
        loadInitialExplorerData();
    } else if (tab === "fhir") {
        loadStoredFhirBundles(1);
    }

    // 8. Update URL hash without browser jump
    if (window.location.hash.replace("#", "") !== tab) {
        history.replaceState(null, "", `#${tab}`);
    }
}

/**
 * Toggle Collapsed / Expanded state of Desktop Sidebar.
 */
export function toggleSidebarCollapse(forceState = null) {
    const sidebar = document.getElementById("app-sidebar");
    const toggleIcon = document.getElementById("sidebar-toggle-icon");
    if (!sidebar) return;

    let willCollapse;
    if (typeof forceState === "boolean") {
        willCollapse = forceState;
    } else {
        willCollapse = !sidebar.classList.contains("collapsed");
    }

    if (willCollapse) {
        sidebar.classList.add("collapsed");
        if (toggleIcon) toggleIcon.classList.add("rotate-180");
        try { localStorage.setItem("onye_sidebar_collapsed", "true"); } catch (e) {}
    } else {
        sidebar.classList.remove("collapsed");
        if (toggleIcon) toggleIcon.classList.remove("rotate-180");
        try { localStorage.setItem("onye_sidebar_collapsed", "false"); } catch (e) {}
    }
}

/**
 * Initialize Desktop Sidebar state from persisted preference.
 */
export function initSidebarState() {
    try {
        const saved = localStorage.getItem("onye_sidebar_collapsed");
        // On tablet screens (768px - 1024px), collapse by default to preserve content width
        const isTablet = window.innerWidth >= 768 && window.innerWidth < 1024;
        if (saved === "true" || (saved === null && isTablet)) {
            toggleSidebarCollapse(true);
        }
    } catch (e) {}
}

/**
 * Open Mobile Off-Canvas Navigation Drawer.
 */
export function openMobileNav() {
    const drawer = document.getElementById("mobile-nav-drawer");
    const backdrop = document.getElementById("mobile-nav-backdrop");

    if (drawer && backdrop) {
        backdrop.classList.remove("hidden");
        // Small delay to allow CSS transition
        requestAnimationFrame(() => {
            drawer.classList.add("open");
        });
        document.body.style.overflow = "hidden";
    }
}

/**
 * Close Mobile Off-Canvas Navigation Drawer.
 */
export function closeMobileNav() {
    const drawer = document.getElementById("mobile-nav-drawer");
    const backdrop = document.getElementById("mobile-nav-backdrop");

    if (drawer && backdrop) {
        drawer.classList.remove("open");
        setTimeout(() => {
            backdrop.classList.add("hidden");
        }, 200);
        document.body.style.overflow = "";
    }
}

/**
 * Toggle Mobile Off-Canvas Navigation Drawer.
 */
export function toggleMobileNav() {
    const drawer = document.getElementById("mobile-nav-drawer");
    if (drawer && drawer.classList.contains("open")) {
        closeMobileNav();
    } else {
        openMobileNav();
    }
}

// Window bindings for inline HTML handlers
window.switchMainTab = switchMainTab;
window.toggleSidebarCollapse = toggleSidebarCollapse;
window.openMobileNav = openMobileNav;
window.closeMobileNav = closeMobileNav;
window.toggleMobileNav = toggleMobileNav;
