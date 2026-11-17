import globals from "globals";

export default [
  { ignores: ["node_modules/**", "dist/**", "frontend/js/vendor/**", "src-tauri/**"] },
  {
    files: [
      "frontend/js/**/*.mjs",
      "editor-src/**/*.mjs",
      "scripts/**/*.mjs",
      "tests/**/*.mjs",
      "*.config.mjs",
    ],
    languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: globals.browser },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none", varsIgnorePattern: "^_" }],
      "no-unreachable": "error",
      "no-dupe-args": "error",
      "no-dupe-keys": "error",
    },
  },
  {
    files: ["scripts/**/*.mjs", "tests/**/*.mjs", "*.config.mjs"],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["frontend/js/core/**/*.mjs"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: [
                "**/features/**",
                "**/ui/**",
                "**/preview/**",
                "**/main.mjs",
                "**/adapters/*-api.mjs",
                "**/adapters/tauri.mjs",
              ],
              message:
                "Core rules must not depend on feature controllers, DOM components, or native commands.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["frontend/js/ui/**/*.mjs"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/features/**", "**/main.mjs", "**/adapters/**"],
              message: "Shared UI receives application/native actions through explicit callbacks.",
            },
          ],
        },
      ],
    },
  },
];
