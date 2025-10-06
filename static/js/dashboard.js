/**
 * yourMoment Dashboard JavaScript Utilities
 *
 * Provides essential client-side functionality for the yourMoment monitoring dashboard.
 * Focused on loading additional data and basic interactivity for server-side rendered pages.
 */

class YourMomentDashboard {
    constructor() {
        this.apiBaseUrl = '/';
        this.updateInterval = 30000; // 30 seconds
        this.updateTimer = null;
        this.isUpdating = false;

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.startAutoUpdates();
        this.setupToastContainer();
    }

    setupEventListeners() {
        // Process control buttons
        document.addEventListener('click', (e) => {
            if (e.target.matches('[data-action="start-process"]')) {
                this.handleProcessAction(e.target, 'start');
            } else if (e.target.matches('[data-action="stop-process"]')) {
                this.handleProcessAction(e.target, 'stop');
            } else if (e.target.matches('[data-action="delete-process"]')) {
                this.handleProcessAction(e.target, 'delete');
            }
        });

        // Load more content buttons
        document.addEventListener('click', (e) => {
            if (e.target.matches('[data-action="load-processes"]')) {
                this.loadProcesses(e.target);
            } else if (e.target.matches('[data-action="refresh"]')) {
                e.preventDefault();
                this.refreshData();
            }
        });

        // Auto-update toggle
        const autoUpdateToggle = document.getElementById('autoUpdateToggle');
        if (autoUpdateToggle) {
            autoUpdateToggle.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.startAutoUpdates();
                } else {
                    this.stopAutoUpdates();
                }
            });
        }
    }

    async handleProcessAction(button, action) {
        const processId = button.dataset.processId;
        if (!processId) return;

        const originalText = button.textContent;
        const loadingText = button.dataset.loadingText || 'Processing...';

        try {
            this.setButtonLoading(button, loadingText);

            let endpoint;
            let method = 'POST';

            switch (action) {
                case 'start':
                    endpoint = `/monitoring-processes/${processId}/start`;
                    break;
                case 'stop':
                    endpoint = `/monitoring-processes/${processId}/stop`;
                    break;
                case 'delete':
                    endpoint = `/monitoring-processes/${processId}`;
                    method = 'DELETE';
                    break;
                default:
                    throw new Error(`Unknown action: ${action}`);
            }

            const response = await this.apiCall(endpoint, { method });

            if (response.ok) {
                this.showToast(`Process ${action} successful`, 'success');
                await this.refreshData();
            } else {
                const errorData = await response.json();
                throw new Error(errorData.message || `Failed to ${action} process`);
            }

        } catch (error) {
            console.error(`Process ${action} error:`, error);
            this.showToast(`Error: ${error.message}`, 'danger');
        } finally {
            this.setButtonLoading(button, originalText, false);
        }
    }

    async loadProcesses(button) {
        const status = button.dataset.status || 'all';
        const page = button.dataset.page || 1;
        const containerId = button.dataset.target || 'processes-container';

        try {
            this.setButtonLoading(button, 'Loading...');

            const response = await this.apiCall(`/monitoring-processes?status=${status}&page=${page}`);

            if (response.ok) {
                const html = await response.text();
                const container = document.getElementById(containerId);
                if (container) {
                    container.innerHTML = html;
                }
            } else {
                throw new Error('Failed to load processes');
            }

        } catch (error) {
            console.error('Load processes error:', error);
            this.showToast('Failed to load processes', 'danger');
        } finally {
            this.setButtonLoading(button, 'Load Processes', false);
        }
    }

    async apiCall(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : this.apiBaseUrl + endpoint.replace(/^\//, '');

        const defaultOptions = {
            headers: {
                'Accept': 'application/json',
            }
        };

        // Add auth token if available
        const token = this.getAuthToken();
        if (token) {
            defaultOptions.headers['Authorization'] = `Bearer ${token}`;
        }

        // Handle JSON content type
        if (options.body && !(options.body instanceof FormData)) {
            defaultOptions.headers['Content-Type'] = 'application/json';
            if (typeof options.body === 'object') {
                options.body = JSON.stringify(options.body);
            }
        }

        return fetch(url, { ...defaultOptions, ...options });
    }

    getAuthToken() {
        // Try to get token from localStorage or cookie
        return localStorage.getItem('auth_token') || this.getCookie('auth_token');
    }

    getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    setButtonLoading(button, text, loading = true) {
        if (loading) {
            button.disabled = true;
            button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${text}`;
        } else {
            button.disabled = false;
            button.textContent = text;
        }
    }

    startAutoUpdates() {
        if (this.updateTimer) return;

        this.updateTimer = setInterval(() => {
            if (!this.isUpdating) {
                this.refreshData();
            }
        }, this.updateInterval);

        // Update toggle state
        const toggle = document.getElementById('autoUpdateToggle');
        if (toggle) toggle.checked = true;
    }

    stopAutoUpdates() {
        if (this.updateTimer) {
            clearInterval(this.updateTimer);
            this.updateTimer = null;
        }

        // Update toggle state
        const toggle = document.getElementById('autoUpdateToggle');
        if (toggle) toggle.checked = false;
    }

    async refreshData() {
        if (this.isUpdating) return;

        this.isUpdating = true;

        try {
            // Update process statuses
            await this.updateProcessStatuses();

            // Update last refresh time
            this.updateLastRefreshTime();

        } catch (error) {
            console.error('Data refresh error:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    async updateProcessStatuses() {
        const statusElements = document.querySelectorAll('[data-process-status]');

        for (const element of statusElements) {
            const processId = element.dataset.processId;
            if (!processId) continue;

            try {
                const response = await this.apiCall(`/monitoring-processes/${processId}`);
                if (response.ok) {
                    const data = await response.json();
                    this.updateProcessStatusElement(element, data);
                }
            } catch (error) {
                console.error(`Failed to update status for process ${processId}:`, error);
            }
        }
    }

    updateProcessStatusElement(element, processData) {
        const statusBadge = element.querySelector('.status-badge');
        const actionButtons = element.querySelectorAll('[data-action]');

        if (statusBadge) {
            // Remove existing status classes
            statusBadge.className = statusBadge.className.replace(/status-\w+/g, '');

            // Add new status class
            statusBadge.classList.add(`status-${processData.status}`);
            statusBadge.textContent = processData.status.toUpperCase();
        }

        // Update action buttons based on status
        actionButtons.forEach(button => {
            const action = button.dataset.action;

            if (action === 'start') {
                button.disabled = processData.status === 'running';
            } else if (action === 'stop') {
                button.disabled = processData.status !== 'running';
            }
        });

        // Update other process details
        const detailElements = element.querySelectorAll('[data-field]');
        detailElements.forEach(detail => {
            const field = detail.dataset.field;
            if (processData[field] !== undefined) {
                detail.textContent = processData[field];
            }
        });
    }

    updateLastRefreshTime() {
        const refreshElements = document.querySelectorAll('[data-last-refresh]');
        const now = new Date().toLocaleTimeString();

        refreshElements.forEach(element => {
            element.textContent = now;
        });
    }

    setupToastContainer() {
        // Create toast container if it doesn't exist
        if (!document.getElementById('toast-container')) {
            const container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '1100';
            document.body.appendChild(container);
        }
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toastId = `toast-${Date.now()}`;
        const toast = document.createElement('div');

        const typeClasses = {
            success: 'text-bg-success',
            danger: 'text-bg-danger',
            warning: 'text-bg-warning',
            info: 'text-bg-info'
        };

        toast.innerHTML = `
            <div class="toast ${typeClasses[type] || typeClasses.info}" id="${toastId}" role="alert">
                <div class="toast-header">
                    <strong class="me-auto">yourMoment</strong>
                    <small class="text-muted">now</small>
                    <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;

        container.appendChild(toast);

        const bsToast = new bootstrap.Toast(toast.firstElementChild, {
            autohide: true,
            delay: 5000
        });

        bsToast.show();

        // Clean up after toast is hidden
        toast.firstElementChild.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }

    // Utility functions for common operations
    static formatDateTime(dateString) {
        if (!dateString) return 'N/A';
        return new Date(dateString).toLocaleString();
    }

    static formatDuration(minutes) {
        if (!minutes) return 'N/A';

        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;

        if (hours > 0) {
            return `${hours}h ${mins}m`;
        }
        return `${mins}m`;
    }

    static getStatusIcon(status) {
        const icons = {
            running: 'bi-play-circle-fill text-success',
            stopped: 'bi-stop-circle text-secondary',
            failed: 'bi-exclamation-circle-fill text-danger',
            completed: 'bi-check-circle-fill text-info'
        };

        return icons[status] || 'bi-question-circle text-muted';
    }

    static truncateText(text, maxLength = 50) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.ymDashboard = new YourMomentDashboard();
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = YourMomentDashboard;
}
