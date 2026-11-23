/**
 * Toast Notification Component for user-facing status and error alerts.
 */
import { iconSvg } from "../utils/icons.js";
import { escapeHtml } from "../utils/formatters.js";

let toastContainer = null;

function ensureToastContainer() {
    if (!toastContainer) {
        toastContainer = document.getElementById("toast-container");
        if (!toastContainer) {
            toastContainer = document.createElement("div");
            toastContainer.id = "toast-container";
            toastContainer.className = "fixed bottom-4 inset-x-4 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-96 z-50 flex flex-col space-y-2 pointer-events-none";
            document.body.appendChild(toastContainer);
        }
    }
    return toastContainer;
}

export function showToast(type = "info", title = "", message = "", durationMs = 5000) {
    const container = ensureToastContainer();

    let displayMsg = message;
    if (displayMsg instanceof Error) {
        displayMsg = displayMsg.message;
    } else if (typeof displayMsg === "object" && displayMsg !== null) {
        if (typeof displayMsg.error_message === "string" && displayMsg.error_message.trim()) {
            displayMsg = displayMsg.error_message.trim();
        } else if (typeof displayMsg.message === "string" && displayMsg.message.trim()) {
            displayMsg = displayMsg.message.trim();
        } else if (Array.isArray(displayMsg.detail)) {
            displayMsg = displayMsg.detail.map(d => {
                if (typeof d === "string") return d;
                const loc = Array.isArray(d.loc) ? d.loc.filter(l => l !== "body").join(".") : "";
                const msg = d.msg || d.message || JSON.stringify(d);
                return loc ? `${loc}: ${msg}` : msg;
            }).join("; ");
        } else if (typeof displayMsg.detail === "string" && displayMsg.detail.trim()) {
            displayMsg = displayMsg.detail.trim();
        } else if (Array.isArray(displayMsg)) {
            displayMsg = displayMsg.map(d => (typeof d === "string" ? d : (d.msg || d.message || JSON.stringify(d)))).join("; ");
        } else {
            displayMsg = JSON.stringify(displayMsg);
        }
    }
    displayMsg = String(displayMsg || "");

    const toast = document.createElement("div");
    toast.className = "pointer-events-auto flex items-start space-x-3 p-4 rounded-xl border shadow-lg bg-white transition-all transform duration-300 opacity-0 translate-y-2";

    let borderCol = "border-slate-200 text-slate-800";
    let iconName = "check";
    let iconCol = "text-[#389B98] bg-[#389B98]/10";

    if (type === "success") {
        borderCol = "border-emerald-200 text-slate-800";
        iconName = "check";
        iconCol = "text-emerald-600 bg-emerald-50";
    } else if (type === "error") {
        borderCol = "border-rose-200 text-slate-800";
        iconName = "close";
        iconCol = "text-[#DE3449] bg-[#DE3449]/10";
    } else if (type === "warning") {
        borderCol = "border-amber-200 text-slate-800";
        iconName = "refresh";
        iconCol = "text-amber-600 bg-amber-50";
    }

    toast.classList.add(borderCol.split(" ")[0]);

    toast.innerHTML = `
        <div class="p-1.5 rounded-lg ${iconCol} flex-shrink-0">
            ${iconSvg(iconName, "w-4 h-4")}
        </div>
        <div class="flex-1 min-w-0">
            ${title ? `<h4 class="text-xs font-bold text-slate-800">${escapeHtml(title)}</h4>` : ""}
            <p class="text-xs text-slate-600 mt-0.5 leading-relaxed break-words">${escapeHtml(displayMsg)}</p>
        </div>
        <button class="text-slate-400 hover:text-slate-600 p-1 rounded-md text-xs" onclick="this.parentElement.remove()">
            &times;
        </button>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.classList.remove("opacity-0", "translate-y-2");
        toast.classList.add("opacity-100", "translate-y-0");
    });

    const activeDuration = type === "error" ? Math.max(durationMs, 7500) : durationMs;

    // Auto remove
    if (activeDuration > 0) {
        setTimeout(() => {
            toast.classList.remove("opacity-100", "translate-y-0");
            toast.classList.add("opacity-0", "translate-y-2");
            setTimeout(() => toast.remove(), 300);
        }, activeDuration);
    }
}
