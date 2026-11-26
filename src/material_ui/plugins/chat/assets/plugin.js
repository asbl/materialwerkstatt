// Chat-Plugin (Frontend): verdrahtet das Chat-Dock (HTML-Slot im Kern-Template)
// mit dem Chat-Panel-Controller und meldet den Controller beim Kern an.

import { createChatPanelController } from "./chat-panel.js";

export function register(ctx) {
  const deps = ctx.deps || {};
  const chatDeps = deps.chat;
  if (!chatDeps) return;
  const controller = createChatPanelController({
    elements: chatDeps.elements,
    api: ctx.api,
    getDocument: chatDeps.getDocument,
    replaceText: chatDeps.replaceText,
    openDocument: chatDeps.openDocument,
  });
  deps.registerController?.("chat", controller);

  const byId = (id) => document.getElementById(id);
  byId("chatForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    controller.sendMessage();
  });
  byId("chatProvider")?.addEventListener("change", controller.handleProviderChange);
  byId("chatModel")?.addEventListener("change", controller.handleModelChange);
  byId("chatInput")?.addEventListener("keydown", controller.handleInputKeydown);
  byId("chatStop")?.addEventListener("click", controller.stopResponse);
  byId("chatNew")?.addEventListener("click", controller.newChat);
}
