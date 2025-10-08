import { fetchOptions, deleteResource } from './utils.js';

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
    // Find the button that triggered this test
    const button = document.querySelector(`button[data-credential-id="${credentialId}"][data-action="test-credential"]`);
    const originalContent = button ? button.innerHTML : null;

    try {
        // Show loading state on button
        if (button) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Wird getestet …';
        }

        window.showAlert('🔄 Zugang wird gegen die myMoment-Plattform getestet …', 'info', false);
        window.scrollTo({ top: 0, behavior: 'smooth' });

        const response = await fetch(`/api/v1/mymoment-credentials/${credentialId}/test`, fetchOptions('POST'));

        if (response.ok) {
            const result = await response.json();
            window.showAlert(`✅ Zugangstest erfolgreich! Angemeldet als ${result.username} auf ${result.platform}.`, 'success');

            // Temporarily show success state on button
            if (button) {
                button.innerHTML = '<i class="bi bi-check-circle-fill"></i> Erfolgreich';
                button.classList.remove('btn-outline-info');
                button.classList.add('btn-success');

                // Reset button after 2 seconds
                setTimeout(() => {
                    button.innerHTML = originalContent;
                    button.classList.remove('btn-success');
                    button.classList.add('btn-outline-info');
                    button.disabled = false;
                }, 2000);
            }
        } else {
            const error = await response.json();
            const message = error?.detail || 'Authentifizierung fehlgeschlagen';
            window.showAlert(`❌ Zugangstest fehlgeschlagen: ${message}`, 'danger');

            // Reset button on error
            if (button) {
                button.innerHTML = originalContent;
                button.disabled = false;
            }
        }
    } catch (error) {
        console.error('Error testing credential:', error);
        window.showAlert('❌ Fehler beim Testen des Zugangs. Bitte Netzwerk prüfen und erneut versuchen.', 'danger');

        // Reset button on error
        if (button) {
            button.innerHTML = originalContent;
            button.disabled = false;
        }
    }
}

async function handleCredentialDelete(credentialId) {
    await deleteResource(
        `/api/v1/mymoment-credentials/${credentialId}`,
        'myMoment-Zugang',
        () => {
            window.showAlert('Zugang erfolgreich gelöscht!', 'success');
            setTimeout(() => window.location.reload(), 1200);
        },
        'Diesen myMoment-Zugang löschen? Dies kann nicht rückgängig gemacht werden.'
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
                'Prompt-Vorlage',
                () => {
                    window.showAlert('Prompt-Vorlage erfolgreich gelöscht.', 'success');
                    setTimeout(() => window.location.reload(), 1200);
                },
                'Diese Prompt-Vorlage löschen? Diese Aktion kann nicht rückgängig gemacht werden.'
            );
        } catch (error) {
            window.showAlert(`Fehler beim Löschen der Vorlage: ${error.message}`, 'danger');
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
