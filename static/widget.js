/**
 * SchoolX Enterprise RAG — Embeddable Web Chat Widget (widget.js)
 * Standalone, zero-dependency floating chat bubble for any website (HTML, WordPress, React, Tilda, Bitrix).
 *
 * Usage:
 * <script src="http://your-server:8000/widget.js" 
 *         data-api="http://your-server:8000" 
 *         data-title="Школа № 1468 | AI Помощник"
 *         data-primary-color="#1e3a8a"></script>
 */

(function () {
  'use strict';

  // Prevent multiple initializations
  if (window.__SCHOOLX_RAG_WIDGET_LOADED__) return;
  window.__SCHOOLX_RAG_WIDGET_LOADED__ = true;

  // Extract configuration from current script tag
  const currentScript = document.currentScript || (function () {
    const scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1];
  })();

  const API_BASE = (currentScript && currentScript.getAttribute('data-api')) || window.location.origin;
  const TITLE = (currentScript && currentScript.getAttribute('data-title')) || 'Школа № 1468 | AI-Помощник';
  const SUBTITLE = (currentScript && currentScript.getAttribute('data-subtitle')) || 'Официальная база знаний и регламенты';
  const PRIMARY_COLOR = (currentScript && currentScript.getAttribute('data-primary-color')) || '#1e3a8a';
  const POSITION = (currentScript && currentScript.getAttribute('data-position')) || 'right'; // right or left
  const GREETING = (currentScript && currentScript.getAttribute('data-greeting')) || 
    'Здравствуйте! Я цифровой консультант Школы № 1468. Задайте любой вопрос по правилам приема, учебному процессу, документам или контактам.';

  // Session Management
  const STORAGE_KEY = 'schoolx_rag_session_id';
  let sessionId = localStorage.getItem(STORAGE_KEY);
  if (!sessionId) {
    sessionId = 'web_' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
    localStorage.setItem(STORAGE_KEY, sessionId);
  }

  // Inject Styles
  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .rag-widget-container {
      position: fixed;
      bottom: 24px;
      ${POSITION === 'left' ? 'left: 24px;' : 'right: 24px;'}
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      box-sizing: border-box;
    }
    .rag-widget-container * {
      box-sizing: border-box;
    }
    .rag-widget-toggle {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: ${PRIMARY_COLOR};
      color: #ffffff;
      border: none;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.22);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.2s ease;
      outline: none;
    }
    .rag-widget-toggle:hover {
      transform: scale(1.08);
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
    }
    .rag-widget-toggle svg {
      width: 28px;
      height: 28px;
      fill: currentColor;
      transition: transform 0.2s ease;
    }
    .rag-widget-box {
      display: none;
      flex-direction: column;
      width: 380px;
      max-width: calc(100vw - 32px);
      height: 560px;
      max-height: calc(100vh - 100px);
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
      position: absolute;
      bottom: 75px;
      ${POSITION === 'left' ? 'left: 0;' : 'right: 0;'}
      overflow: hidden;
      animation: ragWidgetSlideUp 0.25s ease-out forwards;
    }
    @keyframes ragWidgetSlideUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .rag-widget-header {
      background: ${PRIMARY_COLOR};
      color: #ffffff;
      padding: 14px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top-left-radius: 16px;
      border-top-right-radius: 16px;
    }
    .rag-widget-header-title {
      display: flex;
      flex-direction: column;
    }
    .rag-widget-header-title span.main-title {
      font-weight: 600;
      font-size: 15px;
      letter-spacing: -0.2px;
    }
    .rag-widget-header-title span.sub-title {
      font-size: 11px;
      opacity: 0.85;
      display: flex;
      align-items: center;
      gap: 5px;
      margin-top: 2px;
    }
    .rag-widget-status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: #22c55e;
      display: inline-block;
    }
    .rag-widget-header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .rag-widget-btn-icon {
      background: transparent;
      border: none;
      color: #ffffff;
      cursor: pointer;
      opacity: 0.85;
      padding: 4px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: opacity 0.2s, background 0.2s;
    }
    .rag-widget-btn-icon:hover {
      opacity: 1;
      background: rgba(255, 255, 255, 0.15);
    }
    .rag-widget-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      background: #f8fafc;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .rag-widget-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.45;
      word-break: break-word;
    }
    .rag-widget-msg-user {
      align-self: flex-end;
      background: ${PRIMARY_COLOR};
      color: #ffffff;
      border-bottom-right-radius: 4px;
    }
    .rag-widget-msg-bot {
      align-self: flex-start;
      background: #ffffff;
      color: #1e293b;
      border: 1px solid #e2e8f0;
      border-bottom-left-radius: 4px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .rag-widget-msg-bot p {
      margin: 0 0 8px 0;
    }
    .rag-widget-msg-bot p:last-child {
      margin-bottom: 0;
    }
    .rag-widget-msg-bot ul, .rag-widget-msg-bot ol {
      margin: 4px 0 8px 18px;
      padding: 0;
    }
    .rag-widget-sources {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px dashed #cbd5e1;
      font-size: 11px;
      color: #64748b;
    }
    .rag-widget-sources-title {
      font-weight: 600;
      margin-bottom: 4px;
      color: #475569;
    }
    .rag-widget-source-item {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-bottom: 2px;
    }
    .rag-widget-typing {
      display: flex;
      gap: 4px;
      padding: 8px 12px;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      width: fit-content;
      align-self: flex-start;
    }
    .rag-widget-typing span {
      width: 6px;
      height: 6px;
      background: #94a3b8;
      border-radius: 50%;
      animation: ragBounce 1.2s infinite ease-in-out;
    }
    .rag-widget-typing span:nth-child(2) { animation-delay: 0.2s; }
    .rag-widget-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes ragBounce {
      0%, 80%, 100% { transform: translateY(0); }
      40% { transform: translateY(-6px); }
    }
    .rag-widget-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .rag-widget-chip {
      background: #e2e8f0;
      color: #334155;
      font-size: 11.5px;
      padding: 5px 10px;
      border-radius: 12px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s;
    }
    .rag-widget-chip:hover {
      background: #cbd5e1;
      border-color: #94a3b8;
    }
    .rag-widget-input-area {
      padding: 12px 14px;
      background: #ffffff;
      border-top: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .rag-widget-input {
      flex: 1;
      border: 1px solid #cbd5e1;
      border-radius: 20px;
      padding: 9px 14px;
      font-size: 13.5px;
      outline: none;
      transition: border-color 0.2s;
    }
    .rag-widget-input:focus {
      border-color: ${PRIMARY_COLOR};
    }
    .rag-widget-send-btn {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: ${PRIMARY_COLOR};
      color: #ffffff;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s, transform 0.1s;
    }
    .rag-widget-send-btn:hover {
      opacity: 0.92;
      transform: scale(1.05);
    }
    .rag-widget-send-btn:disabled {
      background: #cbd5e1;
      cursor: not-allowed;
      transform: none;
    }
  `;
  document.head.appendChild(styleEl);

  // Build DOM Structure
  const container = document.createElement('div');
  container.className = 'rag-widget-container';
  container.innerHTML = `
    <div class="rag-widget-box" id="ragWidgetBox">
      <div class="rag-widget-header">
        <div class="rag-widget-header-title">
          <span class="main-title">${TITLE}</span>
          <span class="sub-title"><span class="rag-widget-status-dot"></span>${SUBTITLE}</span>
        </div>
        <div class="rag-widget-header-actions">
          <button class="rag-widget-btn-icon" id="ragResetBtn" title="Начать новый диалог">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
              <path d="M3 3v5h5"/>
            </svg>
          </button>
          <button class="rag-widget-btn-icon" id="ragCloseBtn" title="Свернуть">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </div>
      <div class="rag-widget-messages" id="ragMessages">
        <div class="rag-widget-msg rag-widget-msg-bot">
          ${GREETING}
          <div class="rag-widget-chips">
            <div class="rag-widget-chip" data-q="Как записать ребенка в 1 класс?">Как записать ребенка в 1 класс?</div>
            <div class="rag-widget-chip" data-q="Какие профили есть в 10 классе?">Профили 10 класса</div>
            <div class="rag-widget-chip" data-q="Контакты администрации и часы приема">Контакты администрации</div>
          </div>
        </div>
      </div>
      <div class="rag-widget-input-area">
        <input type="text" class="rag-widget-input" id="ragInput" placeholder="Напишите ваш вопрос..." />
        <button class="rag-widget-send-btn" id="ragSendBtn" title="Отправить">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
    </div>
    <button class="rag-widget-toggle" id="ragToggleBtn" title="Открыть чат с консультантом">
      <svg id="ragIconOpen" viewBox="0 0 24 24">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/>
      </svg>
      <svg id="ragIconClose" style="display:none;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    </button>
  `;
  document.body.appendChild(container);

  // Elements
  const box = document.getElementById('ragWidgetBox');
  const toggleBtn = document.getElementById('ragToggleBtn');
  const closeBtn = document.getElementById('ragCloseBtn');
  const resetBtn = document.getElementById('ragResetBtn');
  const messagesContainer = document.getElementById('ragMessages');
  const input = document.getElementById('ragInput');
  const sendBtn = document.getElementById('ragSendBtn');
  const iconOpen = document.getElementById('ragIconOpen');
  const iconClose = document.getElementById('ragIconClose');

  let isOpen = false;
  let isGenerating = false;

  function toggleWidget() {
    isOpen = !isOpen;
    box.style.display = isOpen ? 'flex' : 'none';
    iconOpen.style.display = isOpen ? 'none' : 'block';
    iconClose.style.display = isOpen ? 'block' : 'none';
    if (isOpen) {
      setTimeout(() => input.focus(), 150);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  }

  toggleBtn.addEventListener('click', toggleWidget);
  closeBtn.addEventListener('click', toggleWidget);

  // Markdown-like text formatter
  function formatText(text) {
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bullet lists
    html = html.replace(/^[•\-\*]\s+(.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    // Newlines
    html = html.replace(/\n/g, '<br/>');
    return html;
  }

  // Quick Chips
  container.addEventListener('click', function(e) {
    const chip = e.target.closest('.rag-widget-chip');
    if (chip && !isGenerating) {
      const q = chip.getAttribute('data-q');
      if (q) {
        input.value = q;
        sendMessage();
      }
    }
  });

  // Reset Session
  resetBtn.addEventListener('click', async function () {
    if (isGenerating) return;
    if (confirm('Начать новую тему? Текущая история диалога будет сброшена.')) {
      try {
        await fetch(`${API_BASE}/api/v1/chat/reset`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId })
        });
      } catch (e) {
        console.warn('Reset error:', e);
      }
      sessionId = 'web_' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
      localStorage.setItem(STORAGE_KEY, sessionId);
      messagesContainer.innerHTML = `
        <div class="rag-widget-msg rag-widget-msg-bot">
          Контекст очищен. Задайте новый вопрос!
          <div class="rag-widget-chips">
            <div class="rag-widget-chip" data-q="Как записать ребенка в 1 класс?">Как записать ребенка в 1 класс?</div>
            <div class="rag-widget-chip" data-q="Какие профили есть в 10 классе?">Профили 10 класса</div>
            <div class="rag-widget-chip" data-q="Контакты администрации и часы приема">Контакты администрации</div>
          </div>
        </div>
      `;
    }
  });

  // Sending messages with SSE streaming
  async function sendMessage() {
    const query = input.value.trim();
    if (!query || isGenerating) return;

    // Append User Message
    const userMsgEl = document.createElement('div');
    userMsgEl.className = 'rag-widget-msg rag-widget-msg-user';
    userMsgEl.textContent = query;
    messagesContainer.appendChild(userMsgEl);
    input.value = '';
    isGenerating = true;
    sendBtn.disabled = true;

    // Append Typing Indicator
    const typingEl = document.createElement('div');
    typingEl.className = 'rag-widget-typing';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    messagesContainer.appendChild(typingEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Create Bot Message Container
    const botMsgEl = document.createElement('div');
    botMsgEl.className = 'rag-widget-msg rag-widget-msg-bot';
    let fullResponseText = '';
    let sourcesData = [];

    try {
      // Try SSE Streaming endpoint first
      const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        },
        body: JSON.stringify({
          query: query,
          session_id: sessionId
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      // Remove typing indicator once stream starts
      typingEl.remove();
      messagesContainer.appendChild(botMsgEl);

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep partial line

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const rawJson = line.replace('data: ', '').trim();
            if (!rawJson) continue;
            try {
              const parsed = JSON.parse(rawJson);
              if (parsed.delta) {
                fullResponseText += parsed.delta;
                botMsgEl.innerHTML = formatText(fullResponseText);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
              }
              if (parsed.done && parsed.sources) {
                sourcesData = parsed.sources;
              }
            } catch (jsonErr) {
              console.warn('SSE JSON parse error:', jsonErr);
            }
          }
        }
      }

    } catch (streamErr) {
      console.warn('Streaming error, falling back to REST endpoint:', streamErr);
      try {
        const restResp = await fetch(`${API_BASE}/api/v1/chat/message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query,
            session_id: sessionId
          })
        });
        const data = await restResp.json();
        typingEl.remove();
        if (!botMsgEl.parentNode) {
          messagesContainer.appendChild(botMsgEl);
        }
        fullResponseText = data.answer || 'Ответ не получен.';
        sourcesData = data.sources || [];
        botMsgEl.innerHTML = formatText(fullResponseText);
      } catch (restErr) {
        typingEl.remove();
        if (!botMsgEl.parentNode) {
          messagesContainer.appendChild(botMsgEl);
        }
        botMsgEl.innerHTML = '<span style="color:#ef4444;">⚠️ Ошибка соединения с сервером консультаций. Пожалуйста, попробуйте позже.</span>';
      }
    } finally {
      // Append sources if available
      if (sourcesData && sourcesData.length > 0) {
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'rag-widget-sources';
        let srcHtml = '<div class="rag-widget-sources-title">📚 Источники информации:</div>';
        sourcesData.slice(0, 3).forEach(s => {
          const pgStr = s.page ? ` (стр. ${s.page})` : '';
          srcHtml += `<div class="rag-widget-source-item">• <strong>${s.source}</strong>${pgStr}</div>`;
        });
        sourcesDiv.innerHTML = srcHtml;
        botMsgEl.appendChild(sourcesDiv);
      }

      isGenerating = false;
      sendBtn.disabled = false;
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      input.focus();
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

})();
