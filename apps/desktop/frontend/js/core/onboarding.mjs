const INTENTS = new Set(["document", "book"]);

export function normalizeOnboardingIntent(value) {
  return INTENTS.has(value) ? value : null;
}

export function onboardingPrimaryActionKey(step, intent) {
  if (Number(step) < 2) return "next";
  const normalized = normalizeOnboardingIntent(intent);
  if (normalized === "document") return "startDocument";
  if (normalized === "book") return "startBookProject";
  return "close";
}

export function onboardingIntentPresentation(intent) {
  const normalized = normalizeOnboardingIntent(intent);
  if (normalized === "document") {
    return {
      icon: "MD",
      titleKey: "newDocument",
      detailKey: "onboardingDocumentFinishHelp",
    };
  }
  if (normalized === "book") {
    return {
      icon: "B",
      titleKey: "newBookProject",
      detailKey: "onboardingBookFinishHelp",
    };
  }
  return null;
}
