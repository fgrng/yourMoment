/**
 * AI Comments Page JavaScript
 * Handles comment listing, filtering, polling, and posting operations
 */

import {
    escapeHtml,
    escapeAttribute,
    fetchOptions,
    safeParseJson,
    extractErrorMessage
} from './utils.js';

let allComments = [];
let monitoringProcess = null;
let pollingInterval = null;
let processId = null;

// DOM elements
let statusFilter, searchInput, limitSelect, refreshBtn;
let loadingState, emptyState, commentsList, processDetailsCard;

/**
 * Initialize the AI comments page
 * @param {string|null} processIdParam - Optional process ID for filtering
 */
export function initCommentsPage(processIdParam = null) {
    processId = processIdParam;

    // Get DOM elements
    statusFilter = document.getElementById('statusFilter');
    searchInput = document.getElementById('searchInput');
    limitSelect = document.getElementById('limitSelect');
    refreshBtn = document.getElementById('refreshBtn');
    loadingState = document.getElementById('loadingState');
    emptyState = document.getElementById('emptyState');
    commentsList = document.getElementById('commentsList');
    processDetailsCard = document.getElementById('processDetailsCard');

    // Event listeners
    statusFilter.addEventListener('change', () => renderComments(filterComments()));
    searchInput.addEventListener('input', () => renderComments(filterComments()));
    limitSelect.addEventListener('change', () => loadComments());
    refreshBtn.addEventListener('click', () => loadComments());

    // Initial load
    loadComments();

    // Clean up polling on page unload
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
    commentsList.style.display = 'none';
    commentsList.innerHTML = '';

    try {
        const limit = limitSelect.value;
        let commentsUrl = `/api/v1/comments/index?limit=${limit}`;

        // If viewing process-specific comments, add filter
        if (processId) {
            commentsUrl += `&monitoring_process_id=${processId}`;
            // Also fetch process details
            await loadProcessDetails();
        }

        const response = await fetch(commentsUrl, fetchOptions('GET'));

        if (!response.ok) {
            throw new Error(`Kommentare konnten nicht geladen werden (HTTP ${response.status})`);
        }

        const data = await response.json();
        allComments = data.items || [];

        loadingState.style.display = 'none';

        if (!allComments.length) {
            emptyState.style.display = 'block';
        } else {
            commentsList.style.display = 'flex';
            renderComments(filterComments());
        }

        // Setup polling if viewing process-specific comments and process is running
        updatePolling();

    } catch (error) {
        console.error('Error loading AI comments:', error);
        loadingState.style.display = 'none';
        window.showAlert(error.message || 'KI-Kommentare konnten nicht geladen werden. Bitte versuche es erneut.', 'danger');
    }
}

async function loadProcessDetails() {
    if (!processId) return;

    try {
        const response = await fetch(`/api/v1/monitoring-processes/${processId}`, fetchOptions('GET'));

        if (!response.ok) {
            return;
        }

        monitoringProcess = await response.json();
        renderProcessDetails();

    } catch (error) {
        console.error('Error loading process details:', error);
    }
}

function renderProcessDetails() {
    if (!monitoringProcess) {
        processDetailsCard.style.display = 'none';
        return;
    }

    const generatedCount = allComments.filter(c => c.status === 'generated').length;
    const postedCount = allComments.filter(c => c.status === 'posted').length;

    const statusBadgeClass = monitoringProcess.is_running
        ? 'bg-success'
        : monitoringProcess.error_message ? 'bg-danger' : 'bg-secondary';
    const statusText = monitoringProcess.is_running
        ? 'LÄUFT'
        : monitoringProcess.error_message ? 'FEHLER' : 'ANGEHALTEN';

    processDetailsCard.innerHTML = `
        <div class="card mt-4 border-primary">
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0">
                    <i class="bi bi-gear-fill me-2"></i>
                    Überwachungsprozess: ${escapeHtml(monitoringProcess.name)}
                </h5>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-8">
                        ${monitoringProcess.description ? `<p class="text-muted mb-3">${escapeHtml(monitoringProcess.description)}</p>` : ''}
                        <div class="row g-3 mb-3">
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Status</div>
                                <div class="fw-bold">
                                    <span class="badge ${statusBadgeClass}">
                                        ${statusText}
                                    </span>
                                </div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Modus</div>
                                <div class="fw-bold">
                                    ${monitoringProcess.generate_only
                                        ? '<span class="badge bg-warning text-dark">Nur erzeugen</span>'
                                        : '<span class="badge bg-primary">Erzeugen & Veröffentlichen</span>'}
                                </div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Gefundene Artikel</div>
                                <div class="fw-bold">${monitoringProcess.articles_discovered || 0}</div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Generierte Kommentare</div>
                                <div class="fw-bold">${monitoringProcess.comments_generated || 0}</div>
                            </div>
                        </div>
                        <div class="row g-3">
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Ausstehende Veröffentlichungen</div>
                                <div class="fw-bold text-warning">${generatedCount}</div>
                            </div>
                            <div class="col-6 col-md-3">
                                <div class="text-muted small">Veröffentlichte insgesamt</div>
                                <div class="fw-bold text-success">${postedCount}</div>
                            </div>
                            <div class="col-12 col-md-6">
                                <div class="text-muted small">Letzte Aktivität</div>
                                <div class="small">
                                    ${formatLastActivity(monitoringProcess)}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4 border-start">
                        <h6 class="mb-3">Aktionen</h6>
                        <div class="d-grid gap-2">
                            <button
                                class="btn btn-success"
                                id="postCommentsBtn"
                                ${generatedCount === 0 ? 'disabled' : ''}>
                                <i class="bi bi-send-fill me-2"></i>
                                Alle generierten Kommentare veröffentlichen
                                ${generatedCount > 0 ? `<span class="badge bg-white text-success ms-1">${generatedCount}</span>` : ''}
                            </button>
                            <a href="/processes/${monitoringProcess.id}/edit" class="btn btn-outline-primary">
                                <i class="bi bi-pencil me-2"></i>Prozess bearbeiten
                            </a>
                            <a href="/processes" class="btn btn-outline-secondary">
                                <i class="bi bi-arrow-left me-2"></i>Zurück zu den Prozessen
                            </a>
                        </div>
                        ${generatedCount === 0
                            ? `<div class="alert alert-info mt-3 small mb-0">
                                <i class="bi bi-info-circle me-1"></i>
                                Keine ausstehenden Kommentare zum Veröffentlichen
                            </div>`
                            : `<div class="alert alert-warning mt-3 small mb-0">
                                <i class="bi bi-exclamation-triangle me-1"></i>
                                ${generatedCount} Kommentar${generatedCount === 1 ? '' : 'e'} zur Veröffentlichung bereit
                            </div>`}
                    </div>
                </div>
            </div>
        </div>
    `;

    processDetailsCard.style.display = 'block';

    // Attach event listener for post comments button
    const postCommentsBtn = document.getElementById('postCommentsBtn');
    if (postCommentsBtn) {
        postCommentsBtn.addEventListener('click', handlePostAllComments);
    }
}

async function handlePostAllComments() {
    if (!monitoringProcess) return;

    if (!confirm('Alle generierten Kommentare für diesen Überwachungsprozess veröffentlichen?')) {
        return;
    }

    const btn = document.getElementById('postCommentsBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aufgabe wird gestartet…';

    try {
        const response = await fetch(`/api/v1/monitoring-processes/${processId}/post-comments`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Aufgabe zum Veröffentlichen der Kommentare konnte nicht gestartet werden');
        }

        const data = await response.json();

        window.showAlert(`Aufgabe zum Veröffentlichen der Kommentare erfolgreich gestartet! Aufgaben-ID: ${data.task_id}. Die Kommentare werden im Hintergrund veröffentlicht. Aktualisiere diese Seite, um Updates zu sehen.`, 'success');

        btn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Aufgabe gestartet';

        setTimeout(() => {
            if (confirm('Das Veröffentlichen läuft. Seite aktualisieren, um Updates zu sehen?')) {
                window.location.reload();
            }
        }, 3000);

    } catch (error) {
        console.error('Error starting comment posting task:', error);
        window.showAlert(`Kommentarveröffentlichung konnte nicht gestartet werden: ${error.message}`, 'danger');
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function updatePolling() {
    const shouldPoll = monitoringProcess && monitoringProcess.is_running;

    if (shouldPoll && !pollingInterval) {
        pollingInterval = setInterval(() => {
            loadComments();
        }, 10000); // Poll every 10 seconds
    } else if (!shouldPoll && pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function filterComments() {
    const status = statusFilter.value;
    const query = searchInput.value.trim().toLowerCase();

    return allComments.filter(comment => {
        const matchesStatus = status === 'ALL' || comment.status === status;

        const haystack = [
            comment.article_title || '',
            comment.article_author || ''
        ].join(' ').toLowerCase();
        const matchesQuery = !query || haystack.includes(query);

        return matchesStatus && matchesQuery;
    });
}

function renderComments(comments) {
    commentsList.innerHTML = '';

    if (!comments.length) {
        commentsList.style.display = 'none';
        emptyState.style.display = 'block';
        emptyState.querySelector('h3').textContent = allComments.length ? 'Keine Kommentare entsprechen deinen Filtern' : 'Noch keine KI-Kommentare';
        emptyState.querySelector('p').textContent = allComments.length ? 'Passe Filter oder Suchbegriffe an, um weitere Kommentare anzuzeigen.' : 'Sobald Überwachungsprozesse Kommentare generieren, erscheinen sie hier.';
        return;
    }

    emptyState.style.display = 'none';
    commentsList.style.display = 'flex';

    comments.forEach(comment => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';

        const statusBadgeClass = comment.status === 'posted'
            ? 'bg-success'
            : comment.status === 'generated' ? 'bg-info text-dark'
            : comment.status === 'failed' ? 'bg-danger'
            : 'bg-secondary';
        const statusLabel = formatCommentStatus(comment.status);

        const truncatedTitle = (comment.article_title || 'Unbekannter Artikel').length > 25
            ? (comment.article_title || 'Unbekannter Artikel').substring(0, 25) + '…'
            : (comment.article_title || 'Unbekannter Artikel');

        const commentPreview = comment.comment_content
            ? (comment.comment_content.length > 160
                ? comment.comment_content.substring(0, 160) + '…'
                : comment.comment_content)
            : '<span class="fst-italic">Kein Kommentarinhalt erfasst.</span>';

        col.innerHTML = `
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                        <h5 class="mb-1 text-truncate" data-bs-toggle="tooltip" data-bs-placement="top" title="${escapeAttribute(comment.article_title || 'Unbekannter Artikel')}">
                            <i class="bi bi-journal-text me-2"></i>
                            ${escapeHtml(truncatedTitle)}
                        </h5>
                        <span class="badge ${statusBadgeClass}">
                            ${statusLabel}
                        </span>
                    </div>
                    <small class="text-muted text-end ms-2">
                        ${formatDate(comment.created_at)}
                    </small>
                </div>
                <div class="card-body">
                    <p class="small text-muted mb-2">Autor: ${escapeHtml(comment.article_author || 'Unbekannt')}</p>
                    <div class="mb-2">
                        <strong>Kommentarvorschau:</strong>
                        <p class="small text-muted mb-0">
                            ${commentPreview}
                        </p>
                    </div>
                    <div class="small text-muted">
                        Modell: ${escapeHtml(comment.ai_provider_name || 'k. A.')} ${escapeHtml(comment.ai_model_name || '')}
                    </div>
                    <div class="small text-muted">
                        Veröffentlicht am: ${comment.posted_at ? formatDate(comment.posted_at) : 'Noch nicht veröffentlicht'}
                    </div>
                </div>
                <div class="card-footer bg-transparent">
                    <div class="d-flex flex-wrap gap-2">
                        <a href="/ai-comments/${comment.id}" class="btn btn-outline-primary btn-sm">
                            <i class="bi bi-eye"></i> Details anzeigen
                        </a>
                        <button
                            class="btn btn-success btn-sm post-comment-btn"
                            data-comment-id="${comment.id}"
                            ${comment.status === 'posted' ? 'disabled' : ''}>
                            <i class="bi bi-send"></i> ${comment.status === 'posted' ? 'Veröffentlicht' : 'Auf myMoment veröffentlichen'}
                        </button>
                    </div>
                </div>
            </div>
        `;

        commentsList.appendChild(col);
    });

    // Attach post comment event listeners
    document.querySelectorAll('.post-comment-btn').forEach(button => {
        if (!button.disabled) {
            button.addEventListener('click', handlePostComment);
        }
    });
}

function formatCommentStatus(status) {
    const mapping = {
        posted: 'Veröffentlicht',
        generated: 'Generiert',
        failed: 'Fehlgeschlagen',
        skipped: 'Übersprungen',
        pending: 'Ausstehend'
    };
    return mapping[status] || status;
}

async function handlePostComment(event) {
    const button = event.currentTarget;
    const commentId = button.getAttribute('data-comment-id');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Wird veröffentlicht…';

    try {
        const response = await fetch(`/api/v1/comments/${commentId}/post`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Kommentar konnte nicht veröffentlicht werden');
        }

        const data = await response.json();

        // Update UI
        button.innerHTML = '<i class="bi bi-check-circle"></i> Veröffentlicht';
        button.classList.remove('btn-success');
        button.classList.add('btn-secondary');

        // Update status badge in card header
        const card = button.closest('.card');
        const statusBadge = card.querySelector('.badge');
        if (statusBadge) {
            statusBadge.textContent = formatCommentStatus('posted');
            statusBadge.className = 'badge bg-success';
        }

        // Update comment in local array
        const commentIndex = allComments.findIndex(c => c.id === commentId);
        if (commentIndex !== -1) {
            allComments[commentIndex].status = 'posted';
            allComments[commentIndex].posted_at = data.posted_at;
        }

        window.showAlert('Kommentar erfolgreich auf myMoment veröffentlicht!', 'success');

        // Refresh process details if viewing process-specific comments
        if (processId) {
            await loadProcessDetails();
        }

    } catch (error) {
        console.error('Error posting comment:', error);
        window.showAlert(`Kommentar konnte nicht veröffentlicht werden: ${error.message}`, 'danger');
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

function formatLastActivity(process) {
    if (process.stopped_at) {
        return `Gestoppt: ${formatDateTime(process.stopped_at)}`;
    } else if (process.started_at) {
        return `Gestartet: ${formatDateTime(process.started_at)}`;
    } else {
        return `Erstellt: ${formatDateTime(process.created_at)}`;
    }
}

function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toISOString().slice(0, 16).replace('T', ' ');
}

function formatDateTime(dateString) {
    if (!dateString) return 'Nicht verfügbar';
    const date = new Date(dateString);
    return date.toISOString().slice(0, 16).replace('T', ' ');
}
