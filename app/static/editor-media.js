/* Shared, dependency-free media helpers for the case and tool Markdown editors. */
window.BmcEditorMedia = (() => {
  const allowedType = /^image\/(?:png|jpeg|gif|webp)$/i;
  const allowedSource = /^(?:https?:\/\/[^\s)]+|data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+)$/;
  const maxBytes = 2 * 1024 * 1024;
  const minWidth = 40;

  const source = value => allowedSource.test(String(value || '')) ? String(value) : '';
  const width = value => {
    const candidate = String(value || '').trim().toLowerCase();
    if (/^(?:25|50|75|100)%$/.test(candidate)) return candidate;
    if (/^(?:[1-9]\d{0,5})px$/.test(candidate)) return candidate;
    return '';
  };
  const numeric = value => {
    const match = String(value || '').trim().match(/^([0-9]+(?:\.[0-9]+)?)(%|px)$/i);
    return match ? {value: Number(match[1]), unit: match[2].toLowerCase()} : null;
  };
  const naturalWidth = image => {
    if (!image) return 0;
    const intrinsic = Number(image.naturalWidth || 0);
    if (intrinsic > 0) return intrinsic;
    const recorded = Number.parseFloat(String(image.dataset?.naturalWidth || ''));
    if (recorded > 0) return recorded;
    const rendered = Number(image.getBoundingClientRect?.().width || 0);
    return rendered > 0 ? rendered : 0;
  };
  const imageWidth = image => width(image?.dataset?.imageWidth || '');
  const clampPixels = (image, value) => {
    const requested = Math.max(minWidth, Math.round(Number(value) || 0));
    const natural = naturalWidth(image);
    const editor = image?.closest?.('[contenteditable="true"]');
    const available = Number(editor?.clientWidth || 0);
    const maximum = natural > 0 ? natural : available;
    return maximum > 0 ? Math.min(maximum, Math.max(minWidth, requested)) : requested;
  };
  const setPixelWidth = (image, value) => {
    if (!image) return '';
    const px = `${clampPixels(image, value)}px`;
    image.style.width = px;
    image.dataset.imageWidth = px;
    image.style.maxWidth = '100%';
    image.style.height = 'auto';
    return px;
  };
  const applyWhenLoaded = (image, callback) => {
    if (!image || typeof callback !== 'function') return;
    if (Number(image.naturalWidth || 0) > 0) { callback(); return; }
    if (image.dataset.imageResizePending === '1') return;
    image.dataset.imageResizePending = '1';
    image.addEventListener('load', () => {
      delete image.dataset.imageResizePending;
      callback();
    }, {once: true});
  };
  const setImageWidth = (image, value) => {
    if (!image) return '';
    const next = width(value);
    // “原始” means intrinsic size. max-width only prevents overflow in a
    // narrow editor; it never makes a small image fill the editor.
    if (!next || next === '100%') {
      image.style.removeProperty('width');
      delete image.dataset.imageWidth;
      image.style.maxWidth = '100%';
      image.style.height = 'auto';
      return '';
    }
    const parsed = numeric(next);
    const apply = () => {
      const base = naturalWidth(image);
      const desired = parsed?.unit === '%' ? base * parsed.value / 100 : parsed?.value;
      if (desired > 0) setPixelWidth(image, desired);
    };
    if (naturalWidth(image) <= 0) applyWhenLoaded(image, apply);
    else apply();
    return next;
  };
  const normalizeRenderedImages = root => {
    const images = Array.from(root?.querySelectorAll?.('img[data-image-width]') || []);
    images.forEach(image => {
      const configured = width(image.dataset.imageWidth);
      if (!configured || configured === '100%') {
        image.style.removeProperty('width');
        delete image.dataset.imageWidth;
        return;
      }
      setImageWidth(image, configured);
    });
  };
  const ensureImageShell = image => {
    if (!image || !image.parentNode) return null;
    const existing = image.closest?.('[data-editor-image-shell]');
    if (existing) return existing;
    const shell = document.createElement('span');
    shell.className = 'editor-image-shell';
    shell.dataset.editorImageShell = '1';
    shell.contentEditable = 'false';
    image.parentNode.insertBefore(shell, image);
    shell.appendChild(image);
    const handle = document.createElement('span');
    handle.className = 'editor-image-resize-handle';
    handle.dataset.editorResizeHandle = '1';
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-label', '拖动调整图片宽度');
    handle.title = '拖动调整图片宽度';
    shell.appendChild(handle);
    return shell;
  };
  const selectImage = (image, editor, onChange) => {
    if (!image || !editor) return null;
    const shell = ensureImageShell(image);
    if (!shell) return null;
    editor.querySelectorAll('[data-editor-image-shell].is-selected, img.is-selected').forEach(item => item.classList.remove('is-selected'));
    shell.classList.add('is-selected');
    image.classList.add('is-selected');
    const handle = shell.querySelector('[data-editor-resize-handle]');
    if (handle && handle.dataset.resizeBound !== '1') {
      handle.dataset.resizeBound = '1';
      handle.addEventListener('pointerdown', event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = image.getBoundingClientRect().width || naturalWidth(image);
        const ownerDocument = editor.ownerDocument || document;
        const move = moveEvent => {
          const next = Math.max(minWidth, startWidth + moveEvent.clientX - startX);
          setPixelWidth(image, next);
          if (typeof onChange === 'function') onChange(image);
        };
        const end = () => {
          ownerDocument.removeEventListener('pointermove', move);
          ownerDocument.removeEventListener('pointerup', end);
          ownerDocument.removeEventListener('pointercancel', end);
          shell.classList.remove('is-resizing');
        };
        shell.classList.add('is-resizing');
        ownerDocument.addEventListener('pointermove', move);
        ownerDocument.addEventListener('pointerup', end, {once: true});
        ownerDocument.addEventListener('pointercancel', end, {once: true});
      });
    }
    return shell;
  };
  const imageMarkdown = (alt, src, image) => {
    const cleanAlt = String(alt || '图片').replace(/[\]\r\n]/g, '').slice(0, 80) || '图片';
    const safeSource = source(src);
    if (!safeSource) return '';
    const size = imageWidth(image);
    return `![${cleanAlt}](${safeSource})${size && size !== '100%' ? `{width=${size}}` : ''}`;
  };
  const readImage = (file) => new Promise((resolve, reject) => {
    if (!file || !allowedType.test(file.type || '')) return reject(new Error('仅支持 PNG、JPG、GIF 或 WebP 图片。'));
    if (file.size > maxBytes) return reject(new Error('图片不能超过 2 MB，请压缩后再插入。'));
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('图片读取失败，请重试。'));
    reader.readAsDataURL(file);
  });
  const clipboardImage = event => {
    const items = Array.from(event?.clipboardData?.items || []);
    const item = items.find(candidate => candidate.kind === 'file' && allowedType.test(candidate.type || ''));
    return item ? item.getAsFile() : null;
  };
  const handlePaste = (event, {onImage, onText} = {}) => {
    const file = clipboardImage(event);
    if (file && typeof onImage === 'function') {
      event.preventDefault();
      onImage(file);
      return true;
    }
    if (typeof onText === 'function') {
      event.preventDefault();
      onText(String(event.clipboardData?.getData('text/plain') || ''));
      return true;
    }
    return false;
  };
  return {source, width, imageWidth, setImageWidth, setPixelWidth, naturalWidth, normalizeRenderedImages, selectImage, ensureImageShell, imageMarkdown, readImage, clipboardImage, handlePaste, maxBytes};
})();
