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
    const tabs = ["ingest", "jobs", "explorer", "fhir", "search"];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-btn-${t}`);
        const content = document.getElementById(`tab-content-${t}`);
        if (!btn || !content) return;
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
// 10. Clinical Semantic Search & Vector DB Retrieval
// =============================================================================

function applySampleSearch(query) {
    const input = document.getElementById("search-query-input");
    if (input) {
        input.value = query;
        executeSemanticSearch();
    }
}

function clearSearchInput() {
    const input = document.getElementById("search-query-input");
    if (input) {
        input.value = "";
        input.focus();
    }
}

function resetSearchFilters() {
    const resSelect = document.getElementById("search-filter-resource");
    const patInput = document.getElementById("search-filter-patient");
    const fromInput = document.getElementById("search-filter-date-from");
    const toInput = document.getElementById("search-filter-date-to");
    const topKSelect = document.getElementById("search-filter-top-k");

    if (resSelect) resSelect.value = "";
    if (patInput) patInput.value = "";
    if (fromInput) fromInput.value = "";
    if (toInput) toInput.value = "";
    if (topKSelect) topKSelect.value = "5";
}

async function executeSemanticSearch(event) {
    if (event) event.preventDefault();

    const queryInput = document.getElementById("search-query-input");
    const query = (queryInput ? queryInput.value : "").trim();
    if (!query) return;

    const resSelect = document.getElementById("search-filter-resource");
    const patInput = document.getElementById("search-filter-patient");
    const fromInput = document.getElementById("search-filter-date-from");
    const toInput = document.getElementById("search-filter-date-to");
    const topKSelect = document.getElementById("search-filter-top-k");

    const resourceType = resSelect ? resSelect.value.trim() : "";
    const patientId = patInput ? patInput.value.trim() : "";
    const dateFrom = fromInput ? fromInput.value.trim() : "";
    const dateTo = toInput ? toInput.value.trim() : "";
    const topK = topKSelect ? parseInt(topKSelect.value, 10) || 5 : 5;

    if (dateFrom && dateTo && dateFrom > dateTo) {
        alert("Date From cannot be after Date To.");
        return;
    }

    const emptyState = document.getElementById("search-empty-state");
    const skeleton = document.getElementById("search-loading-skeleton");
    const metricsBar = document.getElementById("search-metrics-bar");
    const resultsContainer = document.getElementById("search-results-container");
    const submitBtn = document.getElementById("search-submit-btn");

    if (emptyState) emptyState.classList.add("hidden");
    if (skeleton) skeleton.classList.remove("hidden");
    if (resultsContainer) resultsContainer.innerHTML = "";
    if (metricsBar) metricsBar.classList.add("hidden");
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add("opacity-60", "cursor-not-allowed");
    }

    const params = new URLSearchParams();
    if (resourceType) params.append("resource_type", resourceType);
    if (patientId) params.append("patient_id", patientId);
    if (dateFrom) params.append("date_from", dateFrom);
    if (dateTo) params.append("date_to", dateTo);
    if (topK) params.append("top_k", topK);

    const queryString = params.toString() ? `?${params.toString()}` : "";

    try {
        const response = await fetch(`/api/v1/search${queryString}`, {
            method: "POST",
            headers: getAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ query: query }),
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const errMsg = (errData && errData.error && errData.error.message) || `Search failed (HTTP ${response.status})`;
            throw new Error(errMsg);
        }

        const data = await response.json();
        renderSearchResults(data, { query, patientId, resourceType, dateFrom, dateTo, topK });
    } catch (err) {
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="bg-rose-950/20 border border-rose-500/30 rounded-2xl p-6 text-center text-xs space-y-2">
                    <div class="text-rose-400 font-bold">Search Execution Error</div>
                    <div class="text-slate-300 font-mono text-[11px]">${escapeHtml(err.message)}</div>
                </div>
            `;
        }
    } finally {
        if (skeleton) skeleton.classList.add("hidden");
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove("opacity-60", "cursor-not-allowed");
        }
    }
}

function renderSearchResults(data, filters) {
    const metricsBar = document.getElementById("search-metrics-bar");
    const countEl = document.getElementById("search-results-count");
    const latencyEl = document.getElementById("search-results-latency");
    const filterTagsEl = document.getElementById("search-active-filter-tags");
    const resultsContainer = document.getElementById("search-results-container");

    if (metricsBar) metricsBar.classList.remove("hidden");
    if (countEl) countEl.textContent = `${data.count} distinct record${data.count === 1 ? '' : 's'} retrieved`;
    if (latencyEl) latencyEl.textContent = `Retrieved in ${data.took_ms.toFixed(1)} ms`;

    if (filterTagsEl) {
        const badges = [];
        if (filters.resourceType) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-mono">Type: ${escapeHtml(filters.resourceType)}</span>`);
        }
        if (filters.patientId) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 text-[10px] font-mono">Patient: ${escapeHtml(filters.patientId)}</span>`);
        }
        if (filters.dateFrom || filters.dateTo) {
            badges.push(`<span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono">Date: [${escapeHtml(filters.dateFrom || 'start')} to ${escapeHtml(filters.dateTo || 'now')}]</span>`);
        }
        filterTagsEl.innerHTML = badges.join(" ");
    }

    if (!data.results || data.results.length === 0) {
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-10 text-center space-y-2">
                    <div class="text-slate-400 font-medium text-xs">No records matched this clinical query and filter criteria</div>
                    <p class="text-slate-500 text-[11px]">Try broadening your filters or entering a different medical search phrase.</p>
                </div>
            `;
        }
        return;
    }

    const cardsHtml = data.results.map((item, idx) => {
        const pct = Math.round(item.score * 100);
        let scoreBg = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
        let barCol = "bg-emerald-500";
        if (pct < 60) {
            scoreBg = "bg-amber-500/20 text-amber-300 border-amber-500/30";
            barCol = "bg-amber-500";
        } else if (pct < 75) {
            scoreBg = "bg-blue-500/20 text-blue-300 border-blue-500/30";
            barCol = "bg-blue-500";
        }

        const isSummary = item.source === "ai_summary";
        const sourceBadge = isSummary
            ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">AI Summary</span>`
            : `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">FHIR Document</span>`;

        let typeBg = "bg-slate-800 text-slate-300 border-slate-700";
        if (item.resource_type === "Observation") typeBg = "bg-blue-900/30 text-blue-300 border-blue-700/40";
        else if (item.resource_type === "Condition") typeBg = "bg-rose-900/30 text-rose-300 border-rose-700/40";
        else if (item.resource_type === "DiagnosticReport") typeBg = "bg-purple-900/30 text-purple-300 border-purple-700/40";
        else if (item.resource_type === "ClinicalSummary") typeBg = "bg-emerald-900/30 text-emerald-300 border-emerald-700/40";

        return `
            <div class="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 shadow-lg space-y-3 transition-colors">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
                    <div class="flex flex-wrap items-center gap-2">
                        <span class="text-xs font-mono font-bold text-slate-400">#${idx + 1}</span>
                        <span class="px-2 py-0.5 rounded text-xs font-bold font-mono border ${typeBg}">
                            ${escapeHtml(item.resource_type)}
                        </span>
                        ${sourceBadge}
                        <span class="text-xs text-slate-400">
                            Patient: <strong class="text-blue-400 font-mono">${escapeHtml(item.patient_id)}</strong>
                        </span>
                        <span class="text-slate-600">|</span>
                        <span class="text-xs text-slate-400 font-mono text-[11px] truncate max-w-xs" title="${escapeHtml(item.record_id)}">
                            ID: ${escapeHtml(item.record_id)}
                        </span>
                    </div>

                    <div class="flex items-center space-x-3 self-end sm:self-auto">
                        <div class="text-right">
                            <span class="px-2.5 py-1 rounded-lg text-xs font-mono font-bold border ${scoreBg}">
                                ${pct}% Relevance
                            </span>
                            <div class="w-24 bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden ml-auto">
                                <div class="${barCol} h-full rounded-full" style="width: ${pct}%"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Record Date -->
                <div class="flex items-center space-x-2 text-xs text-slate-400 font-mono text-[11px]">
                    <svg class="w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span>Record Timestamp: <span class="text-slate-300">${escapeHtml(item.date)}</span></span>
                </div>

                <!-- Clinical Text Snippet -->
                <div class="bg-slate-950 border border-slate-800/80 rounded-xl p-3.5 text-xs text-slate-200 font-sans leading-relaxed">
                    <p class="whitespace-pre-wrap">${escapeHtml(item.snippet)}</p>
                </div>
            </div>
        `;
    }).join("");

    if (resultsContainer) {
        resultsContainer.innerHTML = cardsHtml;
    }
}

async function triggerBackfillReindex() {
    const btn = document.getElementById("reindex-btn");
    if (!confirm("Start vector database backfill re-indexing? This encodes all stored FHIR documents and summaries.")) {
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.classList.add("opacity-60", "cursor-not-allowed");
        btn.innerHTML = `
            <svg class="w-3.5 h-3.5 text-slate-400 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            <span>Indexing...</span>
        `;
    }

    try {
        const resp = await fetch("/api/v1/search", {
            method: "POST",
            headers: getAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ query: "warmup check" }),
        });
        if (resp.ok) {
            alert("Vector store is healthy and active. Use the CLI 'python -m app.scripts.reindex_embeddings' for complete database backfill.");
        } else {
            alert("Vector store query responded with status: " + resp.status);
        }
    } catch (err) {
        alert("Could not reach vector store: " + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove("opacity-60", "cursor-not-allowed");
            btn.innerHTML = `
                <svg class="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                <span>Re-index Vector Store</span>
            `;
        }
    }
}

// =============================================================================
// 11. App Initialization
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
    checkBackendHealth();
    setInterval(checkBackendHealth, 5000);
    setupDragAndDrop();
});
