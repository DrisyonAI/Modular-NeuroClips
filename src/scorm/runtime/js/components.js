/**
 * NeuroClips Component Registry & Content Renderer
 * Implements content blocks and interactions matching screenshots 59-65 and specifications.
 */

const sanitizeHtml = (raw) => {
  if (!raw) return '';
  // Basic safe sanitization preventing script injection and event handlers
  return String(raw)
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/on\w+="[^"]*"/g, '')
    .replace(/on\w+='[^']*'/g, '')
    .replace(/javascript:/gi, '');
};

const esc = (str) => {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
};

const ComponentRegistry = {
  // --- Content Block Renderers ---

  heading: (block) => {
    const level = block.level || 2;
    const text = esc(block.text);
    return `<h${level} class="block-heading-${level}">${text}</h${level}>`;
  },

  paragraph: (block) => {
    return `<p class="block-paragraph">${esc(block.text)}</p>`;
  },

  richText: (block) => {
    return `<div class="block-rich-text">${sanitizeHtml(block.html || block.text)}</div>`;
  },

  note: (block) => {
    return `<p class="block-note">${esc(block.text)}</p>`;
  },

  list: (block) => {
    const items = block.items || [];
    const style = block.style || 'unordered';

    if (style === 'pills' || style === 'grid') {
      return `
        <div class="pills-grid">
          ${items.map(item => `
            <div class="pill-card">
              <span class="pill-bullet">•</span>
              <span>${esc(item)}</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    if (style === 'ordered') {
      return `
        <ol class="content-ordered-list" style="margin-left: 20px; font-size: 13px; line-height: 1.7; color: #334155;">
          ${items.map(item => `<li>${esc(item)}</li>`).join('')}
        </ol>
      `;
    }

    return `
      <ul class="content-unordered-list" style="margin-left: 20px; font-size: 13px; line-height: 1.7; color: #334155;">
        ${items.map(item => `<li>${esc(item)}</li>`).join('')}
      </ul>
    `;
  },

  // 2-Column Red-Tinted Pills Grid (Screenshot 59 & 60)
  pills: (block) => {
    const items = block.items || [];
    return `
      <div class="pills-grid">
        ${items.map(item => `
          <div class="pill-card">
            <span class="pill-bullet">•</span>
            <span>${esc(item)}</span>
          </div>
        `).join('')}
      </div>
    `;
  },

  // Side-by-Side Comparison Cards (Screenshot 60)
  comparison: (block) => {
    const cards = block.cards || [];
    return `
      <div class="comparison-grid">
        ${cards.map(card => {
          const isHighlight = card.variant === 'highlight' || card.variant === 'accent';
          return `
            <div class="comparison-card ${isHighlight ? 'highlight' : 'neutral'}">
              <div class="comparison-title">${esc(card.title)}</div>
              <div class="comparison-content">${sanitizeHtml(card.content || card.text)}</div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  // Example Scenario Card (Screenshot 61)
  example: (block) => {
    const title = block.title || 'EXAMPLE';
    const description = block.description || block.lead || '';
    const steps = block.steps || [];
    const conclusion = block.conclusion || '';

    return `
      <div class="example-box">
        <div class="example-title">${esc(title)}</div>
        ${description ? `<div class="example-lead">${esc(description)}</div>` : ''}
        ${steps.length > 0 ? `
          <div class="example-steps">
            ${steps.map(s => `<div class="example-step-item">${esc(s)}</div>`).join('')}
          </div>
        ` : ''}
        ${conclusion ? `<div class="example-conclusion">${esc(conclusion)}</div>` : ''}
      </div>
    `;
  },

  // Key Learning / Callout Card (Screenshot 61)
  callout: (block) => {
    const variant = block.variant || 'info';
    const title = block.title || (variant === 'key' ? 'KEY LEARNING' : 'NOTE');
    const text = block.text || '';

    if (variant === 'key') {
      return `
        <div class="key-learning-card">
          <div class="key-learning-label">${esc(title)}</div>
          <div class="key-learning-text">${esc(text)}</div>
        </div>
      `;
    }

    return `
      <div class="generic-callout" style="background: #F1F5F9; border-left: 4px solid var(--color-brand-red); padding: 16px 20px; border-radius: 4px; margin: 16px 0;">
        <div style="font-size: 12px; font-weight: 800; color: var(--color-navy); margin-bottom: 4px;">${esc(title)}</div>
        <div style="font-size: 13px; color: #334155;">${esc(text)}</div>
      </div>
    `;
  },

  // Data Table (Screenshot 62)
  table: (block) => {
    const headers = block.headers || [];
    const rows = block.rows || [];
    const caption = block.caption ? `<div style="font-size: 12px; font-weight: 700; color: #64748B; margin-bottom: 6px;">${esc(block.caption)}</div>` : '';

    return `
      <div class="content-table-container">
        ${caption}
        <table class="content-table">
          ${headers.length > 0 ? `
            <thead>
              <tr>
                ${headers.map(h => `<th>${esc(h)}</th>`).join('')}
              </tr>
            </thead>
          ` : ''}
          <tbody>
            ${rows.map(row => `
              <tr>
                ${(Array.isArray(row) ? row : []).map(cell => `<td>${esc(cell)}</td>`).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  },

  image: (block) => {
    const src = esc(block.src);
    const alt = esc(block.alt || '');
    const caption = block.caption ? `<div style="font-size: 11px; text-align: center; color: #64748B; margin-top: 6px;">${esc(block.caption)}</div>` : '';
    return `
      <div class="content-image-box" style="margin: 20px 0; text-align: center;">
        <img src="${src}" alt="${alt}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06);" />
        ${caption}
      </div>
    `;
  },

  divider: () => {
    return `<hr style="border: 0; height: 1px; background: #E2E8F0; margin: 24px 0;" />`;
  },

  definition: (block) => {
    return `
      <div class="definition-box" style="background: #F8FAFC; border-left: 3px solid #6366F1; padding: 14px 18px; border-radius: 4px; margin: 16px 0;">
        <div style="font-size: 13px; font-weight: 700; color: #312E81;">${esc(block.term)}</div>
        <div style="font-size: 13px; color: #475569; margin-top: 4px;">${esc(block.definition)}</div>
      </div>
    `;
  },

  // --- Interactive Components ---

  accordion: (block) => {
    const id = block.id || `acc_${Math.random().toString(36).substr(2, 6)}`;
    const items = block.items || [];
    return `
      <div class="accordion-group" id="${id}">
        ${items.map((it, idx) => `
          <div class="accordion-item" onclick="toggleAccordion(this)">
            <div class="accordion-header">
              <span>${esc(it.title)}</span>
              <span class="accordion-chevron">▼</span>
            </div>
            <div class="accordion-body">
              ${sanitizeHtml(it.content || it.text)}
            </div>
          </div>
        `).join('')}
      </div>
    `;
  },

  tabs: (block) => {
    const id = block.id || `tabs_${Math.random().toString(36).substr(2, 6)}`;
    const tabs = block.tabs || [];
    return `
      <div class="tabs-container" id="${id}">
        <div class="tabs-nav">
          ${tabs.map((tab, idx) => `
            <button class="tab-btn ${idx === 0 ? 'active' : ''}" onclick="switchLocalTab('${id}', ${idx})">
              ${esc(tab.label || tab.title)}
            </button>
          `).join('')}
        </div>
        ${tabs.map((tab, idx) => `
          <div class="tab-pane tab-pane-${id}-${idx} ${idx === 0 ? 'active' : ''}">
            ${sanitizeHtml(tab.content || tab.text)}
          </div>
        `).join('')}
      </div>
    `;
  },

  flashcards: (block) => {
    const cards = block.cards || [];
    return `
      <div class="flashcards-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin: 18px 0;">
        ${cards.map((card, idx) => `
          <div class="flashcard" onclick="this.classList.toggle('flipped')" style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 24px; min-height: 140px; cursor: pointer; text-align: center; display: flex; flex-direction: column; justify-content: center; box-shadow: 0 2px 8px rgba(0,0,0,0.04); transition: transform 0.2s;">
            <div class="flashcard-front" style="font-weight: 700; color: var(--color-navy); font-size: 14px;">${esc(card.front)}</div>
            <div class="flashcard-hint" style="font-size: 11px; color: #94A3B8; margin-top: 8px;">(Click to flip)</div>
          </div>
        `).join('')}
      </div>
    `;
  }
};

/**
 * Global helper for accordions
 */
window.toggleAccordion = function(itemEl) {
  itemEl.classList.toggle('open');
};

/**
 * Global helper for tab containers
 */
window.switchLocalTab = function(containerId, activeIdx) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const btns = container.querySelectorAll('.tab-btn');
  const panes = container.querySelectorAll('.tab-pane');

  btns.forEach((btn, idx) => {
    btn.classList.toggle('active', idx === activeIdx);
  });
  panes.forEach((pane, idx) => {
    pane.classList.toggle('active', idx === activeIdx);
  });
};

/**
 * Main render function
 */
function renderBlock(block) {
  if (!block || !block.type) return '';
  const renderer = ComponentRegistry[block.type];
  if (renderer) {
    return renderer(block);
  }
  return `<div class="unsupported-block" style="display:none;" data-type="${block.type}"></div>`;
}

window.ComponentRegistry = ComponentRegistry;
window.renderBlock = renderBlock;
