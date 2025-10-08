/**
 * Monitoring Processes Page JavaScript
 * Handles process listing, filtering, polling, and CRUD operations
 */

import {
    escapeHtml,
    escapeAttribute,
    fetchOptions,
    safeParseJson,
    extractErrorMessage,
    formatDate,
    formatProviderLabel,
    formatDuration
} from './utils.js';

let processes = [];
let providers = [];
let providerMap = new Map();
let promptTemplateMap = new Map();
let credentialMap = new Map();
let pollingInterval = null;

// DOM elements
let statusFilter, providerFilter, searchInput, refreshBtn;
let loadingState, emptyState, processList;

/**
 * Initialize the monitoring processes page
 */
export function initMonitoringPage() {
    // Get DOM elements
    statusFilter = document.getElementById('statusFilter');
    providerFilter = document.getElementById('providerFilter');
    searchInput = document.getElementById('searchInput');
    refreshBtn = document.getElementById('refreshBtn');
    loadingState = document.getElementById('loadingState');
    emptyState = document.getElementById('emptyState');
    processList = document.getElementById('processList');

    // Event listeners
    statusFilter.addEventListener('change', () => renderProcesses(filterProcesses()));
    providerFilter.addEventListener('change', () => renderProcesses(filterProcesses()));
    searchInput.addEventListener('input', () => renderProcesses(filterProcesses()));
    refreshBtn.addEventListener('click', () => loadAllData());

    // Initial load
    loadAllData();

    // Clean up polling on page unload
    window.addEventListener('beforeunload', () => {
        if (pollingInterval) {
            clearInterval(pollingInterval);
        }
    });
}

async function loadAllData() {
    window.showAlert();
    loadingState.style.display = 'block';
    emptyState.style.display = 'none';
    processList.style.display = 'none';
    processList.innerHTML = '';

    try {
        const [processResp, providerResp, templateResp, credentialResp] = await Promise.all([
            fetch('/api/v1/monitoring-processes/index?limit=100', fetchOptions()),
            fetch('/api/v1/llm-providers/index', fetchOptions()),
            fetch('/api/v1/prompt-templates/index?limit=100', fetchOptions()),
            fetch('/api/v1/mymoment-credentials/index', fetchOptions())
        ]);

        await assertOk(processResp, 'Überwachungsprozesse konnten nicht geladen werden.');
        await assertOk(providerResp, 'LLM-Anbieter konnten nicht geladen werden.');
        await assertOk(templateResp, 'Prompt-Vorlagen konnten nicht geladen werden.');
        await assertOk(credentialResp, 'myMoment-Zugangsdaten konnten nicht geladen werden.');

        processes = await processResp.json();
        providers = await providerResp.json();
        const templates = await templateResp.json();
        const credentials = await credentialResp.json();

        providerMap = new Map(providers.map(item => [item.id, item]));
        promptTemplateMap = new Map(templates.map(item => [item.id, item]));
        credentialMap = new Map(credentials.map(item => [item.id, item]));

        populateProviderFilter();

        loadingState.style.display = 'none';

        if (!processes.length) {
            emptyState.style.display = 'block';
        } else {
            processList.style.display = 'flex';
            renderProcesses(filterProcesses());
        }

        // Setup polling if there are running processes
        updatePolling();

    } catch (error) {
        console.error('Error loading monitoring processes:', error);
        loadingState.style.display = 'none';
        window.showAlert(error.message || 'Überwachungsprozesse konnten nicht geladen werden. Bitte versuche es erneut.', 'danger');
    }
}

function updatePolling() {
    const running = processes.some(p => p.is_running);

    if (running && !pollingInterval) {
        // Start polling every 10 seconds
        pollingInterval = setInterval(() => {
            loadProcessesOnly();
        }, 10000);
    } else if (!running && pollingInterval) {
        // Stop polling
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function loadProcessesOnly() {
    // Lightweight update - only fetch processes
    try {
        const response = await fetch('/api/v1/monitoring-processes/index?limit=100', fetchOptions());
        if (response.ok) {
            processes = await response.json();
            renderProcesses(filterProcesses());
            updatePolling();
        }
    } catch (error) {
        console.error('Error polling processes:', error);
    }
}

async function assertOk(response, message) {
    if (!response.ok) {
        const errorBody = await safeParseJson(response);
        const detail = extractErrorMessage(errorBody) || `${message} (HTTP ${response.status})`;
        throw new Error(detail);
    }
}

function populateProviderFilter() {
    const currentSelection = providerFilter.value;
    providerFilter.innerHTML = '<option value="ALL">Alle Anbieter</option>';
    providers.forEach(provider => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = formatProviderLabel(provider.provider_name) + ' - ' + (provider.model_name || 'Kein Modell festgelegt');
        providerFilter.appendChild(option);
    });
    providerFilter.value = currentSelection || 'ALL';
}

function filterProcesses() {
    const status = statusFilter.value;
    const providerId = providerFilter.value;
    const query = searchInput.value.trim().toLowerCase();

    return processes.filter(process => {
        const matchesStatus = (
            status === 'ALL' ||
            (status === 'RUNNING' && process.is_running) ||
            (status === 'STOPPED' && !process.is_running && !process.error_message) ||
            (status === 'ERROR' && Boolean(process.error_message))
        );

        const matchesProvider = providerId === 'ALL' || process.llm_provider_id === providerId;

        const haystack = [
            process.name || '',
            process.description || ''
        ].join(' ').toLowerCase();
        const matchesQuery = !query || haystack.includes(query);

        return matchesStatus && matchesProvider && matchesQuery;
    });
}

function renderProcesses(list) {
    processList.innerHTML = '';

    if (!list.length) {
        processList.style.display = 'none';
        emptyState.style.display = 'block';
        emptyState.querySelector('h3').textContent = processes.length ? 'Keine Prozesse entsprechen deinen Filtern' : 'Noch keine Überwachungsprozesse';
        emptyState.querySelector('p').textContent = processes.length ? 'Passe Filter oder Suchbegriffe an, um weitere Prozesse anzuzeigen.' : 'Erstelle einen Überwachungsprozess, um myMoment zu beobachten und KI-Kommentare automatisch zu posten.';
        return;
    }

    emptyState.style.display = 'none';
    processList.style.display = 'flex';

    list.forEach(process => {
        const col = document.createElement('div');
        col.className = 'col-12 col-lg-6 col-xxl-4 mb-4';

        const provider = providerMap.get(process.llm_provider_id);
        const providerLabel = provider ? `${formatProviderLabel(provider.provider_name)} - ${provider.model_name || 'Kein Modell festgelegt'}` : 'Unbekannter Anbieter';
        const promptNames = process.prompt_template_ids
            .map(templateId => promptTemplateMap.get(templateId)?.name || 'Unbekannte Vorlage')
            .join(', ');
        const credentialNames = process.mymoment_login_ids
            .map(credentialId => credentialMap.get(credentialId)?.name || credentialMap.get(credentialId)?.username || 'Unbekannter Zugang')
            .join(', ');

        const statusBadge = process.is_running
            ? '<span class="badge bg-success">Läuft</span>'
            : process.error_message ? '<span class="badge bg-danger">Fehler</span>' : '<span class="badge bg-secondary">Angehalten</span>';

        const errorBlock = process.error_message
            ? `<div class="alert alert-warning mt-3 mb-0"><strong>Fehler:</strong> ${escapeHtml(process.error_message)}</div>`
            : '';

        col.innerHTML = `
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-start">
                    <div>
                        <h5 class="mb-1" data-bs-toggle="tooltip" data-bs-placement="top" title=${escapeHtml(process.name)}>
                            ${escapeHtml(process.name.length > 25 ? process.name.substring(0, 25) + "…" : process.name)}
                        </h5>
                    </div>
                    <div class="text-end small text-muted">
                        ${statusBadge}
                    </div>
                </div>
                <div class="card-body">
                    ${process.description ? `<p class="text-muted mb-3">${escapeHtml(process.description)}</p>` : ''}
                    <div class="mb-2">
                        <strong>Modus:</strong>
                        <span class="small">
                            ${process.generate_only
                                ? '<span class="badge bg-info">Nur erzeugen</span>'
                                : '<span class="badge bg-primary">Erzeugen & Veröffentlichen</span>'}
                        </span>
                    </div>
                    <div class="mb-2">
                        <strong>LLM-Anbieter:</strong>
                        <div class="small">${escapeHtml(providerLabel)}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Zugangsdaten:</strong>
                        <div class="small text-truncate" title="${escapeAttribute(credentialNames)}">${escapeHtml(credentialNames) || '<span class="text-muted">Keine ausgewählt</span>'}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Prompts:</strong>
                        <div class="small text-truncate" title="${escapeAttribute(promptNames)}">${escapeHtml(promptNames) || '<span class="text-muted">Keine ausgewählt</span>'}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Maximale Dauer:</strong>
                        <span class="small">${process.max_duration_minutes} Minuten</span>
                    </div>
                    ${formatSchedule(process)}
                    ${errorBlock}
                    <div class="text-end small text-muted">
                        <div>Aktualisiert ${formatRelative(process.updated_at)}</div>
                    </div>
                </div>
                <div class="card-footer bg-transparent">
                    <div class="d-flex flex-wrap gap-2">
                        <a class="btn btn-outline-info btn-sm" href="/processes/${process.id}/ai-comments">
                            <i class="bi bi-chat-dots"></i> Details anzeigen
                        </a>
                        ${process.is_running
                            ? `<button class="btn btn-outline-warning btn-sm" type="button" onclick="window.YM.monitoring.stopProcess('${process.id}')"><i class="bi bi-pause-circle"></i> Stoppen</button>`
                            : `<button class="btn btn-outline-success btn-sm" type="button" onclick="window.YM.monitoring.startProcess('${process.id}')"><i class="bi bi-play-circle"></i> Starten</button>`
                        }
                        <a class="btn btn-outline-primary btn-sm" href="/processes/${process.id}/edit">
                            <i class="bi bi-pencil"></i> Bearbeiten
                        </a>
                        <button class="btn btn-outline-danger btn-sm" type="button" onclick="window.YM.monitoring.deleteProcess('${process.id}')">
                            <i class="bi bi-trash"></i> Löschen
                        </button>
                    </div>
                </div>
            </div>
        `;

        processList.appendChild(col);
    });
}

export async function startProcess(processId) {
    try {
        const response = await fetch(`/api/v1/monitoring-processes/${processId}/start`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        await assertOk(response, 'Prozess konnte nicht gestartet werden.');
        window.showAlert('Prozess erfolgreich gestartet.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Start process error:', error);
        window.showAlert(error.message || 'Prozess konnte nicht gestartet werden.', 'danger');
    }
}

export async function stopProcess(processId) {
    try {
        const response = await fetch(`/api/v1/monitoring-processes/${processId}/stop`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        await assertOk(response, 'Prozess konnte nicht gestoppt werden.');
        window.showAlert('Prozess erfolgreich gestoppt.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Stop process error:', error);
        window.showAlert(error.message || 'Prozess konnte nicht gestoppt werden.', 'danger');
    }
}

export async function deleteProcess(processId) {
    if (!confirm('Diesen Überwachungsprozess löschen? Dies kann nicht rückgängig gemacht werden.')) {
        return;
    }
    try {
        const response = await fetch(`/api/v1/monitoring-processes/${processId}`, {
            method: 'DELETE',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        if (!response.ok) {
            const errorBody = await safeParseJson(response);
            const message = extractErrorMessage(errorBody) || `Prozess konnte nicht gelöscht werden (HTTP ${response.status}).`;
            window.showAlert(message, 'danger');
            return;
        }
        window.showAlert('Überwachungsprozess gelöscht.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Delete process error:', error);
        window.showAlert(error.message || 'Prozess konnte nicht gelöscht werden.', 'danger');
    }
}

function formatSchedule(process) {
    if (process.is_running) {
        const started = formatRelative(process.started_at);
        const expiresText = process.expires_at ? formatRelative(process.expires_at) : '';
        const expires = expiresText ? `<br>Läuft ab ${expiresText}` : '';
        return `<div class="mb-2"><strong>Aktiv:</strong><div class="small">Gestartet ${started}${expires}</div></div>`;
    }
    if (process.stopped_at) {
        return `<div class="mb-2"><strong>Letzter Lauf:</strong><div class="small">Gestoppt ${formatRelative(process.stopped_at)}</div></div>`;
    }
    return '<div class="mb-2"><strong>Status:</strong><div class="small">Noch nicht gestartet</div></div>';
}

function formatRelative(value) {
    if (!value) {
        return 'Nicht verfügbar';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'Nicht verfügbar';
    }

    const diffMs = date.getTime() - Date.now();
    const isFuture = diffMs > 0;
    const diffMinutes = Math.round(Math.abs(diffMs) / 60000);

    if (diffMinutes < 1) {
        return isFuture ? 'in weniger als einer Minute' : 'gerade eben';
    }

    if (diffMinutes < 60) {
        const unit = diffMinutes === 1 ? 'Minute' : 'Minuten';
        return isFuture
            ? `in ${diffMinutes} ${unit}`
            : `vor ${diffMinutes} ${unit}`;
    }

    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) {
        const unit = diffHours === 1 ? 'Stunde' : 'Stunden';
        return isFuture
            ? `in ${diffHours} ${unit}`
            : `vor ${diffHours} ${unit}`;
    }

    const diffDays = Math.round(diffHours / 24);
    const unit = diffDays === 1 ? 'Tag' : 'Tagen';
    return isFuture
        ? `in ${diffDays} ${unit}`
        : `vor ${diffDays} ${unit}`;
}
