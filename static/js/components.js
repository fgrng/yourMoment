/**
 * Reusable UI components for yourMoment application
 *
 * This module provides factory functions for common UI patterns:
 * - Loading spinners
 * - Empty states
 * - Filter controls
 * - Card layouts
 */

import { escapeHtml, escapeAttribute } from './utils.js';

// ============================================================================
// State Components
// ============================================================================

/**
 * Create a loading spinner component
 * @param {string} message - Loading message to display
 * @param {string} id - Element ID (optional)
 * @returns {string} HTML string
 */
export function createLoadingSpinner(message = 'Loading...', id = 'loadingState') {
    return `
        <div id="${id}" class="text-center my-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-2 text-muted">${escapeHtml(message)}</p>
        </div>
    `;
}

/**
 * Create an empty state component
 * @param {Object} options - Configuration object
 * @param {string} options.icon - Bootstrap icon class (e.g., 'journal-text')
 * @param {string} options.title - Title text
 * @param {string} options.description - Description text
 * @param {string} options.buttonText - Button text (optional)
 * @param {string} options.buttonUrl - Button URL (optional)
 * @param {string} options.id - Element ID (default: 'emptyState')
 * @returns {string} HTML string
 */
export function createEmptyState(options) {
    const {
        icon,
        title,
        description,
        buttonText = null,
        buttonUrl = null,
        id = 'emptyState'
    } = options;

    const buttonHtml = buttonText && buttonUrl
        ? `<a href="${escapeAttribute(buttonUrl)}" class="btn btn-primary mt-3">
               <i class="bi bi-plus-circle me-2"></i>${escapeHtml(buttonText)}
           </a>`
        : '';

    return `
        <div id="${id}" class="text-center my-5" style="display: none;">
            <i class="bi bi-${icon} text-muted" style="font-size: 4rem;"></i>
            <h3 class="mt-3">${escapeHtml(title)}</h3>
            <p class="text-muted">${escapeHtml(description)}</p>
            ${buttonHtml}
        </div>
    `;
}

/**
 * Create an alert container
 * @param {string} id - Container ID (default: 'alertContainer')
 * @returns {string} HTML string
 */
export function createAlertContainer(id = 'alertContainer') {
    return `<div id="${id}" class="mt-3"></div>`;
}

// ============================================================================
// Filter Components
// ============================================================================

/**
 * Create a category filter dropdown
 * @param {Object} options - Configuration object
 * @param {string} options.id - Select element ID
 * @param {string} options.label - Label text
 * @param {string} options.helpText - Help text below select (optional)
 * @param {Array} options.categories - Array of {value, label} objects
 * @param {string} options.defaultValue - Default selected value (optional)
 * @returns {string} HTML string
 */
export function createCategoryFilter(options) {
    const {
        id,
        label,
        helpText = null,
        categories,
        defaultValue = 'ALL'
    } = options;

    const optionsHtml = categories.map(cat => {
        const selected = cat.value === defaultValue ? 'selected' : '';
        return `<option value="${escapeAttribute(cat.value)}" ${selected}>${escapeHtml(cat.label)}</option>`;
    }).join('\n');

    const helpHtml = helpText
        ? `<div class="form-text">${escapeHtml(helpText)}</div>`
        : '';

    return `
        <div class="col-md-4 mb-3">
            <label for="${id}" class="form-label">${escapeHtml(label)}</label>
            <select id="${id}" class="form-select">
                ${optionsHtml}
            </select>
            ${helpHtml}
        </div>
    `;
}

/**
 * Create a search input
 * @param {Object} options - Configuration object
 * @param {string} options.id - Input element ID
 * @param {string} options.label - Label text
 * @param {string} options.placeholder - Placeholder text
 * @param {string} options.helpText - Help text below input (optional)
 * @returns {string} HTML string
 */
export function createSearchInput(options) {
    const {
        id,
        label,
        placeholder,
        helpText = null
    } = options;

    const helpHtml = helpText
        ? `<div class="form-text">${escapeHtml(helpText)}</div>`
        : '';

    return `
        <div class="col-md-4 mb-3">
            <label for="${id}" class="form-label">${escapeHtml(label)}</label>
            <input type="search" id="${id}" class="form-control" placeholder="${escapeAttribute(placeholder)}">
            ${helpHtml}
        </div>
    `;
}

// ============================================================================
// Card Components
// ============================================================================

/**
 * Create a status badge
 * @param {boolean} isActive - Whether the item is active
 * @param {string} activeText - Text for active state (default: 'Active')
 * @param {string} inactiveText - Text for inactive state (default: 'Inactive')
 * @returns {string} HTML string
 */
export function createStatusBadge(isActive, activeText = 'Active', inactiveText = 'Inactive') {
    if (isActive) {
        return `<span class="badge bg-success">${escapeHtml(activeText)}</span>`;
    }
    return `<span class="badge bg-secondary-subtle text-secondary">${escapeHtml(inactiveText)}</span>`;
}

/**
 * Create a category badge
 * @param {string} category - Category value (e.g., 'SYSTEM', 'USER')
 * @param {Object} mapping - Mapping of category values to display config
 * @returns {string} HTML string
 */
export function createCategoryBadge(category, mapping = null) {
    const defaultMapping = {
        'SYSTEM': { label: 'System', class: 'bg-secondary' },
        'USER': { label: 'User', class: 'bg-primary' }
    };

    const config = (mapping || defaultMapping)[category] || { label: category, class: 'bg-info' };
    return `<span class="badge ${config.class}">${escapeHtml(config.label)}</span>`;
}

/**
 * Create a card header with title and badges
 * @param {Object} options - Configuration object
 * @param {string} options.title - Card title
 * @param {string} options.subtitle - Subtitle text (optional)
 * @param {Array<string>} options.badges - Array of badge HTML strings (optional)
 * @param {string} options.timestamp - Timestamp text (optional)
 * @returns {string} HTML string
 */
export function createCardHeader(options) {
    const {
        title,
        subtitle = null,
        badges = [],
        timestamp = null
    } = options;

    const badgesHtml = badges.length > 0
        ? `<div class="d-flex gap-2">${badges.join(' ')}</div>`
        : '';

    const subtitleHtml = subtitle
        ? `<p class="mb-0 small text-muted">${escapeHtml(subtitle)}</p>`
        : '';

    const timestampHtml = timestamp
        ? `<div class="text-end small text-muted">
               <div>${escapeHtml(timestamp)}</div>
           </div>`
        : '';

    return `
        <div class="card-header d-flex justify-content-between align-items-start gap-2">
            <div>
                <h5 class="mb-1">${escapeHtml(title)}</h5>
                ${badgesHtml}
                ${subtitleHtml}
            </div>
            ${timestampHtml}
        </div>
    `;
}

/**
 * Create card footer with action buttons
 * @param {Object} options - Configuration object
 * @param {boolean} options.isSystemResource - Whether this is a system resource (read-only)
 * @param {string} options.resourceId - Resource ID for edit/delete URLs
 * @param {string} options.editUrl - Edit page URL (optional)
 * @param {string} options.deleteFunction - JavaScript function name for delete (optional)
 * @param {Array} options.customButtons - Array of custom button HTML strings (optional)
 * @returns {string} HTML string
 */
export function createCardFooter(options) {
    const {
        isSystemResource = false,
        resourceId = null,
        editUrl = null,
        deleteFunction = null,
        customButtons = []
    } = options;

    if (isSystemResource) {
        return `
            <div class="card-footer bg-transparent">
                <div class="text-muted small text-center">System resources are read-only.</div>
            </div>
        `;
    }

    const editButton = editUrl
        ? `<a href="${escapeAttribute(editUrl)}" class="btn btn-outline-primary btn-sm flex-grow-1">
               <i class="bi bi-pencil"></i> Edit
           </a>`
        : '';

    const deleteButton = deleteFunction && resourceId
        ? `<button type="button" class="btn btn-outline-danger btn-sm" onclick="${deleteFunction}('${escapeAttribute(resourceId)}')">
               <i class="bi bi-trash"></i> Delete
           </button>`
        : '';

    const customHtml = customButtons.join('\n');

    return `
        <div class="card-footer bg-transparent">
            <div class="d-flex gap-2">
                ${editButton}
                ${customHtml}
                ${deleteButton}
            </div>
        </div>
    `;
}

// ============================================================================
// Form Components
// ============================================================================

/**
 * Create a password input with toggle visibility button
 * @param {Object} options - Configuration object
 * @param {string} options.id - Input ID
 * @param {string} options.name - Input name
 * @param {string} options.label - Label text
 * @param {string} options.placeholder - Placeholder text (optional)
 * @param {boolean} options.required - Whether field is required (default: true)
 * @param {string} options.helpText - Help text below input (optional)
 * @returns {string} HTML string
 */
export function createPasswordInput(options) {
    const {
        id,
        name,
        label,
        placeholder = '',
        required = true,
        helpText = null
    } = options;

    const requiredAttr = required ? 'required' : '';
    const requiredMark = required ? '<span class="text-danger">*</span>' : '';

    const helpHtml = helpText
        ? `<div class="form-text">${escapeHtml(helpText)}</div>`
        : '';

    return `
        <div class="mb-3">
            <label for="${id}" class="form-label">${escapeHtml(label)} ${requiredMark}</label>
            <div class="input-group">
                <input type="password" id="${id}" name="${name}" class="form-control"
                       placeholder="${escapeAttribute(placeholder)}" ${requiredAttr}>
                <button class="btn btn-outline-secondary" type="button" id="${id}Toggle">
                    <i class="bi bi-eye" id="${id}Icon"></i>
                </button>
            </div>
            ${helpHtml}
        </div>
    `;
}

/**
 * Initialize password toggle functionality
 * @param {string} inputId - Password input ID
 * @param {string} buttonId - Toggle button ID (default: inputId + 'Toggle')
 * @param {string} iconId - Icon element ID (default: inputId + 'Icon')
 */
export function initPasswordToggle(inputId, buttonId = null, iconId = null) {
    const input = document.getElementById(inputId);
    const button = document.getElementById(buttonId || `${inputId}Toggle`);
    const icon = document.getElementById(iconId || `${inputId}Icon`);

    if (!input || !button || !icon) {
        console.error('Password toggle elements not found:', { inputId, buttonId, iconId });
        return;
    }

    button.addEventListener('click', function() {
        const type = input.type === 'password' ? 'text' : 'password';
        input.type = type;
        icon.className = type === 'password' ? 'bi bi-eye' : 'bi bi-eye-slash';
    });
}

/**
 * Create a character counter display
 * @param {string} forId - Input/textarea ID this counter is for
 * @param {number} maxLength - Maximum character length
 * @returns {string} HTML string
 */
export function createCharCounter(forId, maxLength) {
    return `<div class="form-text"><span id="${forId}Count">0</span>/${maxLength} characters</div>`;
}

/**
 * Initialize character counter
 * @param {string} inputId - Input/textarea ID
 * @param {string} counterId - Counter span ID (default: inputId + 'Count')
 */
export function initCharCounter(inputId, counterId = null) {
    const input = document.getElementById(inputId);
    const counter = document.getElementById(counterId || `${inputId}Count`);

    if (!input || !counter) {
        console.error('Character counter elements not found:', { inputId, counterId });
        return;
    }

    const updateCount = () => {
        counter.textContent = input.value.length;
    };

    input.addEventListener('input', updateCount);
    updateCount(); // Initialize
}
