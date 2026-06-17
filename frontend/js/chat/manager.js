/**
 * Chat Manager Module — Notion AI Studio
 */

window.NotionAI = window.NotionAI || {};
window.NotionAI.Chat = window.NotionAI.Chat || {};

window.NotionAI.Chat.Manager = {
    startNewChat() {
        if (window.NotionAI.Core.State.get('isGenerating')) return;

        const currentChatId = Date.now().toString();
        window.NotionAI.Core.State.set('currentChatId', currentChatId);
        window.NotionAI.Core.State.set('selectedChatIds', [currentChatId]);

        document.getElementById('headerTitle').classList.add('hidden');
        document.getElementById('chatContainer').innerHTML = '';
        window.NotionAI.UI.Input.clear();

        const welcomeScreen = document.getElementById('welcomeScreen');
        welcomeScreen.classList.remove('hidden');

        if (window.innerWidth < 768) {
            window.NotionAI.UI.Sidebar.close();
        }

        window.NotionAI.UI.Input.focus();
        this.renderChatList();
    },

    selectChat(chatId) {
        if (window.NotionAI.Core.State.get('isGenerating')) return;

        const chats = window.NotionAI.Core.State.get('chats');
        const chat = chats.find(c => c.id === chatId);
        if (!chat) return;

        window.NotionAI.Core.State.set('currentChatId', chatId);
        const selected = window.NotionAI.Core.State.get('selectedChatIds') || [];
        if (!selected.includes(chatId)) {
            window.NotionAI.Core.State.set('selectedChatIds', [chatId]);
        }

        document.getElementById('welcomeScreen').classList.add('hidden');
        document.getElementById('chatContainer').innerHTML = '';

        document.getElementById('headerTitle').textContent = chat.title;
        document.getElementById('headerTitle').classList.remove('hidden');

        chat.messages.forEach(msg => {
            const restoredModelName = msg.role === 'assistant'
                ? (msg.modelMetadata
                    ? window.NotionAI.API.Models.getResponseModelDisplayName(msg.modelMetadata, msg.requestedModel || '')
                    : (msg.requestedModelDisplayName
                        ? `Requested ${msg.requestedModelDisplayName} · unverified`
                        : (msg.modelDisplayName && /^requested/i.test(String(msg.modelDisplayName))
                            ? msg.modelDisplayName
                            : 'Model unverified')))
                : null;
            const wrapper = window.NotionAI.Chat.Renderer.appendMessage(
                msg.role,
                msg.content,
                true,
                restoredModelName,
                msg.createdAt || msg.created_at || msg.timestamp || null
            );

            if (msg.role === 'assistant') {
                const restoredThinking = typeof msg.thinking === 'string' ? msg.thinking : '';
                const restoredSearch = window.NotionAI.Utils.Validation.normalizeSearchPayload(msg.search);

                if (restoredThinking.trim()) {
                    wrapper.thinkingText = restoredThinking;
                    window.NotionAI.Chat.Renderer.updateThinkingPanel(wrapper);
                }

                if ((restoredSearch.queries.length + restoredSearch.sources.length) > 0) {
                    wrapper.searchData = restoredSearch;
                    window.NotionAI.Chat.Renderer.updateSearchPanel(wrapper);
                }
            }
        });

        if (window.innerWidth < 768) {
            window.NotionAI.UI.Sidebar.close();
        }

        window.NotionAI.Utils.DOM.scrollToBottom();
        this.renderChatList();
    },

    _visibleLocalChats() {
        const chats = window.NotionAI.Core.State.get('chats') || [];
        const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
        if (!query) return chats.slice();
        return chats.filter(chat => {
            const text = [
                chat?.title,
                chat?.id,
                ...(Array.isArray(chat?.messages) ? chat.messages.map(msg => msg?.content || '') : [])
            ].map(value => String(value || '').toLowerCase()).join('\n');
            return text.includes(query);
        });
    },

    _sortedLocalChats(chats) {
        const sort = localStorage.getItem('notion_local_chat_sort') || 'date_desc';
        const copy = chats.slice();
        copy.sort((a, b) => {
            if (sort === 'messages_desc') {
                return this._chatMessageCount(b) - this._chatMessageCount(a) || this._chatLastTimestamp(b) - this._chatLastTimestamp(a);
            }
            if (sort === 'messages_asc') {
                return this._chatMessageCount(a) - this._chatMessageCount(b) || this._chatLastTimestamp(b) - this._chatLastTimestamp(a);
            }
            if (sort === 'date_asc') {
                return this._chatLastTimestamp(a) - this._chatLastTimestamp(b);
            }
            return this._chatLastTimestamp(b) - this._chatLastTimestamp(a);
        });
        return copy;
    },

    _groupByDay(chats) {
        const groups = [];
        const byLabel = new Map();
        for (const chat of chats) {
            const label = this._chatDayLabel(chat);
            if (!byLabel.has(label)) {
                const group = { label, items: [] };
                byLabel.set(label, group);
                groups.push(group);
            }
            byLabel.get(label).items.push(chat);
        }
        return groups;
    },

    handleChatClick(e, chatId) {
        if (window.NotionAI.Core.State.get('isGenerating')) return;
        const allRendered = this._sortedLocalChats(this._visibleLocalChats());
        let selected = [...(window.NotionAI.Core.State.get('selectedChatIds') || [])];

        if (e.ctrlKey || e.metaKey) {
            if (selected.includes(chatId)) {
                selected = selected.filter(id => id !== chatId);
                window.NotionAI.Core.State.set('selectedChatIds', selected);
                if (window.NotionAI.Core.State.get('currentChatId') === chatId) {
                    const nextActive = selected[selected.length - 1] || null;
                    if (nextActive) this.selectChat(nextActive);
                    else this.startNewChat();
                } else {
                    this.renderChatList();
                }
            } else {
                selected.push(chatId);
                window.NotionAI.Core.State.set('selectedChatIds', selected);
                this.selectChat(chatId);
            }
        } else if (e.shiftKey) {
            const endIdx = allRendered.findIndex(c => c.id === chatId);
            let startIdx = allRendered.findIndex(c => c.id === window.NotionAI.Core.State.get('currentChatId'));
            if (startIdx === -1) startIdx = 0;
            const minIdx = Math.min(startIdx, endIdx);
            const maxIdx = Math.max(startIdx, endIdx);
            const newSelected = [];
            for (let i = minIdx; i <= maxIdx; i++) {
                if (allRendered[i]?.id) newSelected.push(allRendered[i].id);
            }
            window.NotionAI.Core.State.set('selectedChatIds', newSelected);
            this.selectChat(chatId);
        } else {
            window.NotionAI.Core.State.set('selectedChatIds', [chatId]);
            this.selectChat(chatId);
        }
    },

    async deleteChat(chatId) {
        if (window.NotionAI.Core.State.get('isGenerating')) return;

        const selected = window.NotionAI.Core.State.get('selectedChatIds') || [];
        const targets = selected.includes(chatId) ? selected : [chatId];
        if (targets.length > 1) {
            if (!confirm(`Delete ${targets.length} selected chats?`)) return;
        } else {
            const chats = window.NotionAI.Core.State.get('chats');
            const chat = chats.find(c => c.id === chatId);
            if (!chat) return;
            if (!confirm(`Delete chat "${chat.title}"?`)) return;
        }

        for (const id of targets) {
            const chats = window.NotionAI.Core.State.get('chats');
            const chat = chats.find(c => c.id === id);
            if (chat) {
                if (chat.conversationId) {
                    try {
                        await window.NotionAI.API.Client.deleteConversation(chat.conversationId);
                    } catch (e) {
                        console.warn(`Failed to delete conversation ${chat.conversationId} on backend:`, e);
                    }
                }
                window.NotionAI.Chat.Storage.deleteChat(id);
            }
        }

        const newSelected = selected.filter(id => !targets.includes(id));
        window.NotionAI.Core.State.set('selectedChatIds', newSelected);

        const currentChatId = window.NotionAI.Core.State.get('currentChatId');
        if (targets.includes(currentChatId)) {
            if (newSelected.length > 0) this.selectChat(newSelected[newSelected.length - 1]);
            else this.startNewChat();
        } else {
            this.renderChatList();
        }
    },

    renameChat(chatId, newTitle) {
        window.NotionAI.Chat.Storage.updateChatTitle(chatId, newTitle);
        const currentChatId = window.NotionAI.Core.State.get('currentChatId');
        if (currentChatId === chatId) document.getElementById('headerTitle').textContent = newTitle;
        this.renderChatList();
    },

    toggleStar(chatId) {
        window.NotionAI.Chat.Storage.toggleStar(chatId);
        this.renderChatList();
    },

    _messageTimestamp(message) {
        const value = message?.createdAt || message?.created_at || message?.timestamp || message?.time || '';
        if (typeof value === 'number') return value;
        const text = String(value || '').trim();
        if (/^\d+$/.test(text)) return Number(text);
        const parsed = Date.parse(text);
        return Number.isFinite(parsed) ? parsed : 0;
    },

    _chatLastTimestamp(chat) {
        const messages = Array.isArray(chat?.messages) ? chat.messages : [];
        for (let i = messages.length - 1; i >= 0; i--) {
            const ts = this._messageTimestamp(messages[i]);
            if (ts) return ts;
        }
        const fallback = chat?.updatedAt || chat?.createdAt || chat?.id || '';
        if (typeof fallback === 'number') return fallback;
        const text = String(fallback || '').trim();
        if (/^\d+$/.test(text)) return Number(text);
        const parsed = Date.parse(text);
        return Number.isFinite(parsed) ? parsed : 0;
    },

    _chatTimeLabel(chat) {
        const ts = this._chatLastTimestamp(chat);
        if (!ts) return 'Unknown time';
        const date = new Date(ts);
        if (Number.isNaN(date.getTime())) return 'Unknown time';
        return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', hour12: true });
    },

    _chatDayLabel(chat) {
        const ts = this._chatLastTimestamp(chat);
        if (!ts) return 'Unknown date';
        const date = new Date(ts);
        if (Number.isNaN(date.getTime())) return 'Unknown date';
        const today = new Date();
        const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
        const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
        const diffDays = Math.round((startToday - startDate) / 86400000);
        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Yesterday';
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    },

    _chatMessageCount(chat) {
        return Array.isArray(chat?.messages) ? chat.messages.length : 0;
    },

    renderChatList(options = {}) {
        const chatList = document.getElementById('chatList');
        if (!chatList) return;
        chatList.innerHTML = '';
        if (options.suppressLocal) return;

        const currentChatId = window.NotionAI.Core.State.get('currentChatId');
        const selected = window.NotionAI.Core.State.get('selectedChatIds') || [];
        const sortedChats = this._sortedLocalChats(this._visibleLocalChats());
        const groups = this._groupByDay(sortedChats);

        const renderItems = (items) => {
            items.forEach(chat => {
                const item = document.createElement('div');
                const isSelected = selected.includes(chat.id);
                item.className = `chat-item${chat.id === currentChatId ? ' active' : ''}${isSelected ? ' selected' : ''}`;
                item.onclick = (e) => this.handleChatClick(e, chat.id);

                const textWrap = document.createElement('div');
                textWrap.style.minWidth = '0';
                textWrap.style.flex = '1';
                textWrap.style.display = 'flex';
                textWrap.style.flexDirection = 'column';
                textWrap.style.gap = '2px';

                const title = document.createElement('span');
                title.className = 'chat-item-title';
                title.textContent = `${chat.starred ? '★ ' : ''}${chat.title || chat.id}`;

                const meta = document.createElement('span');
                meta.className = 'chat-history-main-meta';
                const localCount = this._chatMessageCount(chat);
                meta.textContent = `${localCount} message${localCount === 1 ? '' : 's'} · Last ${this._chatTimeLabel(chat)}`;

                textWrap.appendChild(title);
                textWrap.appendChild(meta);

                const menuContainer = document.createElement('div');
                menuContainer.className = 'chat-dropdown-container';
                menuContainer.style.position = 'relative';
                menuContainer.style.display = 'flex';
                menuContainer.style.alignItems = 'center';

                const menuBtn = document.createElement('button');
                menuBtn.className = 'chat-item-menu-btn';
                menuBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1.5"></circle><circle cx="6" cy="12" r="1.5"></circle><circle cx="18" cy="12" r="1.5"></circle></svg>';
                menuBtn.onclick = (e) => {
                    e.stopPropagation();
                    this.toggleChatDropdown(e, chat.id);
                };

                const dropdown = this._createDropdown(chat);
                menuContainer.appendChild(menuBtn);
                menuContainer.appendChild(dropdown);

                item.appendChild(textWrap);
                item.appendChild(menuContainer);
                chatList.appendChild(item);
            });
        };

        if (!groups.length) {
            const empty = document.createElement('div');
            empty.className = 'chat-history-main-empty';
            empty.textContent = 'No local chats match this filter.';
            chatList.appendChild(empty);
            return;
        }

        for (const group of groups) {
            const header = document.createElement('div');
            header.className = 'chat-section-header';
            header.textContent = group.label;
            chatList.appendChild(header);
            renderItems(group.items);
        }
    },

    _createDropdown(chat) {
        const dropdown = document.createElement('div');
        dropdown.id = `dropdown-${chat.id}`;
        dropdown.className = 'custom-dropdown';

        const actions = [
            { action: 'star', label: chat.starred ? 'Unstar' : 'Star', icon: '⭐' },
            { action: 'rename', label: 'Rename', icon: '✏️' },
            { action: 'divider' },
            { action: 'delete', label: 'Delete', icon: '🗑️', danger: true },
        ];

        actions.forEach(a => {
            if (a.action === 'divider') {
                const div = document.createElement('div');
                div.className = 'dropdown-divider';
                dropdown.appendChild(div);
                return;
            }

            const btn = document.createElement('button');
            btn.className = `dropdown-item${a.danger ? ' danger' : ''}`;
            btn.textContent = `${a.icon} ${a.label}`;
            btn.onclick = (e) => {
                e.stopPropagation();
                this.closeChatDropdown();
                this.handleMenuAction(a.action, chat.id);
            };
            dropdown.appendChild(btn);
        });

        return dropdown;
    },

    handleMenuAction(action, chatId) {
        switch (action) {
            case 'star': this.toggleStar(chatId); break;
            case 'rename': window.NotionAI.UI.Modal.openRenameModal(chatId); break;
            case 'delete': this.deleteChat(chatId); break;
        }
    },

    toggleChatDropdown(e, chatId) {
        e.stopPropagation();
        if (this._activeDropdownId && this._activeDropdownId !== chatId) this.closeChatDropdown();
        const menu = document.getElementById(`dropdown-${chatId}`);
        if (menu) {
            if (menu.classList.contains('open')) {
                menu.classList.remove('open');
                this._activeDropdownId = null;
            } else {
                menu.classList.add('open');
                this._activeDropdownId = chatId;
            }
        }
    },

    closeChatDropdown() {
        if (this._activeDropdownId) {
            const menu = document.getElementById(`dropdown-${this._activeDropdownId}`);
            if (menu) menu.classList.remove('open');
            this._activeDropdownId = null;
        }
    },

    addSectionHeader(text) {
        const chatList = document.getElementById('chatList');
        const header = document.createElement('div');
        header.className = 'chat-section-header';
        header.textContent = text;
        chatList.appendChild(header);
    }
};

document.addEventListener('click', (e) => {
    if (!e.target.closest('.chat-dropdown-container')) {
        window.NotionAI.Chat.Manager.closeChatDropdown();
    }
});
