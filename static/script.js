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
    editImgElement: null,
    pdfFile: null,
    editNaturalWidth: 0,
    editNaturalHeight: 0,
    editAspectRatio: 1,
    activeEditSubtab: "compress",
    
    // File Output State Managers
    processedImgUrl: null,
    processedImgName: null,
    currentPdf: null,
    currentPdfName: null
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

  /**
   * Universal Credit Deduction: Calls backend /api/deduct_credit ONLY AFTER successful action
   */
  async function triggerDeductCredit() {
    try {
      const response = await fetch("/api/deduct_credit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: appState.user.id })
      });
      if (response.ok) {
        const data = await response.json();
        if (typeof data.credits === "number") {
          appState.user.credits = data.credits;
          updateCreditsDOM();
          return true;
        }
      }
    } catch (err) {
      console.warn("Deduct credit network sync notice:", err);
    }
    // Local fallback decrement if offline or test environment
    if (typeof appState.user.credits === "number" && appState.user.credits > 0) {
      appState.user.credits -= 1;
      updateCreditsDOM();
    }
    return true;
  }

  function checkCreditsAvailable() {
    if (typeof appState.user.credits === "number" && appState.user.credits < 1) {
      showTgAlert("⚠️ Insufficient Credits! You have 0 credits remaining. Please refer friends using your bot link to earn free credits!");
      return false;
    }
    return true;
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
    inspectorDropzone.addEventListener("click", (e) => {
      if (e.target !== btnClearInspector && !btnClearInspector?.contains(e.target)) {
        inspectorFileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      inspectorDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        inspectorDropzone.classList.add("drag-hover");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      inspectorDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        inspectorDropzone.classList.remove("drag-hover");
      });
    });

    inspectorDropzone.addEventListener("drop", (e) => {
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        inspectImage(files[0]);
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
      if (formatExt === "JPEG") formatExt = "JPG";
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
  // SECTION E: CLOUD PAGE (IMGHIPPO CDN - CLIENT PRE-COMPRESSION)
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

  /**
   * Pre-compress image in browser using HTML5 Canvas to accelerate upload
   */
  function preCompressImageForCloud(file) {
    return new Promise((resolve) => {
      const img = new Image();
      const objectUrl = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(objectUrl);
        let w = img.naturalWidth;
        let h = img.naturalHeight;
        const maxDimension = 1920;

        if (w > maxDimension || h > maxDimension) {
          if (w > h) {
            h = Math.round((h * maxDimension) / w);
            w = maxDimension;
          } else {
            w = Math.round((w * maxDimension) / h);
            h = maxDimension;
          }
        }

        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);

        canvas.toBlob((blob) => {
          resolve(blob || file);
        }, "image/jpeg", 0.85);
      };
      img.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        resolve(file);
      };
      img.src = objectUrl;
    });
  }

  if (btnGenerateLink) {
    btnGenerateLink.addEventListener("click", async () => {
      if (!appState.cloudFile) {
        showTgAlert("Please select an image first!");
        return;
      }

      showLoader(true, "Optimizing & uploading asset to ImgHippo CDN...");
      try {
        const uploadBlob = await preCompressImageForCloud(appState.cloudFile);
        const formData = new FormData();
        const fileName = (appState.cloudFile.name.substring(0, appState.cloudFile.name.lastIndexOf('.')) || "upload") + ".jpg";
        formData.append("file", uploadBlob, fileName);
        formData.append("user_id", appState.user.id);

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
  // SECTION F: EDIT STUDIO (100% CLIENT-SIDE CANVAS ENGINE)
  // ===================================================================
  const editUploadBox = document.getElementById("edit-upload-box");
  const editFileInput = document.getElementById("edit-file-input");
  const editPlaceholder = document.getElementById("edit-placeholder");
  const editPreviewWrapper = document.getElementById("edit-preview-wrapper");
  const editPreviewImg = document.getElementById("edit-preview-img");
  const btnEditRemove = document.getElementById("btn-edit-remove");
  const btnProcessImage = document.getElementById("btn-process-image");
  const editResultContainer = document.getElementById("edit-result-container");

  // Isolated Result Cards
  const resCardCompress = document.getElementById("res-card-compress");
  const resCardResize = document.getElementById("res-card-resize");
  const resCardConvert = document.getElementById("res-card-convert");

  // Compress Result Elements
  const baBeforeSize = document.getElementById("ba-before-size");
  const baAfterSize = document.getElementById("ba-after-size");
  const baSavedBadge = document.getElementById("ba-saved-badge");

  // Resize Result Elements
  const resizeBeforeDims = document.getElementById("resize-before-dims");
  const resizeAfterDims = document.getElementById("resize-after-dims");
  const resizeSizeBadge = document.getElementById("resize-size-badge");

  // Convert Result Elements
  const convertBeforeFmt = document.getElementById("convert-before-fmt");
  const convertAfterFmt = document.getElementById("convert-after-fmt");
  const convertSizeBadge = document.getElementById("convert-size-badge");

  const btnDownloadProcessed = document.getElementById("btn-download-processed");
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

  let originalUploadedFile = null;
  const btnUndoReset = document.getElementById("btn-undo-reset");

  // 1. Processed Image Dynamic Downloader 
  if (btnDownloadProcessed) {
    btnDownloadProcessed.addEventListener("click", (e) => {
      e.preventDefault();
      if (appState.processedImgUrl && appState.processedImgName) {
        const link = document.createElement("a");
        link.style.display = "none";
        link.href = appState.processedImgUrl;
        link.download = appState.processedImgName;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } else {
        showTgAlert("No processed image available to download.");
      }
    });
  }

  if (editUploadBox && editFileInput) {
    editUploadBox.addEventListener("click", () => {
      if (!appState.editFile) editFileInput.click();
    });

    editFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        const file = e.target.files[0];
        originalUploadedFile = file;
        appState.editFile = file;

        const img = new Image();
        const objectUrl = URL.createObjectURL(file);
        img.onload = () => {
          appState.editImgElement = img;
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

  if (btnUndoReset) {
    btnUndoReset.addEventListener("click", () => {
      if (!originalUploadedFile) {
        showTgAlert("Please choose an image to edit first!");
        return;
      }

      // Restore to original uploaded file
      appState.editFile = originalUploadedFile;
      
      // Wipe temporary process outputs
      appState.processedImgUrl = null;
      appState.processedImgName = null;

      const objectUrl = URL.createObjectURL(originalUploadedFile);
      editPreviewImg.src = objectUrl;

      // Restore original dimensions
      if (resizeW) resizeW.value = appState.editNaturalWidth;
      if (resizeH) resizeH.value = appState.editNaturalHeight;

      // Reset result containers to default hidden state
      editResultContainer.style.display = "none";
      if (resCardCompress) resCardCompress.style.display = "none";
      if (resCardResize) resCardResize.style.display = "none";
      if (resCardConvert) resCardConvert.style.display = "none";

      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    });
  }

  if (btnEditRemove) {
    btnEditRemove.addEventListener("click", (e) => {
      e.stopPropagation();
      originalUploadedFile = null;
      appState.editFile = null;
      appState.editImgElement = null;
      appState.processedImgUrl = null;
      appState.processedImgName = null;
      
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

      // Hide result container until processed on this subtab
      editResultContainer.style.display = "none";

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

  /**
   * 1-SECOND INSTANT CLIENT-SIDE IMAGE PROCESSING ENGINE (HTML5 CANVAS)
   */
  if (btnProcessImage) {
    btnProcessImage.addEventListener("click", async () => {
      if (!appState.editFile) {
        showTgAlert("Please choose an image to edit first!");
        return;
      }

      // 1. Verify credits before starting
      if (!checkCreditsAvailable()) return;

      const activeTab = appState.activeEditSubtab;
      let targetW = appState.editNaturalWidth;
      let targetH = appState.editNaturalHeight;

      // Handle Resize inputs & STRICT 0x0 validation
      if (activeTab === "resize") {
        targetW = parseInt(resizeW?.value, 10);
        targetH = parseInt(resizeH?.value, 10);

        if (!targetW || !targetH || targetW <= 0 || targetH <= 0 || isNaN(targetW) || isNaN(targetH)) {
          showTgAlert("❌ Invalid dimensions! Both Width and Height must be greater than 0 pixels.");
          return;
        }
      }

      // Target Format & MIME Type
      let mimeType = "image/jpeg";
      let targetExt = "jpg";
      let quality = 0.85;
      let origFormat = "JPG";

      if (appState.editFile.type && appState.editFile.type.includes("/")) {
        origFormat = appState.editFile.type.split("/")[1].toUpperCase();
        if (origFormat === "JPEG") origFormat = "JPG";
      }

      if (activeTab === "compress") {
        // ISSUE 1 FIX: Compression MUST explicitly set format to 'image/jpeg'
        // and pass the quality slider value as a decimal (e.g. 36% -> 0.36)
        mimeType = "image/jpeg";
        targetExt = "jpg";
        const sliderVal = compressSlider ? parseInt(compressSlider.value, 10) : 75;
        quality = Math.max(0.05, Math.min(1.0, sliderVal / 100));
      } else if (activeTab === "convert") {
        const selectedFormat = document.querySelector('input[name="target-format"]:checked')?.value || "jpeg";
        if (selectedFormat === "png") {
          mimeType = "image/png";
          targetExt = "png";
          quality = 1.0;
        } else if (selectedFormat === "webp") {
          mimeType = "image/webp";
          targetExt = "webp";
          quality = 0.85;
        } else {
          mimeType = "image/jpeg";
          targetExt = "jpg";
          quality = 0.85;
        }
      } else {
        // Resize tab: default to JPEG with high quality
        mimeType = "image/jpeg";
        targetExt = "jpg";
        quality = 0.90;
      }

      showLoader(true, "Processing image instantly...");

      try {
        const img = new Image();
        const objectUrl = URL.createObjectURL(appState.editFile);

        img.onload = () => {
          URL.revokeObjectURL(objectUrl);

          const canvas = document.createElement("canvas");
          canvas.width = targetW;
          canvas.height = targetH;
          const ctx = canvas.getContext("2d");

          if (mimeType === "image/jpeg") {
            ctx.fillStyle = "#FFFFFF";
            ctx.fillRect(0, 0, targetW, targetH);
          }

          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = "high";
          ctx.drawImage(img, 0, 0, targetW, targetH);

          canvas.toBlob(async (blob) => {
            if (!blob) {
              showLoader(false);
              showTgAlert("Processing error: Canvas failed to export image blob.");
              return;
            }

            const processedUrl = URL.createObjectURL(blob);
            appState.processedImgUrl = processedUrl; // Persist for downloader action
            
            editPreviewImg.src = processedUrl;

            const origSize = appState.editFile.size;
            const processedSize = blob.size;

            // STRICT SEPARATION OF TOOL RESULTS
            if (resCardCompress) resCardCompress.style.display = "none";
            if (resCardResize) resCardResize.style.display = "none";
            if (resCardConvert) resCardConvert.style.display = "none";

            const cleanName = appState.editFile.name.substring(0, appState.editFile.name.lastIndexOf('.')) || "image";

            if (activeTab === "compress") {
              if (baBeforeSize) baBeforeSize.textContent = formatBytes(origSize);
              if (baAfterSize) baAfterSize.textContent = formatBytes(processedSize);
              const savedPercent = Math.round(((origSize - processedSize) / origSize) * 100);
              if (baSavedBadge) {
                if (savedPercent > 0) {
                  baSavedBadge.textContent = `Saved ${savedPercent}%`;
                  baSavedBadge.style.color = "var(--accent-green)";
                } else {
                  baSavedBadge.textContent = "Optimized";
                  baSavedBadge.style.color = "var(--accent-cyan)";
                }
              }
              if (resCardCompress) resCardCompress.style.display = "flex";
              appState.processedImgName = `${cleanName}-compressed.${targetExt}`;
              
            } else if (activeTab === "resize") {
              if (resizeBeforeDims) resizeBeforeDims.textContent = `${appState.editNaturalWidth} × ${appState.editNaturalHeight}`;
              if (resizeAfterDims) resizeAfterDims.textContent = `${targetW} × ${targetH}`;
              if (resizeSizeBadge) resizeSizeBadge.textContent = formatBytes(processedSize);
              if (resCardResize) resCardResize.style.display = "flex";
              appState.processedImgName = `${cleanName}-${targetW}x${targetH}.${targetExt}`;
              
            } else if (activeTab === "convert") {
              if (convertBeforeFmt) convertBeforeFmt.textContent = origFormat;
              if (convertAfterFmt) convertAfterFmt.textContent = targetExt.toUpperCase();
              if (convertSizeBadge) convertSizeBadge.textContent = formatBytes(processedSize);
              if (resCardConvert) resCardConvert.style.display = "flex";
              appState.processedImgName = `${cleanName}-converted.${targetExt}`;
            }

            editResultContainer.style.display = "flex";

            // Universal Credit Deduction: Call backend ONLY AFTER successful processing
            await triggerDeductCredit();

            showLoader(false);
            if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
          }, mimeType, quality);
        };

        img.onerror = () => {
          URL.revokeObjectURL(objectUrl);
          showLoader(false);
          showTgAlert("Failed to load image for canvas manipulation.");
        };

        img.src = objectUrl;
      } catch (err) {
        showLoader(false);
        showTgAlert(`Processing Error: ${err.message}`);
      }
    });
  }

  // ===================================================================
  // SECTION G: PDF CREATOR (100% CLIENT-SIDE WITH jsPDF)
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

  // 2. jsPDF API File Extractor Logic
  if (btnDownloadPdf) {
    btnDownloadPdf.addEventListener("click", (e) => {
      e.preventDefault();
      if (appState.currentPdf && appState.currentPdfName) {
        appState.currentPdf.save(appState.currentPdfName);
      } else {
        showTgAlert("No PDF available to download.");
      }
    });
  }

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
      appState.currentPdf = null;
      appState.currentPdfName = null;
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

      // Check credit balance before starting
      if (!checkCreditsAvailable()) return;

      showLoader(true, "Compiling PDF document locally...");

      try {
        const img = new Image();
        const objectUrl = URL.createObjectURL(appState.pdfFile);

        await new Promise((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error("Failed to load image for PDF compilation"));
          img.src = objectUrl;
        });

        const width = img.naturalWidth;
        const height = img.naturalHeight;
        const isLandscape = width > height;

        // Render to canvas to produce standard RGB JPEG bytes for jsPDF
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);

        const imgData = canvas.toDataURL("image/jpeg", 0.95);

        const jsPDFClass = window.jspdf?.jsPDF;
        if (!jsPDFClass) {
          throw new Error("jsPDF library is not loaded. Please verify your connection.");
        }

        const pdf = new jsPDFClass({
          orientation: isLandscape ? "landscape" : "portrait",
          unit: "px",
          format: [width, height]
        });

        pdf.addImage(imgData, "JPEG", 0, 0, width, height);
        
        // Cache object map for dynamic downloading feature later
        appState.currentPdf = pdf;
        
        const pdfBlob = pdf.output("blob");

        URL.revokeObjectURL(objectUrl);

        const cleanName = appState.pdfFile.name.substring(0, appState.pdfFile.name.lastIndexOf('.')) || "document";
        const docTitle = `${cleanName}.pdf`;
        appState.currentPdfName = docTitle;

        // Update PDF Result UI
        if (pdfBeforeSize) pdfBeforeSize.textContent = formatBytes(appState.pdfFile.size);
        if (pdfOutputSize) pdfOutputSize.textContent = formatBytes(pdfBlob.size);
        if (pdfOutputName) pdfOutputName.textContent = docTitle;

        pdfResultContainer.style.display = "flex";

        // Call backend deduct route ONLY AFTER successful local processing
        await triggerDeductCredit();

        showLoader(false);
        if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      } catch (err) {
        showLoader(false);
        showTgAlert(`PDF Generation Error: ${err.message}`);
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