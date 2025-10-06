/**
 * Shared JavaScript utilities for yourMoment application
 *
 * This module provides common functionality used across multiple templates:
 * - XSS protection (escaping)
 * - Date/time formatting
 * - API error handling
 * - Alert management
 * - Form helpers
 */

// ============================================================================
// XSS Protection
// ============================================================================

/**
 * Escape HTML special characters to prevent XSS attacks
 * @param {string} text - Text to escape
 * @returns {string} Escaped text safe for HTML insertion
 */
export function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text ? text.replace(/[&<>"']/g, m => map[m]) : '';
}

/**
 * Escape text for use in HTML attributes
 * @param {string} text - Text to escape
 * @returns {string} Escaped text safe for attribute values
 */
export function escapeAttribute(text) {
    return (text || '').replace(/"/g, '&quot;');
}

// ============================================================================
// Formatting Utilities
// ============================================================================

/**
 * Format a date string to localized format
 * @param {string|Date} value - Date value to format
 * @param {string} fallback - Fallback text if date is invalid (default: 'Unknown')
 * @returns {string} Formatted date string or fallback
 */
export function formatDate(value, fallback = 'Unknown') {
    if (!value) {
        return fallback;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString();
}

/**
 * Format LLM provider names to display format
 * @param {string} providerName - Provider identifier (e.g., 'openai')
 * @returns {string} Display name (e.g., 'OpenAI')
 */
export function formatProviderLabel(providerName) {
    const mapping = {
        'openai': 'OpenAI',
        'mistral': 'Mistral',
        'huggingface': 'HuggingFace'
    };
    return mapping[providerName] || providerName;
}

/**
 * Format a duration in minutes to human-readable format
 * @param {number} minutes - Duration in minutes
 * @returns {string} Formatted duration (e.g., '2h 30m')
 */
export function formatDuration(minutes) {
    if (!minutes || minutes === 0) return '0m';
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours > 0 && mins > 0) return `${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h`;
    return `${mins}m`;
}

// ============================================================================
// API Helpers
// ============================================================================

/**
 * Safely parse JSON response, returning null if parsing fails
 * @param {Response} response - Fetch API response object
 * @returns {Promise<Object|null>} Parsed JSON or null
 */
export async function safeParseJson(response) {
    try {
        return await response.json();
    } catch (error) {
        return null;
    }
}

/**
 * Extract a human-readable error message from API error response
 * @param {Object} error - Error object from API
 * @returns {string|null} Error message or null
 */
export function extractErrorMessage(error) {
    if (!error) return null;

    // Direct string detail
    if (typeof error.detail === 'string') {
        return error.detail;
    }

    // Object with message property
    if (error.detail && error.detail.message) {
        return error.detail.message;
    }

    // Array of validation errors
    if (Array.isArray(error.detail)) {
        return error.detail
            .map(item => item.msg || item.message)
            .filter(Boolean)
            .join('\n');
    }

    // Fallback to error.message
    return error.message || null;
}

/**
 * Create standard fetch options for API calls
 * @param {string} method - HTTP method (GET, POST, PUT, PATCH, DELETE)
 * @param {Object} body - Request body (will be JSON stringified)
 * @returns {Object} Fetch options object
 */
export function fetchOptions(method = 'GET', body = null) {
    const options = {
        method,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if (body && method !== 'GET') {
        options.body = JSON.stringify(body);
    }

    return options;
}

// ============================================================================
// UI Helpers
// ============================================================================

/**
 * Display an alert message in a Bootstrap alert container
 * @param {HTMLElement|string} container - Alert container element or ID
 * @param {string} message - Message to display
 * @param {string} type - Bootstrap alert type (success, danger, warning, info)
 */
export function showAlert(container, message, type) {
    const element = typeof container === 'string'
        ? document.getElementById(container)
        : container;

    if (!element) {
        console.error('Alert container not found:', container);
        return;
    }

    // Clear alert if no message
    if (!message) {
        element.innerHTML = '';
        return;
    }

    element.innerHTML = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
}

/**
 * Toggle password input visibility
 * @param {HTMLInputElement} input - Password input element
 * @param {HTMLElement} icon - Icon element to toggle
 */
export function togglePasswordVisibility(input, icon) {
    const type = input.type === 'password' ? 'text' : 'password';
    input.type = type;
    icon.className = type === 'password' ? 'bi bi-eye' : 'bi bi-eye-slash';
}

/**
 * Set button to loading state
 * @param {HTMLButtonElement} button - Button element
 * @param {string} loadingText - Text to display during loading
 * @returns {string} Original button HTML for restoration
 */
export function setButtonLoading(button, loadingText = 'Saving...') {
    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `
        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        ${loadingText}
    `;
    return originalHtml;
}

/**
 * Reset button from loading state
 * @param {HTMLButtonElement} button - Button element
 * @param {string} originalHtml - Original button HTML
 */
export function resetButton(button, originalHtml) {
    button.disabled = false;
    button.innerHTML = originalHtml;
}

/**
 * Update character counter display
 * @param {HTMLInputElement|HTMLTextAreaElement} input - Input element
 * @param {HTMLElement} counter - Counter display element
 */
export function updateCharCounter(input, counter) {
    const length = input.value.length;
    const maxLength = input.maxLength;
    counter.textContent = maxLength > 0 ? `${length}/${maxLength}` : length;
}

// ============================================================================
// CRUD Operation Helpers
// ============================================================================

/**
 * Generic delete resource handler with confirmation
 * @param {string} url - API endpoint URL
 * @param {string} resourceName - Human-readable resource name
 * @param {Function} onSuccess - Callback on successful deletion
 * @param {string} confirmMessage - Custom confirmation message (optional)
 */
export async function deleteResource(url, resourceName, onSuccess, confirmMessage = null) {
    const message = confirmMessage || `Delete this ${resourceName}? This action cannot be undone.`;

    if (!confirm(message)) {
        return;
    }

    try {
        const response = await fetch(url, fetchOptions('DELETE'));

        if (!response.ok) {
            let errorMessage = `Failed to delete ${resourceName}.`;
            const error = await safeParseJson(response);
            if (error) {
                const extracted = extractErrorMessage(error);
                if (extracted) {
                    errorMessage = extracted;
                }
            }
            throw new Error(errorMessage);
        }

        if (onSuccess) {
            onSuccess();
        }
    } catch (error) {
        console.error(`Error deleting ${resourceName}:`, error);
        throw error;
    }
}

/**
 * Generic form submission handler
 * @param {string} url - API endpoint URL
 * @param {string} method - HTTP method (POST, PUT, PATCH)
 * @param {Object} payload - Request payload
 * @param {Function} onSuccess - Callback on success
 * @param {Function} onError - Callback on error
 */
export async function submitForm(url, method, payload, onSuccess, onError) {
    try {
        const response = await fetch(url, fetchOptions(method, payload));

        if (!response.ok) {
            const error = await safeParseJson(response);
            const message = extractErrorMessage(error) || 'Request failed';
            if (onError) {
                onError(message, response.status, error);
            }
            return false;
        }

        const data = await response.json();
        if (onSuccess) {
            onSuccess(data);
        }
        return true;
    } catch (error) {
        console.error('Form submission error:', error);
        if (onError) {
            onError(error.message || 'Unexpected error occurred', 0, error);
        }
        return false;
    }
}

// ============================================================================
// Loading States
// ============================================================================

/**
 * Show loading state, hide other states
 * @param {HTMLElement} loadingElement - Loading state element
 * @param {HTMLElement[]} otherElements - Array of other state elements to hide
 */
export function showLoadingState(loadingElement, otherElements = []) {
    if (loadingElement) {
        loadingElement.style.display = 'block';
    }
    otherElements.forEach(el => {
        if (el) el.style.display = 'none';
    });
}

/**
 * Show content state, hide loading and empty states
 * @param {HTMLElement} contentElement - Content element
 * @param {HTMLElement[]} otherElements - Array of other state elements to hide
 */
export function showContentState(contentElement, otherElements = []) {
    if (contentElement) {
        contentElement.style.display = 'block';
    }
    otherElements.forEach(el => {
        if (el) el.style.display = 'none';
    });
}

/**
 * Show empty state, hide other states
 * @param {HTMLElement} emptyElement - Empty state element
 * @param {HTMLElement[]} otherElements - Array of other state elements to hide
 */
export function showEmptyState(emptyElement, otherElements = []) {
    if (emptyElement) {
        emptyElement.style.display = 'block';
    }
    otherElements.forEach(el => {
        if (el) el.style.display = 'none';
    });
}

// ============================================================================
// Debug Helpers
// ============================================================================

/**
 * Conditional console logging based on debug flag
 * @param {...any} args - Arguments to log
 */
export function debugLog(...args) {
    if (window.DEBUG_MODE) {
        console.log('[DEBUG]', ...args);
    }
}
