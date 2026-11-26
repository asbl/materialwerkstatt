export function createImageController({ state, elements, slug }) {
  const MAX_IMAGE_PIXELS = 8_000_000;
  const ctx = elements.canvas.getContext("2d", { willReadFrequently: true });
  const workCanvas = document.createElement("canvas");
  const workCtx = workCanvas.getContext("2d", { willReadFrequently: true });

  async function loadFile(file) {
    if (!file) return;
    const dataUrl = await readAsDataUrl(file);
    const image = await loadImage(dataUrl);
    const normalized = await normalizeImage(image);
    state.originalImage = normalized.image;
    state.originalDataUrl = normalized.dataUrl;
    state.whiteouts = [];
    resetCropBox();
    elements.filename.value = slug(file.name ? file.name.replace(/\.[^.]+$/, "") : "aufgabe-material-01");
    elements.importAsset.disabled = false;
    elements.resetCrop.disabled = false;
    elements.fitImage.disabled = false;
    elements.actualSize.disabled = false;
    elements.imageZoom.disabled = false;
    elements.imageStatus.textContent = normalized.scaled
      ? `${image.naturalWidth} x ${image.naturalHeight} px geladen, auf ${normalized.image.naturalWidth} x ${normalized.image.naturalHeight} px verkleinert.`
      : `${image.naturalWidth} x ${image.naturalHeight} px geladen.`;
    redraw();
    fitImage();
  }

  function redraw() {
    const image = state.originalImage;
    if (!image) return;
    workCanvas.width = image.naturalWidth;
    workCanvas.height = image.naturalHeight;
    workCtx.drawImage(image, 0, 0);
    const imageData = workCtx.getImageData(0, 0, workCanvas.width, workCanvas.height);
    const data = imageData.data;
    for (let index = 0; index < data.length; index += 4) {
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      if (elements.removeGreen.checked && green > 110 && green > red * 1.18 && green > blue * 1.18) {
        data[index] = 255;
        data[index + 1] = 255;
        data[index + 2] = 255;
      }
      if (elements.grayscale.checked) {
        const gray = Math.round(data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114);
        data[index] = gray;
        data[index + 1] = gray;
        data[index + 2] = gray;
      }
    }
    workCtx.putImageData(imageData, 0, 0);
    workCtx.save();
    workCtx.fillStyle = "#ffffff";
    for (const box of state.whiteouts) {
      workCtx.fillRect(box.x, box.y, box.width, box.height);
    }
    workCtx.restore();

    const crop = state.crop || { x: 0, y: 0, width: image.naturalWidth, height: image.naturalHeight };
    elements.canvas.width = crop.width;
    elements.canvas.height = crop.height;
    ctx.clearRect(0, 0, elements.canvas.width, elements.canvas.height);
    ctx.drawImage(workCanvas, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height);
    drawSelection();
    state.cleanDataUrl = elements.canvas.toDataURL("image/png");
    elements.undoWhiteout.disabled = state.whiteouts.length === 0;
    applyCanvasZoom();
  }

  function finishDrag() {
    if (!state.dragStart || !state.dragCurrent) return;
    const selection = normalizedBox(state.dragStart, state.dragCurrent);
    state.dragStart = null;
    state.dragCurrent = null;
    if (selection.width < 4 || selection.height < 4) {
      redraw();
      return;
    }
    const crop = state.crop;
    const originalBox = {
      x: Math.round(crop.x + selection.x),
      y: Math.round(crop.y + selection.y),
      width: Math.round(selection.width),
      height: Math.round(selection.height)
    };
    if (currentTool() === "crop") {
      state.crop = clampBox(originalBox, state.originalImage.naturalWidth, state.originalImage.naturalHeight);
      elements.imageStatus.textContent = `Zuschnitt gesetzt: ${state.crop.width} x ${state.crop.height} px.`;
    } else {
      state.whiteouts.push(clampBox(originalBox, state.originalImage.naturalWidth, state.originalImage.naturalHeight));
      elements.imageStatus.textContent = "Bereich weiß überdeckt.";
    }
    redraw();
  }

  function edits() {
    const result = [];
    if (isCropped()) result.push("zugeschnitten");
    if (state.whiteouts.length) result.push("bereiche_weiss_ueberdeckt");
    if (elements.grayscale.checked) result.push("graustufen");
    if (elements.removeGreen.checked) result.push("gruener_hintergrund_aufgehellt");
    if (!result.length) result.push("rohimport");
    return result;
  }

  function resetCropBox() {
    if (!state.originalImage) return;
    state.crop = {
      x: 0,
      y: 0,
      width: state.originalImage.naturalWidth,
      height: state.originalImage.naturalHeight
    };
  }

  function isCropped() {
    if (!state.originalImage || !state.crop) return false;
    return state.crop.x !== 0
      || state.crop.y !== 0
      || state.crop.width !== state.originalImage.naturalWidth
      || state.crop.height !== state.originalImage.naturalHeight;
  }

  function currentTool() {
    return document.querySelector("input[name=tool]:checked").value;
  }

  function canvasPoint(event) {
    const rect = elements.canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(elements.canvas.width, (event.clientX - rect.left) * elements.canvas.width / rect.width)),
      y: Math.max(0, Math.min(elements.canvas.height, (event.clientY - rect.top) * elements.canvas.height / rect.height))
    };
  }

  function normalizedBox(a, b) {
    const x = Math.min(a.x, b.x);
    const y = Math.min(a.y, b.y);
    return { x, y, width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
  }

  function clampBox(box, maxWidth, maxHeight) {
    const x = Math.max(0, Math.min(maxWidth - 1, box.x));
    const y = Math.max(0, Math.min(maxHeight - 1, box.y));
    return {
      x,
      y,
      width: Math.max(1, Math.min(maxWidth - x, box.width)),
      height: Math.max(1, Math.min(maxHeight - y, box.height))
    };
  }

  function drawSelection() {
    if (!state.dragStart || !state.dragCurrent) return;
    const box = normalizedBox(state.dragStart, state.dragCurrent);
    ctx.save();
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    ctx.lineWidth = Math.max(2, Math.round(elements.canvas.width / 360));
    ctx.setLineDash([8, 5]);
    ctx.strokeRect(box.x, box.y, box.width, box.height);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.globalAlpha = 0.12;
    ctx.fillRect(box.x, box.y, box.width, box.height);
    ctx.restore();
  }

  function fitImage() {
    if (!state.originalImage || !elements.canvas.width) return;
    const panel = elements.canvas.parentElement.getBoundingClientRect();
    const fit = Math.min(1, Math.max(0.25, (panel.width - 28) / elements.canvas.width));
    setImageZoom(fit);
  }

  function setImageZoom(value) {
    state.imageZoom = Math.max(0.25, Math.min(2, value));
    elements.imageZoom.value = Math.round(state.imageZoom * 100);
    applyCanvasZoom();
  }

  function applyCanvasZoom() {
    elements.canvas.style.width = `${elements.canvas.width * state.imageZoom}px`;
    elements.canvas.style.height = `${elements.canvas.height * state.imageZoom}px`;
  }

  function clearImageState() {
    state.originalImage = null;
    state.originalDataUrl = "";
    state.cleanDataUrl = "";
    state.crop = null;
    state.whiteouts = [];
    state.dragStart = null;
    state.dragCurrent = null;
    workCanvas.width = 0;
    workCanvas.height = 0;
    elements.canvas.width = 0;
    elements.canvas.height = 0;
    elements.canvas.removeAttribute("style");
    elements.importAsset.disabled = true;
    elements.resetCrop.disabled = true;
    elements.undoWhiteout.disabled = true;
    elements.fitImage.disabled = true;
    elements.actualSize.disabled = true;
    elements.imageZoom.disabled = true;
    elements.imageStatus.textContent = "Noch kein Bild geladen.";
  }

  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  function loadImage(dataUrl) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = dataUrl;
    });
  }

  async function imageToPngDataUrl(image) {
    const offscreen = document.createElement("canvas");
    offscreen.width = image.naturalWidth;
    offscreen.height = image.naturalHeight;
    offscreen.getContext("2d").drawImage(image, 0, 0);
    return offscreen.toDataURL("image/png");
  }

  async function normalizeImage(image) {
    const pixels = image.naturalWidth * image.naturalHeight;
    if (pixels <= MAX_IMAGE_PIXELS) {
      return { image, dataUrl: await imageToPngDataUrl(image), scaled: false };
    }
    const scale = Math.sqrt(MAX_IMAGE_PIXELS / pixels);
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d").drawImage(image, 0, 0, width, height);
    const dataUrl = canvas.toDataURL("image/png");
    return { image: await loadImage(dataUrl), dataUrl, scaled: true };
  }

  function canvasToBlob(canvas) {
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Canvas konnte nicht als PNG exportiert werden."));
      }, "image/png");
    });
  }

  async function dataUrlToBlob(dataUrl) {
    const response = await fetch(dataUrl);
    return response.blob();
  }

  return { loadFile, redraw, finishDrag, edits, resetCropBox, isCropped, currentTool, canvasPoint, normalizedBox, clampBox, drawSelection, fitImage, setImageZoom, applyCanvasZoom, clearImageState, readAsDataUrl, loadImage, imageToPngDataUrl, normalizeImage, canvasToBlob, dataUrlToBlob };
}
