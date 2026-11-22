/**
 * Formatting and sanitization utility helpers.
 */

export function escapeHtml(str) {
    if (!str && str !== 0) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export function formatDate(isoString) {
    if (!isoString) return "-";
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return String(isoString);
        return d.toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return String(isoString);
    }
}

export function formatDateShort(isoString) {
    if (!isoString) return "-";
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return String(isoString);
        return d.toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
        });
    } catch {
        return String(isoString);
    }
}

export function formatNumber(num) {
    if (num === null || num === undefined) return "0";
    return Number(num).toLocaleString();
}

export function formatBytes(bytes, decimals = 1) {
    if (!bytes || bytes === 0) return "0 B";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export function truncateText(text, maxLength = 120) {
    if (!text) return "";
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength).trim() + "...";
}

export function getStatusBadgeClass(status) {
    const s = String(status || "").toUpperCase();
    switch (s) {
        case "COMPLETED":
        case "NORMALIZED":
        case "VALID":
        case "HEALTHY":
        case "ONLINE":
            return "bg-emerald-50 text-emerald-700 border-emerald-200";
        case "PROCESSING":
        case "PENDING":
        case "WARNING":
            return "bg-amber-50 text-amber-700 border-amber-200";
        case "FAILED":
        case "REJECTED":
        case "ERROR":
        case "UNREACHABLE":
        case "DEGRADED":
            return "bg-rose-50 text-rose-700 border-rose-200";
        case "DUPLICATE":
            return "bg-purple-50 text-purple-700 border-purple-200";
        case "MANUAL_REVIEW_REQUIRED":
            return "bg-orange-50 text-orange-700 border-orange-200";
        default:
            return "bg-slate-100 text-slate-700 border-slate-200";
    }
}

/**
 * Human-readable clinical preview for canonical records table (avoids raw JSON).
 */
export function formatClinicalSummaryPreview(rec) {
    if (!rec) return "-";
    if (rec.cleaned_text && rec.cleaned_text.trim()) {
        return rec.cleaned_text.substring(0, 85);
    }
    const p = rec.parsed_payload;
    if (p && typeof p === "object") {
        const parts = [];
        if (p.concept_name || p.display || p.test_name || p.title) {
            parts.push(p.concept_name || p.display || p.test_name || p.title);
        }
        if (p.value !== undefined) {
            parts.push(`${p.value} ${p.unit || ''}`.trim());
        }
        if (p.diagnosis || p.condition) {
            parts.push(p.diagnosis || p.condition);
        }
        if (p.reason || p.encounter_type || p.record_type) {
            parts.push(p.reason || p.encounter_type || p.record_type);
        }
        if (parts.length > 0) return parts.join(" • ").substring(0, 85);

        // Readable fallback key-values
        const keys = Object.entries(p)
            .filter(([k, v]) => typeof v !== "object" && k !== "patient_id" && k !== "record_id" && k !== "id")
            .slice(0, 3)
            .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
            .join(" | ");
        if (keys) return keys.substring(0, 85);
    }
    return "Canonical clinical record";
}

