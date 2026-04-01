/**
 * AI Comments Page JavaScript
 * Handles comment listing, filtering, polling, and posting operations.
 */

import {
    escapeHtml,
    escapeAttribute,
    fetchOptions,
    safeParseJson,
    extractErrorMessage,
    formatDate,
    formatProviderLabel
} from './utils.js';

let allComments = [];
let monitoringProcess = null;
let pipelineStatus = null;
let pollingInterval = null;
let processId = null;

// DOM elements
let statusFilter;
let searchInput;
let limitSelect;
let refreshBtn;
let loadingState;
let emptyState;
let commentsList;
let processDetailsCard;

/**
 * Initialize the AI comments page.
 * @param {string|null} processIdParam - Optional process ID for filtering.
 */
export function initCommentsPage(processIdParam = null) {
    processId = processIdParam;

    statusFilter = document.getElementById('statusFilter');
    searchInput = document.getElementById('searchInput');
    limitSelect = document.getElementById('limitSelect');
    refreshBtn = document.getElementById('refreshBtn');
    loadingState = document.getElementById('loadingState');
    emptyState = document.getElementById('emptyState');
    commentsList = document.getElementById('commentsList');
    processDetailsCard = document.getElementById('processDetailsCard');

    statusFilter.addEventListener('change', () => renderComments(filterComments()));
    searchInput.addEventListener('input', () => renderComments(filterComments()));
    limitSelect.addEventListener('change', () => loadComments());
    refreshBtn.addEventListener('click', () => loadComments());

    loadComments();

    window.addEventListener('beforeunload', () => {
        if (pollingInterval) {
            clearInterval(pollingInterval);
        }
    });
}

async function loadComments() {
    window.showAlert();
    loadingState.style.display = 'block';
    emptyState.style.display = 'none';

    try {
        const limit = limitSelect.value;
        let commentsUrl = `/api/v1/comments/index?limit=${limit}`;

        if (processId) {
            commentsUrl += `&monitoring_process_id=${processId}`;
            await loadProcessDetails();
        }

        const response = await fetch(commentsUrl, fetchOptions('GET'));
        await assertOk(response, 'Kommentare konnten nicht geladen werden.');

        const data = await response.json();
        allComments = data.items || [];

        loadingState.style.display = 'none';
        renderComments(filterComments());
        updatePolling();
    } catch (error) {
        console.error('Error loading AI comments:', error);
        loadingState.style.display = 'none';
        window.showAlert(
            error.message || 'KI-Kommentare konnten nicht geladen werden. Bitte versuche es erneut.',
            'danger'
        );
    }
}

async function loadProcessDetails() {
    if (!processId) {
        return;
    }

    try {
        const [processResponse, pipelineResponse] = await Promise.all([
            fetch(`/api/v1/monitoring-processes/${processId}`, fetchOptions('GET')),
            fetch(`/api/v1/monitoring-processes/${processId}/pipeline-status`, fetchOptions('GET'))
        ]);

        await assertOk(processResponse, 'Prozessdetails konnten nicht geladen werden.');
        monitoringProcess = await processResponse.json();

        if (pipelineResponse.ok) {
            pipelineStatus = await pipelineResponse.json();
        } else {
            pipelineStatus = null;
        }

        renderProcessDetails();
    } catch (error) {
        console.error('Error loading process details:', error);
        processDetailsCard.style.display = 'none';
        window.showAlert(error.message || 'Prozessdetails konnten nicht geladen werden.', 'danger');
    }
}

function renderProcessDetails() {
    if (!monitoringProcess) {
        processDetailsCard.style.display = 'none';
        return;
    }

    const discoveredCount = pipelineStatus ? pipelineStatus.discovered : 0;
    const preparedCount = pipelineStatus ? pipelineStatus.prepared : 0;
    const generatedCount = pipelineStatus ? pipelineStatus.generated : 0;
    const postedCount = pipelineStatus ? pipelineStatus.posted : 0;
    const failedCount = pipelineStatus ? pipelineStatus.failed : 0;
    const totalCount = pipelineStatus ? pipelineStatus.total : 0;

    const statusBadge = monitoringProcess.is_running
        ? '<span class="badge bg-success">Laeuft</span>'
        : monitoringProcess.error_message
            ? '<span class="badge bg-danger">Fehler</span>'
            : '<span class="badge bg-secondary">Angehalten</span>';

    const postAllDisabled = generatedCount === 0 ? 'disabled' : '';
    const startStopAction = monitoringProcess.is_running
        ? `<button class="btn btn-outline-warning" type="button" id="toggleProcessBtn">
                <i class="bi bi-pause-circle me-2"></i>Prozess stoppen
           </button>`
        : `<button class="btn btn-outline-success" type="button" id="toggleProcessBtn">
                <i class="bi bi-play-circle me-2"></i>Prozess starten
           </button>`;

    processDetailsCard.innerHTML = `
        <div class="card mt-4 border-primary shadow-sm">
            <div class="card-header bg-primary text-white d-flex justify-content-between align-items-start gap-3">
                <div>
                    <h5 class="mb-1">
                        <i class="bi bi-gear-fill me-2"></i>${escapeHtml(monitoringProcess.name)}
                    </h5>
                    ${monitoringProcess.description ? `<div class="small opacity-75">${escapeHtml(monitoringProcess.description)}</div>` : ''}
                </div>
                <div>${statusBadge}</div>
            </div>
            <div class="card-body">
                <div class="row g-3 mb-4">
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Entdeckt</div>
                        <div class="fw-bold text-secondary fs-5">${discoveredCount}</div>
                    </div>
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Vorbereitet</div>
                        <div class="fw-bold text-primary fs-5">${preparedCount}</div>
                    </div>
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Generiert</div>
                        <div class="fw-bold text-warning fs-5">${generatedCount}</div>
                    </div>
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Veroeffentlicht</div>
                        <div class="fw-bold text-success fs-5">${postedCount}</div>
                    </div>
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Fehlgeschlagen</div>
                        <div class="fw-bold text-danger fs-5">${failedCount}</div>
                    </div>
                    <div class="col-6 col-lg-2">
                        <div class="text-muted small">Gesamt</div>
                        <div class="fw-bold fs-5">${totalCount}</div>
                    </div>
                </div>

                <div class="row g-3 mb-4">
                    <div class="col-md-4">
                        <div class="text-muted small">Modus</div>
                        <div class="fw-semibold">
                            ${monitoringProcess.generate_only
                                ? 'Nur generieren'
                                : 'Generieren und veroeffentlichen'}
                            ${monitoringProcess.hide_comments ? '<span class="badge bg-secondary ms-2">Versteckt</span>' : ''}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-muted small">Maximale Laufzeit</div>
                        <div class="fw-semibold">${monitoringProcess.max_duration_minutes} Minuten</div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-muted small">Letzte Aktivitaet</div>
                        <div class="fw-semibold">${formatLastActivity(monitoringProcess)}</div>
                    </div>
                </div>

                ${monitoringProcess.error_message
                    ? `<div class="alert alert-warning mb-4"><strong>Prozessfehler:</strong> ${escapeHtml(monitoringProcess.error_message)}</div>`
                    : ''}

                <div class="d-flex flex-wrap gap-2">
                    ${startStopAction}
                    <button class="btn btn-success" type="button" id="postCommentsBtn" ${postAllDisabled}>
                        <i class="bi bi-send-fill me-2"></i>Generierte Kommentare veroeffentlichen
                    </button>
                    <a href="/processes/${monitoringProcess.id}/edit" class="btn btn-outline-primary">
                        <i class="bi bi-pencil me-2"></i>Prozess bearbeiten
                    </a>
                    <a href="/processes" class="btn btn-outline-secondary">
                        <i class="bi bi-arrow-left me-2"></i>Zurueck zu den Prozessen
                    </a>
                </div>
            </div>
        </div>
    `;

    processDetailsCard.style.display = 'block';

    const postCommentsBtn = document.getElementById('postCommentsBtn');
    if (postCommentsBtn) {
        postCommentsBtn.addEventListener('click', handlePostAllComments);
    }

    const toggleProcessBtn = document.getElementById('toggleProcessBtn');
    if (toggleProcessBtn) {
        toggleProcessBtn.addEventListener('click', async () => {
            if (monitoringProcess.is_running) {
                await window.YM.monitoring.stopProcess(monitoringProcess.id);
            } else {
                await window.YM.monitoring.startProcess(monitoringProcess.id);
            }
            await loadComments();
        });
    }
}

async function handlePostAllComments() {
    if (!monitoringProcess) {
        return;
    }

    if (!confirm('Alle generierten Kommentare fuer diesen Ueberwachungsprozess veroeffentlichen?')) {
        return;
    }

    const btn = document.getElementById('postCommentsBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aufgabe wird gestartet...';

    try {
        const response = await fetch(
            `/api/v1/monitoring-processes/${processId}/post-comments`,
            fetchOptions('POST')
        );
        await assertOk(response, 'Aufgabe zum Veroeffentlichen der Kommentare konnte nicht gestartet werden.');

        const data = await response.json();
        window.showAlert(
            `Aufgabe zum Veroeffentlichen der Kommentare gestartet. Aufgaben-ID: ${escapeHtml(data.task_id)}`,
            'success'
        );

        btn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Aufgabe gestartet';
        await loadComments();
    } catch (error) {
        console.error('Error starting comment posting task:', error);
        window.showAlert(`Kommentarveroeffentlichung konnte nicht gestartet werden: ${error.message}`, 'danger');
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function updatePolling() {
    const shouldPoll = Boolean(monitoringProcess && monitoringProcess.is_running);

    if (shouldPoll && !pollingInterval) {
        pollingInterval = setInterval(() => {
            loadComments();
        }, 10000);
    } else if (!shouldPoll && pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function filterComments() {
    const status = statusFilter.value;
    const query = searchInput.value.trim().toLowerCase();

    return allComments.filter((comment) => {
        const matchesStatus = status === 'ALL' || comment.status === status;
        const haystack = [
            comment.article_title || '',
            comment.article_author || '',
            comment.comment_content || '',
            comment.ai_provider_name || '',
            comment.ai_model_name || ''
        ].join(' ').toLowerCase();

        return matchesStatus && (!query || haystack.includes(query));
    });
}

function renderComments(comments) {
    commentsList.innerHTML = '';

    if (!comments.length) {
        commentsList.style.display = 'none';
        renderEmptyState();
        return;
    }

    emptyState.style.display = 'none';
    commentsList.style.display = 'flex';

    comments.forEach((comment) => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-xl-4';

        const statusMeta = getStatusMeta(comment.status);
        const commentPreview = buildCommentPreview(comment);
        const generationMeta = buildGenerationMeta(comment);
        const postingMeta = buildPostingMeta(comment);
        const processMeta = !processId && comment.monitoring_process_id
            ? `<span class="badge bg-light text-dark border">Prozess</span>`
            : '';
        const loginMeta = comment.mymoment_login_id
            ? '<span class="badge bg-light text-dark border">Zugang hinterlegt</span>'
            : '';
        const errorBlock = comment.error_message
            ? `<div class="alert alert-warning py-2 px-3 mt-3 mb-0 small"><strong>Fehler:</strong> ${escapeHtml(comment.error_message)}</div>`
            : '';

        col.innerHTML = `
            <div class="card h-100 shadow-sm">
                <div class="card-header d-flex justify-content-between align-items-start gap-3">
                    <div class="min-w-0">
                        <h5 class="mb-1 text-truncate" data-bs-toggle="tooltip" data-bs-placement="top" title="${escapeAttribute(comment.article_title || 'Unbekannter Artikel')}">
                            <i class="bi bi-journal-text me-2"></i>${escapeHtml(comment.article_title || 'Unbekannter Artikel')}
                        </h5>
                        <div class="d-flex flex-wrap gap-1">
                            <span class="badge comment-status-badge ${statusMeta.badgeClass}">${statusMeta.label}</span>
                            ${comment.is_hidden ? '<span class="badge bg-secondary"><i class="bi bi-eye-slash me-1"></i>Versteckt</span>' : '<span class="badge bg-light text-dark border"><i class="bi bi-eye me-1"></i>Sichtbar</span>'}
                            ${processMeta}
                            ${loginMeta}
                        </div>
                    </div>
                    <small class="text-muted text-end">${formatDate(comment.created_at, 'Unbekannt')}</small>
                </div>
                <div class="card-body">
                    <p class="small text-muted mb-3">Autor: ${escapeHtml(comment.article_author || 'Unbekannt')}</p>
                    <div class="mb-3">
                        <strong>Kommentar</strong>
                        <p class="small text-muted mb-0">${commentPreview}</p>
                    </div>
                    <div class="small text-muted mb-2">${generationMeta}</div>
                    <div class="small text-muted">${postingMeta}</div>
                    ${errorBlock}
                </div>
                <div class="card-footer bg-transparent d-flex flex-wrap gap-2">
                    <a href="/ai-comments/${comment.id}" class="btn btn-outline-primary btn-sm">
                        <i class="bi bi-eye me-1"></i>Details
                    </a>
                    <button
                        class="btn ${comment.status === 'generated' ? 'btn-success' : 'btn-outline-success'} btn-sm post-comment-btn"
                        data-comment-id="${comment.id}"
                        ${comment.status === 'generated' ? '' : 'disabled'}>
                        <i class="bi bi-send me-1"></i>${comment.status === 'posted' ? 'Veroeffentlicht' : 'Auf myMoment veroeffentlichen'}
                    </button>
                </div>
            </div>
        `;

        commentsList.appendChild(col);
    });

    document.querySelectorAll('.post-comment-btn').forEach((button) => {
        if (!button.disabled) {
            button.addEventListener('click', handlePostComment);
        }
    });
}

function renderEmptyState() {
    emptyState.style.display = 'block';

    const heading = emptyState.querySelector('h3');
    const copy = emptyState.querySelector('p');

    if (allComments.length) {
        heading.textContent = 'Keine Kommentare entsprechen deinen Filtern';
        copy.textContent = 'Passe Filter oder Suchbegriffe an, um weitere Kommentare anzuzeigen.';
        return;
    }

    if (processId && monitoringProcess?.is_running) {
        heading.textContent = 'Der Prozess arbeitet noch';
        copy.textContent = 'Kommentare erscheinen hier, sobald der Ueberwachungsprozess Artikel entdeckt und verarbeitet.';
        return;
    }

    heading.textContent = 'Noch keine KI-Kommentare';
    copy.textContent = 'Sobald Ueberwachungsprozesse KI-Kommentare erzeugen, erscheinen sie hier.';
}

function getStatusMeta(status) {
    const mapping = {
        discovered: { label: 'Entdeckt', badgeClass: 'bg-secondary' },
        prepared: { label: 'Vorbereitet', badgeClass: 'bg-primary' },
        generated: { label: 'Generiert', badgeClass: 'bg-warning text-dark' },
        posted: { label: 'Veroeffentlicht', badgeClass: 'bg-success' },
        failed: { label: 'Fehlgeschlagen', badgeClass: 'bg-danger' },
        deleted: { label: 'Geloescht', badgeClass: 'bg-dark' }
    };
    return mapping[status] || { label: status || 'Unbekannt', badgeClass: 'bg-secondary' };
}

function buildCommentPreview(comment) {
    if (!comment.comment_content) {
        if (comment.status === 'discovered') {
            return '<span class="fst-italic">Artikel wurde entdeckt, aber noch nicht vorbereitet.</span>';
        }
        if (comment.status === 'prepared') {
            return '<span class="fst-italic">Artikelinhalt ist vorbereitet, die Generierung laeuft noch.</span>';
        }
        return '<span class="fst-italic">Kein Kommentarinhalt gespeichert.</span>';
    }

    const preview = comment.comment_content.length > 200
        ? `${comment.comment_content.substring(0, 200)}...`
        : comment.comment_content;

    return escapeHtml(preview);
}

function buildGenerationMeta(comment) {
    const providerLabel = comment.ai_provider_name
        ? formatProviderLabel(comment.ai_provider_name)
        : 'k. A.';
    const modelLabel = comment.ai_model_name || 'kein Modell';
    const timing = comment.generation_time_ms ? `${comment.generation_time_ms} ms` : 'keine Zeitmessung';
    const tokens = comment.generation_tokens ? `${comment.generation_tokens} Tokens` : 'keine Tokenzahl';

    return `Generierung: ${escapeHtml(providerLabel)} / ${escapeHtml(modelLabel)} | ${timing} | ${tokens}`;
}

function buildPostingMeta(comment) {
    if (comment.status === 'posted') {
        return `Veroeffentlicht: ${formatDate(comment.posted_at, 'Unbekannt')}`;
    }
    if (comment.status === 'failed') {
        return `Fehlgeschlagen: ${formatDate(comment.failed_at, 'Unbekannt')}`;
    }
    return `Artikel-Snapshot: ${formatDate(comment.article_scraped_at, 'Unbekannt')}`;
}

async function handlePostComment(event) {
    const button = event.currentTarget;
    const commentId = button.getAttribute('data-comment-id');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Wird veroeffentlicht...';

    try {
        const response = await fetch(`/api/v1/comments/${commentId}/post`, fetchOptions('POST'));
        await assertOk(response, 'Kommentar konnte nicht veroeffentlicht werden.');

        const data = await response.json();
        const commentIndex = allComments.findIndex((item) => item.id === commentId);
        if (commentIndex !== -1) {
            allComments[commentIndex] = data;
        }

        window.showAlert('Kommentar erfolgreich auf myMoment veroeffentlicht.', 'success');
        renderComments(filterComments());

        if (processId) {
            await loadProcessDetails();
        }
    } catch (error) {
        console.error('Error posting comment:', error);
        window.showAlert(`Kommentar konnte nicht veroeffentlicht werden: ${error.message}`, 'danger');
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

async function assertOk(response, message) {
    if (response.ok) {
        return;
    }

    const errorBody = await safeParseJson(response);
    const detail = extractErrorMessage(errorBody) || `${message} (HTTP ${response.status})`;
    throw new Error(detail);
}

function formatLastActivity(process) {
    if (process.stopped_at) {
        return `Gestoppt: ${formatDate(process.stopped_at, 'Nicht verfuegbar')}`;
    }
    if (process.started_at) {
        return `Gestartet: ${formatDate(process.started_at, 'Nicht verfuegbar')}`;
    }
    return `Erstellt: ${formatDate(process.created_at, 'Nicht verfuegbar')}`;
}
