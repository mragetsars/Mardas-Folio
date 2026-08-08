const templates = {
  blank: {
    id: "blank",
    icon: "＋",
    titleKey: "templateBlank",
    descriptionKey: "templateBlankHelp",
    content: {
      fa: '---\ntitle: ""\nlang: fa\ndir: rtl\n---\n\n# سند جدید\n\n',
      en: '---\ntitle: ""\nlang: en\ndir: ltr\n---\n\n# New document\n\n',
    },
  },
  report: {
    id: "report",
    icon: "R",
    titleKey: "templateReport",
    descriptionKey: "templateReportHelp",
    content: {
      fa: '---\ntitle: "گزارش"\nauthor: ""\nlang: fa\ndir: rtl\ntoc: true\n---\n\n# خلاصه مدیریتی\n\n## مقدمه\n\n## یافته‌ها\n\n## نتیجه‌گیری\n\n',
      en: '---\ntitle: "Report"\nauthor: ""\nlang: en\ndir: ltr\ntoc: true\n---\n\n# Executive Summary\n\n## Introduction\n\n## Findings\n\n## Conclusion\n\n',
    },
  },
  academic: {
    id: "academic",
    icon: "A",
    titleKey: "templateAcademic",
    descriptionKey: "templateAcademicHelp",
    content: {
      fa: '---\ntitle: "مقاله"\nauthor: ""\nlang: fa\ndir: rtl\ntoc: true\ncitations: true\n---\n\n# چکیده\n\n## مقدمه\n\n## روش پژوهش\n\n## یافته‌ها\n\n## بحث\n\n## نتیجه‌گیری\n\n',
      en: '---\ntitle: "Academic Paper"\nauthor: ""\nlang: en\ndir: ltr\ntoc: true\ncitations: true\n---\n\n# Abstract\n\n## Introduction\n\n## Methodology\n\n## Results\n\n## Discussion\n\n## Conclusion\n\n',
    },
  },
  technical: {
    id: "technical",
    icon: "</>",
    titleKey: "templateTechnical",
    descriptionKey: "templateTechnicalHelp",
    content: {
      fa: '---\ntitle: "مستند فنی"\nauthor: ""\nlang: fa\ndir: rtl\ntoc: true\n---\n\n# هدف\n\n## معماری\n\n## راه‌اندازی\n\n## استفاده\n\n## عیب‌یابی\n\n',
      en: '---\ntitle: "Technical Document"\nauthor: ""\nlang: en\ndir: ltr\ntoc: true\n---\n\n# Purpose\n\n## Architecture\n\n## Setup\n\n## Usage\n\n## Troubleshooting\n\n',
    },
  },
};

export const DOCUMENT_TEMPLATES = Object.freeze(templates);

export function templateById(id) {
  return templates[id] || templates.blank;
}

export function templateContent(id, locale = "fa") {
  const template = templateById(id);
  return template.content[String(locale).toLowerCase().startsWith("fa") ? "fa" : "en"];
}

export function templateList() {
  return Object.values(templates).map(({ content: _content, ...metadata }) => ({ ...metadata }));
}
