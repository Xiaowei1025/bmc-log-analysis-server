(() => {
  /* FileReader validation and clipboard image handling live in editor-media.js; data:image sources stay inline. */
  const form = document.querySelector('form[data-tool-editor-form]');
  const block = document.querySelector('.tool-description-editor');
  const markdown = document.getElementById('tool-description-input');
  const rich = document.getElementById('tool-rich-editor');
  if (!form || !block || !markdown || !rich || !window.BmcMarkdown) return;

  const toolbar = document.getElementById('tool-rich-toolbar');
  const preview = document.getElementById('tool-preview');
  const previewContent = document.getElementById('tool-preview-content');
  const previewButton = document.getElementById('tool-preview-button');
  const imageInput = document.getElementById('tool-image-input');
  const hint = document.getElementById('tool-description-hint');
  const error = document.getElementById('tool-description-error');
  const newline = String.fromCharCode(10);
  const fence = String.fromCharCode(96).repeat(3);
  const media = window.BmcEditorMedia;
  const imageSize = document.querySelector('[data-tool-image-size]');
  let mode = 'markdown';
  let markdownRange = {start: 0, end: 0};
  let richRange = null;
  let selectedImage = null;
  const imageSource = value => media ? media.source(value) : '';

  const inlineMarkdown = node => {
    if (node.nodeType === Node.TEXT_NODE) return String(node.nodeValue || '').replace(/\u00a0/g, ' ');
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    if (node.dataset?.editorResizeHandle) return '';
    if (node.tagName === 'IMG') {
      const source = imageSource(node.getAttribute('src'));
      if (!source) return '';
      const alt = String(node.getAttribute('alt') || '图片').replace(/[\]\r\n]/g, '');
      return media ? media.imageMarkdown(alt, source, node) : `![${alt}](${source})`;
    }
    const content = Array.from(node.childNodes).map(inlineMarkdown).join('');
    if (node.tagName === 'BR') return newline;
    if (node.tagName === 'STRONG' || node.tagName === 'B') return `**${content}**`;
    if (node.tagName === 'EM' || node.tagName === 'I') return `*${content}*`;
    if (node.tagName === 'CODE') return '`' + content + '`';
    return content;
  };
  const blockMarkdown = node => {
    if (node.nodeType === Node.TEXT_NODE) return String(node.nodeValue || '');
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    if (node.dataset?.editorResizeHandle) return '';
    if (node.dataset?.editorImageShell) return inlineMarkdown(node);
    const tag = node.tagName;
    const inline = inlineMarkdown(node).trim();
    const table = tag === 'TABLE' ? node : (tag === 'DIV' ? node.querySelector('table') : null);
    if (table) {
      const rows = Array.from(table.querySelectorAll('tr')).map(row => Array.from(row.children).map(cell => inlineMarkdown(cell).trim()));
      if (rows.length) return `| ${rows[0].join(' | ')} |${newline}| ${rows[0].map(() => '---').join(' | ')} |${newline}${rows.slice(1).map(row => `| ${rows[0].map((_, index) => row[index] || '').join(' | ')} |`).join(newline)}${newline}${newline}`;
    }
    if (/^H[1-6]$/.test(tag)) return '#'.repeat(Number(tag[1])) + ` ${inline}${newline}${newline}`;
    if (tag === 'P' || tag === 'DIV') return inline ? `${inline}${newline}${newline}` : '';
    if (tag === 'UL' || tag === 'OL') return Array.from(node.children).map((item, index) => `${tag === 'OL' ? `${index + 1}.` : '-'} ${inlineMarkdown(item).trim()}`).join(newline) + newline + newline;
    if (tag === 'BLOCKQUOTE') return inline.split(newline).map(line => `> ${line}`).join(newline) + newline + newline;
    if (tag === 'PRE') return `${fence}${newline}${String(node.textContent || '').trim()}${newline}${fence}${newline}${newline}`;
    if (tag === 'HR') return `---${newline}${newline}`;
    return inline ? `${inline}${newline}${newline}` : '';
  };
  const richToMarkdown = () => Array.from(rich.childNodes).map(blockMarkdown).join('').replace(/\n{3,}/g, newline + newline).trim();
  const currentMarkdown = () => mode === 'rich' ? richToMarkdown() : markdown.value.trim();
  const syncMarkdown = () => { if (mode === 'rich') markdown.value = richToMarkdown(); };
  const renderPreview = () => window.BmcMarkdown.renderTo(previewContent, currentMarkdown() || '尚未填写工具说明。');
  const cacheMarkdownRange = () => { markdownRange = {start: markdown.selectionStart || 0, end: markdown.selectionEnd || 0}; };
  const focusMarkdown = () => { markdown.focus(); markdown.setSelectionRange(Math.min(markdownRange.start, markdown.value.length), Math.min(markdownRange.end, markdown.value.length)); };
  const replaceMarkdown = (start, end, value, selectedStart, selectedEnd) => { markdown.focus(); markdown.setRangeText(value, start, end, 'select'); markdown.setSelectionRange(selectedStart, selectedEnd); cacheMarkdownRange(); renderPreview(); };
  const wrapMarkdown = (prefix, suffix, emptyText) => {
    focusMarkdown();
    const start = markdown.selectionStart;
    const end = markdown.selectionEnd;
    const selected = markdown.value.slice(start, end);
    replaceMarkdown(start, end, prefix + (selected || emptyText) + suffix, start + prefix.length, start + prefix.length + (selected || emptyText).length);
  };
  const prefixLines = prefix => {
    focusMarkdown();
    const value = markdown.value;
    const start = markdown.selectionStart;
    const end = markdown.selectionEnd;
    const lineStart = value.lastIndexOf(newline, Math.max(0, start - 1)) + 1;
    const nextBreak = value.indexOf(newline, end);
    const lineEnd = nextBreak === -1 ? value.length : nextBreak;
    const changed = value.slice(lineStart, lineEnd).split(newline).map(line => line.trim() ? prefix + line : line).join(newline);
    replaceMarkdown(lineStart, lineEnd, changed, Math.max(lineStart, start + prefix.length), Math.max(lineStart, end + prefix.length));
  };
  const applyMarkdownCommand = command => {
    if (command === 'bold') wrapMarkdown('**', '**', '加粗文字');
    else if (command === 'italic') wrapMarkdown('*', '*', '强调文字');
    else if (command === 'code') wrapMarkdown(fence + newline, newline + fence, '代码内容');
    else if (command === 'heading') prefixLines('## ');
    else if (command === 'unordered') prefixLines('- ');
    else if (command === 'ordered') prefixLines('1. ');
    else if (command === 'quote') prefixLines('> ');
    else if (command === 'link') wrapMarkdown('[', '](https://example.com)', '链接文字');
    else if (command === 'hr') { focusMarkdown(); const at = markdown.selectionStart; replaceMarkdown(at, markdown.selectionEnd, `${newline}---${newline}`, at + 5, at + 5); }
    else if (command === 'table') { focusMarkdown(); const at = markdown.selectionStart; const value = `${newline}| 参数 | 说明 | 示例 |${newline}| --- | --- | --- |${newline}| --input | 输入目录 | /var/log |${newline}`; replaceMarkdown(at, markdown.selectionEnd, value, at + 1, at + 1); }
  };
  const cacheRichSelection = () => {
    const selection = window.getSelection();
    if (selection?.rangeCount && rich.contains(selection.getRangeAt(0).commonAncestorContainer)) richRange = selection.getRangeAt(0).cloneRange();
  };
  const restoreRichSelection = () => {
    rich.focus();
    if (!richRange) return;
    const selection = window.getSelection();
    if (selection && rich.contains(richRange.commonAncestorContainer)) { selection.removeAllRanges(); selection.addRange(richRange); }
  };
  const applyRichCommand = command => {
    if (command === 'image') { if (imageInput) imageInput.click(); return; }
    restoreRichSelection();
    const execute = (name, value) => typeof document.execCommand === 'function' && document.execCommand(name, false, value);
    if (command === 'heading') execute('formatBlock', 'h2');
    else if (command === 'quote') execute('formatBlock', 'blockquote');
    else if (command === 'code') execute('formatBlock', 'pre');
    else if (command === 'unordered') execute('insertUnorderedList');
    else if (command === 'ordered') execute('insertOrderedList');
    else if (command === 'clear') { execute('removeFormat'); execute('formatBlock', 'p'); }
    else if (command === 'bold') execute('bold');
    else if (command === 'italic') execute('italic');
    else if (command === 'link') { const url = window.prompt('请输入 https:// 或 http:// 链接', 'https://'); if (/^https?:\/\//i.test(url || '')) execute('createLink', url.trim()); }
    else if (command === 'hr') execute('insertHorizontalRule');
    else if (command === 'table') insertRichTable();
    cacheRichSelection(); syncMarkdown(); renderPreview();
  };
  const showEditorError = message => { error.textContent = message; error.hidden = false; };
  const insertRichImage = (source, alt) => {
    rich.focus();
    const image = document.createElement('img');
    image.src = source; image.alt = alt || '图片'; image.loading = 'lazy'; image.decoding = 'async';
    const selection = window.getSelection();
    if (selection && selection.rangeCount && rich.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      const range = selection.getRangeAt(0); range.deleteContents(); range.insertNode(image); range.setStartAfter(image); range.collapse(true);
      selection.removeAllRanges(); selection.addRange(range);
    } else rich.appendChild(image);
    selectedImage = image;
    if (media) media.selectImage(image, rich, () => { syncMarkdown(); renderPreview(); });
    cacheRichSelection(); syncMarkdown(); renderPreview();
  };
  const insertRichTable = () => {
    restoreRichSelection();
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>参数</th><th>说明</th><th>示例</th></tr></thead><tbody><tr><td>--input</td><td>输入目录</td><td>/var/log</td></tr><tr><td>--output</td><td>输出文件</td><td>report.md</td></tr></tbody>';
    const selection = window.getSelection();
    if (selection && selection.rangeCount && rich.contains(selection.getRangeAt(0).commonAncestorContainer)) { const range = selection.getRangeAt(0); range.deleteContents(); range.insertNode(table); range.setStartAfter(table); range.collapse(true); selection.removeAllRanges(); selection.addRange(range); } else rich.appendChild(table);
    cacheRichSelection(); syncMarkdown(); renderPreview();
  };
  const insertImage = file => (media ? media.readImage(file) : Promise.reject(new Error('图片能力未加载，请刷新页面。'))).then(source => {
    error.hidden = true;
    const alt = String(file.name || '图片').replace(/\.[^.]+$/, '').replace(/[\]\r\n]/g, '').slice(0, 80) || '图片';
    if (mode === 'rich') insertRichImage(source, alt);
    else {
      cacheMarkdownRange();
      const start = markdownRange.start, end = markdownRange.end;
      const value = `![${alt}](${source})`;
      replaceMarkdown(start, end, value, start + value.length, start + value.length);
    }
  }).catch(errorValue => showEditorError(errorValue.message));
  const setMode = nextMode => {
    if (nextMode === 'rich') {
      rich.innerHTML = markdown.value.trim() ? window.BmcMarkdown.render(markdown.value) : '';
      if (media) media.normalizeRenderedImages(rich);
      rich.hidden = false; markdown.hidden = true; preview.hidden = true; previewButton.hidden = false;
      hint.textContent = '选中文本后使用工具栏格式化；图片可点击后拖动右下角调整宽度，原始尺寸不会被放大。';
    } else {
      markdown.value = richToMarkdown(); rich.hidden = true; markdown.hidden = false; preview.hidden = false; previewButton.hidden = true;
      hint.textContent = '左侧书写、右侧实时预览；支持标题、粗体、列表、引用、代码块和表格。';
      cacheMarkdownRange();
    }
    mode = nextMode;
    block.dataset.editorMode = mode;
    toolbar.querySelectorAll('[data-tool-rich-only]').forEach(button => { button.hidden = mode !== 'rich'; });
    document.querySelectorAll('[data-tool-editor-mode]').forEach(button => { const active = button.dataset.toolEditorMode === mode; button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', String(active)); });
    renderPreview();
  };

  ['select', 'keyup', 'click', 'focus', 'input'].forEach(name => markdown.addEventListener(name, cacheMarkdownRange));
  markdown.addEventListener('input', () => {
    // Draft restoration runs after this editor script. Keep the visible rich
    // surface in sync when app_interactions restores the hidden Markdown field.
    if (mode === 'rich' && markdown.value.trim() !== richToMarkdown()) { rich.innerHTML = window.BmcMarkdown.render(markdown.value); if (media) media.normalizeRenderedImages(rich); }
    error.hidden = true;
    renderPreview();
  });
  markdown.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') { event.preventDefault(); cacheMarkdownRange(); applyMarkdownCommand('bold'); } });
  markdown.addEventListener('paste', event => { if (media) media.handlePaste(event, {onImage: insertImage}); });
  ['keyup', 'mouseup', 'focus', 'input'].forEach(name => rich.addEventListener(name, () => { cacheRichSelection(); syncMarkdown(); error.hidden = true; renderPreview(); }));
  document.querySelectorAll('[data-tool-editor-mode]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.toolEditorMode)));
  previewButton.addEventListener('click', () => { preview.hidden = !preview.hidden; previewButton.textContent = preview.hidden ? '实时预览' : '收起预览'; if (!preview.hidden) renderPreview(); });
  toolbar.addEventListener('mousedown', event => { if (event.target.closest('[data-tool-editor-command]')) event.preventDefault(); });
  toolbar.addEventListener('click', event => { const button = event.target.closest('[data-tool-editor-command]'); if (!button) return; const command = button.dataset.toolEditorCommand; if (command === 'image') { if (imageInput) imageInput.click(); return; } mode === 'rich' ? applyRichCommand(command) : applyMarkdownCommand(command); });
  if (imageSize) imageSize.addEventListener('change', () => { if (selectedImage && media) { media.setImageWidth(selectedImage, imageSize.value); syncMarkdown(); renderPreview(); } imageSize.value = ''; });
  if (imageInput) {
    imageInput.addEventListener('change', () => { const file = imageInput.files && imageInput.files[0]; if (file) insertImage(file); imageInput.value = ''; });
  }
  rich.addEventListener('click', event => { const image = event.target.closest('img'); if (!image || !rich.contains(image)) return; selectedImage = image; if (media) media.selectImage(image, rich, () => { syncMarkdown(); renderPreview(); }); else { rich.querySelectorAll('img.is-selected').forEach(item => item.classList.remove('is-selected')); image.classList.add('is-selected'); } });
  rich.addEventListener('paste', event => { if (media) media.handlePaste(event, {onImage: insertImage, onText: text => document.execCommand('insertText', false, text)}); else { event.preventDefault(); document.execCommand('insertText', false, event.clipboardData.getData('text/plain')); } });
  form.addEventListener('submit', event => { syncMarkdown(); if (!markdown.value.trim()) { event.preventDefault(); error.hidden = false; (mode === 'rich' ? rich : markdown).focus(); } });
  cacheMarkdownRange();
  setMode('rich');
  window.setTimeout(() => {
    if (mode === 'rich' && markdown.value.trim()) { rich.innerHTML = window.BmcMarkdown.render(markdown.value); if (media) media.normalizeRenderedImages(rich); }
  }, 0);
})();
