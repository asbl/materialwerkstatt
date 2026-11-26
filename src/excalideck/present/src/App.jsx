import { assertCompatibility } from "../../../material_ui/static/protocol.js";
import { flushSync } from "react-dom";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { CaptureUpdateAction, Excalidraw, restoreElements, serializeAsJSON } from "@excalidraw/excalidraw";

import { captureScene, sameSceneVersion, sameReferences, sameContent, validateScene } from "./scene-state";
import { sortSlides, newSlide, isBackground, duplicateSlide } from "./slide-tools";
import { DrawingOptions, Dropup, GeometryGuide, Icon } from "./DrawingTools";
import { PresentationScene, belongsToSlide, solutionStep } from "./presentation-scene";
import { paperElements, paperFiles } from "./slide-backgrounds";
import { useLocalDraft, draftKey, draftOperation } from "./local-drafts";
import { useToolProfiles, profileKey, profileState } from "./tool-profiles";
import FeatureBoundary from "./FeatureBoundary";
import SlideOverview from "./SlideOverview";
import { BackgroundPanel, SolutionPanel, ExportPanel } from "./LessonPanels";
import WorksheetImport from "./WorksheetImport";
const MathTools = lazy(() => import("./MathTools"));

const CANVAS_SLIDE_ID = "__canvas__";
const REVISION_POLL_MS = 5000;
const ANNOTATIONS_PREF_KEY = "excalideck:annotations-separate";

// Aeltere Generator-Versionen schrieben Frames vor deren Kinder. Excalidraw
// fuegt neue Anmerkungen vor dem Frame ein: sie lagen damit unter dem
// Template-Hintergrund. Beim Laden Frames hinter ihr letztes Kind setzen und
// bereits vor einem solchen alten Frame gespeicherte Striche wieder ueber
// dessen Inhalte legen. Korrekt aufgebaute Decks behalten ihre Zeichenordnung.
const restoreDeckElements = (source) => {
  const frames = new Map(source.filter((el) => el.type === "frame").map((el) => [el.id, el]));
  const framePositions = new Map(source.map((el, i) => [el.id, i]));
  const lastChild = new Map();
  const lastContent = new Map();
  source.forEach((el, i) => {
    if (frames.has(el.frameId)) {
      lastChild.set(el.frameId, i);
      if (el.type !== "freedraw") lastContent.set(el.frameId, i);
    }
  });
  const recovered = new Map();
  const deferred = new Set();
  source.forEach((el, i) => {
    const framePosition = framePositions.get(el.frameId);
    if (el.type === "freedraw" && frames.has(el.frameId) &&
        i < framePosition && framePosition < lastContent.get(el.frameId)) {
      const strokes = recovered.get(el.frameId) ?? [];
      strokes.push(el);
      recovered.set(el.frameId, strokes);
      deferred.add(el);
    }
  });
  const ordered = [];
  source.forEach((el, i) => {
    if (!lastChild.has(el.id) && !deferred.has(el)) ordered.push(el);
    if (lastContent.get(el.frameId) === i) ordered.push(...(recovered.get(el.frameId) ?? []));
    if (lastChild.get(el.frameId) === i) ordered.push(frames.get(el.frameId));
  });
  // Alte fractional indices beschreiben noch die urspruengliche Reihenfolge;
  // restoreElements vergibt passende neue Werte fuer die korrigierte Szene.
  return restoreElements(ordered.map((el) => ({ ...el, index: null })), null);
};

// Ohne Frames ist die gesamte Leinwand eine Folie: Pseudo-Rahmen ueber die
// Bounding-Box aller sichtbaren Elemente (mit Rand), leer sonst Standardgroesse.
const canvasSlide = (elements) => {
  const visible = elements.filter((el) => !el.isDeleted);
  if (!visible.length) {
    return { id: CANVAS_SLIDE_ID, x: 0, y: 0, width: 1600, height: 900 };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const el of visible) {
    minX = Math.min(minX, el.x);
    minY = Math.min(minY, el.y);
    maxX = Math.max(maxX, el.x + (el.width || 0));
    maxY = Math.max(maxY, el.y + (el.height || 0));
  }
  const pad = 40;
  return {
    id: CANVAS_SLIDE_ID,
    x: minX - pad,
    y: minY - pad,
    width: maxX - minX + pad * 2,
    height: maxY - minY + pad * 2,
  };
};

const PEN_COLORS = ["#1e1e1e", "#e03131", "#1971c2", "#2f9e44", "#f08c00", "#862e9c"];
const PEN_WIDTHS = [
  { width: 0.5, label: "Extra fein" },
  { width: 1, label: "Fein" },
  { width: 2, label: "Dünn" },
  { width: 4, label: "Mittel" },
  { width: 8, label: "Dick" },
];
const MARKER_WIDTH = 16;
const MARKER_OPACITY = 35;
// Zoom-Grenzen wie Excalidraw (10 % bis 3000 %), fuer Disabled-Zustaende.
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 30;

// Statisch, deshalb ausserhalb der Komponente: ein Inline-Objekt wuerde
// bei jedem Render einen neuen Prop erzeugen und Excalidraw mitrendern.
const UI_OPTIONS = {
  canvasActions: {
    loadScene: false,
    saveToActiveFile: false,
    export: false,
    saveAsImage: true,
    clearCanvas: false,
  },
};

// Handballen-Erkennung ab dem Start aktiv: nur der Stift zeichnet, der Finger
// verschiebt die Folie (Excalidraw wuerde penMode sonst erst beim ersten
// Stift-Kontakt selbst einschalten). Statisch, damit Excalidraw nicht bei
// jedem Render einen neuen Prop erhaelt und mitrendert.
const INITIAL_DATA = { appState: { penMode: true, penDetected: true } };

function loadAnnotationsPreference() {
  try {
    return localStorage.getItem(ANNOTATIONS_PREF_KEY) !== "off";
  } catch {
    return true;
  }
}

export default function App() {
  const apiRef = useRef(null);
  const nativeApiRef = useRef(null);
  const projectionRef = useRef(null);
  if (!projectionRef.current) projectionRef.current = new PresentationScene();
  const profiles = useToolProfiles();
  const switchingProfileRef = useRef(false);
  const [overviewOpen, setOverviewOpen] = useState(false);
  const [worksheetImportOpen, setWorksheetImportOpen] = useState(false);
  const [worksheetOwner, setWorksheetOwner] = useState(() => new URLSearchParams(window.location.search).get("worksheet"));
  const [isolateSlide, setIsolateSlide] = useState(true);
  const [revealedSteps, setRevealedSteps] = useState({});
  const [draftIdentity, setDraftIdentity] = useState(null);
  const [exportBusy, setExportBusy] = useState(null);
  const [startupDraft, setStartupDraft] = useState(null);
  const [restoredDraftKey, setRestoredDraftKey] = useState(null);
  const loadedDeckRef = useRef(false);
  const draftControlsRef = useRef(null);
  const fileInputRef = useRef(null);
  const [slides, setSlides] = useState([]);
  const [index, setIndex] = useState(-1);
  const [deckName, setDeckName] = useState(null);
  const [materialPath, setMaterialPath] = useState(null);
  const [annotationsMode, setAnnotationsMode] = useState(loadAnnotationsPreference);
  const [saveState, setSaveState] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [presenting, setPresenting] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [tool, setTool] = useState("selection");
  const [continueLines, setContinueLines] = useState(true);
  const continueLinesRef = useRef(true);
  const [marker, setMarker] = useState(false);
  // Standard: Handballen-Erkennung an – nur der Stift zeichnet, der Finger
  // verschiebt die Folie. Per "Handballen"-Knopf explizit umschaltbar (z. B.
  // wenn kein Stift dabei ist, zeichnet der Finger wieder).
  const [penMode, setPenMode] = useState(true);
  const penModeRef = useRef(true);
  const [zoom, setZoom] = useState(1);
  const [penColor, setPenColor] = useState(PEN_COLORS[0]);
  const [penWidth, setPenWidth] = useState(2);
  const penWidthRef = useRef(2);
  const markerRef = useRef(false);
  const restoringPenRef = useRef(false);
  const [drawingState, setDrawingState] = useState({});
  const [geometry, setGeometry] = useState(null);
  const [mathOpen, setMathOpen] = useState(false);
  const [protectedBackground, setProtectedBackground] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [frameless, setFrameless] = useState(false);
  const [externalRevision, setExternalRevision] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState([]);
  const indexRef = useRef(-1);
  const slidesRef = useRef([]);
  const toolRef = useRef("selection");
  const deckIdsRef = useRef(new Set());
  const savedElementsRef = useRef([]);
  const lastElementsRef = useRef([]);
  const deckElementsRef = useRef([]);
  const backgroundIdsRef = useRef(new Set());
  const sceneRevisionRef = useRef(0);
  const savingRef = useRef(false);
  const requireFullSaveRef = useRef(false);
  const annotationsRevisionRef = useRef(null);
  const [pendingSceneChange, setPendingSceneChange] = useState(null);
  const [notice, setNotice] = useState(null);
  const baselinePendingRef = useRef(false);
  const pendingDirtyRef = useRef(false);
  const dirtyRef = useRef(false);
  const deckRevisionRef = useRef(null);
  const materialPathRef = useRef(null);

  const setDirtyState = useCallback((value) => {
    dirtyRef.current = value;
    setDirty(value);
  }, []);

  const requestSceneChange = useCallback((action) => {
    if (savingRef.current) {
      setNotice("Bitte den laufenden Speichervorgang abwarten.");
      return;
    }
    if (dirtyRef.current) setPendingSceneChange({ action });
    else action();
  }, []);

  const goTo = useCallback((i) => {
    const list = slidesRef.current;
    if (!apiRef.current || list.length === 0) return;
    const clamped = Math.max(0, Math.min(list.length - 1, i));
    indexRef.current = clamped;
    setIndex(clamped);
    const frame = apiRef.current.getSceneElements().find((el) => el.id === list[clamped].id) ?? list[clamped];
    const toolbar = document.querySelector(".presenting .deck-toolbar");
    if (toolbar) {
      const state = apiRef.current.getAppState();
      const overview = document.querySelector(".deck-overview");
      const left = overview && state.width >= 700 ? overview.getBoundingClientRect().right + 16 : 0;
      const availableWidth = Math.max(180, state.width - left);
      const availableHeight = Math.max(120, toolbar.getBoundingClientRect().top - state.offsetTop - 16);
      const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM,
        (availableWidth - 48) / frame.width, (availableHeight - 32) / frame.height));
      apiRef.current.updateScene({ appState: { zoom: { value: zoom },
        scrollX: (left + availableWidth / 2) / zoom - frame.x - frame.width / 2,
        scrollY: availableHeight / (2 * zoom) - frame.y - frame.height / 2 } });
    } else {
      apiRef.current.scrollToContent(frame, { fitToViewport: true, viewportZoomFactor: 0.9 });
    }
  }, []);

  const next = useCallback(() => goTo(indexRef.current + 1), [goTo]);
  const prev = useCallback(() => goTo(indexRef.current - 1), [goTo]);

  const applyScene = useCallback((data, name, options = {}) => {
    const api = apiRef.current;
    if (!api) return;
    // restoreElements fuellt Pflichtfelder (backgroundColor etc.) auf,
    // sonst crasht das Hit-Testing bei Klicks auf unvollstaendige Elemente.
    loadedDeckRef.current = true;
    switchingProfileRef.current = true;
    projectionRef.current.configure({ presenting: false, isolate: true, frame: null, revealed: 0 });
    projectionRef.current.hidden.clear();
    const ids = options.deckIds ?? new Set((data.elements ?? []).filter((el) => !el.customData?.insertAfter && !el.customData?.slideBackground).map((el) => el.id));
    deckIdsRef.current = ids;
    backgroundIdsRef.current = ids;
    const elements = restoreDeckElements(data.elements ?? []).map((source) => {
      const el = { ...source, customData: { ...source.customData } };
      return isBackground(el, ids) ? { ...el, locked: true } : el;
    });
    setProtectedBackground(true);
    deckElementsRef.current = captureScene(elements.filter((el) => ids.has(el.id) && !el.isDeleted));
    if (!options.dirty) savedElementsRef.current = captureScene(elements.filter((el) => !el.isDeleted));
    requireFullSaveRef.current = !!options.dirty;
    baselinePendingRef.current = true;
    pendingDirtyRef.current = !!options.dirty;
    api.updateScene({ elements, captureUpdate: CaptureUpdateAction.NEVER });
    api.history.clear();
    setLoadError(null);
    setNotice(null);
    const files = Object.values(data.files ?? {});
    if (files.length > 0) {
      api.addFiles(files);
    }

    if (options.annotationsRevision !== undefined) {

      annotationsRevisionRef.current = options.annotationsRevision;
    }
    setDeckName(name);
    setDraftIdentity(options.draftIdentity ?? draftKey(materialPathRef.current, name, elements));
    setRevealedSteps({});
    const frames = sortSlides(elements.filter((el) => el.type === "frame"));
    if (frames.length) {
      slidesRef.current = frames;
      setSlides(frames);
      setFrameless(false);
    } else {
      const pseudo = canvasSlide(elements);
      slidesRef.current = [pseudo];
      setSlides([pseudo]);
      setFrameless(true);
    }
    indexRef.current = -1;
    setPresenting(true);
    setMarker(false);
    setPenWidth(profiles.profiles.pen.strokeWidth);
    penWidthRef.current = profiles.profiles.pen.strokeWidth;
    markerRef.current = false;
    setPenColor(profiles.profiles.pen.strokeColor);
    toolRef.current = "freedraw";
    setTool("freedraw");
    api.setActiveTool({ type: "freedraw" });
    api.updateScene({
      appState: {
        ...profileState(profiles.profiles.pen),
        // Helvetica (2) statt Excalifont: besser lesbar fuer Anmerkungen
        // und Folientext; Ueberschriften aus dem Generator bleiben unberuehrt.
        currentItemFontFamily: 2,
      },
    });
    // Erste onChange-Runde nach dem Laden legt den Vergleichsfuss fuer den
    // Ungespeichert-Indikator; pendingDirty markiert geladene Versionen.
    switchingProfileRef.current = false;
    const requestedFrame = new URLSearchParams(window.location.search).get("frame");
    const initialIndex = requestedFrame ? slidesRef.current.findIndex((frame) => frame.id === requestedFrame) : 0;
    setTimeout(() => goTo(Math.max(0, initialIndex)), 50);
  }, [goTo, profiles]);

  const toggleBackground = useCallback(() => {
    const api = apiRef.current;
    if (!api) return;
    const protect = !protectedBackground;
    // Hintergrundschutz ist ein Ansichtsmodus, wie Handballen-Erkennung:
    // er gehoert nicht in die Undo-Historie der Zeichnungen.
    api.updateScene({ elements: api.getSceneElementsIncludingDeleted().map((el) =>
      isBackground(el, backgroundIdsRef.current)
        ? { ...el, locked: protect, version: el.version + 1, versionNonce: Math.floor(Math.random() * 2 ** 31) } : el),
      captureUpdate: CaptureUpdateAction.NEVER });
    setProtectedBackground(protect);
    if (!protect && materialPathRef.current && annotationsMode) {
      setAnnotationsMode(false);
      setNotice("Folieninhalte entsperrt: Änderungen werden im gesamten Deck gespeichert.");
    }
  }, [protectedBackground, annotationsMode]);

  const insertSlide = useCallback((grid) => {
    const api = apiRef.current;
    if (!api) return;
    let current = slidesRef.current[indexRef.current];
    const elements = [...api.getSceneElementsIncludingDeleted()];
    if (current?.id === CANVAS_SLIDE_ID) {
      current = restoreElements([{ ...current, id: crypto.randomUUID(), type: "frame", name: "Leinwand", locked: true }], null)[0];
      elements.push(current);
    }
    let added = restoreElements(newSlide(elements.filter((e) => !e.isDeleted), current, grid), null);
    const backgroundFiles = paperFiles(added.at(-1), typeof grid === "string" ? grid : grid ? "grid" : "blank");
    if (backgroundFiles.length) api.addFiles(backgroundFiles);
    if (current?.customData?.presentationOrder !== undefined) {
      const before = slidesRef.current.slice(0, indexRef.current + 1);
      const after = slidesRef.current.slice(indexRef.current + 1);
      const order = new Map([...before, added.at(-1), ...after].map((frame, i) => [frame.id, i]));
      const ordered = elements.map((el) => el.type === "frame" && order.has(el.id) ? { ...el, customData: { ...el.customData, presentationOrder: order.get(el.id) }, version: el.version + 1 } : el);
      elements.splice(0, elements.length, ...ordered);
      added = added.map((el) => el.type === "frame" ? { ...el, customData: { ...el.customData, presentationOrder: order.get(el.id) } } : el);
      if (materialPathRef.current) setAnnotationsMode(false);
    }
    const frames = sortSlides([...elements.filter((el) => el.type === "frame" && !el.isDeleted), added.at(-1)]);
    api.updateScene({ elements: restoreDeckElements([...elements, ...added]), captureUpdate: CaptureUpdateAction.IMMEDIATELY });
    slidesRef.current = frames;
    setSlides(frames);
    goTo(frames.findIndex((f) => f.id === added.at(-1).id));
  }, [goTo]);

  const insertClipboardImage = useCallback(async (blob) => {
    const api = apiRef.current;
    if (!api) return;
    const dataURL = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
    });
    const image = new Image();
    image.src = dataURL;
    await image.decode();
    const frame = slidesRef.current[indexRef.current];
    const scale = Math.min(1, (frame?.width ?? 1200) * 0.8 / image.width, (frame?.height ?? 800) * 0.8 / image.height);
    const width = image.width * scale, height = image.height * scale;
    const id = crypto.randomUUID();
    api.addFiles([{ id, dataURL, mimeType: blob.type, created: Date.now() }]);
    const frameId = frame?.id === CANVAS_SLIDE_ID ? null : frame?.id;
    const elements = restoreElements([{ id: crypto.randomUUID(), type: "image", fileId: id, status: "saved", scale: [1, 1],
      x: (frame?.x ?? 0) + ((frame?.width ?? width) - width) / 2,
      y: (frame?.y ?? 0) + ((frame?.height ?? height) - height) / 2,
      width, height, frameId }], null);
    // Kinder muessen vor ihrem Frame im Array stehen (Konvention wie in slide-tools.newSlide);
    // sonst rutscht spaeter frame-lokal Gezeichnetes unter das hier eingefuegte Bild.
    const current = api.getSceneElements();
    const frameIndex = frameId ? current.findIndex((el) => el.id === frameId) : -1;
    const next = frameIndex === -1 ? [...current, ...elements]
      : [...current.slice(0, frameIndex), ...elements, ...current.slice(frameIndex)];
    api.updateScene({ elements: next, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  }, []);

  useEffect(() => {
    const paste = (event) => {
      if (event.target?.closest?.("input, textarea, [contenteditable=true]")) return;
      const image = [...(event.clipboardData?.items ?? [])].find((item) => item.type.startsWith("image/"))?.getAsFile();
      if (!image) return;
      event.preventDefault();
      event.stopPropagation();
      insertClipboardImage(image).catch(() => setLoadError("Bild konnte nicht eingefügt werden."));
    };
    window.addEventListener("paste", paste, true);
    return () => window.removeEventListener("paste", paste, true);
  }, [insertClipboardImage]);

  const pasteImage = useCallback(async () => {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (type) { await insertClipboardImage(await item.getType(type)); setLoadError(null); return; }
      }
      setLoadError("Kein Bild in der Zwischenablage. Bild kopieren und Strg+V drücken.");
    } catch {
      setLoadError("Zwischenablage nicht zugänglich. Bild mit Strg+V einfügen.");
    }
  }, [insertClipboardImage]);

  const loadFile = useCallback(async (file) => {
    try {
      const data = validateScene(JSON.parse(await file.text()));
      requestSceneChange(() => {
        const location = new URL(window.location.href);
        location.searchParams.delete("path");
        window.history.replaceState(null, "", location);
        materialPathRef.current = null;
        setMaterialPath(null);
        setWorksheetOwner(null);
        setWorksheetImportOpen(false);
        deckRevisionRef.current = null;

        annotationsRevisionRef.current = null;

        setExternalRevision(null);
        applyScene(data, file.name);
      });
    } catch {
      setLoadError("Datei konnte nicht geöffnet werden: keine gültige Excalidraw-Szene.");
    }
  }, [applyScene, requestSceneChange]);

  // Material-UI-Modus: Deck plus gespeicherte Anmerkungen (Sidecar) laden.
  // Bereits im Deck enthaltene Anmerkungen werden nicht doppelt ueberlagert.
  const loadMaterialDeck = useCallback(async () => {
    const path = materialPathRef.current;
    if (!path) return;
    await assertCompatibility();
    const deckResponse = await fetch(`/api/deck?path=${encodeURIComponent(path)}`);
    if (!deckResponse.ok) throw new Error(`HTTP ${deckResponse.status}`);
    const revision = deckResponse.headers.get("X-Material-Revision");
    const deck = await deckResponse.json();
    setWorksheetOwner(new URLSearchParams(window.location.search).get("worksheet") ||
      deck.elements?.find(el => el.customData?.worksheetOwner)?.customData.worksheetOwner || null);
    const annotationsResponse = await fetch(`/api/deck/annotations?path=${encodeURIComponent(path)}`);
    if (!annotationsResponse.ok) throw new Error("Anmerkungen konnten nicht geladen werden.");
    const annotations = annotationsResponse.ok
      ? await annotationsResponse.json()
      : { elements: [], files: {}, revision: null };
    const deckIds = new Set((deck.elements ?? []).map((el) => el.id));
    const extra = (annotations.elements ?? []).filter((el) => !deckIds.has(el.id));
    applyScene(
      {
        ...deck,
        elements: [...(deck.elements ?? []), ...extra],
        files: { ...(deck.files ?? {}), ...(annotations.files ?? {}) },
      },
      path.split("/").pop(),
      { deckIds, annotationsRevision: annotationsResponse.headers.get("X-Material-Revision") ?? annotations.revision ?? null },
    );
    deckRevisionRef.current = revision;

    setExternalRevision(null);
  }, [applyScene]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const path = params.get("path");
    if (!path || !window.__MATERIAL_TOKEN__) return;
    let cancelled = false;
    materialPathRef.current = path;
    setMaterialPath(path);
    loadMaterialDeck()
      .catch(error => {
        if (!cancelled) setLoadError(error.status === 426 ? error.message : "Deck konnte nicht geladen werden.");
      });
    return () => {
      cancelled = true;
    };
  }, [loadMaterialDeck]);

  const activate = useCallback((type, asMarker = false) => {
    const key = profileKey(type, asMarker);
    switchingProfileRef.current = true;
    markerRef.current = asMarker;
    setMarker(asMarker);
    if (type === "freedraw" && !asMarker) {
      penWidthRef.current = profiles.profiles.pen.strokeWidth;
      setPenWidth(penWidthRef.current);
    }
    if (key) apiRef.current?.updateScene({ appState: profileState(profiles.profiles[key], key === "pen" ? apiRef.current.getAppState().zoom.value : 1) });
    toolRef.current = type;
    setTool(type);
    apiRef.current?.setActiveTool({ type, locked: ["line", "arrow"].includes(type) && continueLinesRef.current });
    switchingProfileRef.current = false;
  }, [profiles]);
  const choosePen = useCallback(() => activate("freedraw"), [activate]);
  const chooseMarker = useCallback(() => activate("freedraw", true), [activate]);
  const chooseTool = useCallback((type) => activate(type), [activate]);

  useEffect(() => {
    const key = profileKey(tool, markerRef.current);
    if (key) apiRef.current?.updateScene({ appState: profileState(profiles.profiles[key], key === "pen" ? apiRef.current.getAppState().zoom.value : 1) });
    const state = apiRef.current?.getAppState();
    if (state) apiRef.current.updateScene({ appState: { activeTool: { ...state.activeTool, locked: ["line", "arrow"].includes(tool) && continueLinesRef.current } } });
    restoringPenRef.current = false;
    switchingProfileRef.current = false;
  }, [tool, marker, profiles]);

  const toggleContinueLines = useCallback(() => {
    const api = apiRef.current;
    const active = api?.getAppState().activeTool;
    const next = !active?.locked;
    continueLinesRef.current = next;
    setContinueLines(next);
    if (active && ["line", "arrow"].includes(active.type)) api.updateScene({ appState: { activeTool: { ...active, locked: next } } });
  }, []);

  // Die eigene Toolbar liegt außerhalb von Excalidraws Tastaturbereich.
  // Esc soll dort ebenfalls das Linienwerkzeug beenden, ohne Eingaben oder
  // offene Dialoge zu beeinflussen. Auf der Leinwand behandelt Excalidraw Esc.
  useEffect(() => {
    const exitLines = (event) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target;
      if (target?.closest?.(".excalidraw, input, textarea, select, [contenteditable=true]")) return;
      if (document.querySelector(".deck-dropup-panel, .deck-dialog-backdrop, .deck-math [role=dialog]")) return;
      if (!["line", "arrow"].includes(apiRef.current?.getAppState().activeTool.type)) return;
      event.preventDefault();
      chooseTool("selection");
      document.querySelector(".excalidraw")?.focus({ preventScroll: true });
    };
    window.addEventListener("keydown", exitLines);
    return () => window.removeEventListener("keydown", exitLines);
  }, [chooseTool]);

  // Handballen-Erkennung (penMode): Touch-Eingaben zeichnen nicht, der Stift
  // zeichnet allein; der Finger verschiebt stattdessen die Folie (siehe
  // onCanvasPointerDown). Standardmaessig aktiv, damit nicht erst der erste
  // Stift-Kontakt den Modus einschaltet. Excalidraws eingebauter Umschalter
  // ist im Praesentationsmodus ausgeblendet, deshalb hier ein eigener.
  const togglePenMode = useCallback(() => {
    penModeRef.current = !penModeRef.current;
    apiRef.current?.updateScene({
      appState: { penMode: penModeRef.current, penDetected: true },
    });
  }, []);

  const chooseColor = useCallback((color) => {
    setPenColor(color);
    const key = profileKey(toolRef.current, markerRef.current) ?? "pen";
    profiles.update(key, { strokeColor: color });
    apiRef.current?.updateScene({ appState: { currentItemStrokeColor: color } });
  }, [profiles]);

  const chooseWidth = useCallback((width) => {
    profiles.update("pen", { strokeWidth: width });
    penWidthRef.current = width;
    setPenWidth(width);
    if (!marker) {
      apiRef.current?.updateScene({ appState: { currentItemStrokeWidth: width / (apiRef.current?.getAppState().zoom.value || 1) } });
    }
  }, [marker, profiles]);

  // Excalidraw bindet Undo/Redo an Strg+Z; die API bietet dafuer keine
  // Methode. Der Keydown-Handler haengt als React-Handler am Excalidraw-
  // Container, deshalb wird das Tastaturereignis dort synthetisch
  // ausgeloesst (matchKey prueft event.key, synthetische Events genuegen).
  const historyKey = useCallback((key, shiftKey) => {
    const target = document.querySelector(".excalidraw") ?? document;
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key,
        code: key === "[" ? "BracketLeft" : key === "]" ? "BracketRight" : undefined,
        ctrlKey: true,
        shiftKey,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, []);

  const undo = useCallback(() => historyKey("z", false), [historyKey]);
  const redo = useCallback(() => historyKey("z", true), [historyKey]);

  // Zoom-Aktionen sind wie Undo/Redo an Tastaturkuerzel gebunden (Strg mit
  // +/-/0); die API bietet dafuer keine Methode. Die Zoom-keyTest pruefen
  // event.code statt event.key, deshalb bekommt das synthetische Ereignis
  // beides mit, damit auch kuenftige keyTest-Varianten greifen.
  const zoomShortcut = useCallback((code, key) => {
    const target = document.querySelector(".excalidraw") ?? document;
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key,
        code,
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, []);
  const zoomIn = useCallback(() => zoomShortcut("Equal", "+"), [zoomShortcut]);
  const zoomOut = useCallback(() => zoomShortcut("Minus", "-"), [zoomShortcut]);
  const resetZoom = useCallback(() => zoomShortcut("Digit0", "0"), [zoomShortcut]);
  const fitSlide = useCallback(() => goTo(indexRef.current), [goTo]);

  // Entfernt alle Anmerkungen (Freedraw-Striche) auf der aktuellen Folie.
  // Rahmen und Folieninhalte (Text, Formen) bleiben unberuehrt; Rueckgaengig
  // macht das Loeschen wieder rückgängig.
  const clearSlide = useCallback(() => {
    const api = apiRef.current;
    const frame = slidesRef.current[indexRef.current];
    if (!api || !frame) return;
    const kept = api.getSceneElements().filter((el) => {
      if (el.type !== "freedraw" || el.isDeleted) return true;
      if (el.frameId === frame.id) return false;
      const overlaps =
        el.x + el.width > frame.x &&
        el.x < frame.x + frame.width &&
        el.y + el.height > frame.y &&
        el.y < frame.y + frame.height;
      return !overlaps;
    });
    api.updateScene({ elements: kept, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  }, []);

  const exitPresenting = useCallback(() => {
    setPresenting(false);
    chooseTool("selection");
  }, [chooseTool]);

  const reloadDeck = useCallback(() => {
    requestSceneChange(async () => {
      try { await loadMaterialDeck(); setConflict(null); }
      catch (error) { setLoadError(error.status === 426 ? error.message : "Deck konnte nicht geladen werden."); }
    });
  }, [loadMaterialDeck, requestSceneChange]);

  const saveFile = useCallback(async (overrideRevision) => {
    const api = apiRef.current;
    if (!api || savingRef.current) return false;
    const snapshot = [...api.getSceneElements()];
    const sentSnapshot = captureScene(snapshot);
    const originals = snapshot.filter((el) => deckIdsRef.current.has(el.id));
    if (materialPathRef.current && annotationsMode && (requireFullSaveRef.current || !sameContent(originals, deckElementsRef.current))) {
      setAnnotationsMode(false);
      setNotice("Auch Folieninhalte wurden geändert. Bitte das gesamte Deck speichern.");
      return false;
    }
    const elements = snapshot.map((el) => backgroundIdsRef.current.has(el.id)
      ? el : { ...el, customData: { ...el.customData, presenterAnnotation: true } });
    const appState = api.getAppState();
    const files = api.getFiles?.() ?? {};
    const separate = !!materialPathRef.current && annotationsMode;
    const exported = separate ? elements.filter((el) => !deckIdsRef.current.has(el.id)) : elements;
    const scene = serializeAsJSON(exported, appState, files, "local");
    const markSaved = async () => {
      savedElementsRef.current = sentSnapshot;
      const newer = !sameContent(api.getSceneElements(), sentSnapshot);
      setDirtyState(newer);
      if (!newer) await draftControlsRef.current?.clearSaved();
    };
    if (!materialPathRef.current) {
      const url = URL.createObjectURL(new Blob([scene], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = deckName ?? "deck.excalidraw";
      a.click();
      URL.revokeObjectURL(url);
      await markSaved();
      return true;
    }
    savingRef.current = true;
    setSaveState("saving");
    try {
      await assertCompatibility(true);
      const response = await fetch(separate ? "/api/deck/annotations/save" : "/api/deck/save", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Material-Token": window.__MATERIAL_TOKEN__ ?? "" },
        body: JSON.stringify({ path: materialPathRef.current, scene,
          revision: overrideRevision ?? (separate ? annotationsRevisionRef.current : deckRevisionRef.current),
          ...(separate ? { deckRevision: deckRevisionRef.current } : {}) }),
      });
      if (response.status === 409) {
        setSaveState(null);
        const failure = await response.json().catch(() => null);
        setConflict({ target: separate
          ? failure?.error?.code === "deck_changed" ? "annotations-deck" : "annotations"
          : "deck" });
        return false;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (separate) {
        annotationsRevisionRef.current = payload.revision ?? null;
        // Nach einem Folien-Rebuild uebertraegt der Server die Anmerkungen auf
        // die neue Deck-Fassung. Der Client folgt der neuen Deck-Revision und
        // muss die laufende Folienansicht dazu nicht neu laden.
        if (payload.deckRevision && payload.deckRevision !== deckRevisionRef.current) {
          deckRevisionRef.current = payload.deckRevision;
          setExternalRevision(null);
        }

      } else {
        deckRevisionRef.current = payload.revision ?? null;

        annotationsRevisionRef.current = null;

        deckIdsRef.current = new Set(snapshot.map((el) => el.id));
        deckElementsRef.current = sentSnapshot;
        requireFullSaveRef.current = false;
        setExternalRevision(null);
      }
      // Ausschliesslich der gesendete Snapshot ist gespeichert. Neuere
      // Striche bleiben in der Szene und weiterhin als ungespeichert markiert.
      await markSaved();
      setSaveState("saved");
      return true;
    } catch (error) {
      if (error.status === 426) setNotice(error.message);
      setSaveState("error");
      return false;
    } finally {
      savingRef.current = false;
    }
  }, [annotationsMode, deckName, setDirtyState]);

  const downloadLocalScene = useCallback(() => {
    const api = apiRef.current;
    if (!api) return;
    const scene = serializeAsJSON(api.getSceneElements(), api.getAppState(), api.getFiles?.() ?? {}, "local");
    const url = URL.createObjectURL(new Blob([scene], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = deckName ?? "lokale-anmerkungen.excalidraw";
    link.click();
    URL.revokeObjectURL(url);
  }, [deckName]);

  const overwriteConflict = useCallback(async () => {
    const target = conflict?.target;
    setConflict(null);
    try {
      if (target === "deck") {
        const response = await fetch(`/api/deck/revision?path=${encodeURIComponent(materialPathRef.current)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        await saveFile(payload.revision);
      } else {
        const response = await fetch(`/api/deck/annotations?path=${encodeURIComponent(materialPathRef.current)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await saveFile(response.headers.get("X-Material-Revision"));
      }
    } catch {
      setSaveState("error");
      setTimeout(() => setSaveState(null), 2500);
    }
  }, [conflict, saveFile]);

  const openHistory = useCallback(async () => {
    if (!materialPathRef.current) return;
    setHistoryOpen(true);
    setVersions([]);
    try {
      const response = await fetch(`/api/deck/history?path=${encodeURIComponent(materialPathRef.current)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setVersions(payload.versions ?? []);
    } catch {
      setVersions([]);
    }
  }, []);

  const loadVersion = useCallback((identifier) => {
    if (!materialPathRef.current) return;
    requestSceneChange(async () => {
      try {
        const response = await fetch(
          `/api/deck/history/${identifier}?path=${encodeURIComponent(materialPathRef.current)}`,
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const snapshot = await response.json();
        const data = JSON.parse(snapshot.text);
        const deckIds = new Set((data.elements ?? []).map((el) => el.id));
        const annotationsResponse = await fetch(
          `/api/deck/annotations?path=${encodeURIComponent(materialPathRef.current)}`,
        );
        if (!annotationsResponse.ok) throw new Error("Anmerkungen konnten nicht geladen werden.");
        const annotations = await annotationsResponse.json();
        const extra = (annotations.elements ?? []).filter((el) => !deckIds.has(el.id));
        applyScene(
          {
            ...data,
            elements: [...(data.elements ?? []), ...extra],
            files: { ...(data.files ?? {}), ...(annotations.files ?? {}) },
          },
          materialPathRef.current.split("/").pop(),
          { deckIds, annotationsRevision: annotationsResponse.headers.get("X-Material-Revision") ?? annotations.revision ?? null, dirty: true },
        );
        setAnnotationsMode(false);
        setNotice("Frühere Fassung geladen. Zum Übernehmen das gesamte Deck speichern.");
        setHistoryOpen(false);
      } catch {
        setLoadError("Version konnte nicht geladen werden.");
      }
    });
  }, [applyScene, requestSceneChange]);

  const toggleAnnotationsMode = useCallback(() => {
    if (requireFullSaveRef.current || !sameContent(apiRef.current?.getSceneElements().filter((el) => deckIdsRef.current.has(el.id)) ?? [], deckElementsRef.current)) {
      setNotice("Folieninhalte wurden geändert. Zuerst das gesamte Deck speichern.");
      return;
    }
    setAnnotationsMode((previous) => {
      const next = !previous;
      try {
        localStorage.setItem(ANNOTATIONS_PREF_KEY, next ? "on" : "off");
      } catch {
        // Die Voreinstellung ist nur ein Komfort; ohne localStorage bleibt der Schalter sitzungsglobal.
      }
      return next;
    });
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      // exitFullscreen wartet nur auf den Browser; ein Rueckschlag bleibt
      // ohne Folgen, der Zustand laesst sich dabei nicht verstellen.
      document.exitFullscreen()?.catch?.(() => {});
    } else {
      // Eingebettete Fenster ohne Vollbild-Erlaubnis (z. B. Firefox-Modals)
      // lehnen requestFullscreen ab: sichtbarer Hinweis statt stiller
      // Promise-Rejektion im Log.
      document.documentElement.requestFullscreen?.().catch?.(() => setNotice(
        "Vollbild wurde vom Fenster abgelehnt. Im eingebetteten Modus „In neuem Tab öffnen“ nutzen.",
      ));
    }
  }, []);

  // Vollbild-Zustand verfolgen, damit der Knopf anzeigt, ob das Fenster
  // bereits im Vollbild laeuft (Esc verlaesst es ohnehin).
  useEffect(() => {
    const sync = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  // Ungespeicherte Aenderungen vor dem Schliessen des Tabs schuetzen.
  useEffect(() => {
    const guard = (event) => {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  // Strg+S speichert wie die Schaltflaeche.
  useEffect(() => {
    const onKey = (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.key !== "s") return;
      if (document.querySelector(".deck-dialog-backdrop")) return;
      event.preventDefault();
      if (deckName) saveFile();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deckName, saveFile]);

  // Periodischer Revisionsabgleich: externe Aenderungen sichtbar machen,
  // ohne die Szene selbst anzufassen.
  useEffect(() => {
    if (!materialPath) return;
    const tick = async () => {
      if (document.hidden || !materialPathRef.current) return;
      try {
        const response = await fetch(`/api/deck/revision?path=${encodeURIComponent(materialPathRef.current)}`);
        if (!response.ok) return;
        const payload = await response.json();
        if (payload.revision !== deckRevisionRef.current) {
          setExternalRevision(payload.revision);
        } else {
          setExternalRevision(null);
        }
      } catch {
        return;
      }
    };
    const timer = setInterval(tick, REVISION_POLL_MS);
    return () => clearInterval(timer);
  }, [materialPath]);

  useEffect(() => {
    const onKey = (e) => {
      if (document.querySelector(".deck-dropup-panel, .deck-dialog-backdrop, .deck-math [role=dialog]")) return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement?.isContentEditable || e.ctrlKey || e.metaKey || e.altKey) return;
      if (toolRef.current === "selection" && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
      const forward = e.key === "PageDown" || (presenting && e.key === "ArrowRight");
      const back = e.key === "PageUp" || (presenting && e.key === "ArrowLeft");
      if (forward || back) {
        e.preventDefault();
        if (forward) next();
        else prev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev, presenting]);

  useEffect(() => {
    const onDrop = (e) => {
      e.preventDefault();
      const file = e.dataTransfer?.files?.[0];
      if (file && file.name.endsWith(".excalidraw")) {
        loadFile(file);
      }
    };
    const onDragOver = (e) => e.preventDefault();
    window.addEventListener("drop", onDrop);
    window.addEventListener("dragover", onDragOver);
    return () => {
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragover", onDragOver);
    };
  }, [loadFile]);

  const onFilePicked = (e) => {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
    e.target.value = "";
  };

  // Eigene Kamera-Gesten: Excalidraw sperrt Pinch bei freedraw + penMode.
  const penObservationRef = useRef(null);
  const touchContactsRef = useRef(new Map());
  const panGestureRef = useRef(null);
  const touchCamera = () => {
    const points = [...touchContactsRef.current.values()].slice(0, 2);
    const state = apiRef.current?.getAppState();
    if (!points.length || !state) { panGestureRef.current = null; return; }
    const center = points.length === 2
      ? { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 }
      : points[0];
    panGestureRef.current = { center, distance: points.length === 2 ? Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) : 0,
      zoom: state.zoom.value, scrollX: state.scrollX, scrollY: state.scrollY };
  };
  const onCanvasPointerDown = useCallback((e) => {
    const container = e.target?.closest?.(".excalidraw");
    if (!container) return;
    const active = apiRef.current?.getAppState();
    if (e.pointerType === "touch" && penModeRef.current &&
        !["selection", "text", "image", "hand"].includes(active?.activeTool?.type ?? "selection")) {
      touchContactsRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      touchCamera();
      e.preventDefault();
      e.stopPropagation();
    }
    setTimeout(() => container.focus(), 0);
  }, []);

  useEffect(() => {
    const onPanMove = (e) => {
      if (!touchContactsRef.current.has(e.pointerId)) return;
      touchContactsRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const gesture = panGestureRef.current, api = apiRef.current;
      if (!gesture || !api) return;
      e.preventDefault(); e.stopPropagation();
      const points = [...touchContactsRef.current.values()].slice(0, 2);
      const center = points.length === 2
        ? { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 } : points[0];
      const distance = points.length === 2 ? Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) : 0;
      const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, gesture.zoom * (gesture.distance ? distance / gesture.distance : 1)));
      const state = api.getAppState();
      api.updateScene({ appState: {
        zoom: { value: zoom },
        scrollX: gesture.scrollX + (center.x - state.offsetLeft) / zoom - (gesture.center.x - state.offsetLeft) / gesture.zoom,
        scrollY: gesture.scrollY + (center.y - state.offsetTop) / zoom - (gesture.center.y - state.offsetTop) / gesture.zoom,
      } });
    };
    const onPanEnd = (e) => {
      if (!touchContactsRef.current.delete(e.pointerId)) return;
      e.stopPropagation();
      touchCamera();
    };
    window.addEventListener("pointermove", onPanMove, { passive: false, capture: true });
    window.addEventListener("pointerup", onPanEnd, true);
    window.addEventListener("pointercancel", onPanEnd, true);
    return () => {
      window.removeEventListener("pointermove", onPanMove, true);
      window.removeEventListener("pointerup", onPanEnd, true);
      window.removeEventListener("pointercancel", onPanEnd, true);
    };
  }, []);

  const currentFrame = slides[index];
  const revealed = revealedSteps[currentFrame?.id] ?? 0;
  useEffect(() => {
    projectionRef.current.configure({ presenting, isolate: isolateSlide, frame: currentFrame, revealed, revealedByFrame: revealedSteps });
    projectionRef.current.refresh(CaptureUpdateAction.NEVER);
    nativeApiRef.current?.updateScene({ appState: { frameRendering: { enabled: true, name: !presenting, outline: !presenting, clip: !presenting } } });
  }, [presenting, isolateSlide, currentFrame, revealed, revealedSteps]);
  useEffect(() => { if (presenting && indexRef.current >= 0) goTo(indexRef.current); }, [overviewOpen, goTo, presenting]);

  const makeScene = () => serializeAsJSON(apiRef.current.getSceneElements().map((el) => backgroundIdsRef.current.has(el.id)
    ? el : { ...el, customData: { ...el.customData, presenterAnnotation: true } }), apiRef.current.getAppState(), apiRef.current.getFiles(), "local");
  const drafts = useLocalDraft({ identity: draftIdentity, revision: deckRevisionRef.current, dirty,
    api: apiRef.current, sceneRevision: drawingState.sceneRevision, makeScene, name: deckName, restoredKey: restoredDraftKey });
  draftControlsRef.current = drafts;
  const recoveryDraft = drafts.candidate ?? startupDraft;
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("path")) return;
    let cancelled = false;
    draftOperation("readonly", (store) => store.getAll()).then((all) => {
      if (!cancelled && !loadedDeckRef.current) setStartupDraft(all.filter((draft) => draft.key.startsWith("local:")).sort((a, b) => b.savedAt - a.savedAt)[0] ?? null);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const dismissDraft = async () => {
    if (startupDraft) { await draftOperation("readwrite", (store) => store.delete(startupDraft.key)).catch(() => {}); setStartupDraft(null); }
    else await drafts.dismiss();
  };
  const restoreDraft = () => {
    try {
      const data = validateScene(JSON.parse(recoveryDraft.scene));
      setRestoredDraftKey(recoveryDraft.key);
      if (startupDraft) {
        applyScene(data, recoveryDraft.name || "Wiederhergestellt.excalidraw", { dirty: true, draftIdentity: recoveryDraft.key });
        setStartupDraft(null);
        return;
      }
      apiRef.current.addFiles(Object.values(data.files ?? {}));
      apiRef.current.updateScene({ elements: restoreDeckElements(data.elements), captureUpdate: CaptureUpdateAction.IMMEDIATELY });
      drafts.accept();
      setNotice("Lokaler Entwurf wiederhergestellt. Bitte speichern.");
      setTimeout(() => goTo(0), 50);
    } catch { setLoadError("Der lokale Entwurf konnte nicht wiederhergestellt werden."); }
  };
  const editScene = (elements, full = false) => {
    if (full && materialPathRef.current) {
      setAnnotationsMode(false);
      setNotice("Folieninhalt geändert: Bitte das gesamte Deck speichern.");
    }
    let previous = new Map(apiRef.current.getSceneElementsIncludingDeleted().map((el) => [el.id, el]));
    const metadataBase = new Set(elements.filter((el) => previous.has(el.id) && previous.get(el.id) !== el && previous.get(el.id).customData == null).map((el) => el.id));
    if (metadataBase.size) {
      // Native neue Elemente haben noch keine Metadaten. Eine leere Basis
      // separat committen: Excalidraw kann beim Undo fehlende Eigenschaften
      // nicht verlaesslich von neu gesetzten customData zurueck auf undefined setzen.
      flushSync(() => apiRef.current.updateScene({ elements: [...previous.values()].map((el) => metadataBase.has(el.id)
        ? { ...el, customData: {}, version: el.version + 1, versionNonce: Math.floor(Math.random() * 2 ** 31) } : el), captureUpdate: CaptureUpdateAction.NEVER }));
      previous = new Map(apiRef.current.getSceneElementsIncludingDeleted().map((el) => [el.id, el]));
    }
    const changed = elements.map((el) => previous.get(el.id) === el ? el : { ...el,
      version: Math.max(el.version ?? 1, (previous.get(el.id)?.version ?? 0) + 1),
      versionNonce: Math.floor(Math.random() * 2 ** 31) });
    apiRef.current.updateScene({ elements: restoreDeckElements(changed), captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  };
  const orderFrames = (ordered, extra = []) => {
    const positions = new Map(ordered.map((frame, i) => [frame.id, i]));
    const activeId = slidesRef.current[indexRef.current]?.id;
    editScene([...apiRef.current.getSceneElements(), ...extra].map((el) => positions.has(el.id) ? { ...el, version: el.version + 1,
      customData: { ...el.customData, presentationOrder: positions.get(el.id), insertAfter: undefined } } : el), true);
    setTimeout(() => goTo(ordered.findIndex((frame) => frame.id === activeId)), 0);
  };
  const renameSlide = (id, name) => editScene(apiRef.current.getSceneElements().map((el) => el.id === id ? { ...el, name, version: el.version + 1 } : el), deckIdsRef.current.has(id));
  const insertWorksheetFragment = (fragment, newPage, solution) => {
    const api = apiRef.current;
    if (!api || savingRef.current) throw new Error("Bitte den Speichervorgang abwarten.");
    let elements = [...api.getSceneElementsIncludingDeleted()];
    let frame = slidesRef.current[indexRef.current];
    if (newPage) {
      elements = [...elements, ...newSlide(elements.filter(el => !el.isDeleted), frame, false)];
      frame = elements.at(-1);
    }
    if (!frame) throw new Error("Bitte zuerst eine Zeichenfläche öffnen.");
    const members = elements.filter(el => !el.isDeleted && el.type !== "frame" && !el.customData?.slideBackground && belongsToSlide(el, frame));
    const width = Math.min(frame.width - 80, 1000, fragment.width / 2);
    const height = fragment.height * width / fragment.width;
    const id = crypto.randomUUID(), fileId = crypto.randomUUID();
    const image = { id, type: "image", fileId, status: "saved", scale: [1, 1],
      x: frame.x + 40, y: Math.max(frame.y + 40, ...members.map(el => el.y + el.height + 40)),
      width, height, frameId: frame.id === CANVAS_SLIDE_ID ? null : frame.id,
      customData: { ...fragment.metadata, presenterAnnotation: true,
        ...(frame.id !== CANVAS_SLIDE_ID ? { annotationSlide: frame.id } : {}),
        ...(solution ? { solutionStep: 1 } : {}) } };
    api.addFiles([{ id: fileId, dataURL: fragment.image, mimeType: "image/png", created: Date.now() }]);
    // Insert into the live scene: no reload, history reset or server-side deck mutation.
    editScene([...elements, image]);
    if (solution) setRevealedSteps(old => ({ ...old, [frame.id]: Math.max(old[frame.id] || 0, 1) }));
    chooseTool("selection");
    const frameId = frame.id;
    setTimeout(() => {
      const position = slidesRef.current.findIndex(f => f.id === frameId);
      if (newPage && position >= 0) goTo(position);
      api.updateScene({ appState: { selectedElementIds: { [id]: true } }, captureUpdate: CaptureUpdateAction.NEVER });
      api.scrollToContent(api.getSceneElements().filter(el => el.id === id), { fitToContent: true });
    }, 0);
  };
  const moveSlide = (position, direction) => {
    const ordered = [...slidesRef.current];
    const target = position + direction;
    if (target < 0 || target >= ordered.length) return;
    [ordered[position], ordered[target]] = [ordered[target], ordered[position]];
    orderFrames(ordered);
  };
  const dropSlide = (id, target) => {
    if (id === target || !slidesRef.current.some((frame) => frame.id === id)) return;
    const ordered = slidesRef.current.filter((frame) => frame.id !== id);
    ordered.splice(ordered.findIndex((frame) => frame.id === target), 0, slidesRef.current.find((frame) => frame.id === id));
    orderFrames(ordered);
  };
  const cloneSlide = (id) => {
    const source = slidesRef.current.find((frame) => frame.id === id);
    if (!source || id === CANVAS_SLIDE_ID) return;
    const added = restoreElements(duplicateSlide(apiRef.current.getSceneElements(), source, (el) => isBackground(el, backgroundIdsRef.current)), null);
    const clone = added.find((el) => el.type === "frame");
    const ordered = [...slidesRef.current];
    ordered.splice(ordered.findIndex((frame) => frame.id === id) + 1, 0, clone);
    orderFrames(ordered, added);
  };
  const assignSolution = (step) => {
    const selected = apiRef.current.getAppState().selectedElementIds;
    const selectedElements = apiRef.current.getSceneElements().filter((el) => selected[el.id] && el.type !== "frame" && !el.customData?.slideBackground);
    const ids = new Set(selectedElements.map((el) => el.id));
    const groups = new Set(selectedElements.flatMap((el) => el.groupIds));
    let added = true;
    while (added) {
      added = false;
      for (const el of apiRef.current.getSceneElements()) {
        if (!ids.has(el.id) && ((el.containerId && ids.has(el.containerId)) || el.groupIds.some((group) => groups.has(group)))) {
          ids.add(el.id); added = true;
        }
        if (ids.has(el.id)) for (const bound of el.boundElements ?? []) {
          if (!ids.has(bound.id)) { ids.add(bound.id); added = true; }
        }
      }
    }
    editScene(apiRef.current.getSceneElements().map((el) => ids.has(el.id) ? { ...el, version: el.version + 1,
      customData: { ...el.customData, solutionStep: step } } : el), selectedElements.some((el) => deckIdsRef.current.has(el.id)));
  };
  const applyPaper = (paper, inserted = false) => {
    if (inserted) {
      insertSlide(paper.kind);
      const frame = slidesRef.current[indexRef.current];
      if (frame) setTimeout(() => replacePaper(frame.id, paper), 0);
    } else if (currentFrame?.id !== CANVAS_SLIDE_ID) replacePaper(currentFrame?.id, paper);
  };
  const replacePaper = (id, paper) => {
    const frame = apiRef.current.getSceneElements().find((el) => el.id === id);
    if (!frame) return;
    const background = restoreElements(paperElements(frame, paper.kind, paper.spacing, paper.axisStep), null);
    const files = paperFiles(frame, paper.kind, paper.spacing);
    if (files.length) apiRef.current.addFiles(files);
    const kept = apiRef.current.getSceneElements().filter((el) => !(el.frameId === id && el.customData?.slideBackground));
    const fullTemplates = kept.map((el, i) => ({ el, i })).filter(({ el }) => el.frameId === id && ["image", "rectangle"].includes(el.type)
      && Math.abs(el.x - frame.x) < 2 && Math.abs(el.y - frame.y) < 2 && Math.abs(el.width - frame.width) < 2 && Math.abs(el.height - frame.height) < 2);
    const place = fullTemplates.length ? fullTemplates.at(-1).i + 1 : kept.findIndex((el) => el.id === id || el.frameId === id);
    kept.splice(Math.max(0, place), 0, ...background);
    editScene(kept.map((el) => el.id === id ? { ...el, version: el.version + 1, customData: { ...el.customData, paper } } : el), deckIdsRef.current.has(id));
  };
  const exportPdf = async (solutions) => {
    if (exportBusy || !slidesRef.current.length) return;
    setExportBusy("Vorbereiten …");
    try {
      const { exportLesson } = await import("./lesson-export");
      await exportLesson({ elements: structuredClone(apiRef.current.getSceneElements()), slides: structuredClone(slidesRef.current),
        files: apiRef.current.getFiles(), appState: apiRef.current.getAppState(), solutions, name: deckName, progress: setExportBusy });
    } catch { setLoadError("PDF konnte nicht erstellt werden. Bitte erneut versuchen."); }
    finally { setExportBusy(null); }
  };

  const modalOpen = !!(pendingSceneChange || conflict || historyOpen || recoveryDraft);
  useEffect(() => {
    if (!modalOpen) return;
    const previous = document.activeElement;
    const dialogs = document.querySelectorAll(".deck-dialog");
    const dialog = dialogs[dialogs.length - 1];
    (dialog?.querySelector("[data-initial-focus]") ?? dialog?.querySelector("button:not(:disabled)"))?.focus();
    const trap = (event) => {
      if (event.key === "Escape" && !recoveryDraft) {
        event.preventDefault(); event.stopPropagation();
        setPendingSceneChange(null); setConflict(null); setHistoryOpen(false);
      }
      if (event.key !== "Tab" || !dialog) return;
      const targets = [...dialog.querySelectorAll("button:not(:disabled), input, [tabindex='0']")];
      if (!targets.length) return;
      const first = targets[0], last = targets.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => { document.removeEventListener("keydown", trap); if (previous?.isConnected) previous.focus(); };
  }, [modalOpen, !!pendingSceneChange, !!recoveryDraft]);

  const saveTitle = materialPath
    ? annotationsMode
      ? "Nur Anmerkungen separat speichern (Strg+S); das Deck bleibt unberührt"
      : "Gesamte Szene in die Deck-Datei speichern (Strg+S)"
    : "Als .excalidraw speichern (Strg+S)";
  const saveLabel =
    saveState === "saving"
      ? "Speichert …"
      : saveState === "saved"
        ? dirty ? "Neuere Änderungen" : "Gespeichert"
        : saveState === "error"
          ? "Fehler"
          : materialPath && annotationsMode
            ? "Anmerkungen speichern"
            : "Speichern";

  const counter = (
    <span className="deck-counter">
      {slides.length === 0 ? "-" : `${index + 1} / ${slides.length}`}
    </span>
  );

  const materialExtras = materialPath ? (
    <>
      <button
        onClick={toggleAnnotationsMode}
        disabled={saveState === "saving"}
        aria-pressed={annotationsMode}
        title={
          annotationsMode
            ? "Anmerkungen separat speichern: nur Anmerkungen werden gespeichert, das Deck bleibt unberührt"
            : "In Deck speichern: die gesamte Szene wird in die Deck-Datei geschrieben"
        }
        className={annotationsMode ? "active" : undefined}
      >
        <Icon name="save" /><span className="deck-sr-only">Anmerkungen separat</span>
      </button>
      <button onClick={openHistory} title="Frühere Fassungen der Deck-Datei laden">
        <Icon name="undo" /><span className="deck-sr-only">Versionen</span>
      </button>
    </>
  ) : null;

  const saveButton = (
    <button onClick={() => saveFile()} disabled={!deckName || saveState === "saving"} title={saveTitle}>
      <Icon name="save" /><span className={saveState ? "deck-save-status" : "deck-sr-only"}>{saveLabel}</span>
      {dirty && <span className="deck-dirty-dot" aria-label="Ungespeicherte Änderungen" title="Ungespeicherte Änderungen" />}
    </button>
  );

  return (
    <div className={presenting ? "presenting" : ""} style={{ width: "100%", height: "100%" }}>
      <div style={{ width: "100%", height: "100%" }} onPointerDownCapture={onCanvasPointerDown}>
      <Excalidraw
        initialData={INITIAL_DATA}
        excalidrawAPI={(api) => {
          if (nativeApiRef.current !== api) {
            nativeApiRef.current = api;
            apiRef.current = projectionRef.current.bind(api);
          }
          // Test-Hook fuer smoke_test.py (Szenen- und App-State-Pruefungen).
          window.__excalidraw = apiRef.current;
          window.__excalidrawNative = api;
        }}
        onPointerDown={(active, pointer) => {
          const view = projectionRef.current.settings;
          if (active.type === "freedraw" && view.presenting && view.frame && view.frame.id !== CANVAS_SLIDE_ID) {
            projectionRef.current.drawing = { frameId: view.frame.id, known: new Set(pointer.originalElements.keys()) };
          }
        }}
        onPointerUp={() => {
          const drawing = projectionRef.current.drawing;
          if (!drawing) return;
          // Excalidraw finalisiert Punkte und History erst nach diesem Callback.
          queueMicrotask(() => {
            const api = apiRef.current;
            const elements = api.getSceneElementsIncludingDeleted();
            const completed = elements.map((el) => el.type === "freedraw" && !el.isDeleted && !drawing.known.has(el.id)
              ? { ...el, frameId: drawing.frameId, customData: { ...el.customData, annotationSlide: drawing.frameId },
                  version: el.version + 1, versionNonce: Math.floor(Math.random() * 2 ** 31) } : el);
            projectionRef.current.drawing = null;
            api.updateScene({ elements: completed, captureUpdate: CaptureUpdateAction.NEVER });
          });
        }}
        onChange={(renderedElements, appState) => {
          const elements = projectionRef.current.decode(renderedElements);
          // Ungespeichert-Indikator: Szenenstand gegen den letzten gesicherten
          // Stand vergleichen; Werkzeugwechsel aendern die Szene nicht.
          const elementsChanged = !sameSceneVersion(elements, lastElementsRef.current);
          if (baselinePendingRef.current) {
            if (!pendingDirtyRef.current) savedElementsRef.current = captureScene(elements.filter((el) => !el.isDeleted));
            baselinePendingRef.current = false;
            setDirtyState(pendingDirtyRef.current);
            pendingDirtyRef.current = false;
          } else if (elementsChanged) {
            setDirtyState(!sameContent(elements.filter((el) => !el.isDeleted), savedElementsRef.current));
          }
          if (elementsChanged) {
            lastElementsRef.current = captureScene(elements);
            sceneRevisionRef.current += 1;
            const frames = sortSlides(elements.filter((el) => el.type === "frame" && !el.isDeleted));
            const current = frames.length ? frames : [canvasSlide(elements)];
            const activeId = slidesRef.current[indexRef.current]?.id;
            const activePosition = current.findIndex((frame) => frame.id === activeId);
            if (!sameReferences(current, slidesRef.current)) setSlides(current);
            slidesRef.current = current;
            if (activePosition >= 0 && activePosition !== indexRef.current) {
              indexRef.current = activePosition;
              setIndex(activePosition);
            }
            setFrameless(!frames.length);
            if (indexRef.current >= current.length) {
              indexRef.current = current.length - 1;
              setIndex(indexRef.current);
            }
            const backgrounds = elements.filter((el) => !el.isDeleted && isBackground(el, backgroundIdsRef.current));
            setProtectedBackground(backgrounds.length > 0 && backgrounds.every((el) => el.locked));
          }
          // Werkzeug-Status nachfuehren (z. B. Wechsel nach Texteingabe oder
          // Kuerzel), damit die Palette das aktive Werkzeug anzeigt.
          const active = appState.activeTool?.type;
          const toolChanged = active && active !== toolRef.current;
          if (toolChanged) {
            if (profileKey(active, false)) switchingProfileRef.current = true;
            if (active === "freedraw" && !markerRef.current) restoringPenRef.current = true;
            toolRef.current = active;
            setTool(active);
            if (active !== "freedraw") {
              markerRef.current = false;
              setMarker(false);
            }
          }
          // penMode nachfuehren: Excalidraw aktiviert die Handballen-Erkennung
          // automatisch beim ersten Stift-Kontakt, der Knopf muss das spiegeln.
          penModeRef.current = appState.penMode ?? false;
          setPenMode(penModeRef.current);
          const nextDrawing = Object.fromEntries(Object.entries(appState).filter(([key]) => key.startsWith("currentItem") || key === "selectedElementIds"));
          nextDrawing.view = { scrollX: appState.scrollX, scrollY: appState.scrollY, zoom: appState.zoom, offsetLeft: appState.offsetLeft, offsetTop: appState.offsetTop };
          nextDrawing.activeToolLocked = appState.activeTool.locked;
          nextDrawing.sceneRevision = sceneRevisionRef.current;
          setDrawingState((previous) => JSON.stringify(previous) === JSON.stringify(nextDrawing) ? previous : nextDrawing);
          setPenColor(appState.currentItemStrokeColor);
          if (["line", "arrow"].includes(active) && !toolChanged && !switchingProfileRef.current) {
            continueLinesRef.current = !!appState.activeTool.locked;
            setContinueLines(continueLinesRef.current);
          }
          const currentProfile = profileKey(active, markerRef.current);
          const observation = penObservationRef.current;
          const penActive = currentProfile === "pen";
          const currentZoom = appState.zoom?.value || 1;
          if (penActive && observation?.pen && observation.zoom === currentZoom &&
              Math.abs(observation.width - appState.currentItemStrokeWidth) > 1e-9 &&
              !toolChanged && !switchingProfileRef.current && !restoringPenRef.current) {
            // Native Editor-Stärkenwahl ist eine ausdrückliche Profiländerung.
            penWidthRef.current = appState.currentItemStrokeWidth * currentZoom;
          }
          penObservationRef.current = { pen: penActive, zoom: currentZoom, width: appState.currentItemStrokeWidth };
          if (currentProfile && !toolChanged && !switchingProfileRef.current && !restoringPenRef.current) {
            profiles.update(currentProfile, { strokeColor: appState.currentItemStrokeColor,
              strokeWidth: currentProfile === "pen" ? penWidthRef.current : appState.currentItemStrokeWidth, opacity: appState.currentItemOpacity,
              strokeStyle: appState.currentItemStrokeStyle, roughness: appState.currentItemRoughness });
          }
          if (elementsChanged) queueMicrotask(() => projectionRef.current.refresh(CaptureUpdateAction.NEVER));
          // Die gemeinsame Excalidraw-Breite gehoert nur bei aktivem Stift
          // zur Stift-Voreinstellung, niemals bei Marker oder anderen Tools.
          if (active === "freedraw" && !markerRef.current && !toolChanged && !restoringPenRef.current && !switchingProfileRef.current) {
            setPenWidth(penWidthRef.current);
            const sceneWidth = penWidthRef.current / (appState.zoom?.value || 1);
            if (Math.abs(appState.currentItemStrokeWidth - sceneWidth) > 1e-9) {
              apiRef.current?.updateScene({ appState: { currentItemStrokeWidth: sceneWidth } });
            }
          }
          // Zoom-Anzeige nachfuehren (Strg+Rad, Knopfe, Folienwechsel).
          setZoom(appState.zoom?.value ?? 1);
        }}
        UIOptions={UI_OPTIONS}
      />
      </div>
      <div className="deck-live-status deck-sr-only" role="status" aria-live="polite">{saveState === "saved" && dirty ? "Gespeichert. Neuere Änderungen sind noch ungespeichert." : saveState ? saveLabel : ""}</div>
      {notice && <div className="deck-notice" role="status"><span>{notice}</span><button aria-label="Hinweis schließen" onClick={() => setNotice(null)}>×</button></div>}
      {pendingSceneChange && <div className="deck-dialog-backdrop"><div className="deck-dialog" role="alertdialog" aria-modal="true" aria-labelledby="sceneChangeTitle">
        <strong id="sceneChangeTitle">Diese Folie hat noch ungespeicherte Änderungen</strong>
        <p>Vor dem Wechsel entscheiden, was mit diesen Änderungen passieren soll. „Auf dieser Folie bleiben“ verlässt die Slide-Ansicht nicht.</p>
        <div className="deck-dialog-actions">
          <button autoFocus data-initial-focus className="deck-dialog-safe" onClick={() => setPendingSceneChange(null)}>Auf dieser Folie bleiben</button>
          <button onClick={async () => { const action = pendingSceneChange.action; drafts.cancel(); await drafts.clearSaved(); setPendingSceneChange(null); action(); }}>Verwerfen und wechseln</button>
          <button disabled={saveState === "saving"} onClick={async () => { const action = pendingSceneChange.action; if (await saveFile() && !dirtyRef.current) { setPendingSceneChange(null); action(); } else setPendingSceneChange(null); }}>Speichern und wechseln</button>
        </div>
        <p className="deck-dialog-hint">„Auf dieser Folie bleiben“ schließt dieses Fenster: Die Slide-Ansicht bleibt unverändert, die Zeichnungen bleiben auf der Folie. „Verwerfen und wechseln“ löscht sie endgültig.</p>
      </div></div>}
      {externalRevision && !conflict && (
        <div className="deck-notice" role="status">
          <span>Deck wurde außerhalb dieser App neu gebaut. Deine Anmerkungen lassen sich weiterhin speichern und wandern mit auf die neue Fassung; „Neu laden“ zeigt die neuen Folieninhalte.</span>
          <button onClick={reloadDeck}>Neu laden</button>
        </div>
      )}
      {frameless && slides.length > 0 && (
        <div className="deck-frameless-hint" role="status">
          Keine Frames – die gesamte Leinwand ist eine Folie.
        </div>
      )}
      {conflict && !pendingSceneChange && (
        <div className="deck-dialog-backdrop">
          <div className="deck-dialog" role="alertdialog" aria-modal="true">
            <strong>
              {conflict.target === "annotations-deck"
                ? "Deck wurde neu gebaut oder geändert"
                : conflict.target === "deck"
                ? "Deck-Datei wurde zwischenzeitlich geändert"
                : "Anmerkungen wurden zwischenzeitlich geändert"}
            </strong>
            <p>
              {conflict.target === "annotations-deck"
                ? "Deine lokalen Anmerkungen gehören zur alten Deck-Fassung. Sichere sie als Datei, bevor du das neue Deck lädst."
                : conflict.target === "deck"
                ? "Die Datei wurde in einem anderen Fenster oder Programm geändert. Die fremde Fassung ist automatisch in der Versionshistorie gesichert."
                : "Die gespeicherten Anmerkungen wurden in einem anderen Fenster oder Programm geändert."}
            </p>
            <p className="deck-dialog-hint">
              „Weiter präsentieren“ schließt dieses Fenster: Die Slide-Ansicht bleibt mit allen Zeichnungen unverändert.
              Deine Anmerkungen sind als lokale Sicherung erhalten und beim nächsten Start der Folien wiederherstellbar.
            </p>
            <div className="deck-dialog-actions">
              <button autoFocus data-initial-focus className="deck-dialog-safe" onClick={() => setConflict(null)}>Weiter präsentieren</button>
              <button onClick={reloadDeck}>Neu laden (verwirft lokale Änderungen)</button>
              {conflict.target === "annotations-deck"
                ? <button onClick={downloadLocalScene}>Lokale Fassung herunterladen</button>
                : <button onClick={overwriteConflict}>Trotzdem speichern</button>}
            </div>
          </div>
        </div>
      )}
      {historyOpen && !pendingSceneChange && (
        <div className="deck-dialog-backdrop">
          <div className="deck-dialog" role="dialog" aria-modal="true" aria-labelledby="deckHistoryTitle">
            <strong id="deckHistoryTitle">Versionen des Decks</strong>
            <p className="deck-dialog-hint">
              Automatisch gesicherte Fassungen der Deck-Datei. Laden ersetzt die aktuelle Szene;
              gespeichert wird erst anschließend.
            </p>
            <ul className="deck-history-list">
              {versions.length === 0 && (
                <li className="deck-dialog-hint">Noch keine gesicherten Fassungen.</li>
              )}
              {versions.map((version) => (
                <li key={version.id}>
                  <span>{new Date((version.created ?? 0) * 1000).toLocaleString("de-DE")}</span>
                  <button onClick={() => loadVersion(version.id)}>Laden</button>
                </li>
              ))}
            </ul>
            <div className="deck-dialog-actions">
              <button onClick={() => setHistoryOpen(false)}>Schließen</button>
            </div>
          </div>
        </div>
      )}
      {recoveryDraft && <div className="deck-dialog-backdrop"><div className="deck-dialog" role="alertdialog" aria-modal="true" aria-labelledby="draftTitle">
        <strong id="draftTitle">Lokalen Entwurf wiederherstellen?</strong><p>Es gibt eine automatische Sicherung vom {new Date(recoveryDraft.savedAt).toLocaleString("de-DE")}.</p>
        {recoveryDraft.revision && recoveryDraft.revision !== deckRevisionRef.current && <p>Die Deck-Datei wurde seit dieser Sicherung geändert. Wiederherstellen übernimmt den lokalen Entwurf.</p>}
        <div className="deck-dialog-actions"><button onClick={dismissDraft}>Entwurf verwerfen</button><button autoFocus data-initial-focus onClick={restoreDraft}>Entwurf wiederherstellen</button></div>
      </div></div>}
      {/* Vollbild-Knopf am oberen Rand: in der Praesentation ohne den Umweg
          ueber "Weitere Werkzeuge" erreichbar (der Editor hat seinen eigenen oben). */}
      {presenting && (
        <button
          className="deck-top-fullscreen"
          onClick={toggleFullscreen}
          aria-pressed={isFullscreen}
          title="Vollbild für den Beamer; Esc verlässt das Vollbild"
        >
          <Icon name="fullscreen" /><span className="deck-sr-only">Vollbild</span>
        </button>
      )}
      <div className={presenting ? "deck-toolbar deck-toolbar--present" : "deck-toolbar"}>
        <button aria-label="Folienübersicht" title="Folienübersicht" aria-expanded={overviewOpen} onClick={() => setOverviewOpen(!overviewOpen)}><Icon name="slides" /></button>
        {presenting ? (
          <>
            <div className="deck-toolbar-group">
              <button onClick={prev} disabled={index <= 0} title="PageUp / &larr;">
                &larr;
              </button>
              {counter}
              <button onClick={next} disabled={index < 0 || index >= slides.length - 1} title="PageDown / &rarr;">
                &rarr;
              </button>
            </div>
            <span className="deck-toolbar-sep" />
            <div className="deck-toolbar-group">
              <button
                onClick={choosePen}
                aria-pressed={tool === "freedraw" && !marker}
                title="Stift (Stylus zeichnet direkt auf die Folie)"
                className={tool === "freedraw" && !marker ? "active" : undefined}
              >
                <Icon name="pen" /><span className="deck-sr-only">Stift</span>
              </button>
              <button
                onClick={chooseMarker}
                aria-pressed={tool === "freedraw" && marker}
                title="Marker: dicker, halbtransparenter Strich"
                className={tool === "freedraw" && marker ? "active" : undefined}
              >
                <Icon name="marker" /><span className="deck-sr-only">Marker</span>
              </button>
              <button
                onClick={() => chooseTool("text")}
                aria-pressed={tool === "text"}
                title="Text auf die Folie schreiben"
                className={tool === "text" ? "active" : undefined}
              >
                Text
              </button>
              <button
                onClick={() => chooseTool("eraser")}
                aria-pressed={tool === "eraser"}
                title="Radierer"
                className={tool === "eraser" ? "active" : undefined}
              >
                <Icon name="eraser" /><span className="deck-sr-only">Radierer</span>
              </button>
              <button
                onClick={() => chooseTool("selection")}
                aria-pressed={tool === "selection"}
                title="Auswahl: Anmerkungen verschieben oder löschen"
                className={tool === "selection" ? "active" : undefined}
              >
                <Icon name="selection" /><span className="deck-sr-only">Auswahl</span>
              </button>
              <button
                onClick={() => chooseTool("hand")}
                aria-pressed={tool === "hand"}
                title="Verschieben: Leinwand mit gedrücktem Stift/Finger schieben, ohne zu zeichnen"
                className={tool === "hand" ? "active" : undefined}
              >
                <Icon name="hand" /><span className="deck-sr-only">Verschieben</span>
              </button>
            </div>
            <span className="deck-toolbar-sep" />
            <Dropup label="Stiftfarbe" color={penColor}>
              {PEN_COLORS.map((color) => (
                <button
                  key={color}
                  onClick={() => chooseColor(color)}
                  title={`Farbe ${color}`}
                  aria-label={`Farbe ${color}`}
                  aria-pressed={penColor === color}
                  className={`deck-color-dot${penColor === color ? " active" : ""}`}
                  style={{ background: color }}
                />
              ))}
              <div className="deck-favorites">{profiles.favorites.map((favorite, i) => <div key={i}>
                <button aria-label={`Lieblingsstift ${i + 1}`} title={`Lieblingsstift ${i + 1}`} onClick={() => { profiles.update("pen", favorite); choosePen(); }}><span style={{ color: favorite.strokeColor }}>✎</span> {i + 1}</button>
                <button aria-label={`Aktuellen Stift als Lieblingsstift ${i + 1} speichern`} disabled={tool !== "freedraw" || marker} onClick={() => { profiles.favorite(i); setNotice(`Lieblingsstift ${i + 1} gespeichert.`); }}>☆</button>
              </div>)}</div>
            </Dropup>
            <div className="deck-toolbar-group">
              {PEN_WIDTHS.map(({ width, label }) => (
                <button
                  key={width}
                  onClick={() => chooseWidth(width)}
                  title={`Strichstärke ${label.toLowerCase()}`}
                  aria-pressed={penWidth === width}
                  disabled={tool !== "freedraw" || marker}
                  className={`deck-width-btn${penWidth === width ? " active" : ""}`}
                >
                  <span className="deck-width-bar" style={{ height: Math.max(2, width) }} />
                  <span className="deck-sr-only">{label}</span>
                </button>
              ))}
            </div>
            <span className="deck-toolbar-sep" />
            <div className="deck-toolbar-group">
              <button onClick={undo} title="Rückgängig (Strg+Z)">
                <Icon name="undo" /><span className="deck-sr-only">Rückgängig</span>
              </button>
              <button onClick={redo} title="Wiederholen (Strg+Umschalt+Z)">
                <Icon name="redo" /><span className="deck-sr-only">Wiederholen</span>
              </button>
            </div>
            <span className="deck-toolbar-sep" />
            <div className="deck-toolbar-group">
              <Dropup label="Formen" icon="shapes">{(close) => <div className="deck-shapes">{[
                ["rectangle", "▭", "Rechteck"], ["ellipse", "◯", "Ellipse / Kreis"], ["diamond", "◇", "Raute"], ["line", "╱", "Linie"], ["arrow", "↗", "Pfeil"],
              ].map(([type, symbol, label]) => <button key={type} title={label} aria-label={label} aria-pressed={tool === type} onClick={() => { chooseTool(type); close(); }}>{symbol}</button>)}<small>Umschalt: Kreis, Quadrat oder feste Winkel. Linien/Pfeile bleiben mit „Weiterzeichnen“ aktiv.</small></div>}</Dropup>
              {["line", "arrow"].includes(tool) && <button className="deck-continue-lines" aria-label="Linienwerkzeug beibehalten"
                title="Weiterzeichnen: mehrere Linien oder Pfeile nacheinander. Zum Beenden Auswahl oder Esc wählen."
                aria-pressed={drawingState.activeToolLocked ?? continueLines} onClick={toggleContinueLines}>
                <Icon name="lock" /><span>Weiterzeichnen</span>
              </button>}
              <Dropup label="Zeichenoptionen" icon="settings"><DrawingOptions api={apiRef.current} state={drawingState} shortcut={historyKey} tool={tool} penScreenWidth={tool === "freedraw" && !marker ? penWidth : null} onPenWidth={chooseWidth} /></Dropup>
              <Dropup label="Folie einfügen" icon="plus">{(close) => <><strong>Nach aktueller Folie einfügen</strong><button onClick={() => { insertSlide(false); close(); }}>▭ Leerfolie</button><button onClick={() => { insertSlide(true); close(); }}>▦ Rechenkästchen</button></>}</Dropup>
              <button title="Bild aus Zwischenablage einfügen (Strg+V)" aria-label="Bild einfügen" onClick={pasteImage}><Icon name="clipboard" /></button>
              <Dropup label="Geometriehilfen" icon="ruler">{(close) => <>{[["ruler", "Lineal"], ["triangle", "Geodreieck"], ["compass", "Zirkel"]].map(([kind, label]) => <button key={kind} onClick={() => { setGeometry(kind); close(); }}>{label}</button>)}</>}</Dropup>
              <button title="ExcaliMath: Formeln, Graphen und STEM-Formen" aria-label="ExcaliMath" aria-pressed={mathOpen} onClick={() => setMathOpen(!mathOpen)}>∑</button>
            </div>
            <div className="deck-toolbar-group">
              {saveButton}
              <Dropup label="Weitere Werkzeuge" icon="settings">{(close) => <div className="deck-more-tools" onClick={(event) => { if (event.target.closest("button")) close(); }}>
              <button
                onClick={() => chooseTool("laser")}
                aria-pressed={tool === "laser"}
                title="Laserpointer: verblasst und wird nicht gespeichert"
                className={tool === "laser" ? "active" : undefined}
              >
                Laser
              </button>
              <button
                onClick={togglePenMode}
                aria-pressed={penMode}
                title="Handballen-Erkennung: nur der Stift zeichnet, der Finger verschiebt die Folie – abschalten, damit der Finger zeichnet (z. B. ohne Stift)"
                className={penMode ? "active" : undefined}
              >
                Handballen
              </button>
              <button onClick={clearSlide} title="Stiftstriche auf dieser Folie löschen">
                <Icon name="trash" /><span className="deck-sr-only">Stiftstriche löschen</span>
              </button>
              <button title="Folienhintergrund schützen" aria-label="Folienhintergrund schützen" aria-pressed={protectedBackground} className={protectedBackground ? "active" : ""} onClick={toggleBackground}><Icon name="lock" /></button>
              <button aria-label="Nur aktuelle Folie zeigen" aria-pressed={isolateSlide} onClick={() => setIsolateSlide(!isolateSlide)}>Nur aktuelle Folie</button>
                {materialExtras}
              <button onClick={toggleFullscreen} title="Vollbild">
                <Icon name="fullscreen" /><span className="deck-sr-only">Vollbild</span>
              </button>
              <button onClick={exitPresenting} title="Editor-Werkzeuge anzeigen">
                Bearbeiten
              </button>
              </div>}</Dropup>
            </div>
          </>
        ) : (
          <>
            <button className="deck-open-label" title=".excalidraw oeffnen oder hierher ziehen" onClick={() => fileInputRef.current?.click()}>Öffnen</button>
            <input ref={fileInputRef} type="file" accept=".excalidraw" onChange={onFilePicked} hidden />
            <button onClick={prev} disabled={index <= 0} title="PageUp">
              &larr;
            </button>
            {counter}
            <button onClick={next} disabled={index < 0 || index >= slides.length - 1} title="PageDown">
              &rarr;
            </button>
            <button onClick={() => goTo(indexRef.current)} title="Folie einpassen">
              Fit
            </button>
            {materialExtras}
            {saveButton}
            <button onClick={toggleFullscreen} title="Vollbild">
              <Icon name="fullscreen" /><span className="deck-sr-only">Vollbild</span>
            </button>
            <button
              onClick={() => {
                setPresenting(true);
                choosePen();
              }}
              title="Präsentationsmodus starten"
            >
              Präsentieren
            </button>
          </>
        )}
      </div>
      {overviewOpen && apiRef.current && <SlideOverview api={apiRef.current} slides={slides} index={index} revision={drawingState.sceneRevision}
        close={() => setOverviewOpen(false)} goTo={(position) => { goTo(position); if (window.innerWidth < 700) setOverviewOpen(false); }} rename={renameSlide} move={moveSlide} duplicate={cloneSlide} drop={dropSlide} />}
      {presenting && (
        <div className="deck-zoom" role="group" aria-label="Zoom">
          <button onClick={zoomOut} disabled={zoom <= MIN_ZOOM} title="Herauszoomen (Strg+-)">
            -
          </button>
          <button
            onClick={resetZoom}
            className="deck-zoom-value"
            title="Zoom auf 100 % zurücksetzen (Strg+0)"
          >
            {Math.round(zoom * 100)} %
          </button>
          <button onClick={zoomIn} disabled={zoom >= MAX_ZOOM} title="Hineinzoomen (Strg+ +)">
            +
          </button>
          <button onClick={fitSlide} title="Aktuelle Folie einpassen">
            Fit
          </button>
        </div>
      )}
      {geometry && <GeometryGuide key={`${geometry}:${slides[index]?.id}`} kind={geometry} api={apiRef.current} frame={slides[index]} view={drawingState.view} close={() => setGeometry(null)} />}
      {mathOpen && <FeatureBoundary close={() => setMathOpen(false)}><Suspense fallback={<div className="deck-notice">ExcaliMath lädt …</div>}><MathTools api={apiRef.current} frame={slides[index]} close={() => setMathOpen(false)} /></Suspense></FeatureBoundary>}
      {apiRef.current && deckName && <div className={`deck-lesson-tools${presenting ? "" : " deck-lesson-tools--editor"}`}>
        {worksheetOwner && <button onClick={() => setWorksheetImportOpen(true)}>Aus AB einfügen</button>}
        <Dropup label="Lösungsschritte" icon="reveal"><SolutionPanel api={apiRef.current} frame={currentFrame} revealed={revealed} revision={drawingState.sceneRevision}
          change={(value) => setRevealedSteps((old) => ({ ...old, [currentFrame?.id]: value }))} assign={assignSolution} /></Dropup>
        <Dropup label="Hintergründe" icon="grid"><BackgroundPanel apply={(paper) => applyPaper(paper)} insert={(paper) => applyPaper(paper, true)} /></Dropup>
        <Dropup label="PDF exportieren" icon="export"><ExportPanel busy={exportBusy} exportPdf={exportPdf} /></Dropup>
      </div>}
      {worksheetImportOpen && worksheetOwner && <WorksheetImport owner={worksheetOwner} insert={insertWorksheetFragment} close={() => setWorksheetImportOpen(false)} />}
      {drafts.status && <div className="deck-draft-status" role="status">{drafts.status}</div>}
      {deckName && <div className="deck-name">{deckName}</div>}
      {loadError && <div className="deck-error">{loadError}</div>}
    </div>
  );
}
