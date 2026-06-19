/**
 * Models Module
 * Handles model selection and management
 */

// Initialize namespace
window.NotionAI = window.NotionAI || {};
window.NotionAI.API = window.NotionAI.API || {};

window.NotionAI.API.Models = {
    // Current selected model
    _currentModel: window.NotionAI.Core.Constants.DEFAULT_MODEL,
    _currentModelLabel: null,

    /**
     * Gets the current selected model ID
     * @returns {string} Model ID
     */
    getCurrentModel() {
        return this._currentModel;
    },

    /**
     * Gets the current selected model label
     * @returns {string} Model display label
     */
    getCurrentModelLabel() {
        if (!this._currentModelLabel) {
            this._currentModelLabel = this.getModelDisplayName(this._currentModel);
        }
        return this._currentModelLabel;
    },

    /**
     * Sets the current selected model
     * @param {string} modelId - Model ID
     * @param {string} label - Model display label
     */
    setCurrentModel(modelId, label) {
        this._currentModel = modelId;
        this._currentModelLabel = label;
    },

    /**
     * Gets display name for a model ID, including Notion/internal model codes.
     * @param {string} modelId - Model ID
     * @returns {string} Display name
     */
    getModelDisplayName(modelId) {
        const id = String(modelId || '').trim();
        const names = window.NotionAI.Core.State.get('modelDisplayNames') || {};
        const aliases = {
            'almond-croissant-low': 'Sonnet 4.6',
            'avocado-froyo-medium': 'Opus 4.6',
            'apricot-sorbet-high': 'Opus 4.7',
            'ambrosia-tart-high': 'Opus 4.8',
            'anthropic-haiku-4.5': 'Haiku 4.5',
            'acai-budino': 'Fable 5',
            'openai-turbo': 'OpenAI Turbo',
            'oatmeal-cookie': 'GPT 5.2',
            'oval-kumquat-medium': 'GPT 5.4',
            'oregon-grape-medium': 'GPT 5.4 Mini',
            'otaheite-apple-medium': 'GPT 5.4 Nano',
            'opal-quince-medium': 'GPT 5.5',
            'gingerbread': 'Gemini 3 Flash',
            'galette-medium-thinking': 'Gemini 3.1 Pro',
            'vertex-gemini-3.5-flash': 'Gemini 3.5 Flash',
            'vertex-gemini-2.5-flash': 'Gemini 2.5 Flash',
            'xigua-mochi-medium': 'Grok 4.3',
            'xinomavro-cake': 'Grok Build 0.1',
            'fireworks-minimax-m2.5': 'MiniMax M2.5',
            'fireworks-kimi-k2.6': 'Kimi 2.6',
            'baseten-deepseek-v4-pro': 'DeepSeek V4 Pro'
        };
        return names[id] || aliases[id] || id || 'Unknown model';
    },

    /**
     * Gets the display label for the model that actually produced a response.
     * Falls back to an explicit unverified requested label when actual metadata is unavailable.
     */
    getResponseModelDisplayName(metadata, fallbackModelId = '') {
        const meta = metadata && typeof metadata === 'object' ? metadata : {};
        const actual = String(meta.actual_model || meta.notion_model_name || meta.notion_step_model || '').trim();
        const requested = String(meta.requested_model || fallbackModelId || '').trim();
        const verified = meta.actual_model_verified;

        if (actual) {
            const actualName = this.getModelDisplayName(actual);
            const requestedName = requested ? this.getModelDisplayName(requested) : '';
            // When the backend explicitly flags as unverified (echo detection),
            // show "Requested X · unverified" instead of a confident label.
            if (verified === false) {
                const label = requestedName || actualName;
                return `Requested ${label} · unverified`;
            }
            if (requestedName && requested !== actual && requestedName !== actualName) {
                return `${actualName} ← requested ${requestedName}`;
            }
            return actualName;
        }

        return requested ? `Requested ${this.getModelDisplayName(requested)} · unverified` : 'Model unverified';
    },

    /**
     * Loads model display names from constants
     */
    loadModels() {
        const modelDisplayNames = {
            ...window.NotionAI.Core.Constants.MODEL_DISPLAY_NAMES
        };
        window.NotionAI.Core.State.set('modelDisplayNames', modelDisplayNames);
    },

    /**
     * Gets all available models
     * @returns {Array} Array of model objects
     */
    getAvailableModels() {
        return window.NotionAI.Core.Constants.MODELS;
    }
};
