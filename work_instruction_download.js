(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WorkInstructionDownload = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function safeBasename(value, fallback) {
    const basename = String(value || '').split(/[\\/]/).pop().replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();
    return basename && basename !== '.' && basename !== '..' ? basename : fallback;
  }

  function filenameFromContentDisposition(header, fallback) {
    if (!header) return fallback;
    const encoded = header.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i);
    if (encoded) {
      try { return safeBasename(decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, '')), fallback); }
      catch (_) { /* intenta filename tradicional */ }
    }
    const regular = header.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
    return regular ? safeBasename((regular[1] || regular[2]).trim(), fallback) : fallback;
  }

  async function responseError(response) {
    let detail = '';
    try {
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('json')) detail = (await response.json()).detail || '';
      else detail = await response.text();
    } catch (_) {}
    const error = new Error(detail || `No se pudo generar el Excel (HTTP ${response.status}).`);
    error.status = response.status;
    return error;
  }

  async function downloadXlsxResponse(response, fallbackFilename, environment) {
    if (!response.ok) throw await responseError(response);
    const blob = await response.blob();
    const filename = filenameFromContentDisposition(response.headers.get('content-disposition'), fallbackFilename);
    const objectUrl = environment.URL.createObjectURL(blob);
    try {
      const link = environment.document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      link.style.display = 'none';
      environment.document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      environment.URL.revokeObjectURL(objectUrl);
    }
    return { filename, size: blob.size };
  }

  function getBrowserDependencies(browserWindow) {
    return {
      // Los wrappers conservan el receptor nativo; nunca exponen métodos sueltos de Window/URL.
      fetchImpl: (...args) => browserWindow.fetch(...args),
      environment: {
        URL: {
          createObjectURL: blob => browserWindow.URL.createObjectURL(blob),
          revokeObjectURL: url => browserWindow.URL.revokeObjectURL(url),
        },
        document: browserWindow.document,
      },
    };
  }

  async function exportXlsxFromUi(options) {
    const originalText = options.button.textContent;
    options.button.disabled = true;
    options.button.textContent = 'Generando Excel...';
    options.renderMessage('info', 'Generando Excel...');
    try {
      const response = await options.fetchImpl(options.url, { method: 'GET' });
      const result = await downloadXlsxResponse(response, options.fallbackFilename, options.environment);
      options.renderMessage('ok', `Descarga iniciada: ${result.filename}`);
      return { ok: true, ...result };
    } catch (error) {
      options.renderMessage(error.status === 503 ? 'info' : 'err', error.message);
      return { ok: false, error };
    } finally {
      options.button.disabled = false;
      options.button.textContent = originalText;
    }
  }

  return { filenameFromContentDisposition, downloadXlsxResponse, exportXlsxFromUi, getBrowserDependencies };
});
