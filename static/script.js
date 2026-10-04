/**
 * EditMedia Pro - Telegram Mini App Engine
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Telegram WebApp SDK
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor("#1E1E1E");
    tg.setBackgroundColor("#121212");

    // Load User Profile Data
    const user = tg.initDataUnsafe?.user;
    if (user) {
      document.getElementById("user-name").textContent = user.first_name || "Creator";
      if (user.photo_url) {
        document.getElementById("user-avatar").innerHTML = `<img src="${user.photo_url}" style="width:100%;height:100%;border-radius:50%;" />`;
      }
    }
  }

  // Application State
  const state = {
    file: null,
    previewUrl: null,
    naturalWidth: 0,
    naturalHeight: 0,
    activeTool: "select",
    aspectRatio: 1
  };

  // DOM Elements Cache
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const btnBrowse = document.getElementById("btn-browse");
  const dropzonePrompt = document.getElementById("dropzone-prompt");
  const previewWrapper = document.getElementById("preview-wrapper");
  const previewImage = document.getElementById("preview-image");
  const fileInfobar = document.getElementById("file-infobar");
  const btnRemoveFile = document.getElementById("btn-remove-file");

  const loaderOverlay = document.getElementById("loader-overlay");
  const loaderText = document.getElementById("loader-text");
  const outputDrawer = document.getElementById("output-drawer");
  const outputTitle = document.getElementById("output-title");
  const outputDesc = document.getElementById("output-desc");
  const btnResultLink = document.getElementById("btn-result-link");
  const btnCopyLink = document.getElementById("btn-copy-link");
  const btnDownload = document.getElementById("btn-download");

  // Inputs
  const resizeW = document.getElementById("resize-w");
  const resizeH = document.getElementById("resize-h");
  const resizeAspect = document.getElementById("resize-aspect");
  const compressQuality = document.getElementById("compress-quality");
  const qualityVal = document.getElementById("quality-val");
  const convertFormat = document.getElementById("convert-format");

  // Tool buttons & Panels
  const toolBtns = document.querySelectorAll(".ps-tool-btn");
  const panels = {
    select: document.getElementById("opt-select"),
    cloud: document.getElementById("opt-cloud"),
    resize: document.getElementById("opt-resize"),
    compress: document.getElementById("opt-compress"),
    convert: document.getElementById("opt-convert"),
    pdf: document.getElementById("opt-pdf")
  };

  // 2. Drag & Drop and File Selection Handlers
  btnBrowse.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) handleFile(e.target.files[0]);
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  });

  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
  });

  btnRemoveFile.addEventListener("click", resetCanvas);

  function handleFile(file) {
    if (!file.type.startsWith("image/")) {
      alertTelegram("Only images (PNG, JPG, WEBP) are supported!");
      return;
    }

    state.file = file;
    state.previewUrl = URL.createObjectURL(file);

    const img = new Image();
    img.onload = () => {
      state.naturalWidth = img.naturalWidth;
      state.naturalHeight = img.naturalHeight;
      state.aspectRatio = img.naturalWidth / img.naturalHeight;

      // Update Form Defaults
      resizeW.value = img.naturalWidth;
      resizeH.value = img.naturalHeight;

      // Update Infobar
      document.getElementById("info-name").innerHTML = `<i class="fa-regular fa-image"></i> ${file.name}`;
      document.getElementById("info-res").textContent = `${img.naturalWidth}x${img.naturalHeight} px`;
      document.getElementById("info-size").textContent = formatBytes(file.size);

      // Render Stage Preview
      previewImage.src = state.previewUrl;
      dropzonePrompt.style.display = "none";
      previewWrapper.style.display = "flex";
      fileInfobar.style.display = "flex";

      // Haptic feedback on Telegram
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    };
    img.src = state.previewUrl;
  }

  function resetCanvas() {
    state.file = null;
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = null;
    fileInput.value = "";

    dropzonePrompt.style.display = "flex";
    previewWrapper.style.display = "none";
    fileInfobar.style.display = "none";
    outputDrawer.style.display = "none";
  }

  // 3. Toolbar Switching Logic
  toolBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tool = btn.dataset.tool;
      toolBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // Switch panels
      Object.keys(panels).forEach((k) => (panels[k].style.display = "none"));
      if (panels[tool]) panels[tool].style.display = "block";
      document.getElementById("panel-title").textContent = `${tool.toUpperCase()} OPTIONS`;

      state.activeTool = tool;
      if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
    });
  });

  // 4. Panel Input Synchronizers
  resizeW.addEventListener("input", () => {
    if (resizeAspect.checked && state.aspectRatio) {
      resizeH.value = Math.round(resizeW.value / state.aspectRatio);
    }
  });

  resizeH.addEventListener("input", () => {
    if (resizeAspect.checked && state.aspectRatio) {
      resizeW.value = Math.round(resizeH.value * state.aspectRatio);
    }
  });

  document.querySelectorAll("[data-res]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const [w, h] = btn.dataset.res.split("x");
      resizeW.value = w;
      resizeH.value = h;
    });
  });

  compressQuality.addEventListener("input", (e) => {
    qualityVal.textContent = `${e.target.value}%`;
  });

  document.querySelectorAll("[data-qual]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.qual;
      compressQuality.value = q;
      qualityVal.textContent = `${q}%`;
    });
  });

  // 5. API Execution Handlers
  document.getElementById("btn-exec-cloud").addEventListener("click", () => {
    executeTask("/api/upload", new FormData(), "Uploading to ImgBB CDN...");
  });

  document.getElementById("btn-exec-resize").addEventListener("click", () => {
    const formData = new FormData();
    formData.append("width", resizeW.value);
    formData.append("height", resizeH.value);
    executeTask("/api/resize", formData, "Resizing image layers...");
  });

  document.getElementById("btn-exec-compress").addEventListener("click", () => {
    const formData = new FormData();
    formData.append("quality", compressQuality.value);
    executeTask("/api/compress", formData, "Compressing file footprint...");
  });

  document.getElementById("btn-exec-convert").addEventListener("click", () => {
    const formData = new FormData();
    formData.append("format", convertFormat.value);
    executeTask("/api/convert", formData, `Converting format to ${convertFormat.value.toUpperCase()}...`);
  });

  document.getElementById("btn-exec-pdf").addEventListener("click", () => {
    executeTask("/api/pdf", new FormData(), "Compiling active layer into PDF...");
  });

  // Unified Request Dispatcher
  async function executeTask(endpoint, formData, spinnerText) {
    if (!state.file) {
      alertTelegram("Please import an image into the canvas first!");
      return;
    }

    formData.append("file", state.file);
    if (tg?.initData) {
      formData.append("initData", tg.initData);
    }

    showLoader(true, spinnerText);
    outputDrawer.style.display = "none";

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        body: formData
      });

      const contentType = response.headers.get("content-type") || "";
      if (!response.ok) {
        const errorData = contentType.includes("application/json") ? await response.json() : {};
        throw new Error(errorData.error || `Server responded with ${response.status}`);
      }

      // Check if response is JSON (like Cloud upload) or Binary Blob (image/pdf file)
      if (contentType.includes("application/json")) {
        const result = await response.json();
        showResultNotification("Upload Succeeded!", "Public link generated successfully.", {
          url: result.url || result.link
        });
      } else {
        const blob = await response.blob();
        const outputUrl = URL.createObjectURL(blob);
        const disposition = response.headers.get("content-disposition");
        let filename = "processed-asset";
        
        if (disposition && disposition.includes("filename=")) {
          filename = disposition.split("filename=")[1].replace(/["']/g, "");
        } else {
          filename = endpoint.includes("pdf") ? "document.pdf" : `edited.${convertFormat.value || "png"}`;
        }

        showResultNotification("Operation Succeeded!", "Your processed file is ready for download.", {
          downloadUrl: outputUrl,
          downloadName: filename
        });
      }

      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } catch (err) {
      console.error(err);
      alertTelegram(`Error: ${err.message}`);
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("error");
    } finally {
      showLoader(false);
    }
  }

  // 6. UI Helpers
  function showLoader(show, text = "") {
    loaderText.textContent = text;
    loaderOverlay.style.display = show ? "flex" : "none";
  }

  function showResultNotification(title, desc, { url, downloadUrl, downloadName }) {
    outputTitle.textContent = title;
    outputDesc.textContent = desc;

    btnResultLink.style.display = "none";
    btnCopyLink.style.display = "none";
    btnDownload.style.display = "none";

    if (url) {
      btnResultLink.href = url;
      btnResultLink.style.display = "inline-flex";

      btnCopyLink.style.display = "inline-flex";
      btnCopyLink.onclick = () => {
        navigator.clipboard.writeText(url);
        alertTelegram("Public Link copied to clipboard!");
      };
    }

    if (downloadUrl) {
      btnDownload.href = downloadUrl;
      btnDownload.download = downloadName || "download";
      btnDownload.style.display = "inline-flex";
    }

    outputDrawer.style.display = "flex";
  }

  function alertTelegram(msg) {
    if (tg?.showAlert) {
      tg.showAlert(msg);
    } else {
      alert(msg);
    }
  }

  function formatBytes(bytes, decimals = 1) {
    if (!+bytes) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  }
});