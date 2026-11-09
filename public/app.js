(() => {
  const form = document.getElementById("download-form");
  const input = document.getElementById("sfile-url");
  const clearButton = document.querySelector(".clear-url-button");
  const submitButton = document.querySelector(".submit-button");
  const inputError = document.getElementById("url-error");
  const startError = document.getElementById("start-error");
  const jobPanel = document.getElementById("job-panel");

  let active = false;
  let phase = "resolve"; // "resolve" = server mencari link, "download" = file sedang diterima
  let startedAt = null;
  let timerId = null;
  let job = null;
  let downloadedFile = null;
  let downloadError = "";
  let copyFeedback = "";

  const icons = {
    arrowDown: '<path d="M12 17V3"></path><path d="m6 11 6 6 6-6"></path><path d="M19 21H5"></path>',
    check: '<path d="m20 6-11 11-5-5"></path>',
    alert: '<circle cx="12" cy="12" r="10"></circle><path d="M12 8v4"></path><path d="M12 16h.01"></path>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>',
    external: '<path d="M15 3h6v6"></path><path d="M10 14 21 3"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>',
    loader: '<path d="M12 2v4"></path><path d="m16.2 7.8 2.9-2.9"></path><path d="M18 12h4"></path><path d="m16.2 16.2 2.9 2.9"></path><path d="M12 18v4"></path><path d="m4.9 19.1 2.9-2.9"></path><path d="M2 12h4"></path><path d="m4.9 4.9 2.9 2.9"></path>',
  };

  function icon(name, size = 15, className = "") {
    const paths = name === "x"
      ? '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>'
      : icons[name] || "";
    return `<svg${className ? ` class="${className}"` : ""} width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function getManualUrl(currentJob) {
    if (!["blocked", "success"].includes(currentJob?.status) || !currentJob.manualUrl) return null;
    try {
      const url = new URL(currentJob.manualUrl);
      const allowedHosts = [
        "safefileku.com", 
        "mediafire.com", 
        "drive.google.com", 
        "sfile.co"
      ];
      const isAllowed = allowedHosts.some(host => 
        url.hostname === host || url.hostname.endsWith("." + host)
      );
      if (url.protocol !== "https:" || !isAllowed) {
        return null;
      }
      return url.href;
    } catch {
      return null;
    }
  }

  function formatSize(size) {
    if (size === null || !Number.isFinite(size)) return "Ukuran tidak tersedia";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function renderJobPanel() {
    if (!job || active) {
      jobPanel.hidden = true;
      jobPanel.replaceChildren();
      return;
    }

    jobPanel.hidden = false;
    const manualUrl = getManualUrl(job);
    if (job.status === "completed") {
      jobPanel.innerHTML = `
        <div class="result-card success-result" data-testid="summary-downloaded-file">
          <div class="result-eyebrow">FILE HASIL</div>
          <div class="result-copy">
            <strong data-testid="text-file-name">${escapeHtml(job.fileName || "File siap")}</strong>
            <span data-testid="text-file-size">${escapeHtml(formatSize(job.fileSize))}</span>
          </div>
          <button class="download-button" data-save-file type="button" data-testid="button-save-file" ${downloadedFile ? "" : "disabled"}>
            ${icon("arrowDown", 14)}
            Simpan
          </button>
          ${downloadError ? `<p class="download-error" role="alert" data-testid="text-download-error">${escapeHtml(downloadError)}</p>` : ""}
        </div>`;
      return;
    }

    if (manualUrl) {
      jobPanel.innerHTML = `
        <div class="result-card manual-result" data-testid="text-terminal-guidance">
          <div class="result-eyebrow">SUKSES</div>
          <code class="manual-url">${escapeHtml(manualUrl)}</code>
          <div class="result-actions">
            <button class="result-action" data-copy-url type="button">
              ${icon(copyFeedback === "URL disalin" ? "check" : "copy", 15)}
              ${copyFeedback === "URL disalin" ? "COPIED" : "COPY"}
            </button>
            <a class="result-action" data-testid="button-manual-safefileku" href="${escapeHtml(manualUrl)}" target="_blank" rel="noopener noreferrer">
              OPEN ${icon("external", 14)}
            </a>
          </div>
          ${copyFeedback && copyFeedback !== "URL disalin" ? `<p class="copy-feedback" role="alert">${escapeHtml(copyFeedback)}</p>` : ""}
        </div>`;
      return;
    }

    const message = job.error || (job.status === "cancelled" ? "Dibatalkan." : "Tautan tidak dapat diproses.");
    jobPanel.innerHTML = `
      <div class="result-card error-result" data-testid="text-terminal-guidance">
        ${icon("alert", 17)}
        <span>${escapeHtml(message)}</span>
      </div>`;
  }

  function render() {
    clearButton.hidden = !input.value;
    submitButton.disabled = active;
    submitButton.setAttribute("aria-busy", String(active));
    if (active) {
      const elapsed = startedAt === null ? 1 : Math.floor((Date.now() - startedAt) / 1000) + 1;
      submitButton.innerHTML = `${icon("loader", 14, "spin-icon")}<span>${phase === "download" ? "Mengunduh" : "Memproses"}</span><span class="button-timer" data-testid="text-elapsed-time" aria-live="off">${elapsed}s</span>`;
    } else {
      submitButton.innerHTML = "<span>Bypass</span>";
    }

    inputError.hidden = !inputError.textContent;
    input.setAttribute("aria-describedby", inputError.hidden ? "" : "url-error");
    startError.hidden = !startError.textContent;
    if (!startError.hidden) {
      startError.innerHTML = `${icon("alert", 15)}<span>${escapeHtml(startError.textContent)}</span>`;
    }
    renderJobPanel();
  }

  function validateUrl(value) {
    let parsed;
    try {
      parsed = new URL(value);
    } catch {
      return "Masukkan tautan lengkap, termasuk https://";
    }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return "Tautan harus menggunakan http:// atau https://";
    }
    if (value.length > 2048) {
      return "Tautan ini melebihi batas 2.048 karakter.";
    }
    return "";
  }

  async function submit(event) {
    event.preventDefault();
    inputError.textContent = "";
    startError.textContent = "";
    if (active) return;

    const url = input.value.trim();
    const invalid = validateUrl(url);
    if (invalid) {
      inputError.textContent = invalid;
      render();
      return;
    }

    job = null;
    downloadedFile = null;
    downloadError = "";
    copyFeedback = "";
    active = true;
    phase = "resolve";
    startedAt = Date.now();
    render();
    timerId = window.setInterval(render, 1000);

    try {
      const response = await fetch("/api/downloads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        cache: "no-store",
      });
      phase = "download"; // header sudah diterima = pencarian link selesai
      render();
      const contentType = response.headers.get("Content-Type") || "";
      if (contentType.includes("application/json")) {
        const body = await response.json();
        if (!response.ok) {
          throw new Error(body?.error || "Permintaan tidak dapat diproses. Silakan coba lagi.");
        }
        job = {
          status: body.status || (body.manualUrl ? "blocked" : "failed"),
          manualUrl: body.manualUrl || null,
          error: body.error || null,
        };
      } else {
        if (!response.ok) {
          let message = "Permintaan tidak dapat diproses. Silakan coba lagi.";
          try {
            const body = await response.json();
            message = body?.error || message;
          } catch {}
          throw new Error(message);
        }
        downloadedFile = await response.blob();
        const encodedName = response.headers.get("X-File-Name") || "unduhan";
        let fileName = "unduhan";
        try {
          fileName = decodeURIComponent(encodedName);
        } catch {
          fileName = encodedName;
        }
        const rawSize = Number(response.headers.get("X-File-Size"));
        const fileSize = Number.isFinite(rawSize) && rawSize > 0 ? rawSize : downloadedFile.size;
        job = { status: "completed", fileName, fileSize };
      }
    } catch (error) {
      job = null;
      startError.textContent = error instanceof Error
        ? error.message
        : "Permintaan tidak dapat dimulai. Silakan coba lagi.";
    } finally {
      active = false;
      phase = "resolve";
      startedAt = null;
      if (timerId) window.clearInterval(timerId);
      timerId = null;
      render();
    }
  }

  form.addEventListener("submit", submit);
  input.addEventListener("input", () => {
    inputError.textContent = "";
    render();
  });
  clearButton.addEventListener("click", () => {
    input.value = "";
    inputError.textContent = "";
    render();
    input.focus();
  });

  jobPanel.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;

    if (target.hasAttribute("data-save-file")) {
      downloadError = "";
      if (!downloadedFile) {
        downloadError = "File tidak tersedia. Silakan mulai unduhan lagi.";
        renderJobPanel();
        return;
      }
      const objectUrl = URL.createObjectURL(downloadedFile);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = job?.fileName || "unduhan";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } else if (target.hasAttribute("data-copy-url")) {
      const manualUrl = getManualUrl(job);
      if (!manualUrl) return;
      try {
        await navigator.clipboard.writeText(manualUrl);
        copyFeedback = "URL disalin";
      } catch {
        copyFeedback = "URL tidak dapat disalin.";
      }
      renderJobPanel();
    }
  });

  render();
})();