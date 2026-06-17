/**
 * Renderer Module — Notion AI Studio
 * Handles message DOM rendering and updates
 */

window.NotionAI = window.NotionAI || {};
window.NotionAI.Chat = window.NotionAI.Chat || {};

window.NotionAI.Chat.Renderer = {
    /**
     * Creates a message element wrapper
     */
    createMessageElement(role, modelDisplayName = 'Assistant') {
        const wrapper = document.createElement('div');
        wrapper.className = `message-row ${role === 'user' ? 'user-message' : 'assistant-message'} fade-in`;

        if (role === 'user') {
            const bubble = document.createElement('div');
            bubble.className = 'user-bubble';
            wrapper.appendChild(bubble);
            return { wrapper, bubble };
        }

        const content = document.createElement('div');
        content.className = 'assistant-content';
        wrapper.appendChild(content);

        return { wrapper, bubble: content };
    },

    _coerceDate(value) {
        if (value instanceof Date) return value;
        if (typeof value === 'number' && Number.isFinite(value)) return new Date(value);
        const text = String(value || '').trim();
        if (/^\d+$/.test(text)) return new Date(Number(text));
        const parsed = Date.parse(text);
        return Number.isFinite(parsed) ? new Date(parsed) : new Date();
    },

    _formatTime(value) {
        const date = this._coerceDate(value);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', hour12: true });
    },

    /**
     * Updates assistant model label after backend actual-model metadata arrives.
     */
    updateModelLabel(wrapper, modelDisplayName, metadata = null) {
        if (!wrapper || !modelDisplayName) return;
        const label = wrapper.querySelector('.assistant-model-name');
        if (!label) return;
        label.textContent = modelDisplayName;
        wrapper.modelDisplayName = modelDisplayName;
        if (metadata && typeof metadata === 'object') {
            wrapper.modelMetadata = metadata;
            const requested = metadata.requested_model || '';
            const notionRequested = metadata.notion_requested_model || '';
            const actual = metadata.actual_model || metadata.notion_model_name || metadata.notion_step_model || '';
            const provider = metadata.model_provider || '';
            const details = [];
            if (actual) details.push(`Actual: ${actual}`);
            if (provider) details.push(`Provider: ${provider}`);
            if (requested) details.push(`Requested: ${requested}`);
            if (notionRequested) details.push(`Notion requested: ${notionRequested}`);
            label.title = details.join('\n');
        }
    },

    /**
     * Updates AI message content in DOM
     */
    updateAIMessage(wrapper, content, isFinished) {
        const mdDiv = wrapper.mdDivRef;
        if (!content && !isFinished) {
            mdDiv.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
            return;
        }

        // Remove streaming cursor class before re-render
        mdDiv.classList.remove('streaming-cursor');

        window.NotionAI.Utils.Markdown.setSafeMarkdown(mdDiv, content);

        if (isFinished) {
            mdDiv.classList.remove('streaming-cursor');
            mdDiv.querySelectorAll('pre code').forEach((block) => {
                if (!block.dataset.highlighted) {
                    hljs.highlightElement(block);
                }
            });
            window.NotionAI.Utils.DOM.addCodeBlockCopyButtons(mdDiv);

            // Stop thinking timer if still running
            if (wrapper._thinkingTimerInterval) {
                clearInterval(wrapper._thinkingTimerInterval);
                wrapper._thinkingTimerInterval = null;
            }
        } else {
            mdDiv.classList.add('streaming-cursor');
        }

        const chatContainer = document.getElementById('chatContainer');
        if (chatContainer.scrollHeight - chatContainer.scrollTop < chatContainer.clientHeight + 120) {
            window.NotionAI.Utils.DOM.scrollToBottom();
        }
    },

    /**
     * Updates thinking panel
     */
    updateThinkingPanel(wrapper) {
        const card = wrapper.thinkingCardRef;
        if (!card) return;

        const rawText = String(wrapper.thinkingText || '');
        const hasThinking = rawText.trim().length > 0;

        if (!hasThinking) {
            card.classList.add('hidden');
            return;
        }

        card.classList.remove('hidden');

        // Update timer text if we have one
        const timerEl = card.querySelector('.thinking-header-timer');
        if (timerEl && wrapper._thinkingStartTime) {
            const elapsed = Math.round((Date.now() - wrapper._thinkingStartTime) / 1000);
            timerEl.textContent = `${elapsed}s`;
        }

        if (wrapper.thinkingExpanded) {
            card.classList.add('expanded');
            window.NotionAI.Utils.Markdown.setSafeMarkdown(wrapper.thinkingBodyRef, rawText);
        } else {
            card.classList.remove('expanded');
        }
    },

    /**
     * Updates search panel
     */
    updateSearchPanel(wrapper) {
        const card = wrapper.searchCardRef;
        if (!card) return;

        const queries = wrapper.searchData?.queries || [];
        const sources = wrapper.searchData?.sources || [];
        const hasData = queries.length > 0 || sources.length > 0;

        if (!hasData) {
            card.classList.add('hidden');
            return;
        }

        card.classList.remove('hidden');

        const count = sources.length || queries.length;
        const headerLabel = card.querySelector('.search-header-label');
        if (headerLabel) {
            headerLabel.textContent = `Searched ${count} source${count !== 1 ? 's' : ''}`;
        }

        const queryText = card.querySelector('.search-query-text');
        if (queryText) {
            queryText.textContent = queries.length
                ? `Queries: ${queries.map(q => `"${q}"`).join(', ')}`
                : 'Web search executed';
        }

        const linksContainer = card.querySelector('.search-links-container');
        if (linksContainer) {
            linksContainer.innerHTML = '';
            if (sources.length === 0) {
                linksContainer.innerHTML = '<div style="color:var(--text-tertiary)">No sources to display.</div>';
            } else {
                sources.forEach(src => {
                    if (src.url) {
                        const a = document.createElement('a');
                        a.className = 'search-link';
                        a.href = src.url;
                        a.target = '_blank';
                        a.rel = 'noopener noreferrer';
                        a.textContent = src.title || src.url;
                        linksContainer.appendChild(a);
                    } else {
                        const div = document.createElement('div');
                        div.textContent = src.title;
                        div.style.fontSize = '12px';
                        linksContainer.appendChild(div);
                    }
                });
            }
        }

        if (wrapper.searchExpanded) {
            card.classList.add('expanded');
        } else {
            card.classList.remove('expanded');
        }
    },

    /**
     * Appends a message to the chat container
     */
    appendMessage(role, content, isFinished = false, modelDisplayName = null, timestamp = null) {
        const resolvedName = (modelDisplayName || (role === 'assistant' ? 'Model unverified' : '')).trim() || 'Assistant';

        const { wrapper, bubble } = this.createMessageElement(role, resolvedName);

        if (role === 'user') {
            bubble.textContent = content;
        } else {
            const refs = this._buildAssistantContent(bubble, content, isFinished, resolvedName, timestamp);
            Object.assign(wrapper, refs);
            this._setupPanelListeners(wrapper);
        }

        document.getElementById('chatContainer').appendChild(wrapper);
        return wrapper;
    },

    /**
     * Builds assistant message content (thinking card + search card + markdown)
     */
    _buildAssistantContent(container, content, isFinished, modelDisplayName, timestamp = null) {
        // Search card
        const searchCard = document.createElement('div');
        searchCard.className = 'search-card hidden';
        searchCard.innerHTML = `
            <div class="search-header">
                <span>🔍</span>
                <span class="search-header-label">Searched 0 sources</span>
                <span class="search-header-arrow" style="margin-left:auto;font-size:10px">▸</span>
            </div>
            <div class="search-body">
                <div class="search-query-text"></div>
                <div class="search-links-container"></div>
            </div>
        `;
        container.appendChild(searchCard);

        // Thinking card
        const thinkingCard = document.createElement('div');
        thinkingCard.className = 'thinking-card hidden';
        thinkingCard.innerHTML = `
            <div class="thinking-header">
                <span class="thinking-header-icon">◆</span>
                <span class="thinking-header-label">Thoughts</span>
                <span class="thinking-header-timer"></span>
                <span class="thinking-header-arrow">▸</span>
            </div>
            <div class="thinking-body">
                <div class="markdown-body thinking-markdown"></div>
            </div>
        `;
        container.appendChild(thinkingCard);

        // Markdown content
        const mdDiv = document.createElement('div');
        mdDiv.className = 'markdown-body';
        container.appendChild(mdDiv);

        if (content === '') {
            if (isFinished) {
                window.NotionAI.Utils.Markdown.setSafeMarkdown(mdDiv, '*No visible response received.*');
            } else {
                mdDiv.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
            }
        } else {
            window.NotionAI.Utils.Markdown.setSafeMarkdown(mdDiv, content);
            if (isFinished) {
                mdDiv.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
                window.NotionAI.Utils.DOM.addCodeBlockCopyButtons(mdDiv);
            }
        }

        const footer = document.createElement('div');
        footer.className = 'assistant-meta';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'message-copy-btn';
        copyBtn.textContent = 'Copy';
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(mdDiv.innerText).then(() => {
                copyBtn.textContent = 'Copied!';
                setTimeout(() => copyBtn.textContent = 'Copy', 2000);
            });
        };
        footer.appendChild(copyBtn);

        const modelLabel = document.createElement('span');
        modelLabel.className = 'assistant-model-name';
        modelLabel.textContent = modelDisplayName;
        footer.appendChild(modelLabel);

        const timestampEl = document.createElement('span');
        timestampEl.className = 'message-timestamp';
        timestampEl.textContent = this._formatTime(timestamp || new Date());
        footer.appendChild(timestampEl);
        container.appendChild(footer);

        return {
            bubbleRef: container,
            mdDivRef: mdDiv,
            // Search refs
            searchCardRef: searchCard,
            searchExpanded: false,
            searchData: { queries: [], sources: [] },
            // Thinking refs
            thinkingCardRef: thinkingCard,
            thinkingBodyRef: thinkingCard.querySelector('.thinking-body .thinking-markdown'),
            thinkingExpanded: false,
            thinkingText: '',
            thinkingModelDisplayName: modelDisplayName,
            _thinkingStartTime: isFinished ? null : Date.now(),
            _thinkingTimerInterval: null,
        };
    },

    /**
     * Sets up click listeners for thinking/search panels
     */
    _setupPanelListeners(wrapper) {
        const thinkingHeader = wrapper.querySelector('.thinking-header');
        const searchHeader = wrapper.querySelector('.search-header');

        if (thinkingHeader) {
            thinkingHeader.addEventListener('click', () => {
                wrapper.thinkingExpanded = !wrapper.thinkingExpanded;
                this.updateThinkingPanel(wrapper);
            });
        }

        if (searchHeader) {
            searchHeader.addEventListener('click', () => {
                wrapper.searchExpanded = !wrapper.searchExpanded;
                this.updateSearchPanel(wrapper);
            });
        }
    },

    /**
     * Shows a structured error card in the AI message area
     */
    showErrorCard(wrapper, message, code, suggestion, detail, httpStatus) {
        const mdDiv = wrapper.mdDivRef;
        if (!mdDiv) return;

        // Stop thinking timer
        if (wrapper._thinkingTimerInterval) {
            clearInterval(wrapper._thinkingTimerInterval);
            wrapper._thinkingTimerInterval = null;
        }

        // Hide thinking card on error
        if (wrapper.thinkingCardRef) {
            wrapper.thinkingCardRef.classList.add('hidden');
        }

        let html = '<div class="error-card">';
        html += '<div class="error-card-header">';
        html += '<span class="error-card-icon">⚠</span>';
        html += '<span class="error-card-title">Request failed</span>';
        if (code) {
            html += `<span class="error-card-code">${this._escapeHtml(code)}</span>`;
        }
        html += '</div>';
        html += `<div class="error-card-message">${this._escapeHtml(message)}</div>`;
        if (suggestion) {
            html += `<div class="error-card-suggestion">💡 ${this._escapeHtml(suggestion)}</div>`;
        }
        if (detail) {
            html += '<details class="error-card-details"><summary>Technical details</summary>';
            html += `<pre>${this._escapeHtml(detail)}</pre></details>`;
        }
        html += '</div>';

        mdDiv.innerHTML = html;
        mdDiv.classList.remove('streaming-cursor');
        window.NotionAI.Utils.DOM.scrollToBottom();
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
