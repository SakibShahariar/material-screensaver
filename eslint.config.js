export default [
  {
    files: [
      "screensavers/clock-shared.js",
      "extensions/material-screensaver-gestures@io.github.sakib/extension.js",
    ],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        Clutter: "readonly",
        Extension: "readonly",
        Intl: "readonly",
        URLSearchParams: "readonly",
        Date: "readonly",
        location: "readonly",
        setInterval: "readonly",
        global: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unexpected-multiline": "error",
      "no-unreachable": "error",
    },
  },
];
