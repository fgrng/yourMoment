import { showAlert, fetchOptions, deleteResource } from './utils.js';

export function initCredentialsPage() {
    const credentialButtons = document.querySelectorAll('[data-credential-id]');
    if (!credentialButtons.length) {
        return;
    }

    document.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-credential-id]');
        if (!button) {
            return;
        }

        const action = button.getAttribute('data-action');
        const credentialId = button.getAttribute('data-credential-id');
        if (!action || !credentialId) {
            return;
        }

        if (action === 'test-credential') {
            await handleCredentialTest(credentialId);
        } else if (action === 'delete-credential') {
            await handleCredentialDelete(credentialId);
        }
    });
}

async function handleCredentialTest(credentialId) {
    try {
        showAlert('alertContainer', '🔄 Testing credential against myMoment platform...', 'info');
        const response = await fetch(`/api/v1/mymoment-credentials/${credentialId}/test`, fetchOptions('POST'));

        if (response.ok) {
            const result = await response.json();
            showAlert('alertContainer', `✅ Credential test successful! Authenticated as ${result.username} on ${result.platform}.`, 'success');
        } else {
            const error = await response.json();
            const message = error?.detail || 'Authentication failed';
            showAlert('alertContainer', `❌ Credential test failed: ${message}`, 'danger');
        }
    } catch (error) {
        showAlert('alertContainer', '❌ Error testing credential. Please try again.', 'danger');
    }
}

async function handleCredentialDelete(credentialId) {
    await deleteResource(
        `/api/v1/mymoment-credentials/${credentialId}`,
        'myMoment credential',
        () => {
            showAlert('alertContainer', 'Credential deleted successfully!', 'success');
            setTimeout(() => window.location.reload(), 1200);
        },
        'Delete this myMoment credential? This action cannot be undone.'
    );
}

export function initPromptTemplatesPage() {
    const templateButtons = document.querySelectorAll('[data-template-id]');
    if (!templateButtons.length) {
        return;
    }

    document.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-template-id]');
        if (!button) {
            return;
        }

        const action = button.getAttribute('data-action');
        const templateId = button.getAttribute('data-template-id');
        if (action !== 'delete-template' || !templateId) {
            return;
        }

        try {
            await deleteResource(
                `/api/v1/prompt-templates/${templateId}`,
                'prompt template',
                () => {
                    showAlert('alertContainer', 'Prompt template deleted successfully.', 'success');
                    setTimeout(() => window.location.reload(), 1200);
                },
                'Delete this prompt template? This action cannot be undone.'
            );
        } catch (error) {
            showAlert('alertContainer', `Error deleting template: ${error.message}`, 'danger');
        }
    });
}

export function initLogoutHandler() {
    const logoutBtn = document.getElementById('logoutBtn');
    if (!logoutBtn) {
        return;
    }

    logoutBtn.addEventListener('click', async (event) => {
        event.preventDefault();
        try {
            await fetch('/api/v1/auth/logout', fetchOptions('POST'));
        } catch (error) {
            console.error('Logout error:', error);
        } finally {
            window.location.href = '/login';
        }
    });
}
