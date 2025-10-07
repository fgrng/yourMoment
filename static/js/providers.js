/**
 * LLM Providers Page JavaScript
 * Handles provider listing, filtering, and CRUD operations
 */

import {
    escapeHtml,
    formatDate,
    formatProviderLabel,
    fetchOptions,
    showLoadingState,
    showEmptyState,
    showContentState,
    deleteResource
} from './utils.js';

let providers = [];
let providerFilter, searchInput, loadingState, emptyState, providersList;

/**
 * Initialize the LLM providers page
 */
export function initProvidersPage() {
    providerFilter = document.getElementById('providerFilter');
    searchInput = document.getElementById('searchInput');
    loadingState = document.getElementById('loadingState');
    emptyState = document.getElementById('emptyState');
    providersList = document.getElementById('providersList');

    providerFilter.addEventListener('change', () => renderProviders(filterProviders()));
    searchInput.addEventListener('input', () => renderProviders(filterProviders()));

    loadProviders();
}

async function loadProviders() {
    showLoadingState(loadingState, [emptyState, providersList]);
    providersList.innerHTML = '';
    window.showAlert();

    try {
        const response = await fetch('/api/v1/llm-providers/index', fetchOptions('GET'));

        if (!response.ok) {
            throw new Error(`Anbieter konnten nicht geladen werden (HTTP ${response.status})`);
        }

        providers = await response.json();

        if (!providers.length) {
            showEmptyState(emptyState, [loadingState, providersList]);
        } else {
            showContentState(providersList, [loadingState, emptyState]);
            providersList.style.display = 'flex';
            renderProviders(filterProviders());
        }
    } catch (error) {
        console.error('Error loading providers:', error);
        showLoadingState(null, [loadingState, emptyState, providersList]);
        window.showAlert('LLM-Anbieter konnten nicht geladen werden. Bitte versuche es erneut.', 'danger');
    }
}

function filterProviders() {
    const vendor = providerFilter.value;
    const query = searchInput.value.trim().toLowerCase();

    return providers.filter(provider => {
        const matchesVendor = vendor === 'ALL' || provider.provider_name === vendor;
        const haystack = [
            provider.provider_name || '',
            provider.model_name || '',
            (provider.max_tokens || '').toString()
        ].join(' ').toLowerCase();
        const matchesQuery = !query || haystack.includes(query);
        return matchesVendor && matchesQuery;
    });
}

function renderProviders(items) {
    providersList.innerHTML = '';

    if (!items.length) {
        providersList.style.display = 'none';
        emptyState.style.display = providers.length ? 'block' : 'none';
        if (providers.length) {
            emptyState.querySelector('h3').textContent = 'Keine Anbieter entsprechen deinen Filtern';
            emptyState.querySelector('p').textContent = 'Passe Filter oder Suchbegriffe an, um andere Anbieter zu sehen.';
        } else {
            emptyState.querySelector('h3').textContent = 'Noch keine LLM-Anbieter';
            emptyState.querySelector('p').textContent = 'Füge deinen ersten Anbieter hinzu, um automatische Kommentare zu aktivieren.';
        }
        return;
    }

    emptyState.style.display = 'none';
    providersList.style.display = 'flex';

    items.forEach(provider => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4 mb-4';

        const providerLabel = formatProviderLabel(provider.provider_name);
        const model = provider.model_name ? escapeHtml(provider.model_name) : '<span class="text-muted">Kein Modell festgelegt</span>';
        const tokens = provider.max_tokens ? `${provider.max_tokens} Token` : 'Standard-Token';
        const temperature = provider.temperature !== null && provider.temperature !== undefined
            ? provider.temperature.toFixed(2)
            : 'Standard';

        col.innerHTML = `
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-start">
                    <div>
                        <h5 class="mb-1">${providerLabel}</h5>
                        <span class="badge ${provider.is_active ? 'bg-success' : 'bg-secondary'}">
                            ${provider.is_active ? 'Aktiv' : 'Inaktiv'}
                        </span>
                    </div>
                    <small class="text-muted text-end">${formatDate(provider.created_at)}</small>
                </div>
                <div class="card-body">
                    <div class="mb-2">
                        <strong>Modell:</strong>
                        <div>${model}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Maximale Token:</strong>
                        <div>${tokens}</div>
                    </div>
                    <div class="mb-2">
                        <strong>Temperatur:</strong>
                        <div>${temperature}</div>
                    </div>
                    <div class="small text-muted">API-Schlüssel werden verschlüsselt und nach dem Speichern nicht angezeigt.</div>
                </div>
                <div class="card-footer bg-transparent">
                    <div class="d-flex gap-2">
                        <a class="btn btn-outline-primary btn-sm flex-grow-1" href="/settings/llm-providers/${provider.id}/edit">
                            <i class="bi bi-pencil"></i> Bearbeiten
                        </a>
                        <button class="btn btn-outline-danger btn-sm" type="button" onclick="window.YM.providers.deleteProvider('${provider.id}')">
                            <i class="bi bi-trash"></i> Löschen
                        </button>
                    </div>
                </div>
            </div>
        `;

        providersList.appendChild(col);
    });
}

export async function deleteProvider(providerId) {
    try {
        await deleteResource(
            `/api/v1/llm-providers/${providerId}`,
            'Anbieterkonfiguration',
            () => {
                window.showAlert('Anbieterkonfiguration erfolgreich gelöscht.', 'success');
                setTimeout(loadProviders, 800);
            }
        );
    } catch (error) {
        window.showAlert(`Fehler beim Löschen des Anbieters: ${error.message}`, 'danger');
    }
}
