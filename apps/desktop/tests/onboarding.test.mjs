import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeOnboardingIntent,
  onboardingIntentPresentation,
  onboardingPrimaryActionKey,
} from "../frontend/js/core/onboarding.mjs";

test("onboarding completion CTA follows the workflow chosen by the user", () => {
  assert.equal(onboardingPrimaryActionKey(0, "document"), "next");
  assert.equal(onboardingPrimaryActionKey(1, "book"), "next");
  assert.equal(onboardingPrimaryActionKey(2, "document"), "startDocument");
  assert.equal(onboardingPrimaryActionKey(2, "book"), "startBookProject");
  assert.equal(onboardingPrimaryActionKey(2, "unknown"), "close");
});

test("onboarding presentation is bounded to supported intents", () => {
  assert.equal(normalizeOnboardingIntent("document"), "document");
  assert.equal(normalizeOnboardingIntent("book"), "book");
  assert.equal(normalizeOnboardingIntent("other"), null);
  assert.equal(onboardingIntentPresentation("document").icon, "MD");
  assert.equal(onboardingIntentPresentation("book").icon, "B");
  assert.equal(onboardingIntentPresentation(null), null);
});
