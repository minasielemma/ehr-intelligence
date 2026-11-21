/**
 * EHR Intelligence Platform - Frontend Ingestion & Normalization Client
 */

let currentJobId = null;
let currentPage = 1;
let totalPages = 1;
let currentRecords = [];
let jobPollingInterval = null;

const API_KEY = localStorage.getItem("ehr_api_key") || "dev-test-key";
function getAuthHeaders(extra = {}) {
    return {
        "X-API-Key": API_KEY,
        ...extra,
    };
}

// =============================================================================
// 1. Health Monitoring
// =============================================================================

async function checkBackendHealth() {
    const backendStatusEl = document.getElementById("backend-status");
    const backendIndicatorEl = document.getElementById("backend-indicator");
    const vectorStatusEl = document.getElementById("vector-status");
    const vectorIndicatorEl = document.getElementById("vector-indicator");

    try {
        const response = await fetch("/api/v1/health");
        if (response.ok) {
            const data = await response.json();
            backendIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
            backendStatusEl.textContent = `Online (${data.environment})`;

            if (data.services && data.services.vector_store) {
                const vs = data.services.vector_store;
                if (vs.status === "healthy") {
                    vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
                    vectorStatusEl.textContent = "Connected";
                } else {
                    vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-amber-400";
                    vectorStatusEl.textContent = vs.status;
                }
            }
        } else {
            throw new Error(`HTTP ${response.status}`);
        }
    } catch (err) {
        backendIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-rose-500";
        backendStatusEl.textContent = "Offline";
        vectorIndicatorEl.className = "w-2.5 h-2.5 rounded-full bg-slate-600";
        vectorStatusEl.textContent = "Unreachable";
    }
}

// =============================================================================
// 2. Navigation & View Switching
// =============================================================================

function switchMainTab(tab) {
    const tabs = ["ingest", "jobs", "explorer", "fhir"];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-btn-${t}`);
        const content = document.getElementById(`tab-content-${t}`);
        if (t === tab) {
            btn.className = "tab-button border-b-2 border-blue-500 text-blue-400 pb-3 flex items-center space-x-2";
            content.classList.remove("hidden");
            if (t === "fhir") {
                loadStoredFhirBundles();
            }
        } else {
            btn.className = "tab-button border-b-2 border-transparent text-slate-400 hover:text-slate-200 pb-3 flex items-center space-x-2";
            content.classList.add("hidden");
        }
    });
}

function switchIngestMode(mode) {
    const filePanel = document.getElementById("ingest-file-panel");
    const jsonPanel = document.getElementById("ingest-json-panel");
    const fileBtn = document.getElementById("mode-file-btn");
    const jsonBtn = document.getElementById("mode-json-btn");

    if (mode === "file") {
        filePanel.classList.remove("hidden");
        jsonPanel.classList.add("hidden");
        fileBtn.className = "px-4 py-1.5 rounded-md bg-blue-600 text-white shadow";
        jsonBtn.className = "px-4 py-1.5 rounded-md text-slate-400 hover:text-slate-200";
    } else {
        filePanel.classList.add("hidden");
        jsonPanel.classList.remove("hidden");
        fileBtn.className = "px-4 py-1.5 rounded-md text-slate-400 hover:text-slate-200";
        jsonBtn.className = "px-4 py-1.5 rounded-md bg-blue-600 text-white shadow";
    }
}

// =============================================================================
// 3. Drag and Drop & File Upload Handling
// =============================================================================

function setupDragAndDrop() {
    const dropZone = document.getElementById("drop-zone");
    if (!dropZone) return;

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add("border-blue-500", "bg-blue-950/20");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove("border-blue-500", "bg-blue-950/20");
        });
    });

    dropZone.addEventListener("drop", e => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            document.getElementById("file-input").files = files;
            handleFileSelected(files);
        }
    });
}

function handleFileSelected(files) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const displayEl = document.getElementById("selected-file-display");
    const nameEl = document.getElementById("selected-file-name");
    const sizeEl = document.getElementById("selected-file-size");

    const sizeKb = (file.size / 1024).toFixed(1);
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    const sizeStr = file.size > 1024 * 1024 ? `${sizeMb} MB` : `${sizeKb} KB`;

    nameEl.textContent = file.name;
    sizeEl.textContent = `(${sizeStr})`;
    displayEl.classList.remove("hidden");
    displayEl.classList.add("inline-flex");
}

async function handleFileUpload(event) {
    event.preventDefault();
    const fileInput = document.getElementById("file-input");
    const sourceSystem = document.getElementById("file-source-system").value;
    const idempotencyKey = document.getElementById("file-idempotency-key").value;
    const syncMode = document.getElementById("file-sync-mode").value === "true";

    if (!fileInput.files || fileInput.files.length === 0) {
        showResultAlert("error", "Validation Error", "Please select or drag an EHR file to upload (.json, .csv, or .txt).");
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);
    formData.append("source_system", sourceSystem);
    if (idempotencyKey) {
        formData.append("idempotency_key", idempotencyKey);
    }

    setButtonLoading("file-submit-btn", true, "Uploading & Processing...");

    try {
        const url = `/api/v1/ingestion/upload?sync=${syncMode}`;
        const response = await fetch(url, {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (response.status === 201 || response.status === 200) {
            currentJobId = data.job_id;
            showResultAlert("success", "Ingestion Completed Successfully!", 
                `Job ID: ${data.job_id} | Processed: ${data.total_records} records | Normalized: ${data.successful_records} | Duplicates: ${data.duplicate_records} | Conflicts: ${data.conflict_records}`);
            updateJobCard(data);
            loadJobReport(data.job_id);
            loadRecordsPage(1);
        } else if (response.status === 202) {
            currentJobId = data.job_id;
            showResultAlert("info", "Background Ingestion Enqueued (HTTP 202)", 
                `Job ID: ${data.job_id} is running in the background. Polling for completion...`);
            updateJobCard(data);
            startJobPolling(data.job_id);
        } else {
            const errDetail = data.error ? data.error.message : (data.detail || "Upload rejected.");
            showResultAlert("error", `Ingestion Failed (${response.status})`, errDetail);
        }
    } catch (err) {
        showResultAlert("error", "Network / Server Error", err.message || "Failed to communicate with ingestion API.");
    } finally {
        setButtonLoading("file-submit-btn", false, "Process Ingestion File");
    }
}

// =============================================================================
// 4. Sample File Loaders & Direct JSON Console
// =============================================================================

function loadSampleFile(type) {
    let filename = "";
    let content = "";
    let mime = "";

    if (type === "csv") {
        filename = "simulated_patients.csv";
        mime = "text/csv";
        content = "mrn,first_name,last_name,dob,gender,clinical_text\n" +
                  "00099812,Clara,Barton,1978-12-25,F,\"Patient presents with persistent cough. BP: 120/80 mmHg.\"\n" +
                  "00099813,Florence,Nightingale,03/24/1982,Female,\"Follow-up visit. Labs: HbA1c 5.6%. Prescribed Metformin 500mg BID.\"\n" +
                  "00099814,Marie,Curie,1867-11-07,2,\"Oncology evaluation. No acute distress.\"\n";
    } else if (type === "json") {
        filename = "ehr_export.json";
        mime = "application/json";
        content = JSON.stringify([
            {
                id: "REC-J1",
                mrn: "  0018491  ",
                first_name: "Alexander",
                last_name: "Fleming",
                dob: "1881-08-06",
                gender: "M",
                clinical_text: "Prescribed Penicillin 500mg TID. Patient tolerating regimen well.\r\nVitals: Temp 36.8°C, HR 70 bpm.\x00"
            },
            {
                id: "REC-J2",
                mrn: "0018492",
                first_name: "Louis",
                last_name: "Pasteur",
                dob: "1822-12-27",
                gender: "Male",
                clinical_text: "Vaccination protocol consultation completed. SpO2: 99%."
            }
        ], null, 2);
    } else if (type === "txt") {
        filename = "clinical_progress_note.txt";
        mime = "text/plain";
        content = "PATIENT NAME: Lovelace, Augusta\n" +
                  "MRN: 0088471\n" +
                  "DOB: 1980-04-18\n" +
                  "GENDER: Female\n" +
                  "REPORT TYPE: Progress Note\n\n" +
                  "CLINICAL IMPRESSION:\n" +
                  "Patient recovering well. Cardiopulmonary exam normal.\n" +
                  "Vitals: BP 118/76 mmHg, HR 68 bpm, SpO2 99% on room air.\n" +
                  "Current Medications: Lisinopril 10mg daily PO.\n";
    }

    const blob = new Blob([content], { type: mime });
    const file = new File([blob], filename, { type: mime });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    document.getElementById("file-input").files = dataTransfer.files;
    handleFileSelected(dataTransfer.files);
}

function fillSampleJSON(type) {
    const input = document.getElementById("json-records-input");
    if (type === "messy") {
        input.value = JSON.stringify([
            {
                id: "MESSY-01",
                mrn: "  00099812  ",
                first_name: "  Clara  ",
                last_name: "  Barton  ",
                dob: "1978-12-25",
                gender: "F",
                clinical_text: "Patient presents with persistent cough.\r\nBP: 120/80 mmHg. No acute distress.\x00"
            },
            {
                id: "MESSY-02",
                mrn: "00099813",
                first_name: "Florence",
                last_name: "Nightingale",
                dob: "05/12/1982",
                gender: "Female",
                clinical_text: "Follow-up visit. Labs: HbA1c 5.6%. Prescribed Metformin 500mg BID."
            }
        ], null, 2);
    } else if (type === "conflict") {
        input.value = JSON.stringify([
            {
                id: "CONF-01",
                mrn: "SHARED-MRN-999",
                first_name: "Marie",
                last_name: "Curie",
                dob: "1977-11-07",
                gender: "female",
                clinical_text: "Oncology consultation."
            },
            {
                id: "CONF-02",
                mrn: "SHARED-MRN-999",
                first_name: "Pierre",
                last_name: "Curie",
                dob: "1979-05-15",
                gender: "male",
                clinical_text: "Conflicting demographics under shared MRN."
            }
        ], null, 2);
    }
}

async function submitJSONPayload() {
    const sourceSystem = document.getElementById("json-source-system").value || "metro_health";
    const idempotencyKey = document.getElementById("json-idempotency-key").value;
    const rawText = document.getElementById("json-records-input").value.trim();

    if (!rawText) {
        showResultAlert("error", "JSON Validation", "Please enter a valid JSON array of records.");
        return;
    }

    let records;
    try {
        records = JSON.parse(rawText);
        if (!Array.isArray(records)) {
            records = [records];
        }
    } catch (err) {
        showResultAlert("error", "Malformed JSON Syntax", err.message);
        return;
    }

    const payload = {
        source_system: sourceSystem,
        idempotency_key: idempotencyKey || null,
        records: records,
    };

    setButtonLoading("json-submit-btn", true, "Ingesting JSON...");

    try {
        const response = await fetch("/api/v1/ingestion/json", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (response.status === 201 || response.status === 200) {
            currentJobId = data.job_id;
            showResultAlert("success", "JSON Ingested & Normalized!", 
                `Job ID: ${data.job_id} | Total: ${data.total_records} | Normalized: ${data.successful_records} | Conflicts: ${data.conflict_records}`);
            updateJobCard(data);
            loadJobReport(data.job_id);
            loadRecordsPage(1);
        } else {
            const errDetail = data.error ? data.error.message : (data.detail || "Submission rejected.");
            showResultAlert("error", `Ingestion Error (${response.status})`, errDetail);
        }
    } catch (err) {
        showResultAlert("error", "Network Error", err.message);
    } finally {
        setButtonLoading("json-submit-btn", false, "Ingest JSON Payload");
    }
}

// =============================================================================
// 5. Job Lifecycle & Dashboard Management
// =============================================================================

function updateJobCard(job) {
    document.getElementById("card-job-id").textContent = job.job_id;
    document.getElementById("card-job-format").textContent = job.source_format ? job.source_format.toUpperCase() : "N/A";
    document.getElementById("card-job-system").textContent = job.source_system || "N/A";
    document.getElementById("card-job-duration").textContent = job.duration_seconds !== null && job.duration_seconds !== undefined
        ? `${job.duration_seconds.toFixed(3)}s` : "-";

    const badge = document.getElementById("card-job-status-badge");
    badge.textContent = job.status;
    badge.className = getStatusBadgeClass(job.status);

    document.getElementById("metric-total").textContent = job.total_records || 0;
    document.getElementById("metric-success").textContent = job.successful_records || 0;
    document.getElementById("metric-duplicates").textContent = job.duplicate_records || 0;
    document.getElementById("metric-conflicts").textContent = job.conflict_records || 0;
    document.getElementById("metric-warnings").textContent = job.warning_records || 0;
    document.getElementById("metric-rejected").textContent = job.rejected_records || 0;
}

function getStatusBadgeClass(status) {
    switch (status) {
        case "COMPLETED":
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
        case "COMPLETED_WITH_WARNINGS":
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-yellow-500/20 text-yellow-300 border border-yellow-500/30";
        case "MANUAL_REVIEW_REQUIRED":
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30";
        case "FAILED":
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30";
        case "PROCESSING":
        case "PENDING":
        case "RECEIVED":
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30 animate-pulse";
        default:
            return "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700";
    }
}

async function lookupJobById() {
    const jobId = document.getElementById("lookup-job-id").value.trim();
    if (!jobId) return;

    try {
        const res = await fetch(`/api/v1/ingestion/jobs/${jobId}`);
        if (res.ok) {
            const data = await res.json();
            currentJobId = data.job_id;
            updateJobCard(data);
            loadJobReport(data.job_id);
            loadRecordsPage(1);
            switchMainTab("jobs");
        } else {
            showResultAlert("error", "Job Not Found", `Unable to locate ingestion job '${jobId}'.`);
        }
    } catch (err) {
        showResultAlert("error", "Lookup Error", err.message);
    }
}

function startJobPolling(jobId) {
    if (jobPollingInterval) clearInterval(jobPollingInterval);
    jobPollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/v1/ingestion/jobs/${jobId}`);
            if (res.ok) {
                const job = await res.json();
                updateJobCard(job);
                if (job.status !== "PENDING" && job.status !== "PROCESSING" && job.status !== "RECEIVED") {
                    clearInterval(jobPollingInterval);
                    jobPollingInterval = null;
                    loadJobReport(job.job_id);
                    loadRecordsPage(1);
                    showResultAlert("success", "Background Ingestion Completed!", 
                        `Job ${job.job_id} finished with status: ${job.status}.`);
                }
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 2000);
}

// =============================================================================
// 6. Audit Trail & Reconciliation Report
// =============================================================================

async function loadJobReport(jobId) {
    if (!jobId) return;
    try {
        const res = await fetch(`/api/v1/ingestion/jobs/${jobId}/report`);
        if (!res.ok) return;
        const report = await res.json();

        const tbody = document.getElementById("audit-table-body");
        const countBadge = document.getElementById("audit-count-badge");
        tbody.innerHTML = "";

        const events = report.recent_audit_events || [];
        countBadge.textContent = `${events.length} Audit Events`;

        if (events.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="px-3 py-6 text-center text-slate-500">No transformation audit events generated for this job.</td></tr>`;
            return;
        }

        events.forEach(ev => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-slate-800/40 transition-colors";
            tr.innerHTML = `
                <td class="px-3 py-2 text-blue-400 font-semibold">${escapeHtml(ev.field_name || "record")}</td>
                <td class="px-3 py-2 text-rose-300 max-w-[150px] truncate" title="${escapeHtml(ev.original_value || "-")}">${escapeHtml(ev.original_value || "-")}</td>
                <td class="px-3 py-2 text-emerald-300 max-w-[150px] truncate" title="${escapeHtml(ev.normalized_value || "-")}">${escapeHtml(ev.normalized_value || "-")}</td>
                <td class="px-3 py-2 text-slate-200">${escapeHtml(ev.transformation_applied)}</td>
                <td class="px-3 py-2 text-slate-400">${escapeHtml(ev.component)}</td>
                <td class="px-3 py-2 text-slate-400 max-w-[200px] truncate" title="${escapeHtml(ev.reason)}">${escapeHtml(ev.reason)}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Failed to load audit report", err);
    }
}

function viewJobAuditReport() {
    if (!currentJobId) {
        showResultAlert("info", "No Job Selected", "Please ingest a file or enter a Job ID first.");
        return;
    }
    switchMainTab("explorer");
    document.getElementById("audit-trail-container").scrollIntoView({ behavior: "smooth" });
}

function viewJobRecordsList() {
    if (!currentJobId) {
        showResultAlert("info", "No Job Selected", "Please ingest a file or enter a Job ID first.");
        return;
    }
    switchMainTab("explorer");
    loadRecordsPage(1);
}

// =============================================================================
// 7. Clinical Records Explorer & Deep Dive Modal
// =============================================================================

async function loadRecordsPage(page) {
    if (!currentJobId) return;
    currentPage = page;

    const statusFilter = document.getElementById("explorer-status-filter").value;
    const url = `/api/v1/ingestion/jobs/${currentJobId}/records?page=${page}&page_size=10${statusFilter ? `&status=${statusFilter}` : ""}`;

    const tbody = document.getElementById("records-table-body");
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400 font-mono">Loading records...</td></tr>`;

    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        currentRecords = data.items || [];
        totalPages = data.total_pages || 1;

        document.getElementById("records-pagination-info").textContent = 
            `Showing records ${((page - 1) * 10) + 1}-${Math.min(page * 10, data.total)} of ${data.total}`;

        document.getElementById("prev-page-btn").disabled = page <= 1;
        document.getElementById("next-page-btn").disabled = page >= totalPages;

        tbody.innerHTML = "";
        if (currentRecords.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-500 font-mono">No matching records found.</td></tr>`;
            return;
        }

        currentRecords.forEach((rec, idx) => {
            const tr = document.createElement("tr");
            tr.className = "hover:bg-slate-800/50 transition-colors";

            const p = rec.parsed_payload || {};
            const demo = p.demographics || p.patient || p;
            const pFirst = demo.first_name || p.first_name || "";
            const pLast = demo.last_name || p.last_name || "";
            const pName = (pFirst || pLast) ? `${pFirst} ${pLast}`.trim() : null;
            const pMrn = demo.mrn || p.mrn || demo.patient_id || p.patient_id;
            const patientDisplay = pName
                ? `${pName}${pMrn ? ` (MRN: ${pMrn})` : ""}`
                : (rec.patient_id ? rec.patient_id.substring(0, 8) : "Unassigned");

            const textPreview = rec.cleaned_text 
                ? rec.cleaned_text.replace(/\n/g, " ").substring(0, 80) + "..."
                : (rec.original_content ? rec.original_content.substring(0, 80) + "..." : "No clinical text");

            tr.innerHTML = `
                <td class="px-4 py-3 font-mono text-slate-300 font-medium">${rec.id.substring(0, 8)}...</td>
                <td class="px-4 py-3 text-blue-400 font-medium">${escapeHtml(patientDisplay)}</td>
                <td class="px-4 py-3">
                    <span class="${getStatusBadgeClass(rec.status)}">${rec.status}</span>
                </td>
                <td class="px-4 py-3 text-slate-400 font-mono">${escapeHtml(rec.record_date || "-")}</td>
                <td class="px-4 py-3 text-slate-400 max-w-xs truncate font-mono text-[11px]">${escapeHtml(textPreview)}</td>
                <td class="px-4 py-3 text-right">
                    <button onclick="openRecordModal(${idx})" class="text-xs bg-slate-800 hover:bg-slate-700 text-blue-400 border border-slate-700 px-3 py-1 rounded-md transition-colors">
                        Inspect
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-6 text-center text-rose-400">Failed to load records: ${err.message}</td></tr>`;
    }
}

function changeRecordPage(delta) {
    const newPage = currentPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        loadRecordsPage(newPage);
    }
}

function openRecordModal(index) {
    const rec = currentRecords[index];
    if (!rec) return;

    document.getElementById("modal-record-id").textContent = rec.id;
    document.getElementById("modal-patient-id").textContent = rec.patient_id || "None (Identity Conflict)";
    document.getElementById("modal-fingerprint").textContent = rec.fingerprint ? `${rec.fingerprint.substring(0, 16)}...` : "-";
    document.getElementById("modal-record-date").textContent = rec.record_date || "Unknown";

    const badge = document.getElementById("modal-status-badge");
    badge.textContent = rec.status;
    badge.className = getStatusBadgeClass(rec.status);

    document.getElementById("modal-cleaned-text").textContent = rec.cleaned_text || "No cleaned text available.";
    document.getElementById("modal-parsed-payload").textContent = JSON.stringify(rec.parsed_payload || {}, null, 2);

    const errSection = document.getElementById("modal-errors-section");
    const errContent = document.getElementById("modal-errors-content");
    if (rec.validation_errors && rec.validation_errors.length > 0) {
        errSection.classList.remove("hidden");
        errContent.textContent = JSON.stringify(rec.validation_errors, null, 2);
    } else {
        errSection.classList.add("hidden");
    }

    document.getElementById("record-modal").classList.remove("hidden");
}

function closeRecordModal() {
    document.getElementById("record-modal").classList.add("hidden");
}

// =============================================================================
// 8. Utility Functions
// =============================================================================

function showResultAlert(type, title, message) {
    const box = document.getElementById("ingestion-result-box");
    box.classList.remove("hidden", "bg-emerald-950/40", "border-emerald-500/40", "text-emerald-300", 
                         "bg-rose-950/40", "border-rose-500/40", "text-rose-300",
                         "bg-blue-950/40", "border-blue-500/40", "text-blue-300");

    let styles = "";
    if (type === "success") {
        styles = "bg-emerald-950/40 border-emerald-500/40 text-emerald-300";
    } else if (type === "info") {
        styles = "bg-blue-950/40 border-blue-500/40 text-blue-300";
    } else {
        styles = "bg-rose-950/40 border-rose-500/40 text-rose-300";
    }

    box.className = `rounded-xl p-4 border transition-all ${styles}`;
    box.innerHTML = `
        <div class="flex items-start justify-between">
            <div>
                <h4 class="font-bold text-sm mb-1">${escapeHtml(title)}</h4>
                <p class="text-xs opacity-90 font-mono leading-relaxed">${escapeHtml(message)}</p>
            </div>
            <button onclick="document.getElementById('ingestion-result-box').classList.add('hidden')" class="text-slate-400 hover:text-slate-200 ml-4">
                &times;
            </button>
        </div>
    `;
}

function setButtonLoading(btnId, isLoading, text) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.disabled = isLoading;
    const textSpan = btn.querySelector("span");
    const spinner = btn.querySelector("svg");
    if (textSpan) textSpan.textContent = text;
    if (spinner) {
        if (isLoading) spinner.classList.remove("hidden");
        else spinner.classList.add("hidden");
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// =============================================================================
// 9. HL7 FHIR R4 Bundles & Normalization Client
// =============================================================================

let activeFhirBundleJson = null;
let activeFhirBundleId = null;

async function loadStoredFhirBundles() {
    const tableBody = document.getElementById("fhir-bundles-table-body");
    const countBadge = document.getElementById("fhir-bundle-count-badge");
    if (!tableBody) return;

    tableBody.innerHTML = `
        <tr>
            <td colspan="8" class="px-3.5 py-6 text-center text-slate-500 font-sans">
                Fetching stored FHIR R4 Bundles...
            </td>
        </tr>
    `;

    try {
        const resp = await fetch("/api/v1/fhir/bundles?page=1&page_size=100", {
            headers: getAuthHeaders(),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const pageData = await resp.json();
        const bundles = Array.isArray(pageData) ? pageData : (pageData.items || []);
        const total = pageData.total !== undefined ? pageData.total : bundles.length;

        if (countBadge) {
            countBadge.textContent = `${total} Bundles`;
        }

        if (bundles.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="8" class="px-3.5 py-8 text-center text-slate-500 font-sans">
                        No FHIR Bundles generated yet. Ingest EHR records and normalize to generate FHIR R4 Bundles.
                    </td>
                </tr>
            `;
            return;
        }

        tableBody.innerHTML = bundles.map(b => {
            const statusClass = b.status === "VALID" 
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                : (b.status === "WARNING" ? "bg-amber-500/10 text-amber-400 border-amber-500/20" : "bg-rose-500/10 text-rose-400 border-rose-500/20");

            return `
                <tr class="hover:bg-slate-800/40 transition-colors">
                    <td class="px-3.5 py-3 text-blue-400 font-medium truncate max-w-[180px]">${escapeHtml(b.bundle_id)}</td>
                    <td class="px-3.5 py-3 text-slate-300 font-bold">${escapeHtml(b.patient_mrn)}</td>
                    <td class="px-3.5 py-3 text-slate-400">${escapeHtml(b.bundle_type)}</td>
                    <td class="px-3.5 py-3 text-purple-400 font-semibold">v${b.version}</td>
                    <td class="px-3.5 py-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${statusClass}">${escapeHtml(b.status)}</span>
                    </td>
                    <td class="px-3.5 py-3 text-slate-300">${b.resource_count} resources</td>
                    <td class="px-3.5 py-3 text-slate-400 text-[10px]">${new Date(b.created_at).toLocaleString()}</td>
                    <td class="px-3.5 py-3 text-right space-x-1.5 font-sans">
                        <button onclick="openFhirBundleModal('${escapeHtml(b.bundle_id)}')" class="px-2.5 py-1 text-[11px] rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 transition-colors">
                            View JSON
                        </button>
                        <button onclick="openFhirReportModal('${escapeHtml(b.bundle_id)}')" class="px-2.5 py-1 text-[11px] rounded bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 border border-purple-500/30 transition-colors">
                            Report
                        </button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="8" class="px-3.5 py-6 text-center text-rose-400 font-sans">
                    Failed to load stored FHIR Bundles: ${escapeHtml(err.message)}
                </td>
            </tr>
        `;
    }
}

async function triggerPatientFhirNormalization() {
    const input = document.getElementById("fhir-target-id-input");
    const select = document.getElementById("fhir-bundle-type-select");
    const statusBox = document.getElementById("fhir-action-status");
    const patientId = input ? input.value.trim() : "";
    const bundleType = select ? select.value : "collection";

    if (!patientId) {
        alert("Please enter a Target Patient UUID or MRN");
        return;
    }

    statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-blue-500/30 bg-blue-950/20 text-blue-300 block";
    statusBox.textContent = `Normalizing patient [${patientId}] to HL7 FHIR R4 Bundle...`;

    try {
        const resp = await fetch(`/api/v1/fhir/normalize/patient/${encodeURIComponent(patientId)}?bundle_type=${bundleType}&save_to_store=true`, {
            method: "POST",
            headers: getAuthHeaders(),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || data.error?.message || `HTTP ${resp.status}`);

        if (data.success) {
            statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-emerald-500/30 bg-emerald-950/20 text-emerald-300 block";
            statusBox.textContent = `Successfully generated & persisted FHIR Bundle [${data.bundle_id}] (v${data.version}). Status: ${data.validation_report.status}`;
            loadStoredFhirBundles();
        } else {
            statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-rose-500/30 bg-rose-950/20 text-rose-300 block";
            statusBox.textContent = `Gatekeeper rejected Bundle for patient [${patientId}]. Validation errors: ${data.validation_report.error_count}`;
        }
    } catch (err) {
        statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-rose-500/30 bg-rose-950/20 text-rose-300 block";
        statusBox.textContent = `Normalization request failed: ${err.message}`;
    }
}

async function triggerJobFhirNormalization() {
    const input = document.getElementById("fhir-target-id-input");
    const select = document.getElementById("fhir-bundle-type-select");
    const statusBox = document.getElementById("fhir-action-status");
    const jobId = input ? input.value.trim() : "";
    const bundleType = select ? select.value : "collection";

    if (!jobId) {
        alert("Please enter an Ingestion Job UUID to batch normalize");
        return;
    }

    statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-indigo-500/30 bg-indigo-950/20 text-indigo-300 block";
    statusBox.textContent = `Batch-normalizing all reconciled patients in job [${jobId}]...`;

    try {
        const resp = await fetch(`/api/v1/fhir/normalize/job/${encodeURIComponent(jobId)}?bundle_type=${bundleType}&save_to_store=true`, {
            method: "POST",
            headers: getAuthHeaders(),
        });
        const results = await resp.json();
        if (!resp.ok) throw new Error(results.detail || results.error?.message || `HTTP ${resp.status}`);

        const successCount = results.filter(r => r.success).length;
        statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-emerald-500/30 bg-emerald-950/20 text-emerald-300 block";
        statusBox.textContent = `Batch normalization completed: ${successCount}/${results.length} patient Bundles successfully generated and stored.`;
        loadStoredFhirBundles();
    } catch (err) {
        statusBox.className = "text-xs px-3.5 py-2 rounded-xl border border-rose-500/30 bg-rose-950/20 text-rose-300 block";
        statusBox.textContent = `Batch normalization failed: ${err.message}`;
    }
}

async function openFhirBundleModal(bundleId) {
    const modal = document.getElementById("fhir-bundle-modal");
    const jsonContent = document.getElementById("fhir-modal-json-content");
    const modalTitle = document.getElementById("fhir-modal-title");

    activeFhirBundleId = bundleId;
    activeFhirBundleJson = null;

    modalTitle.textContent = `HL7 FHIR R4 Bundle: ${bundleId}`;
    jsonContent.textContent = "Loading bundle JSON...";
    modal.classList.remove("hidden");

    try {
        const resp = await fetch(`/api/v1/fhir/bundles/${encodeURIComponent(bundleId)}`, {
            headers: getAuthHeaders(),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        activeFhirBundleJson = data;
        jsonContent.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
        jsonContent.textContent = `Error fetching bundle JSON: ${err.message}`;
    }
}

function closeFhirBundleModal() {
    const modal = document.getElementById("fhir-bundle-modal");
    if (modal) modal.classList.add("hidden");
    activeFhirBundleJson = null;
    activeFhirBundleId = null;
}

function downloadActiveFhirBundle() {
    if (!activeFhirBundleJson) return;
    const blob = new Blob([JSON.stringify(activeFhirBundleJson, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${activeFhirBundleId || "fhir_bundle"}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function openFhirReportModal(bundleId) {
    const modal = document.getElementById("fhir-report-modal");
    const cards = document.getElementById("fhir-report-summary-cards");
    const issuesContainer = document.getElementById("fhir-report-issues-container");
    const badge = document.getElementById("fhir-report-status-badge");

    modal.classList.remove("hidden");
    cards.innerHTML = "<div class='col-span-4 py-4 text-slate-400'>Loading validation report...</div>";
    issuesContainer.innerHTML = "";

    try {
        const resp = await fetch(`/api/v1/fhir/bundles/${encodeURIComponent(bundleId)}/report`, {
            headers: getAuthHeaders(),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const report = await resp.json();

        badge.className = report.status === "VALID" 
            ? "w-2.5 h-2.5 rounded-full bg-emerald-400"
            : (report.status === "WARNING" ? "w-2.5 h-2.5 rounded-full bg-amber-400" : "w-2.5 h-2.5 rounded-full bg-rose-500");

        cards.innerHTML = `
            <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800">
                <div class="text-slate-500 text-[10px] uppercase font-semibold">Status</div>
                <div class="text-sm font-bold text-slate-100">${escapeHtml(report.status)}</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800">
                <div class="text-slate-500 text-[10px] uppercase font-semibold">Total Resources</div>
                <div class="text-sm font-bold text-blue-400">${report.total_resources}</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800">
                <div class="text-slate-500 text-[10px] uppercase font-semibold">Errors</div>
                <div class="text-sm font-bold ${report.error_count > 0 ? 'text-rose-400' : 'text-slate-400'}">${report.error_count}</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800">
                <div class="text-slate-500 text-[10px] uppercase font-semibold">Warnings</div>
                <div class="text-sm font-bold ${report.warning_count > 0 ? 'text-amber-400' : 'text-slate-400'}">${report.warning_count}</div>
            </div>
        `;

        if (!report.issues || report.issues.length === 0) {
            issuesContainer.innerHTML = `
                <div class="bg-emerald-950/20 border border-emerald-500/30 rounded-xl p-4 text-emerald-300 text-xs">
                    ✓ All resources fully conform to HL7 FHIR R4 schema and reference integrity standards. Zero errors or warnings detected.
                </div>
            `;
            return;
        }

        issuesContainer.innerHTML = report.issues.map(iss => {
            const isError = iss.severity === "ERROR";
            const borderCol = isError ? "border-rose-500/30 bg-rose-950/20" : "border-amber-500/30 bg-amber-950/20";
            const textCol = isError ? "text-rose-400" : "text-amber-400";

            return `
                <div class="border rounded-xl p-3 text-xs space-y-1.5 ${borderCol}">
                    <div class="flex items-center justify-between">
                        <span class="font-bold font-mono ${textCol}">${escapeHtml(iss.error_code)}</span>
                        <span class="px-2 py-0.5 rounded text-[10px] uppercase font-bold ${isError ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}">${iss.severity}</span>
                    </div>
                    <div class="font-mono text-[11px] text-slate-300">Path: ${escapeHtml(iss.fhir_path)}</div>
                    <div class="text-slate-200">${escapeHtml(iss.description)}</div>
                    <div class="text-slate-400 text-[11px] pt-1 border-t border-slate-800/60">
                        <span class="text-slate-500 font-semibold">Recommended Action:</span> ${escapeHtml(iss.recommended_action)}
                    </div>
                </div>
            `;
        }).join("");

    } catch (err) {
        issuesContainer.innerHTML = `
            <div class="text-rose-400 text-xs py-4 text-center">Failed to load validation report: ${escapeHtml(err.message)}</div>
        `;
    }
}

function closeFhirReportModal() {
    const modal = document.getElementById("fhir-report-modal");
    if (modal) modal.classList.add("hidden");
}

// =============================================================================
// 10. App Initialization
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
    checkBackendHealth();
    setInterval(checkBackendHealth, 5000);
    setupDragAndDrop();
});
