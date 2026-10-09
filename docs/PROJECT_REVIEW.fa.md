# بررسی فنی و برنامهٔ بازسازی Mardas Folio

آغاز بررسی: ۲۰۲۶-۱۰-۰۷؛ بررسی تکمیلی: ۲۰۲۶-۱۰-۰۹. مبنا: کامیت `90b4b73` و تغییرات موجود کاربر برای نسخهٔ ۲.۱.۰.

این سند فهرست اجرایی بررسی است. یافتهٔ قابل بازتولید از پیشنهاد معماری جدا شده و وضعیت کارها با آزمون و کامیت به‌روز می‌شود. تغییرات نسخه و راهنما که پیش از بررسی در working tree وجود داشتند، متعلق به کاربرند و وارد کامیت‌های اصلاحی نمی‌شوند.

## نقشهٔ پروژه و دامنهٔ بررسی

| بخش | مسیر | موارد بررسی |
| --- | --- | --- |
| موتور نشر | `src/mardas_folio/{markdown,renderer,appearance}.py` | Markdown، HTML امن، RTL/LTR، CSS چاپ، MathJax، Mermaid، محدودیت منابع و خروجی قطعی |
| کتاب و منابع | `book.py`, `references.py`, `citations.py` | ترتیب فصل‌ها، مقصدهای لینک، شماره‌گذاری، منابع محلی، تشخیص خطا |
| PDF و کیفیت | `pdf_navigation.py`, `pdf_audit.py`, `quality.py`, `accessibility.py` | فهرست، bookmark، مقصدها، metadata، پیش‌پرواز و دسترس‌پذیری |
| API و فایل | `application.py`, `workspace.py`, `project_commands.py` | خواندن/ذخیره، conflict، مسیر و symlink، جست‌وجو، فایل بزرگ و دارایی |
| اجرای موتور | `sidecar.py`, `protocol.py`, `runtime.py`, `render_pool.py`, `studio_jobs.py` | پروتکل، صف، لغو، timeout، بازیابی و پاک‌سازی |
| محیط مرورگری | `gui.py`, `assets/gui.html` | Host/Origin/token، JSON، پروژه، preview، export، طراحی و محدودیت ورودی |
| ویرایشگر دسکتاپ | `apps/desktop/editor-src`, `frontend/js` | مدل سند، history، انتخاب، recovery، save، metadata، preview و زبان |
| رابط دسکتاپ | `frontend/index.html`, `styles.css`, `workspace.css` | صفحهٔ شروع، workspace، تنظیمات، export، modal، منو، کیبورد، اندازه و theme |
| پوستهٔ بومی | `apps/desktop/src-tauri/src` | چرخهٔ sidecar، IPC، scope فایل، به‌روزرسانی و پنجره |
| ساخت و انتشار | `scripts`, `.github/workflows`, `packaging`, `schemas` | artifact، checksum، امضا، نسخه، ابزارهای QA و صحت گزارش‌ها |
| مستندات | `README.md`, `docs`, راهنماها | هم‌خوانی نسخه‌ها، دستورهای قابل اجرا، محدودیت‌ها و شواهد انتشار |

## خط مبنای آزمون

- Python: ۷۶۱ موفق، ۳ skipped و ۲ شکست؛ هر دو شکست ناشی از تغییر نسخهٔ موجود به ۲.۱.۰ بدون مدخل changelog هستند.
- Node: هر ۲۳۲ آزمون موفق.
- Rust: هر ۴ آزمون موجود موفق؛ پوشش چرخهٔ واقعی process محدود است.
- Ruff و Pyright با مفسر virtualenv: موفق.
- Desktop: screenshot از شش سطح در چهار ترکیب زبان/theme گرفته شد؛ smoke مرورگر و contrast فعلی موفق‌اند. قبولی این آزمون‌ها مشکلات مدل سند و فوکوس را پوشش نمی‌دهد.

## فهرست کارهای اجرایی

| شناسه | اولویت | کار و دلیل | معیار پذیرش | وضعیت |
| --- | --- | --- | --- | --- |
| B01 | P1 | محدودکردن Host به loopback واقعی؛ `127.evil.example` به‌اشتباه محلی شناخته می‌شد و صفحهٔ token نیز Host را بررسی نمی‌کرد | درخواست خصمانه به HTML و API رد شود؛ localhost، IPv4 و IPv6 معتبر کار کنند | انجام شد — `0a07a31` |
| B02 | P1 | ساخت revision از همان bytes متن بازشده؛ خواندن دوباره می‌توانست متن قدیمی را با hash جدید همراه کند و تغییر خارجی را از بین ببرد | بازتولید تغییر میان read/hash و آزمون conflict؛ ذخیرهٔ همزمان محافظت شود | انجام شد — `5238b3e` |
| B03 | P2 | JSON و نوع ورودی سخت‌گیرانه؛ nesting، NaN، surrogate و نوع نادرست markdown/assets نباید ۵۰۰ یا تبدیل خاموش بسازند | پاسخ ۴۰۰ ساختاریافته و آزمون endpoint | انجام شد — `0a07a31` |
| B04 | P2 | پیمایش دارایی محدود و قابل لغو؛ `sorted(rglob('*'))` قبل از اعمال حد کل درخت را می‌پیمود | pruning عمق، پوشه‌های ابزار، شمار فایل و cancellation | انجام شد — `60d1a54` |
| B05 | P2 | جلوگیری از validate/render کل کتاب برای عملیات سبک فایل و جست‌وجو | read/save/search فایل مستقل از رندر فصل‌های دیگر باشد؛ validate/export کامل بماند | انجام شد — `60d1a54` |
| E01 | P1 | metadata: جایگزینی کامل مقدار چندخطی YAML و حفظ کلیدهای دست‌نخورده | scalar، block، list، CRLF و متن بدنه سالم بمانند؛ فرم فقط تغییر واقعی را اعمال کند | انجام شد — `d0fde89` |
| E02 | P1 | جداکردن undo، caret و scroll هر سند هنگام تعویض tab | undo سند دوم متن سند اول را وارد نکند؛ بازگشت به tab موقعیت قبلی را بازیابد | انجام شد — `de74ae7` |
| U01 | P1 | بازسازی نظام بصری تمام سطوح دسکتاپ، typography، spacing، رنگ و hierarchy | شروع، workspace، sidebar، تنظیمات، export، modal و menu منسجم؛ تصویر قابل بررسی | انجام شد — `1a8f7db` |
| U02 | P2 | اصلاح tablist و navigation کیبورد؛ بازسازی DOM فوکوس را به node حذف‌شده می‌برد | Arrow/Home/End فوکوس را در کنترل فعلی نگه دارند؛ RTL معتبر | انجام شد — `1a8f7db` |
| U03 | P2 | یکپارچه‌سازی ترجمهٔ وضعیت citation و متن‌های تولیدشده | وضعیت فارسی و انگلیسی در سطح واقعی UI | انجام شد — `1a8f7db` |
| N01 | P2 | اجازهٔ تصویر محلی شامل `assets/` با مرز canonical و آماده‌سازی scope پیش از تصویر | تصویر واردشده دیده شود؛ symlink خروجی و فایل غیرتصویر مجاز نشوند | انجام شد — `04ca56b` |
| R01 | P2 | رفع crash ساخت update manifest بدون notes اختیاری | CLI بدون notes نیز manifest معتبر بسازد | انجام شد — `e234363` |
| R02 | P1 | اعتبارسنجی رمزنگاری امضای payload زیر public key انتشار | key غلط، payload دست‌کاری‌شده و signature ساختگی پیش از انتشار رد شوند | انجام شد — `e234363` |
| R03 | P1 | انتخاب artifact تازهٔ همان build؛ mtime به‌تنهایی می‌تواند بستهٔ قدیمی را با نام نسخهٔ جدید عرضه کند | artifact قدیمی/future-dated رد شود و خروجی همان build انتخاب شود | انجام شد — `e234363` |
| D01 | P2 | ثبت changelog نسخهٔ در حال توسعه و حذف شمارهٔ قدیمی README دسکتاپ | تست‌های نسخه پاس شوند؛ release اعلام‌نشده به‌عنوان منتشرشده معرفی نشود | انجام شد — `CHANGELOG.md` و README دسکتاپ |
| Q01 | P1 | بررسی نهایی با آزمون‌های رفتاری و خروجی واقعی | Python/Node/Rust، lint/type، build، contrast/responsive/UI و render smoke با نتیجهٔ مستند | انجام شد — جدول شواهد زیر |

## جهت طراحی

رابط جدید یک استودیوی نشر با متن graphite، accent محدود indigo و chrome روشن pearl است. کنترل‌ها با hierarchy، فاصله و سطح از متن جدا شده‌اند؛ typography و سطح سند خوانا مانده‌اند. حالت تاریک، فارسی، پنجرهٔ کوچک، reduced motion، focus-visible و وضعیت‌های خطا/خالی/loading در طراحی لحاظ شدند. رفتارهای ذخیره، recovery، command و preview با آزمون رفتاری بررسی شدند.

## یافته‌های تکمیلی و اصلاحات

این موارد در بررسی مستقل، آزمون رقابت یا مشاهدهٔ خروجی واقعی به فهرست اولیه اضافه شدند.

| شناسه | اولویت | مسئله و کار | معیار پذیرش | وضعیت |
| --- | --- | --- | --- | --- |
| B06 | P1 | startup/restart ناموفق worker و رقابت submit/shutdown/cancel می‌توانست کار را معطل یا موفقیت را پس از لغو منتشر کند | future همیشه تمام شود؛ لغو اتمیک؛ shutdown با سقف زمانی؛ temp تا پایان worker غیرهمکار حذف نشود | انجام شد — `f7ebc88` |
| B07 | P2 | محتوای surrogate در project.save بعد از EOF به‌جای خطای ورودی به cancellation تبدیل می‌شد | ورودی UTF-8 پیش از پیمایش اعتبارسنجی شود و فایل دست‌نخورده بماند | انجام شد — `5fc94d5` |
| B08 | P2 | شمار فایل متنی برای محدودکردن پیمایش کافی نبود؛ میلیون‌ها فایل باینری همچنان خوانده می‌شدند | سقف ۲۰هزار ورودی و عمق ۳۲؛ توقف streaming و هشدار truncation | انجام شد — `8529236` |
| E03 | P1 | تغییر active ID پیش از آماده‌شدن مجوز تصویر، متن قابل مشاهدهٔ A را به B نسبت می‌داد؛ چندفایلی و intent جدید هم درگیر بودند | تایپ هنگام grant، بازکردن C/D، بستن target و رفتن Home متن را به سند درست نسبت دهند | انجام شد — `1a8f7db`، سناریوی مرورگری |
| U04 | P2 | نوار sticky خروجی برخی کنترل‌ها را زیر خود پنهان می‌کرد؛ toast کلیک دکمهٔ فایل را می‌گرفت | کنترل‌های همهٔ ۱۱ گروه expert در پنج اندازه قابل فوکوس و کلیک باشند | انجام شد — `1a8f7db` |
| U05 | P2 | نتایج جست‌وجوی تنظیمات نام accessibility دستهٔ قبلی را داشتند | region جست‌وجو نام ترجمه‌شده داشته باشد و category به tabpanel بازگردد | انجام شد — `40c76b5` |
| S01 | P2 | runtime manifest غیر-object support bundle را می‌شکست؛ resolve زودهنگام symlink خروجی را پنهان می‌کرد | manifest خراب قابل گزارش؛ symlink زنده/شکسته و مقصد غیرعادی رد شود | انجام شد — `5eadcfa` |
| S02 | P1 | floorهای آسیب‌پذیر PDF/selector و ابزار audit/artwork مجاز بودند | floor اصلاح‌شده، pip check، آزمون رندر و صفر advisory شناخته‌شده | انجام شد — `412928a` |
| P01 | P1 | dir=auto بعد از isolate کردن واژهٔ انگلیسی، متن فارسی بعدی را مبنای پاراگراف انگلیسی می‌گرفت؛ فهرست عبارت‌های فارسی نیز ترتیب خود را از دست می‌داد | هندسهٔ Chromium و PDF جهت انگلیسی/فارسی و ترتیب عبارت‌های comma-separated را تأیید کنند | انجام شد — `2284e86`، `d6f3778` |
| Q02 | P2 | QA فقط textarea مخفی را تغییر می‌داد؛ تصویر onboarding پیش از تنظیم زبان/theme گرفته می‌شد؛ TeX نمونه double escape داشت | ورودی واقعی CodeMirror، ۳۲ تصویر با زبان/theme درست و نماد واقعی مجموع/کسر در PDF | انجام شد — `6c4d509`، `1a8f7db` |
| U06 | P2 | Studio مرورگری طراحی قدیمی داشت و در عرض کم preview/settings را بدون جایگزین مخفی می‌کرد | طراحی هم‌خانواده، انتخاب پنل در عرض کم و preview/API واقعی سالم | انجام شد — `9c510ad` |
| S03 | P1 | Rustls به‌روزرسان native پیام handshake را در مرز encryption نامعتبر می‌پذیرفت | Rustls 0.23.45 و WebPKI لازم؛ audit واقعی بدون advisory نوع vulnerability و Rust tests موفق | انجام شد — `1092f16` |
| B09 | P2 | gate تایپ چهار بخش تغییرکرده را بررسی نمی‌کرد | GUI/workspace/pool/jobs وارد gate شوند؛ union آدرس و type صف heterogeneous درست مدل شوند | انجام شد — `0b1f4f2` |

## روش و شواهد پذیرش

آزمون رشتهٔ منبع به‌تنهایی شاهد رفتار واقعی محسوب نشد. برای history از تایپ CodeMirror و Undo/Redo استفاده شد؛ برای رقابت فایل، ترتیب read/hash/save عمداً تغییر کرد؛ برای مجوز تصویر، پاسخ native معلق شد؛ برای انتشار، payload با minisign واقعی امضا و سپس دست‌کاری شد. بررسی responsive به کنترل‌های واقعی خروجی و hit-test آن‌ها گسترش یافت.

- دسکتاپ: ۳۲ تصویر برای onboarding، شروع، تنظیمات، نوشتن، split، command palette، export و کتاب جدید در فارسی/انگلیسی و روشن/تاریک؛ مسیر محلی `build/repo-audit/design-final/`.
- Responsive: ۴۰ ترکیب اندازه/صفحه؛ پنج اندازه × نوشتن/split/export/کتاب جدید × انگلیسی روشن/فارسی تاریک. تنظیمات expert با فوکوس کیبورد و `elementFromPoint` بررسی شدند.
- PDF: چهار appearance نمونه با code، جدول، Mermaid، ریاضی و متن mixed واقعاً تولید و raster شدند؛ `build/audit-final-pdf-features/manifest.json` و `gallery.html`. خروجی راهنما نیز جدا بررسی شد.
- امنیت dependency: گزارش `build/audit-python-security-updated.json`؛ فقط پکیج unpublished محلی از پایگاه advisory قابل بررسی نیست. نبود advisory شناخته‌شده جایگزین آزمون رفتار یا تضمین امنیت نیست.
- API Reader/Writer پس از ارتقای pypdf با آزمون navigation، metadata و خروجی واقعی بررسی شد؛ ابزار artwork نیز PNG/ICO/ICNS معتبر ساخت.

| بررسی نهایی | نتیجه | شاهد محلی / روش |
| --- | --- | --- |
| Python کل پروژه | ۸۶۳ موفق، صفر شکست و صفر skipped | `build/audit-final-python.log`؛ Chromium و minisign واقعی فعال |
| Node | ۲۳۸ موفق | `build/audit-final-node.log` |
| Rust native | ۷ موفق پس از ارتقای TLS | `build/audit-final-rust.log` و گزارش عامل audit |
| Ruff | موفق | `build/audit-final-lint.log` |
| Pyright | صفر error/warning در gate گسترده‌شده | ۱۰ ماژول core و ۳ اسکریپت در `pyrightconfig.json`؛ تمام parser/renderer هنوز در این gate نیستند |
| پوشش branch بحرانی | ۷۳٪؛ gate ۶۰٪ پاس شد | ۱۲۹ آزمون؛ `build/coverage/critical-coverage.xml` |
| رابط دسکتاپ | UI، a11y، history و delayed grant موفق | `build/audit-final-documents.log`؛ ماتریس contrast و responsive در `build/frontend-*.log` |
| Studio مرورگری | ۸۴ حالت موفق | standalone/project × روشن/تاریک × ۹ عرض ۳۲۰ تا ۱۶۰۰ و پنل‌های مربوط؛ `build/studio-final/manifest.json` و `build/studio-project-final/manifest.json` |
| راهنمای واقعی PDF | ۵۱ صفحه، ۲۸ فونت embedded با ToUnicode، ۷۳ outline و ۸۷ مقصد | `build/audit-guide-final-report.json`؛ بدون error، یک warning tagging و دو info مربوط به PDF/A |
| pip / npm audit | صفر آسیب‌پذیری شناخته‌شده | `build/security/pip-audit.json`؛ `build/audit-node-security-updated.json` |
| Cargo audit | صفر advisory نوع vulnerability؛ ۶ unmaintained و ۱ unsound باقی است | ۵۲۲ وابستگی؛ `build/audit-rust-security.json`، بدون suppression؛ شرح پایین |
| هویت و محدودهٔ کامیت | هویت درخواست‌شده؛ تغییرات اولیهٔ نسخه جدا | history پس از `90b4b73` با author/committer `mragetsars <mragetsars@gmail.com>` |

منابع تغییر floorها: [pypdf 6.19](https://github.com/py-pdf/pypdf/releases/tag/6.19.0)، [Soup Sieve](https://facelessuser.github.io/soupsieve/about/changelog/)، [urllib3 2.8](https://github.com/urllib3/urllib3/releases/tag/2.8.0) و [advisory رسمی CairoSVG](https://github.com/Kozea/CairoSVG/security/advisories/GHSA-c3jg-qh8m-j3h2).

اصلاح TLS مطابق [RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html) انجام شد. audit با ابزار رسمی RustSec و پایگاه ۲۰۲۶-۱۰-۰۹ اجرا شد؛ provenance در `build/audit-rust-security-provenance.json` نگه داشته شده است.

## بدهی‌های معماری و محدودیت اعتبارسنجی

- `main.mjs` بیش از ۴۷۰۰ خط دارد و کنترل سند، پروژه، export و modal را جمع کرده است. پس از تثبیت رفتار، جداسازی controllerهای سند/پروژه/export و یک قرارداد state روشن ارزشمند است؛ انتقال مکانیکی همهٔ کدها بدون مسئلهٔ مشخص در این مرحله معیار موفقیت نیست.
- `workspace.css` هنگام آغاز بیش از ۵۴۰۰ خط و چند لایهٔ طراحی متعارض داشت. لایه‌های منسوخ در بازسازی جمع شدند؛ theme با tokenهای مشترک اعمال می‌شود. کنترل رشد cascade در تغییرات بعدی باید ادامه یابد.
- بعضی آزمون‌های UI هنوز وجود رشته یا کلاس را می‌سنجند. سناریوهای واقعی history، focus، permission و metadata اضافه شدند؛ پوشش installer، recovery و conflict در WebViewهای native باید در مرحلهٔ انتشار توسعه یابد.
- اجرای محلی Linux جایگزین شواهد بستهٔ واقعی Windows/macOS، notarization یا نصب update روی کلاینت نیست. نتیجهٔ این موارد باید از runner همان platform ثبت شود.
- آزمون‌های render اختیاری باید جداگانه با Chromium اجرا شوند؛ skipped بودن آن‌ها شاهد سلامت PDF نیست.
- خروجی PDF بررسی‌شده فونت‌های embedded و ToUnicode، outline و named destination دارد؛ ساختار tagged، output intent و شناسهٔ PDF/A ندارد. هشدار accessibility و اطلاعات archival باید باقی بمانند؛ ادعای PDF/UA یا PDF/A مطرح نشده است.
- scope بومی به هر تصویر جدا اجازه می‌دهد و resolver فرانت‌اند فقط مسیر داخل پوشهٔ سند فعال را می‌پذیرد. grantهای per-file در طول session باقی می‌مانند؛ در مسیر فعلی برنامه هنگام بستن سند مجوزها پس گرفته نمی‌شوند و پایان session مرز پاک‌سازی است.
- conflict ذخیره به کمک snapshot، قفل داخل process و مقایسهٔ مجدد پیش از rename محافظت می‌شود. مقایسه و rename در برابر writer خارجیِ بدون قرارداد، یک عملیات اتمیک مشترک نیستند؛ پنجرهٔ بسیار کوتاه خارجی همچنان محدودیت سیستم فایل است.
- Studio مرورگری متن فارسی/انگلیسی را پشتیبانی می‌کند، اما chrome آن انگلیسی است؛ ترجمهٔ کامل chrome یک کار مستقل آتی است. دسکتاپ در هر دو زبان بازسازی و آزموده شد.
- در زنجیرهٔ GTK/Tauri روی Linux، `glib 0.18.5` هشدار [VariantStrIter](https://rustsec.org/advisories/RUSTSEC-2024-0429.html) دارد. در ۱۶۴۹۷ فایل Rust بررسی‌شده caller خارج از خود glib پیدا نشد؛ این اثبات رسمیِ unreachable بودن نیست. اصلاح upstream در glib 0.20 است، اما chain فعلی 0.18 را می‌خواهد؛ مهاجرت framework یا backport آزموده‌شده باید پیگیری شود. هشدار مخفی نشده و از افزودن این iterator در کد برنامه باید پرهیز شود.
- شش هشدار unmaintained مربوط به `proc-macro-error` و خانوادهٔ `unic` باقی‌اند. رفع آن‌ها نیازمند تغییر وابستگی‌های بالادستی است؛ نبود vulnerability advisory به‌معنای بسته‌شدن این بدهی نیست.

## پیگیری‌های بعدی

این‌ها بدهی یا شواهد بیرون از اصلاحات قابل بازتولید این مرحله‌اند؛ انجام‌شده علامت نخورده‌اند.

| شناسه | اولویت | پیگیری | معیار بسته‌شدن |
| --- | --- | --- | --- |
| A01 | P2 | مهاجرت GTK/Tauri یا backport آزموده‌شده برای glib و وابستگی‌های unmaintained | advisory مربوطه با نسخهٔ اصلاح‌شده حذف شود؛ build و رفتار native Linux تأیید شود |
| A02 | P2 پیش از انتشار | نصب واقعی Windows/macOS/Linux، signing/notarization و نصب update | evidence مربوط به همان artifact و commit از runner هر platform، بدون اتکا به فقط آزمون Linux |
| A03 | P3 | جداسازی controllerهای main و افزایش دامنهٔ type checking parser/renderer | مرز state مشخص، رفتار history/recovery/export حفظ و gate جدید پایدار شود |
| A04 | P3 | ترجمهٔ کامل chrome رابط مرورگری Studio | منابع ترجمهٔ مستقل و آزمون RTL/LTR کنترل‌ها با API واقعی |
| A05 | در صورت نیاز محصول | مطالعهٔ خروجی استاندارد tagged/PDF/UA/PDF/A | مسیر تولید معتبر و تأیید مستقل استاندارد؛ افزودن فقط flagهای catalog کافی نیست |

## قرارداد کامیت

هر تغییر مستقل پس از آزمون در کامیت جدا با `mragetsars <mragetsars@gmail.com>` ثبت می‌شود. قالب تاریخچه حفظ می‌شود: `type(scope): concrete outcome`؛ بدنهٔ انگلیسی مسئله، رفتار جدید و شواهد واقعی آزمون را توضیح می‌دهد. صرف قبولی آزمون منبع به‌عنوان بررسی بصری یا نصب موفق گزارش نمی‌شود.
