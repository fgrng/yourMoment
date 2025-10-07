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

        await assertOk(processResp, 'Failed to load monitoring processes.');
        await assertOk(providerResp, 'Failed to load LLM providers.');
        await assertOk(templateResp, 'Failed to load prompt templates.');
        await assertOk(credentialResp, 'Failed to load myMoment credentials.');

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
        window.showAlert(error.message || 'Unable to load monitoring processes. Please try again.', 'danger');
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
    providerFilter.innerHTML = '<option value="ALL">All providers</option>';
    providers.forEach(provider => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = formatProviderLabel(provider.provider_name) + ' - ' + (provider.model_name || 'Model not set');
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
        emptyState.querySelector('h3').textContent = processes.length ? 'No processes match your filters' : 'No Monitoring Processes Yet';
        emptyState.querySelector('p').textContent = processes.length ? 'Adjust the filters or search terms to view other processes.' : 'Create a monitoring process to watch myMoment and post AI comments automatically.';
        return;
    }

    emptyState.style.display = 'none';
    processList.style.display = 'flex';

    list.forEach(process => {
        const col = document.createElement('div');
        col.className = 'col-12 col-lg-6 col-xxl-4 mb-4';

        const provider = providerMap.get(process.llm_provider_id);
        const providerLabel = provider ? `${formatProviderLabel(provider.provider_name)} - ${provider.model_name || 'Model not set'}` : 'Unknown provider';
        const promptNames = process.prompt_template_ids
            .map(templateId => promptTemplateMap.get(templateId)?.name || 'Unknown template')
            .join(', ');
        const credentialNames = process.mymoment_login_ids
            .map(credentialId => credentialMap.get(credentialId)?.name || credentialMap.get(credentialId)?.username || 'Unknown credential')
            .join(', ');

        const statusBadge = process.is_running
            ? '<span class="badge bg-success">Running</span>'
            : process.error_message ? '<span class="badge bg-danger">Error</span>' : '<span class="badge bg-secondary">Stopped</span>';

        const errorBlock = process.error_message
            ? `<div class="alert alert-warning mt-3 mb-0"><strong>Error:</strong> ${escapeHtml(process.error_message)}</div>`
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
                        <strong>Mode:</strong>
                        <span class="small">
                            ${process.generate_only
                                ? '<span class="badge bg-info">Generate Only</span>'
                                : '<span class="badge bg-primary">Generate & Post</span>'}
                        </span>
                    </div>
                    <div class="mb-2">
                        <strong>LLM Provider:</strong>
                        <div class="small">${escapeHtml(providerLabel)}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Credentials:</strong>
                        <div class="small text-truncate" title="${escapeAttribute(credentialNames)}">${escapeHtml(credentialNames) || '<span class="text-muted">None selected</span>'}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Prompts:</strong>
                        <div class="small text-truncate" title="${escapeAttribute(promptNames)}">${escapeHtml(promptNames) || '<span class="text-muted">None selected</span>'}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Max Duration:</strong>
                        <span class="small">${process.max_duration_minutes} minutes</span>
                    </div>
                    ${formatSchedule(process)}
                    ${errorBlock}
                    <div class="text-end small text-muted">
                        <div>Updated ${formatRelative(process.updated_at)}</div>
                    </div>
                </div>
                <div class="card-footer bg-transparent">
                    <div class="d-flex flex-wrap gap-2">
                        <a class="btn btn-outline-info btn-sm" href="/processes/${process.id}/ai-comments">
                            <i class="bi bi-chat-dots"></i> View Details
                        </a>
                        ${process.is_running
                            ? `<button class="btn btn-outline-warning btn-sm" type="button" onclick="window.YM.monitoring.stopProcess('${process.id}')"><i class="bi bi-pause-circle"></i> Stop</button>`
                            : `<button class="btn btn-outline-success btn-sm" type="button" onclick="window.YM.monitoring.startProcess('${process.id}')"><i class="bi bi-play-circle"></i> Start</button>`
                        }
                        <a class="btn btn-outline-primary btn-sm" href="/processes/${process.id}/edit">
                            <i class="bi bi-pencil"></i> Edit
                        </a>
                        <button class="btn btn-outline-danger btn-sm" type="button" onclick="window.YM.monitoring.deleteProcess('${process.id}')">
                            <i class="bi bi-trash"></i> Delete
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
        await assertOk(response, 'Failed to start process.');
        window.showAlert('Process started successfully.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Start process error:', error);
        window.showAlert(error.message || 'Unable to start process.', 'danger');
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
        await assertOk(response, 'Failed to stop process.');
        window.showAlert('Process stopped successfully.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Stop process error:', error);
        window.showAlert(error.message || 'Unable to stop process.', 'danger');
    }
}

export async function deleteProcess(processId) {
    if (!confirm('Delete this monitoring process? This action cannot be undone.')) {
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
            const message = extractErrorMessage(errorBody) || `Failed to delete process (HTTP ${response.status}).`;
            window.showAlert(message, 'danger');
            return;
        }
        window.showAlert('Monitoring process deleted.', 'success');
        loadAllData();
    } catch (error) {
        console.error('Delete process error:', error);
        window.showAlert(error.message || 'Unable to delete process.', 'danger');
    }
}

function formatSchedule(process) {
    if (process.is_running) {
        const started = formatRelative(process.started_at);
        const expires = process.expires_at ? `Expires ${formatRelative(process.expires_at)}` : '';
        return `<div class="mb-2"><strong>Running:</strong><div class="small">Started ${started}<br>${expires}</div></div>`;
    }
    if (process.stopped_at) {
        return `<div class="mb-2"><strong>Last Run:</strong><div class="small">Stopped ${formatRelative(process.stopped_at)}</div></div>`;
    }
    return '<div class="mb-2"><strong>Status:</strong><div class="small">Not started yet</div></div>';
}

function formatRelative(value) {
    if (!value) {
        return 'N/A';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'N/A';
    }

    const diffMs = date.getTime() - Date.now();
    const isFuture = diffMs > 0;
    const diffMinutes = Math.round(Math.abs(diffMs) / 60000);

    if (diffMinutes < 1) {
        return isFuture ? 'in less than a minute' : 'just now';
    }

    if (diffMinutes < 60) {
        return isFuture
            ? `in ${diffMinutes} minute${diffMinutes === 1 ? '' : 's'}`
            : `${diffMinutes} minute${diffMinutes === 1 ? '' : 's'} ago`;
    }

    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) {
        return isFuture
            ? `in ${diffHours} hour${diffHours === 1 ? '' : 's'}`
            : `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
    }

    const diffDays = Math.round(diffHours / 24);
    return isFuture
        ? `in ${diffDays} day${diffDays === 1 ? '' : 's'}`
        : `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
}
