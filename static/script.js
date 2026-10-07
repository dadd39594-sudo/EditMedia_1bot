/**
 * ===================================================================
 * EDITMEDIA PRO - TELEGRAM WEBAPP JAVASCRIPT ENGINE
 * ===================================================================
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Telegram WebApp SDK
  const tg = window.Telegram?.WebApp;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      tg.setHeaderColor("#151821");
      tg.setBackgroundColor("#0c0d12");
    } catch (e) {
      console.warn("Telegram WebApp initialization notice:", e);
    }
  }

  // Application Global State
  const appState = {
    user: {
      name: "Guest Creator",
      username: "@creator",
      id: "777888999",
      credits: null, // Starts as null / "..." until fetched from /api/get_user
      referrals: 0
    },
    cloudFile: null,
    editFile: null,
    pdfFile: null,
    editNaturalWidth: 0,
    editNaturalHeight: 0,
    editAspectRatio: 1,
    activeEditSubtab: "compress"
  };

  // ===================================================================
  // SECTION A: TELEGRAM USER INITIALIZATION & DATA BINDING
  // ===================================================================
  function initUserData() {
    const tgUser = tg?.initDataUnsafe?.user;
    if (tgUser) {
      appState.user.name = tgUser.first_name + (tgUser.last_name ? " " + tgUser.last_name : "");
      appState.user.username = tgUser.username ? `@${tgUser.username}` : "@user";
      appState.user.id = String(tgUser.id);
    }

    // Populate initial text in DOM
    const firstName = appState.user.name.split(" ")[0] || "Creator";
    const welcomeEl = document.getElementById("welcome-user-name");
    if (welcomeEl) welcomeEl.textContent = firstName;

    const fullNameEl = document.getElementById("user-full-name");
    if (fullNameEl) fullNameEl.textContent = appState.user.name;

    const usernameEl = document.getElementById("user-username");
    if (usernameEl) usernameEl.textContent = appState.user.username;

    const tgIdEl = document.getElementById("user-telegram-id");
    if (tgIdEl) tgIdEl.textContent = appState.user.id;

    if (tgUser?.photo_url) {
      const avatarWrap = document.getElementById("user-avatar-wrap");
      if (avatarWrap) {
        avatarWrap.innerHTML = `<img src="${tgUser.photo_url}" alt="Avatar" />`;
      }
    }

    // Fetch live user credits from backend Firebase collection
    fetchUserCredits();
  }

  /**
   * Fetches real user credit balance and referrals from /api/get_user
   */
  async function fetchUserCredits() {
    try {
      const response = await fetch(`/api/get_user?user_id=${encodeURIComponent(appState.user.id)}`);
      if (response.ok) {
        const data = await response.json();
        appState.user.credits = typeof data.credits === "number" ? data.credits : 10;
        appState.user.referrals = typeof data.referrals === "number" ? data.referrals : 0;
        updateCreditsDOM();
      } else {
        if (appState.user.credits === null) {
          appState.user.credits = 10;
          updateCreditsDOM();
        }
      }
    } catch (err) {
      console.warn("Unable to fetch live credits from server:", err);
      if (appState.user.credits === null) {
        appState.user.credits = 10;
        updateCreditsDOM();
      }
    }
  }

  function updateCreditsDOM() {
    const displayVal = appState.user.credits !== null ? appState.user.credits : "...";
    const navCredit = document.getElementById("nav-credit-count");
    if (navCredit) navCredit.textContent = displayVal;

    const cardCredit = document.getElementById("card-credit-count");
    if (cardCredit) cardCredit.textContent = displayVal;

    const cardRef = document.getElementById("card-referral-count");
    if (cardRef) cardRef.textContent = appState.user.referrals;
  }

  function deductLocalCredit() {
    if (typeof appState.user.credits === "number" && appState.user.credits > 0) {
      appState.user.credits -= 1;
      updateCreditsDOM();
    }
  }

  initUserData();

  // ===================================================================
  // SECTION B: FORCE JOIN MEMBERSHIP VERIFICATION
  // ===================================================================
  const fjModal = document.getElementById("force-join-modal");
  const fjContainer = document.getElementById("fj-channels-container");
  const fjStatus = document.getElementById("fj-status");
  const currentUserId = tg?.initDataUnsafe?.user?.id;

  let pollInterval = null;
  let isChecking = false;
  let isVerified = false;

  async function checkMembership() {
    if (isChecking || isVerified || !currentUserId) return;
    isChecking = true;

    try {
      const response = await fetch("/api/check_membership", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: currentUserId })
      });

      const data = await response.json();
      const unjoined = data.channels || data.unjoined || [];

      if (unjoined.length === 0) {
        isVerified = true;
        if (pollInterval) clearInterval(pollInterval);

        if (fjStatus) {
          fjStatus.innerHTML = `<span>✅ Access Granted!</span>`;
          fjStatus.classList.add("success");
        }
        if (fjContainer) fjContainer.innerHTML = "";

        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");

        setTimeout(() => {
          if (fjModal) {
            fjModal.classList.add("fade-out");
            setTimeout(() => {
              fjModal.style.display = "none";
            }, 400);
          }
        }, 800);
      } else {
        if (fjModal) fjModal.style.display = "flex";
        if (fjStatus) {
          fjStatus.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Checking membership...</span>`;
          fjStatus.classList.remove("success");
        }

        const unjoinedIds = new Set(unjoined.map((ch) => ch.id));

        if (fjContainer) {
          fjContainer.querySelectorAll(".fj-btn").forEach((btn) => {
            if (!unjoinedIds.has(btn.dataset.channelId)) {
              btn.remove();
            }
          });

          unjoined.forEach((ch) => {
            if (!fjContainer.querySelector(`[data-channel-id="${ch.id}"]`)) {
              const btn = document.createElement("a");
              btn.href = ch.url;
              btn.className = "fj-btn";
              btn.dataset.channelId = ch.id;
              btn.innerHTML = `<i class="fa-brands fa-telegram"></i> Join ${ch.name}`;

              btn.addEventListener("click", (e) => {
                e.preventDefault();
                if (tg?.openTelegramLink) {
                  tg.openTelegramLink(ch.url);
                } else {
                  window.open(ch.url, "_blank");
                }
              });
              fjContainer.appendChild(btn);
            }
          });
        }
      }
    } catch (err) {
      console.warn("Force join verification error:", err);
    } finally {
      isChecking = false;
    }
  }

  if (currentUserId) {
    checkMembership();
    window.addEventListener("focus", checkMembership);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") checkMembership();
    });
    pollInterval = setInterval(checkMembership, 3500);
  }

  // ===================================================================
  // SECTION C: BOTTOM NAVIGATION SWITCHER
  // ===================================================================
  const navTabs = document.querySelectorAll(".nav-tab-item");
  const pages = {
    home: document.getElementById("page-home"),
    cloud: document.getElementById("page-cloud"),
    edit: document.getElementById("page-edit"),
    pdf: document.getElementById("page-pdf")
  };

  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetPage = tab.dataset.tab;
      navTabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      Object.keys(pages).forEach((k) => {
        if (pages[k]) pages[k].classList.remove("active");
      });
      if (pages[targetPage]) {
        pages[targetPage].classList.add("active");
        const viewport = document.querySelector(".pages-viewport");
        if (viewport) viewport.scrollTop = 0;
      }

      if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
    });
  });

  // ===================================================================
  // SECTION D: HOME PAGE - IMAGE METADATA INSPECTOR (CLIENT-SIDE ONLY)
  // ===================================================================
  const inspectorDropzone = document.getElementById("inspector-dropzone");
  const inspectorFileInput = document.getElementById("inspector-file-input");
  const inspectorDropPrompt = document.getElementById("inspector-drop-prompt");
  const inspectorResultView = document.getElementById("inspector-result-view");
  const inspectorPreviewImg = document.getElementById("inspector-preview-img");
  const btnClearInspector = document.getElementById("btn-clear-inspector");

  const metaName = document.getElementById("meta-name");
  const metaSize = document.getElementById("meta-size");
  const metaDims = document.getElementById("meta-dims");
  const metaFormat = document.getElementById("meta-format");
  const metaAspect = document.getElementById("meta-aspect");

  if (inspectorDropzone && inspectorFileInput) {
    inspectorDropzone.addEventListener("click", () => {
      if (inspectorResultView.style.display === "none") {
        inspectorFileInput.click();
      }
    });

    inspectorFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        inspectImage(e.target.files[0]);
      }
    });
  }

  function inspectImage(file) {
    if (!file.type.startsWith("image/")) {
      showTgAlert("Please select a valid image file!");
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    const img = new Image();

    img.onload = () => {
      metaName.textContent = file.name;
      metaSize.textContent = formatBytes(file.size);
      metaDims.textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;

      let formatExt = "IMG";
      if (file.type && file.type.includes("/")) {
        formatExt = file.type.split("/")[1].toUpperCase();
      } else {
        const ext = file.name.split(".").pop();
        if (ext) formatExt = ext.toUpperCase();
      }
      metaFormat.textContent = formatExt;

      const gcdVal = gcd(img.naturalWidth, img.naturalHeight);
      const aspectW = Math.round(img.naturalWidth / gcdVal);
      const aspectH = Math.round(img.naturalHeight / gcdVal);
      const ratioFloat = (img.naturalWidth / img.naturalHeight).toFixed(2);
      metaAspect.textContent = `${aspectW}:${aspectH} (${ratioFloat})`;

      inspectorPreviewImg.src = objectUrl;
      inspectorDropPrompt.style.display = "none";
      inspectorResultView.style.display = "flex";
      btnClearInspector.style.display = "flex";

      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    };

    img.onerror = () => {
      showTgAlert("Could not read image dimensions.");
    };

    img.src = objectUrl;
  }

  if (btnClearInspector) {
    btnClearInspector.addEventListener("click", (e) => {
      e.stopPropagation();
      inspectorFileInput.value = "";
      inspectorPreviewImg.src = "";
      inspectorDropPrompt.style.display = "block";
      inspectorResultView.style.display = "none";
      btnClearInspector.style.display = "none";
    });
  }

  // ===================================================================
  // SECTION E: CLOUD PAGE (IMGHIPPO CDN - FREE UPLOAD)
  // ===================================================================
  const cloudUploadBox = document.getElementById("cloud-upload-box");
  const cloudFileInput = document.getElementById("cloud-file-input");
  const cloudPlaceholder = document.getElementById("cloud-placeholder");
  const cloudPreviewWrapper = document.getElementById("cloud-preview-wrapper");
  const cloudPreviewImg = document.getElementById("cloud-preview-img");
  const btnCloudRemove = document.getElementById("btn-cloud-remove");
  const btnGenerateLink = document.getElementById("btn-generate-link");
  const cloudResultContainer = document.getElementById("cloud-result-container");
  const cloudOutputUrl = document.getElementById("cloud-output-url");
  const btnCloudCopy = document.getElementById("btn-cloud-copy");
  const btnCloudOpen = document.getElementById("btn-cloud-open");

  if (cloudUploadBox && cloudFileInput) {
    cloudUploadBox.addEventListener("click", () => {
      if (!appState.cloudFile) cloudFileInput.click();
    });

    cloudFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        appState.cloudFile = e.target.files[0];
        cloudPreviewImg.src = URL.createObjectURL(appState.cloudFile);
        cloudPlaceholder.style.display = "none";
        cloudPreviewWrapper.style.display = "flex";
        cloudResultContainer.style.display = "none";
      }
    });
  }

  if (btnCloudRemove) {
    btnCloudRemove.addEventListener("click", (e) => {
      e.stopPropagation();
      appState.cloudFile = null;
      cloudFileInput.value = "";
      cloudPlaceholder.style.display = "flex";
      cloudPreviewWrapper.style.display = "none";
      cloudResultContainer.style.display = "none";
    });
  }

  if (btnGenerateLink) {
    btnGenerateLink.addEventListener("click", async () => {
      if (!appState.cloudFile) {
        showTgAlert("Please select an image first!");
        return;
      }

      const formData = new FormData();
      formData.append("file", appState.cloudFile);
      formData.append("user_id", appState.user.id);

      showLoader(true, "Uploading asset to ImgHippo CDN...");
      try {
        const response = await fetch("/api/upload", {
          method: "POST",
          body: formData
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "ImgHippo upload failed");
        }

        cloudOutputUrl.value = data.url;
        btnCloudOpen.href = data.url;
        cloudResultContainer.style.display = "flex";

        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      } catch (err) {
        showTgAlert(`Upload Error: ${err.message}`);
      } finally {
        showLoader(false);
      }
    });
  }

  if (btnCloudCopy) {
    btnCloudCopy.addEventListener("click", () => {
      if (cloudOutputUrl.value) {
        navigator.clipboard.writeText(cloudOutputUrl.value);
        btnCloudCopy.innerHTML = `<i class="fa-solid fa-check"></i> Copied!`;
        setTimeout(() => {
          btnCloudCopy.innerHTML = `<i class="fa-regular fa-copy"></i> Copy`;
        }, 1800);
        if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
      }
    });
  }

  // ===================================================================
  // SECTION F: EDIT STUDIO (RESIZE, COMPRESS, CONVERT)
  // ===================================================================
  const editUploadBox = document.getElementById("edit-upload-box");
  const editFileInput = document.getElementById("edit-file-input");
  const editPlaceholder = document.getElementById("edit-placeholder");
  const editPreviewWrapper = document.getElementById("edit-preview-wrapper");
  const editPreviewImg = document.getElementById("edit-preview-img");
  const btnEditRemove = document.getElementById("btn-edit-remove");
  const btnProcessImage = document.getElementById("btn-process-image");
  const editResultContainer = document.getElementById("edit-result-container");

  const subtabBtns = document.querySelectorAll(".subtab-btn");
  const subtabPanels = {
    compress: document.getElementById("panel-compress"),
    resize: document.getElementById("panel-resize"),
    convert: document.getElementById("panel-convert")
  };

  const compressSlider = document.getElementById("compress-quality-slider");
  const compressDisplay = document.getElementById("compress-val-display");
  const resizeW = document.getElementById("resize-input-w");
  const resizeH = document.getElementById("resize-input-h");
  const resizeLock = document.getElementById("resize-ratio-lock");

  const baBeforeSize = document.getElementById("ba-before-size");
  const baAfterSize = document.getElementById("ba-after-size");
  const baSavedBadge = document.getElementById("ba-saved-badge");
  const btnDownloadProcessed = document.getElementById("btn-download-processed");

  if (editUploadBox && editFileInput) {
    editUploadBox.addEventListener("click", () => {
      if (!appState.editFile) editFileInput.click();
    });

    editFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        const file = e.target.files[0];
        appState.editFile = file;

        const img = new Image();
        const objectUrl = URL.createObjectURL(file);
        img.onload = () => {
          appState.editNaturalWidth = img.naturalWidth;
          appState.editNaturalHeight = img.naturalHeight;
          appState.editAspectRatio = img.naturalWidth / img.naturalHeight;

          if (resizeW) resizeW.value = img.naturalWidth;
          if (resizeH) resizeH.value = img.naturalHeight;
        };
        img.src = objectUrl;

        editPreviewImg.src = objectUrl;
        editPlaceholder.style.display = "none";
        editPreviewWrapper.style.display = "flex";
        editResultContainer.style.display = "none";
      }
    });
  }

  if (btnEditRemove) {
    btnEditRemove.addEventListener("click", (e) => {
      e.stopPropagation();
      appState.editFile = null;
      editFileInput.value = "";
      editPlaceholder.style.display = "flex";
      editPreviewWrapper.style.display = "none";
      editResultContainer.style.display = "none";
    });
  }

  subtabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      subtabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      appState.activeEditSubtab = btn.dataset.subtab;

      Object.keys(subtabPanels).forEach((k) => {
        if (subtabPanels[k]) subtabPanels[k].classList.remove("active");
      });
      if (subtabPanels[appState.activeEditSubtab]) {
        subtabPanels[appState.activeEditSubtab].classList.add("active");
      }
      if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
    });
  });

  if (compressSlider && compressDisplay) {
    compressSlider.addEventListener("input", (e) => {
      compressDisplay.textContent = `${e.target.value}%`;
    });
  }

  document.querySelectorAll("[data-preset]").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll("[data-preset]").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      if (compressSlider) compressSlider.value = pill.dataset.preset;
      if (compressDisplay) compressDisplay.textContent = `${pill.dataset.preset}%`;
    });
  });

  if (resizeW && resizeH && resizeLock) {
    resizeW.addEventListener("input", () => {
      if (resizeLock.checked && appState.editAspectRatio) {
        resizeH.value = Math.round(resizeW.value / appState.editAspectRatio);
      }
    });

    resizeH.addEventListener("input", () => {
      if (resizeLock.checked && appState.editAspectRatio) {
        resizeW.value = Math.round(resizeH.value * appState.editAspectRatio);
      }
    });
  }

  document.querySelectorAll("[data-res]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const [w, h] = btn.dataset.res.split("x");
      if (resizeW) resizeW.value = w;
      if (resizeH) resizeH.value = h;
    });
  });

  if (btnProcessImage) {
    btnProcessImage.addEventListener("click", async () => {
      if (!appState.editFile) {
        showTgAlert("Please choose an image to edit first!");
        return;
      }

      if (typeof appState.user.credits === "number" && appState.user.credits < 1) {
        showTgAlert("⚠️ Insufficient Credits! You have 0 credits. Please refer friends using your bot link to earn +5 credits for free.");
        return;
      }

      const formData = new FormData();
      formData.append("file", appState.editFile);
      formData.append("user_id", appState.user.id);

      let endpoint = "/api/compress";
      let statusMsg = "Optimizing image bytes...";
      let targetExt = "jpg";

      if (appState.activeEditSubtab === "resize") {
        endpoint = "/api/resize";
        formData.append("width", resizeW.value || appState.editNaturalWidth);
        formData.append("height", resizeH.value || appState.editNaturalHeight);
        statusMsg = "Resizing image resolution...";
      } else if (appState.activeEditSubtab === "convert") {
        const selectedFormat = document.querySelector('input[name="target-format"]:checked')?.value || "jpeg";
        formData.append("format", selectedFormat);
        statusMsg = `Converting format to ${selectedFormat.toUpperCase()}...`;
        targetExt = selectedFormat === "jpeg" ? "jpg" : selectedFormat;
      } else {
        formData.append("quality", compressSlider ? compressSlider.value : 75);
      }

      showLoader(true, statusMsg);

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          body: formData
        });

        if (response.status === 403) {
          const errData = await response.json().catch(() => ({}));
          showTgAlert(`⚠️ Insufficient Credits! ${errData.error || "You do not have enough credits to perform this action. Refer friends to get free credits!"}`);
          return;
        }

        if (!response.ok) {
          const errJson = await response.json().catch(() => ({}));
          throw new Error(errJson.error || "Image processing failed");
        }

        const blob = await response.blob();
        const outputUrl = URL.createObjectURL(blob);

        deductLocalCredit();

        const origSize = appState.editFile.size;
        const processedSize = blob.size;

        baBeforeSize.textContent = formatBytes(origSize);
        baAfterSize.textContent = formatBytes(processedSize);

        const savedPercent = Math.round(((origSize - processedSize) / origSize) * 100);
        if (savedPercent > 0) {
          baSavedBadge.textContent = `Saved ${savedPercent}%`;
          baSavedBadge.style.color = "var(--accent-green)";
        } else if (savedPercent < 0) {
          baSavedBadge.textContent = `+${Math.abs(savedPercent)}% Size`;
          baSavedBadge.style.color = "var(--accent-cyan)";
        } else {
          baSavedBadge.textContent = `Optimized`;
          baSavedBadge.style.color = "var(--accent-cyan)";
        }

        btnDownloadProcessed.href = outputUrl;
        const cleanName = appState.editFile.name.substring(0, appState.editFile.name.lastIndexOf('.')) || "image";
        btnDownloadProcessed.download = `${cleanName}-edited.${targetExt}`;

        editResultContainer.style.display = "flex";
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      } catch (err) {
        showTgAlert(`Error: ${err.message}`);
      } finally {
        showLoader(false);
      }
    });
  }

  // ===================================================================
  // SECTION G: PDF CREATOR LOGIC
  // ===================================================================
  const pdfUploadBox = document.getElementById("pdf-upload-box");
  const pdfFileInput = document.getElementById("pdf-file-input");
  const pdfPlaceholder = document.getElementById("pdf-placeholder");
  const pdfPreviewWrapper = document.getElementById("pdf-preview-wrapper");
  const pdfPreviewImg = document.getElementById("pdf-preview-img");
  const btnPdfRemove = document.getElementById("btn-pdf-remove");
  const btnCreatePdf = document.getElementById("btn-create-pdf");
  const pdfResultContainer = document.getElementById("pdf-result-container");
  const pdfBeforeSize = document.getElementById("pdf-before-size");
  const pdfOutputSize = document.getElementById("pdf-output-size");
  const pdfOutputName = document.getElementById("pdf-output-name");
  const btnDownloadPdf = document.getElementById("btn-download-pdf");

  if (pdfUploadBox && pdfFileInput) {
    pdfUploadBox.addEventListener("click", () => {
      if (!appState.pdfFile) pdfFileInput.click();
    });

    pdfFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        appState.pdfFile = e.target.files[0];
        pdfPreviewImg.src = URL.createObjectURL(appState.pdfFile);
        pdfPlaceholder.style.display = "none";
        pdfPreviewWrapper.style.display = "flex";
        pdfResultContainer.style.display = "none";
      }
    });
  }

  if (btnPdfRemove) {
    btnPdfRemove.addEventListener("click", (e) => {
      e.stopPropagation();
      appState.pdfFile = null;
      pdfFileInput.value = "";
      pdfPlaceholder.style.display = "flex";
      pdfPreviewWrapper.style.display = "none";
      pdfResultContainer.style.display = "none";
    });
  }

  if (btnCreatePdf) {
    btnCreatePdf.addEventListener("click", async () => {
      if (!appState.pdfFile) {
        showTgAlert("Please select an image to convert to PDF!");
        return;
      }

      if (typeof appState.user.credits === "number" && appState.user.credits < 1) {
        showTgAlert("⚠️ Insufficient Credits! You have 0 credits. Please refer friends using your bot link to earn +5 credits for free.");
        return;
      }

      const formData = new FormData();
      formData.append("file", appState.pdfFile);
      formData.append("user_id", appState.user.id);

      showLoader(true, "Compiling PDF document layer...");
      try {
        const response = await fetch("/api/pdf", {
          method: "POST",
          body: formData
        });

        if (response.status === 403) {
          const errData = await response.json().catch(() => ({}));
          showTgAlert(`⚠️ Insufficient Credits! ${errData.error || "You do not have enough credits to perform this action. Refer friends to get free credits!"}`);
          return;
        }

        if (!response.ok) {
          const errJson = await response.json().catch(() => ({}));
          throw new Error(errJson.error || "PDF conversion failed");
        }

        const blob = await response.blob();
        const outputUrl = URL.createObjectURL(blob);

        deductLocalCredit();

        if (pdfBeforeSize) pdfBeforeSize.textContent = formatBytes(appState.pdfFile.size);
        if (pdfOutputSize) pdfOutputSize.textContent = formatBytes(blob.size);

        const docTitle = `${appState.pdfFile.name.substring(0, appState.pdfFile.name.lastIndexOf('.')) || "document"}.pdf`;
        if (pdfOutputName) pdfOutputName.textContent = docTitle;

        if (btnDownloadPdf) {
          btnDownloadPdf.href = outputUrl;
          btnDownloadPdf.download = docTitle;
        }

        pdfResultContainer.style.display = "flex";
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      } catch (err) {
        showTgAlert(`PDF Error: ${err.message}`);
      } finally {
        showLoader(false);
      }
    });
  }

  // ===================================================================
  // SECTION H: COMMON UTILITIES
  // ===================================================================
  function showLoader(show, message = "Processing asset...") {
    const loader = document.getElementById("async-loader");
    const loaderMsg = document.getElementById("loader-status-msg");
    if (loaderMsg) loaderMsg.textContent = message;
    if (loader) loader.style.display = show ? "flex" : "none";
  }

  function showTgAlert(msg) {
    if (tg?.showAlert) {
      tg.showAlert(msg);
    } else {
      alert(msg);
    }
    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("error");
  }

  function formatBytes(bytes, decimals = 1) {
    if (!+bytes) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  }

  function gcd(a, b) {
    return b === 0 ? a : gcd(b, a % b);
  }
});