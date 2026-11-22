/**
 * EHR Data Ingestion Component.
 * Supports multipart file/package uploads (CSV, JSON, TXT, FHIR NDJSON, ZIP/TAR)
 * and direct JSON payloads with schema reconciliation and cleaning.
 */
import { uploadEhrFile, ingestJsonRecords } from "../api/ingestion.js";
import { formatBytes } from "../utils/formatters.js";
import { iconSvg } from "../utils/icons.js";
import { showToast } from "./toast.js";
import { viewSpecificJob } from "./jobs.js";

let selectedFile = null;

export function setupIngestionListeners() {
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");

    if (dropZone && fileInput) {
        dropZone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropZone.classList.add("border-[#389B98]", "bg-[#389B98]/5");
        });

        dropZone.addEventListener("dragleave", (e) => {
            e.preventDefault();
            dropZone.classList.remove("border-[#389B98]", "bg-[#389B98]/5");
        });

        dropZone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropZone.classList.remove("border-[#389B98]", "bg-[#389B98]/5");
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleFileSelected(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleFileSelected(e.target.files[0]);
            }
        });
    }
}

export function handleFileSelected(file) {
    if (!file) return;
    selectedFile = file;

    const display = document.getElementById("selected-file-display");
    const nameEl = document.getElementById("selected-file-name");
    const sizeEl = document.getElementById("selected-file-size");

    if (display && nameEl && sizeEl) {
        nameEl.textContent = file.name;
        sizeEl.textContent = `(${formatBytes(file.size)})`;
        display.classList.remove("hidden");
        display.classList.add("flex");
    }
}

export function switchIngestMode(mode) {
    const filePanel = document.getElementById("ingest-file-panel");
    const jsonPanel = document.getElementById("ingest-json-panel");
    const fileBtn = document.getElementById("mode-file-btn");
    const jsonBtn = document.getElementById("mode-json-btn");

    if (mode === "file") {
        if (filePanel) filePanel.classList.remove("hidden");
        if (jsonPanel) jsonPanel.classList.add("hidden");
        if (fileBtn) fileBtn.className = "px-4 py-2 rounded-xl bg-[#389B98] text-white shadow-sm font-semibold";
        if (jsonBtn) jsonBtn.className = "px-4 py-2 rounded-xl text-slate-600 hover:text-slate-900 font-medium";
    } else {
        if (filePanel) filePanel.classList.add("hidden");
        if (jsonPanel) jsonPanel.classList.remove("hidden");
        if (fileBtn) fileBtn.className = "px-4 py-2 rounded-xl text-slate-600 hover:text-slate-900 font-medium";
        if (jsonBtn) jsonBtn.className = "px-4 py-2 rounded-xl bg-[#389B98] text-white shadow-sm font-semibold";
    }
}

export async function handleFileUpload(event) {
    if (event) event.preventDefault();
    if (!selectedFile) {
        showToast("warning", "File Required", "Please select or drop an EHR file first.");
        return;
    }

    const sourceSystem = document.getElementById("file-source-system").value;
    const idempotencyKey = document.getElementById("file-idempotency-key").value.trim();
    const mappingProfile = document.getElementById("file-mapping-profile").value.trim();
    const sync = document.getElementById("file-sync-toggle").checked;
    const submitBtn = document.getElementById("file-upload-submit-btn");

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("source_system", sourceSystem);
    if (idempotencyKey) formData.append("idempotency_key", idempotencyKey);
    if (mappingProfile) formData.append("mapping_profile", mappingProfile);

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `${iconSvg("spinner", "w-4 h-4 text-white")} <span class="ml-1.5">Uploading & Cleaning...</span>`;
    }

    try {
        showToast("info", "Ingestion In Progress", `Processing ${selectedFile.name}...`, 3000);
        const job = await uploadEhrFile(formData, sync);
        showToast("success", "Ingestion Success", `Processed ${job.total_records} records with status ${job.status}`);
        viewSpecificJob(job.job_id);
    } catch (err) {
        showToast("error", "Ingestion Failed", err.message || "Failed to process file");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>Ingest & Clean File</span>`;
        }
    }
}

export async function handleJsonIngestion(event) {
    if (event) event.preventDefault();
    const sourceSystem = document.getElementById("json-source-system").value;
    const idempotencyKey = document.getElementById("json-idempotency-key").value.trim();
    const mappingProfileStr = document.getElementById("json-mapping-profile").value.trim();
    const sync = document.getElementById("json-sync-toggle").checked;
    const editor = document.getElementById("json-payload-editor");
    const submitBtn = document.getElementById("json-submit-btn");

    let records = [];
    try {
        const parsed = JSON.parse(editor.value);
        records = Array.isArray(parsed) ? parsed : [parsed];
    } catch {
        showToast("error", "Invalid JSON", "Please ensure the JSON payload is valid before submitting.");
        return;
    }

    let mappingProfile = null;
    if (mappingProfileStr) {
        try {
            mappingProfile = JSON.parse(mappingProfileStr);
        } catch {
            showToast("error", "Invalid Mapping Profile", "Mapping profile must be valid JSON.");
            return;
        }
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `${iconSvg("spinner", "w-4 h-4 text-white")} <span class="ml-1.5">Processing Records...</span>`;
    }

    try {
        showToast("info", "Ingestion Started", `Submitting ${records.length} records...`, 2500);
        const job = await ingestJsonRecords({
            source_system: sourceSystem,
            records,
            idempotency_key: idempotencyKey || undefined,
            mapping_profile: mappingProfile || undefined,
        }, sync);

        showToast("success", "Ingestion Success", `Processed ${job.total_records} records: ${job.successful_records} normalized`);
        viewSpecificJob(job.job_id);
    } catch (err) {
        showToast("error", "Ingestion Failed", err.message || "Failed to ingest JSON records");
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>Submit JSON Records</span>`;
        }
    }
}

export function fillSampleJSON(type) {
    const editor = document.getElementById("json-payload-editor");
    if (!editor) return;

    if (type === "single") {
        editor.value = JSON.stringify([
            {
                "patient_id": "PT-90412",
                "mrn": "MRN-90412",
                "first_name": "Eleanor",
                "last_name": "Vance",
                "dob": "1984-06-14",
                "gender": "female",
                "record_type": "observation",
                "code": "8480-6",
                "code_text": "Systolic blood pressure",
                "value": "138",
                "unit": "mmHg",
                "status": "final",
                "effective_date": "2024-11-20T10:15:00Z",
                "clinical_text": "Patient presents with elevated blood pressure (138/88 mmHg). Prescribed amlodipine 5mg oral daily."
            }
        ], null, 2);
    } else if (type === "multi") {
        editor.value = JSON.stringify([
            {
                "patient_id": "PT-10021",
                "mrn": "MRN-10021",
                "first_name": "Arthur",
                "last_name": "Pendleton",
                "dob": "1962-03-22",
                "gender": "male",
                "record_type": "condition",
                "code": "44054006",
                "code_text": "Type 2 diabetes mellitus",
                "clinical_status": "active",
                "recorded_date": "2024-10-05",
                "clinical_text": "Established Type 2 Diabetes Mellitus with recent HbA1c of 8.2%. Metformin dosage titrated to 1000mg BID."
            },
            {
                "patient_id": "PT-10021",
                "mrn": "MRN-10021",
                "first_name": "Arthur",
                "last_name": "Pendleton",
                "dob": "1962-03-22",
                "gender": "male",
                "record_type": "observation",
                "code": "4548-4",
                "code_text": "Hemoglobin A1c/Hemoglobin.total in Blood",
                "value": "8.2",
                "unit": "%",
                "status": "final",
                "effective_date": "2024-10-05T09:30:00Z",
                "clinical_text": "HbA1c measured at 8.2% (uncontrolled diabetes threshold)."
            }
        ], null, 2);
    }
}

// Window bindings
window.switchIngestMode = switchIngestMode;
window.handleFileUpload = handleFileUpload;
window.handleJsonIngestion = handleJsonIngestion;
window.fillSampleJSON = fillSampleJSON;
