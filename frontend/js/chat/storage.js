/**
 * Storage Module
 * Handles LocalStorage operations for chat data
 */

// Initialize namespace
window.NotionAI = window.NotionAI || {};
window.NotionAI.Chat = window.NotionAI.Chat || {};

window.NotionAI.Chat.Storage = {
    /**
     * Saves chats array to localStorage
     */
    saveChats() {
        const chats = window.NotionAI.Core.State.get('chats');
        localStorage.setItem('claude_chats', JSON.stringify(chats));
    },

    /**
     * Loads and sanitizes chats from localStorage
     * @returns {Array} Sanitized chats array
     */
    loadChats() {
        const chats = JSON.parse(localStorage.getItem('claude_chats')) || [];
        const sanitized = window.NotionAI.Utils.Validation.sanitizeChats(chats);
        window.NotionAI.Core.State.set('chats', sanitized);
        return sanitized;
    },

    /**
     * Adds a new message to current chat
     * @param {Object} message - Message object with role and content
     */
    addMessage(message) {
        const chats = window.NotionAI.Core.State.get('chats');
        const currentChatId = window.NotionAI.Core.State.get('currentChatId');
        const chat = chats.find(c => c.id === currentChatId);
        if (chat) {
            const stamped = { ...message };
            if (!stamped.createdAt && !stamped.timestamp) stamped.createdAt = Date.now();
            chat.messages.push(stamped);
            chat.updatedAt = stamped.createdAt || stamped.timestamp || Date.now();
            window.NotionAI.Core.State.set('chats', chats);
            this.saveChats();
        }
    },

    /**
     * Updates chat conversation ID
     * @param {string} chatId - Chat ID
     * @param {string} conversationId - Backend conversation ID
     */
    updateConversationId(chatId, conversationId) {
        const chats = window.NotionAI.Core.State.get('chats');
        const chat = chats.find(c => c.id === chatId);
        if (chat) {
            chat.conversationId = conversationId;
            window.NotionAI.Core.State.set('chats', chats);
            this.saveChats();
        }
    },

    /**
     * Deletes a chat by ID
     * @param {string} chatId - Chat ID to delete
     */
    deleteChat(chatId) {
        let chats = window.NotionAI.Core.State.get('chats');
        chats = chats.filter(c => c.id !== chatId);
        window.NotionAI.Core.State.set('chats', chats);
        this.saveChats();
    },

    /**
     * Updates chat title
     * @param {string} chatId - Chat ID
     * @param {string} title - New title
     */
    updateChatTitle(chatId, title) {
        const chats = window.NotionAI.Core.State.get('chats');
        const chat = chats.find(c => c.id === chatId);
        if (chat) {
            chat.title = title;
            window.NotionAI.Core.State.set('chats', chats);
            this.saveChats();
        }
    },

    /**
     * Toggles chat star status
     * @param {string} chatId - Chat ID
     */
    toggleStar(chatId) {
        const chats = window.NotionAI.Core.State.get('chats');
        const chat = chats.find(c => c.id === chatId);
        if (chat) {
            chat.starred = !chat.starred;
            window.NotionAI.Core.State.set('chats', chats);
            this.saveChats();
        }
    },

    /**
     * Downloads a complete browser-local chat backup as JSON.
     * @returns {Object} Backup summary
     */
    backupChats() {
        const chats = window.NotionAI.Core.State.get('chats') || [];
        const messageCount = chats.reduce((total, chat) => total + (Array.isArray(chat?.messages) ? chat.messages.length : 0), 0);
        const exportedAt = new Date().toISOString();
        const backup = {
            version: 1,
            app: 'Notion AI Studio',
            source: 'browser-localStorage:claude_chats',
            exportedAt,
            chatCount: chats.length,
            messageCount,
            chats
        };
        const safeStamp = exportedAt.replace(/[:.]/g, '-');
        const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `notion-ai-local-chat-backup-${safeStamp}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return { chatCount: chats.length, messageCount, exportedAt };
    },

    _normalizePingPongText(value) {
        return String(value || '')
            .trim()
            .toLowerCase()
            .replace(/^assistant\s*:\s*/, '')
            .replace(/^response\s*:\s*/, '')
            .replace(/[.!?。]+$/g, '')
            .trim();
    },

    isPingPongTestChat(chat) {
        const messages = Array.isArray(chat?.messages) ? chat.messages : [];
        if (messages.length !== 2) return false;
        const second = messages[1];
        if (!second || second.role !== 'assistant') return false;
        const content = this._normalizePingPongText(second.content);
        return content === 'ping' || content === 'pong';
    },

    /**
     * Deletes local two-message ping/pong test conversations.
     * @returns {Object} Cleanup summary
     */
    deletePingPongTestChats() {
        const chats = window.NotionAI.Core.State.get('chats') || [];
        const deleted = chats.filter(chat => this.isPingPongTestChat(chat));
        if (!deleted.length) {
            return { deletedCount: 0, deletedIds: [] };
        }
        const deletedIds = new Set(deleted.map(chat => chat.id));
        const remaining = chats.filter(chat => !deletedIds.has(chat.id));
        window.NotionAI.Core.State.set('chats', remaining);
        this.saveChats();

        const currentChatId = window.NotionAI.Core.State.get('currentChatId');
        if (deletedIds.has(currentChatId)) {
            window.NotionAI.Core.State.set('currentChatId', remaining[0]?.id || Date.now().toString());
            window.NotionAI.Core.State.set('selectedChatIds', remaining[0]?.id ? [remaining[0].id] : []);
        } else {
            const selected = window.NotionAI.Core.State.get('selectedChatIds') || [];
            window.NotionAI.Core.State.set('selectedChatIds', selected.filter(id => !deletedIds.has(id)));
        }
        return { deletedCount: deleted.length, deletedIds: Array.from(deletedIds) };
    }
};
