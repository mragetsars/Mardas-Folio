# بررسی سراسری معماری، پایداری و تجربهٔ کاربری Mardas Folio

تاریخ این دور: ۲۰۲۶-۱۰-۲۴ تا ۲۰۲۶-۱۰-۲۵. مبنای شروع: `d303f30`، پس از اصلاحات نسخهٔ آزمایشی ۲.۱.۰؛ اصلاحات نهایی کد تا `0b0240a`. این سند مکمل [بررسی قبلی پروژه](PROJECT_REVIEW.fa.md) و فهرست اجرایی دور جدید است. تغییرات از پیش موجود کاربر در نسخه‌ها، lockfileها و راهنماها از اصلاحات این دور تفکیک می‌شوند.

## معیار بررسی

یافتهٔ اجرایی باید یک ورودی، ترتیب رویداد یا وضعیت قابل بازتولید داشته باشد؛ پیشنهاد بازآرایی معماری به‌تنهایی خطای محصول محسوب نمی‌شود. اولویت با از دست رفتن متن و منابع، قفل شدن موتور، باقی ماندن فرایندها، خطاهای رقابتی، مرز فایل و رفتار واقعی کاربر است. برای هر اصلاح، آزمونی انتخاب شده که رفتار پیش از اصلاح را آشکار کند.

«پیاده‌سازی شد» در جدول‌ها به معنی وجود اصلاح و آزمون مربوط است. قبولی کل مجموعه، ساخت بستهٔ تازه و آزمون نصب یا update امضاشده شواهد مستقلی هستند؛ تا زمانی که نتیجه ثبت نشده، انجام‌شده تلقی نمی‌شوند. این بررسی ادعای اثبات نبود هر خطای ممکن را ندارد.

## نقشهٔ بررسی و چک‌لیست قابلیت‌ها

| حوزه | قابلیت‌ها و مرزهای بررسی | روش و وضعیت |
| --- | --- | --- |
| مدل سند و فایل | بازکردن، ذخیره، Save As، conflict، UTF-8، مسیر، چند تب، recovery، undo/redo و محتویات خالی | مرور کد، آزمون رقابت فایل، ورودی واقعی ادیتور و سناریوی ذخیره پیش از update؛ یافته‌های BE و FE |
| ویرایش و جست‌وجو | Write/Source/Read/Split، جست‌وجوی سند و پروژه، Replace/Replace All، انتخاب و تغییر تب | آزمون Node و مرورگر؛ متن‌های طولانی، بیش از ۱۰هزار تطبیق، تغییر متن و سند هنگام جست‌وجو |
| نمایش Markdown | جدول، کد، ریاضی، نمودار، تصاویر، متن فارسی/انگلیسی، منابع و ارجاع‌ها | آزمون parser/renderer موجود، اصلاحات ورودی و تصویر در این دور؛ اجرای کامل رندر با Chromium و برابری محتوای Read/پیش‌نمایش موفق |
| پنل‌ها و UX | فرمان‌ها، تأییدها، فوکوس، clipboard، پیش‌نمایش خودکار/دستی، export، تنظیمات و واکنش‌گرایی | آزمون مرورگر فارسی تاریک/انگلیسی روشن؛ آزمون‌های responsive موجود و سناریوهای جدید صف/تأیید |
| کتاب و پروژه | ایجاد کتاب، افزودن/کپی/ترتیب/حذف فصل، TOML، snapshot، خواندن و ذخیره منابع | آزمون منبع واقعی و هم‌زمانی؛ حذف فصل از manifest همچنان فایل منبع را حفظ می‌کند |
| PDF و کیفیت | مسیر خروجی، debug HTML، quality report، محافظت از فصل/کتاب‌شناسی، فونت، navigation، cancellation | آزمون برخورد مسیرها و مجموعهٔ renderer؛ خروجی جدید استاندارد PDF/A یا PDF/UA ادعا نمی‌شود |
| API و امنیت محلی | JSON-RPC، محدودیت درخواست/پاسخ، Host/Origin/token در Studio، ورودی خراب، symlink و grant تصویر | آزمون‌های Python موجود و جدید، آزمون Rust و ورودی‌های خصمانهٔ کوچک و قابل بازتولید |
| چرخهٔ موتور | شروع، handshake، صف، backpressure، timeout، لغو، shutdown و فرزندان Chromium | فرایند واقعی با pipe مسدود، cleanup تأخیردار و فرزند یتیم؛ Linux و Windows |
| به‌روزرسانی | ذخیرهٔ همهٔ draftها، انتظار برای ذخیرهٔ قبلی، conflict، نصب هم‌زمان، timeout دانلود و خروج موتور | مرورگر واقعی با adapter کنترل‌شده و آزمون native؛ نصب live امضاشده در این دور اجرا نشده |
| ساخت و بسته‌بندی | پاک‌سازی، ownership خروجی، staging، rollback، انتخاب artifact همان build، runtime و ZIP قابل تکرار | آزمون مسیر با sentinel، ساخت مصنوعی، مقایسهٔ بایت ZIP و اندازه‌گیری حافظه |
| وابستگی و ابزار QA | audit پایتون، حفظ گزارش آسیب‌پذیری، Ruff، Pyright، تست‌های Python/Node/Rust | گزارش‌های محلی ثبت شده؛ موارد skip و تفاوت نسخهٔ Python صریح‌اند |
| سکوهای انتشار | موتور و native Windows، Linux، macOS، signing و نصب update | آزمون‌های Rust واقعی Windows/Linux موفق؛ بیلد تازهٔ برنامه و شواهد انتشار مستقل در جدول پذیرش |

## یافته‌های بک‌اند و یکپارچگی داده

| شناسه | اولویت | مسئلهٔ قابل بازتولید | رفتار اصلاح‌شده و معیار پذیرش |
| --- | --- | --- | --- |
| BE01 | P1 | payload کتاب از manifest قدیمی استفاده می‌کرد ولی hash را از config تازهٔ روی دیسک می‌گرفت؛ سپس تغییر خارجی با snapshot قدیمی بازنویسی می‌شد | hash از همان bytes ورودی parser ساخته می‌شود؛ hash تازه نمی‌تواند manifest قدیمی را معتبر کند؛ تغییر خارجی سالم می‌ماند |
| BE02 | P1 | افزودن دو فصل با نام یکسان می‌توانست یک مسیر مشترک انتخاب کند؛ rollback یکی فایل فصل موفق دیگری را حذف می‌کرد | قفل reentrant مشترک تمام mutationهای سند/پروژه/دارایی؛ یک تغییر موفق و یک conflict، فایل فصل برنده موجود و سالم |
| BE03 | P1 | به‌روزرسانی manifest کتاب فقط پیش از نوشتن فایل موقت conflict را بررسی می‌کرد | بررسی مجدد بلافاصله پیش از rename؛ ویرایش خارجی هنگام flush جایگزین نمی‌شود |
| BE04 | P1 | پس از commit موفق فصل، شکست refresh وارد rollback می‌شد و فصل ثبت‌شده را حذف می‌کرد | مرز commit از refresh جداست؛ rollback فقط پیش از commit فایل تازه را حذف می‌کند |
| BE05 | P1 | quality report می‌توانست روی bibliography یا فصل دیگر کتاب نوشته شود | PDF، debug و report در برابر منابع مربوط محافظت می‌شوند؛ رد درخواست پیش از شروع Chromium و بدون تغییر منبع |
| BE06 | P2 | پارامتر `book.add_chapter.content` با trim تغییر می‌کرد و رشتهٔ خالی رد می‌شد | حفظ دقیق متن خالی، indentation و newlineها؛ محتوای فایل برابر bytes متن درخواست است |
| BE07 | P2 | متن `[book]` یا `[output]` داخل رشتهٔ چندخطی TOML به‌عنوان header شناخته می‌شد و ویرایش فصل config را خراب می‌کرد | شناسایی header خارج از رشته/comment؛ اعتبارسنجی TOML تازه پیش از نوشتن؛ توضیحات چندخطی و tableهای quoted سالم می‌مانند |
| BE08 | P2 | config دارای book به شکل inline/dotted هنگام ویرایش فصل table تکراری و نامعتبر می‌گرفت | رندر این configها برقرار است؛ mutation با پیام روشن درخواست `[book]` معمولی رد می‌شود و config و فصل‌ها دست‌نخورده می‌مانند |
| BE09 | P2 | نویسنده‌های اتمیک سند/پروژه برای خواندن umask موقتاً `os.umask(0)` اجرا می‌کردند؛ این وضعیت در کل process و threadهای رندر اثر دارد | allocator مشترک با `O_CREAT|O_EXCL`؛ حفظ mode موجود و احترام به umask بدون تغییر آن؛ نام موقت تصادفی و محدود |
| BE10 | P2 | محدودیت حجم config، تصویر، bibliography و import فقط از stat می‌آمد؛ رشد فایل پیش از read آن را دور می‌زد | read محدود به سقف به‌علاوهٔ یک byte و بررسی اندازهٔ واقعی؛ شکست کنترل‌شده و بدون خروجی ناقص |
| BE11 | P2 | حذف/ناخوانا شدن تصویر بین stat و read کل Preview را می‌شکست؛ تصویر تکراری برای هر occurrence دوباره خوانده و encode می‌شد | placeholder و warning برای تصویر مشکل‌دار؛ cache فقط در همان render، یک read برای هر مسیر تکراری |
| BE12 | P2 | دو import هم‌زمان با نام یکسان می‌توانستند فایل یکدیگر را بازنویسی کنند؛ منبع حذف‌شده یا فایل عادی با نام assets خطای داخلی می‌ساخت | تخصیص نام زیر قفل مشترک، حفظ هر دو محتوا، خطای پایدار برای منبع غایب/مسیر assets نامعتبر |
| BE13 | P2 | JSON کتاب‌شناسی عمیق، عدد بسیار بزرگ، NaN/Infinity و surrogate escaped به خطای داخلی یا شکست دیرهنگام رندر می‌رسید | diagnostic کتاب‌شناسی با مسیر؛ محدودیت خواندن، عدد finite و متن UTF-8 معتبر پیش از رندر |
| BE14 | P2 | TOML بسیار عمیق و NUL/surrogate در مسیر API خطای غیرساختاریافته می‌دادند | diagnostic config یا `MARDAS-INVALID-PARAMS`؛ عنوان/محتوای فصل نامعتبر فایل تازه نمی‌سازد |
| BE15 | P2 | جست‌وجوی ساده پس از کاراکتر ۲۰۰۰ هر پاراگراف را نمی‌دید و snippet همیشه ابتدای سطر بود؛ نتیجهٔ دقیقاً برابر سقف نیز truncated معرفی می‌شد | جست‌وجوی literal روی کل فایل محدود، iterator تطبیق، snippet پیرامون hit و فقط اعلام وجود تطبیق اضافهٔ واقعی |
| BE16 | P2 | سقف حفاظتی سطر regex بی‌صدا بخشی از سطر بلند را نادیده می‌گرفت | قرارداد API شامل `truncated_lines` و `regex_line_limit`؛ رابط محدودیت را توضیح می‌دهد و جست‌وجوی ساده مسیر کامل است |

مسیرهای اصلی: `src/mardas_folio/{application,workspace,config,book,citations,markdown,renderer,file_io}.py`. شواهد رفتار: `tests/test_file_transactions.py`، `test_book_mode.py` و `test_citations.py` به‌علاوهٔ آزمون‌های قبلی ذخیره، پروژه، امنیت و renderer.

## یافته‌های ادیتور و تجربهٔ کاربر

| شناسه | اولویت | مسئله | رفتار اصلاح‌شده و آزمون |
| --- | --- | --- | --- |
| FE01 | P1 | offset نتایج Find پس از تایپ یا تعویض تب برای متن/سند قبلی باقی می‌ماند و Replace می‌توانست محل غلط را تغییر دهد | session جست‌وجو به سند، متن و query دقیق وابسته است؛ آزمون تغییر متن/تب و Undo واقعی |
| FE02 | P2 | Replace All سقف ۱۰هزار تطبیق را به‌عنوان پایان کار می‌پذیرفت و باقی متن جایگزین نمی‌شد | تمام تطبیق‌ها در تغییر واحد کامل می‌شوند؛ fixture بیش از ۱۰هزار مورد |
| FE03 | P1 | دو سؤال تأیید هم‌زمان، مانند conflict دیررس و بستن تب دیگر، handler یکدیگر را می‌پوشاندند | presenter صف FIFO و پاسخ مستقل هر سؤال؛ cancel هرگز ذخیرهٔ اجباری نمی‌سازد |
| FE04 | P1 | شروع update به recovery محلی محدود تکیه داشت و ممکن بود draft بزرگ، draftهای زیاد یا ذخیرهٔ در حال اجرا را از دست بدهد | ذخیرهٔ همهٔ draftها در فایل واقعی، انتظار برای ذخیرهٔ قبلی و ثبت آخرین متن؛ cancel/conflict نصب را متوقف می‌کند؛ ویرایش فقط هنگام نصب قفل می‌شود |
| FE05 | P1 | صف‌های جداگانهٔ writer Preview و export می‌توانستند هم‌زمان به sidecar تک‌کار مراجعه و `SERVER_BUSY` تولید کنند | صف مرکزی FIFO برای همهٔ کارهای موتور، اولویت تعامل و لغو کار محلی در صف؛ health/cancel فوری باقی می‌مانند |
| FE06 | P2 | دو کلیک سریع پیش از await می‌توانستند دو export بسازند و تنظیمات کار جاری تغییر کند | claim هم‌زمان و فوری export و قفل کنترل‌های همان کار |
| FE07 | P2 | Copy HTML ممکن بود Preview قدیمی را با auto-preview خاموش کپی کند یا مسیر کیبورد متن جاری را در نظر نگیرد | تولید امن از buffer فعلی و رفتار هم‌سان مسیر toolbar/context/keyboard |
| FE08 | P2 | grant تصویر و refresh دارایی هنگام تایپ/تعویض تب می‌توانست تصویر ارجاع‌شده را از دست بدهد یا کل پوشه را بپیماید | استخراج مراجع واقعی، decode فاصله/پرانتز و grant دقیق؛ refresh پس از تغییر منبع، با حفظ مالکیت سند |
| FE09 | P2 | محدودیت regex در پاراگراف‌های بلند توضیحی نداشت | نمایش پیام ترجمه‌شده بر اساس فیلدهای جدید API؛ جست‌وجوی literal بدون سقف ۲۰۰۰ کاراکتر |

controllerهای تازهٔ `confirmation-queue.mjs`، `engine-queue.mjs`، `update-preparation.mjs` و `document-assets.mjs` مسئولیت‌های مستقل را از `main.mjs` جدا می‌کنند. هدف این استخراج‌ها مالکیت state و قرارداد قابل آزمون است؛ جابه‌جایی مکانیکی کل فایل انجام نشده است.

## یافته‌های پوستهٔ بومی و مدیریت فرایند

| شناسه | اولویت | مسئله | اصلاح و شاهد |
| --- | --- | --- | --- |
| NA01 | P1 | timeout درخواست پس از write مسدودکننده به stdin آغاز می‌شد؛ موتورِ نخواننده برنامه را معطل می‌کرد | صف writer محدود به ۱۶، سقف درخواست ۶۴MiB و deadline شامل write؛ فرایند واقعی با pipe مسدود و پیام ۲MiB در Linux/Windows زیر دو ثانیه تمام می‌شود |
| NA02 | P1 | stdout/stderr بدون سقف بودند و UTF-8 خراب می‌توانست log reader را متوقف و pipe را مسدود کند | پاسخ JSON-RPC تا ۱۲۸MiB، log سطر ۶۴KiB با truncate/drain، خطای ساختاریافته برای pendingها؛ handshake نامعتبر پیش از درخواست رد می‌شود |
| NA03 | P1 | پس از ack خروج، process فوراً کشته می‌شد و worker/Chromium فرصت cleanup نداشتند | فرصت خروج graceful سه‌ثانیه‌ای؛ گروه فرایند و snapshot گروه‌های detached در Unix؛ Job Object با kill-on-close در Windows پیش از اجرای فرزندان |
| NA04 | P2 | timeout سی‌ثانیه‌ای metadata برای دانلود installer بزرگ شامل Chromium نیز اعمال می‌شد؛ خروج مستقیم updater cleanup را دور می‌زد | metadata سی ثانیه، دانلود ده دقیقه، guard نصب هم‌زمان و hook خروج Windows برای پایان موتور |
| NA05 | P2 | هر فعال‌سازی تب کل پوشهٔ سند را تا ۴۰۹۶ ورودی اسکن می‌کرد؛ پوشهٔ Downloads بزرگ کند و تصاویر خارج از سقف غایب می‌شدند | `sources[]` اختیاری برای grant فقط تصاویر ارجاع‌شده؛ آرایهٔ خالی بدون scan؛ مرز canonical، نوع فایل، symlink، مسیر absolute/parent/URI بررسی می‌شود |

مسیرها: `apps/desktop/src-tauri/src/{main,sidecar,updates,process_tree}.rs`. آزمون صرفاً unitِ بدون process نیست: writer مسدود، graceful cleanup و حذف فرزند یتیم با executable واقعی اجرا شده‌اند.

## ساخت، انتشار و وابستگی‌ها

| شناسه | اولویت | مسئله | وضعیت اصلاح/پذیرش |
| --- | --- | --- | --- |
| PK01 | P1 | `--clean` و مسیر خروجی در ابزارهای native، legacy، runtime و visual QA می‌توانستند منبع، ancestor یا پوشهٔ شخصی را پاک کنند | guard مشترک ownership، منابع protected و symlink پیش از resolve؛ sentinelها در درخواست ردشده سالم می‌مانند |
| PK02 | P1 | staging frontend/runtime نام ثابت `.previous` را پیش از کار حذف می‌کرد و فایل/پوشهٔ نامرتبط هم‌نام از بین می‌رفت | backup تصادفی مختص همان عملیات و rollback جایگزینی ناموفق |
| PK03 | P2 | artifact کپی‌شده پیش از verify روی خروجی موفق قبلی قرار می‌گرفت؛ ZIP موقت نیز نام ثابت داشت | publication با staging منحصربه‌فرد و verify پیش از replace؛ بازبینی مستقل symlink marker و portable نیز همین مرز را بررسی کرده است |
| PK04 | P2 | مسیر legacy NSIS می‌توانست setup قدیمی cache را انتخاب کند | snapshot قبل/بعد build و انتخاب فقط فایل تولیدشدهٔ همان اجرا |
| PK05 | P2 | portable/wheelhouse کل payloadها را به bytes تبدیل و هم‌زمان در حافظه نگه می‌داشتند | stream chunked؛ fixture یکسان ۹۶MiB: peak RSS از ۱۲۰۱۹۲KiB به ۲۴۳۴۴KiB، زمان هر دو ۰٫۳۶ ثانیه و بایت ZIP برابر |
| PK06 | P2 | audit امنیتی با exit code مربوط به وجود vulnerability، JSON معتبر را حذف می‌کرد | انتشار اتمیک گزارش معتبر و حفظ nonzero exit؛ گزارش خراب جای گزارش معتبر قبلی را نمی‌گیرد |
| SC01 | P1 | audit محیط بررسی ۵۳ advisory در پنج پکیج نشان داد | محیط بررسی با `pypdf 6.21.2`، `Pillow 13`، `setuptools 84.1`، `certifi 2026.10.19` و `filelock 4.2.1` به صفر advisory شناخته‌شده رسید؛ floorها و CI هماهنگ شدند |
| SC02 | P1 | پایگاه تازهٔ RustSec نُه vulnerability در TLS/ZIP و یک هشدار unsound جدید Tokio گزارش کرد | TLS و Tokio اصلاح شدند؛ آپدیتر رسمی 2.14 با وابستگی‌های سازگار Tauri 2.12 و بدون قابلیت ZIP قدیمی انتخاب شد؛ audit بدون suppression به صفر vulnerability رسید؛ شواهد ساخت و آزمون بستهٔ تازه در جدول پذیرش آمده است |

بازبینی متقابل packaging افزون بر آزمون‌ها انجام شد: marker اکنون مستقل از مسیر checkout و اتمیک است، نوشتن افزایشی symlink را دنبال نمی‌کند، placeholder فقط فایل عادی است و محتوایش حفظ می‌شود، و portable/runtime پیش از جایگزینی خروجی موفق verify می‌شوند. شکست promotion نیز خروجی قبلی را برمی‌گرداند. تمام این موارد با آزمون بازگشت بررسی شدند.

عدد صفر advisory نتیجهٔ پایگاه و محیط audit فعلی است، نه گواهی امنیت همهٔ سکوها. runtime پایتون ۳.۱۰ حفظ شده، اما ابزار artwork با Pillow 13 به پایتون ۳.۱۱ یا جدیدتر نیاز دارد. floor جدید filelock در dev نیز شرط نسخه دارد؛ سلامت زنجیرهٔ dev روی Python 3.10 از این گزارش نتیجه گرفته نمی‌شود.

منابع تغییرات بومی: [انتشار رسمی updater 2.14](https://github.com/tauri-apps/plugins-workspace/releases/tag/updater-v2.14.0)، [هشدار rustls](https://rustsec.org/advisories/RUSTSEC-2026-0349.html) و [هشدار استخراج ZIP](https://rustsec.org/advisories/RUSTSEC-2026-0368.html). قالب‌های منتشرشدهٔ ما NSIS خام در Windows، AppImage خام در Linux و app.tar.gz در macOS هستند؛ حذف ZIP به این سه قالب متکی است. policy امضای نسخه به‌اجبار تغییر نکرده تا artifactهای امضاشدهٔ فعلی ناسازگار نشوند.

## شواهد پذیرش این دور

| بررسی | نتیجهٔ ثبت‌شده در زمان تدوین | شاهد |
| --- | --- | --- |
| Python هدفمند backend | ۲۷۸ موفق | `build/backend-focused-review.log`؛ storage، config، کتاب، API، sidecar، امنیت، تصویر و renderer |
| Python کل پروژه با رندر واقعی | ۹۲۰ موفق، بدون شکست یا skip؛ پس از اصلاحات قرارداد محصول نیز تکرار شد | `build/product-audit/python-final.log`؛ Chromium فعال، Node و CLI رسمی minisign در PATH |
| Ruff | موفق | `build/product-audit/ruff-final.log` |
| Pyright | موفق، صفر error/warning | `build/product-audit/pyright-final.log`؛ مفسر `.venv/bin/python` صریح انتخاب شده |
| Node | ۲۸۷ موفق پس از دور قرارداد محصول | `build/product-audit/node-final.log`؛ تست‌های صف، update، confirmation، نوع سند و موقعیت نیز شامل‌اند |
| Python هدفمند desktop | ۴۲ موفق در بازاجرای نهایی | `build/product-audit/desktop-final.log`؛ علاوه بر مجموعهٔ کامل بالا |
| سناریوی یکپارچگی ادیتور | هر ۸ مورد در انگلیسی روشن و فارسی تاریک موفق | `build/frontend-integrity-audit/report.json`؛ offset، تب، Undo، بیش از ۱۰هزار Replace و تأییدهای رقیب |
| حفظ متن هنگام update | ۶ مورد موفق | `build/update-safety-audit/report.json`؛ ۱۴ draft، متن بیش از یک میلیون کاراکتر، storage ناموجود، save معلق و conflict |
| صف موتور، clipboard و تصاویر | ۶ مورد موفق با CSP سخت ساخته‌شده | `build/engine-queue-audit/report.json`؛ grant تأخیردار، مسیر دارای فاصله/پرانتز، refresh غیرمخرب و لغو export هنگام drain پیش‌نمایش |
| آزمون‌های UX موجود | رفتار، authoring و ۱۶ حالت responsive موفق؛ responsive پس از اصلاح نهایی گروه کنترل‌ها نیز تکرار شد | `scripts/audit_desktop_editor_ux.py` و `build/product-audit/responsive-final/report.json`؛ این شاهد جای آزمون انسانی دسترس‌پذیری را نمی‌گیرد |
| Rust در Linux | ۲۵ موفق با وابستگی‌های نهایی | `build/full-audit/native-security-linux-tests.log`؛ `cargo test --locked` |
| Rust واقعی Windows | ۲۲ موفق با وابستگی‌های نهایی | `build/full-audit/native-security-windows-tests.log`؛ executable ساخته‌شده واقعاً در Windows اجرا شد |
| Packaging هدفمند | ۷۹ موفق در مجموعهٔ نهایی هدفمند | `build/full-audit/packaging-all-tests.log`؛ علاوه بر مجموعهٔ کامل بالا |
| gate پوشش بخش‌های بحرانی | ۱۳۰ موفق؛ پوشش branch/statement تجمیعی ۷۳٪ | `build/full-audit/critical-coverage.log`؛ این درصد پوشش کل برنامه نیست |
| امضاهای updater | ۱۹ موفق با CLI رسمی minisign 0.12 | `build/full-audit/minisign-signed-release-tests.log`؛ provenance و امضای ابزار در `build/full-audit/tools/minisign-0.12/` |
| Preview | ۸ حالت زبان/پوسته/عرض و ۲ رقابت پاسخ قدیمی موفق | `build/product-audit/preview-accepted/report.json`؛ ریاضی آفلاین و بدون خطای JS یا درخواست خارجی |
| عرض/بزرگ‌نمایی سند | ۴ حالت زبان/پوسته موفق | `build/full-audit/document-view/`؛ حالت‌های نمایش و بازیابی فضای پنل‌ها |
| پنل خروجی و scrollbar | ۳۲ حالت اصلی به‌علاوهٔ تغییر اندازه/زبان موفق | `build/full-audit/export/report.json` |
| دسترس‌پذیری ساختاری | بدون finding | `build/product-audit/accessibility/report.json`؛ جای آزمون انسانی screen reader نیست |
| حافظه و خروجی ZIP | کاهش peak RSS با بایت یکسان | `build/full-audit/portable-memory-before.txt` و `portable-memory-after.txt` |
| عملکرد PDF | ۱۲ خروجی واقعی در شش ترکیب profile/mode موفق | `build/full-audit/performance/benchmark.json`؛ سند ۵۳ صفحه میانگین ۲٫۸۹/۲٫۲۰ ثانیه و سند ۲۵۹ صفحه ۷٫۶۲/۷٫۵۴ ثانیه در cold/session؛ دو اجرا در هر ترکیب، وابسته به همین دستگاه و بار هم‌زمان |
| audit وابستگی Python | صفر advisory شناخته‌شده در محیط اصلاح‌شده | `build/full-audit/pip-audit-fixed.json` و `security-fixed.log` |
| audit وابستگی Rust | صفر vulnerability؛ پنج هشدار بالادستی پنهان نشده | `build/full-audit/cargo-audit-fixed.json` و `native-security-provenance.json`؛ پایگاه رسمی تازه، بدون ignore |
| audit وابستگی Node | صفر vulnerability شناخته‌شده | `build/full-audit/npm-audit.json` |
| بستهٔ Windows نهایی پس از اصلاح وابستگی‌ها و قرارداد محصول | موتور: verify و ۱۴ سناریو موفق؛ برنامه: ۱۵ سناریو موفق روی `0b0240a` بدون خطای page/console | `build/product-audit/native-final-0b0240a/native-smoke-report.json`؛ نبود Insert/Format در Read نیز آزموده شد؛ پس از خروج inventory موتور با ۶۹۷ فایل سالم و هیچ پردازش اختصاصی بسته باقی نبود |
| نصب update امضاشده، macOS و نصب Linux | اجرا نشده در این دور | به شواهد runner همان platform، signing و نصب واقعی نیاز دارد |

اجرای نهایی Python با ابزارهای موردنیاز انجام شد و skipهای میانی برطرف شدند. آزمون امضای واقعی، نصب واقعی update نیست؛ محدودیت نصب همچنان برقرار است.

## دور تکمیلی قرارداد محصول، ۲۰۲۶-۱۰-۲۵

پس از بازخورد دربارهٔ منطق Write/Source/Read/Split، بررسی از سلامت پیاده‌سازی به قول هر قابلیت و محدودهٔ اثر آن گسترش یافت. [قرارداد محصول](WORKSPACE_PRODUCT_CONTRACT.fa.md) بیست مسئلهٔ این دور و معیارهای پذیرش را ثبت می‌کند.

سه فعالیت ویرایش/مرور از چیدمان پیش‌نمایش جدا شدند؛ Read و پیش‌نمایش کنار متن یک رندر و typography دارند. تغییر نما جای مطالعه و Undo را حفظ می‌کند و وضعیت قدیمی/بررسی‌نشده صریح است. فایل‌های متنی معمولی زبان، فرمان و inspector مناسب دارند. Insert، Format و نوار قالب‌بندی در Read و منبع معمولی از چیدمان حذف می‌شوند؛ در ویرایش Markdown در دسترس‌اند. مرور کل کتاب زمینهٔ مستقلی دارد و پیش از خواندن فایل‌ها، ورودی‌های تغییرکرده را ذخیره می‌کند یا متوقف می‌شود. درخت پروژه در ناوبر چپ است و محدودهٔ مشخصات سند، defaults پروژه و تنظیمات PDF در رابط روشن شده است.

شواهد مکمل: ۲۰ مسیر رفتاری دو زبان، مقایسهٔ typography در ۶۰/۱۰۰/۲۰۰٪ بدون اختلاف، مهاجرت Split قدیمی، visibility ابزارهای ویرایش با نوار قالب‌بندی باز، هفت مسیر واقعی کتاب/PDF همراه با فهرست مطالب، چهار آزمون موقعیت/نوع سند در CodeMirror، آزمون عرض محدود کنترل سورس، ۱۶ حالت responsive پس از اصلاح نهایی visibility و مجموعهٔ کامل ۹۲۰ Python موفق. بستهٔ Windows نهایی `0b0240a` نیز ۱۵ سناریوی بومی را با موفقیت گذراند؛ نبود Insert/Format در Read، ذخیرهٔ واقعی، PDF، صف موتور، بستن/راه‌اندازی دوباره و recovery در این سناریوها هستند. فایل‌ها و گزارش‌ها در بخش پذیرش سند قرارداد معرفی شده‌اند.

بستهٔ محلی نهایی در `C:\Users\mrage\Programs\Mardas Folio Trial 2.1.0 Workspace 0b0240a` قرار دارد. پوسته و frontend از snapshot کد `0b0240a` ساخته شدند؛ موتور Windows تأییدشدهٔ `17276bb` با بررسی برابری تمام ورودی‌های renderer، assets و ابزار ساخت موتور دوباره استفاده شد. `TRIAL-BUILD.json` هر دو snapshot، hash ورودی‌ها و نتیجهٔ آزمون را جدا ثبت می‌کند. hash فایل اجرایی آزموده‌شده: `c320e1d68771bdcfa237ff4c7d93ae3efa3df73fa58f7927b8ecf379575c1ce4`. این بسته Trial محلی است؛ نصب/update امضاشده یا آزمون رابط macOS/Linux از این شاهد نتیجه گرفته نمی‌شود.

## مرزهای معماری و پیگیری‌های باز

- قفل مشترک فایل از رقابت writerهای داخل همین process جلوگیری می‌کند. در برابر برنامهٔ خارجیِ بدون قرارداد، بررسی revision و rename یک compare-and-swap مشترک سیستم فایل نیستند؛ پنجرهٔ بسیار کوتاه بین آخرین بررسی و replace باقی می‌ماند. این محدودیت نباید به‌عنوان تضمین تراکنش چندپردازه معرفی شود.
- sidecar عمداً یک کار فعال دارد. صف frontend مالک ترتیب و اولویت درخواست‌های محصول است؛ لغو کار queued محلی با لغو کار در حال اجرای موتور تفاوت دارد. مشتری مستقل JSON-RPC همچنان باید قرارداد single-job را رعایت کند.
- `main.mjs` و بخش‌هایی از `application.py`/`workspace.py` همچنان بزرگ‌اند. controllerهای استخراج‌شده مرزهای بحرانی را قابل آزمون کرده‌اند؛ کاهش خط صرفاً برای کوتاه کردن فایل معیار پایان کار نیست. استخراج‌های بعدی باید همراه قرارداد state و تست واقعی باشند.
- renderer/parser آزمون گسترده دارند، اما تمام فایل‌ها وارد gate سخت type checking نشده‌اند. موفقیت Pyright فعلی به معنی اثبات type-safety تمام parser نیست.
- سقف regex برای سطر بلند عمداً برای جلوگیری از زمان اجرای نامحدود باقی است و اکنون به کاربر اعلام می‌شود. برای جست‌وجوی کامل در پاراگراف طولانی باید حالت ساده استفاده شود.
- config کتاب با layout inline/dotted قابل خواندن و رندر است؛ فرم تغییر فصل به table معمولی `[book]` نیاز دارد. پشتیبانی ویرایش ساختاری کامل TOML، بدون از دست دادن comment و formatting، پیگیری مستقلی است.
- grant تصویر فقط فایل‌های canonical مجاز را شامل می‌شود. مجوزهای grantشده در طول session ممکن است باقی بمانند؛ سیاست revoke هنگام بستن تب و محدودیت WebView باید جدا بررسی شود.
- widget تصویر در حالت Write فعلاً تصویر inline را نمایش می‌دهد؛ تصویر با reference definition در متن source باقی می‌ماند، هرچند استخراج مراجع/grant آن پشتیبانی می‌شود. این مرز با رندر تصویر در Read/Preview یکسان نیست. فهرست نتیجهٔ Find به ۱۰هزار مورد محدود است، اما Replace All تمام تطبیق‌ها را جایگزین می‌کند.
- آزمون Rust Windows و PDF در Chromium جای نصب کامل بسته، رفتار سیستم‌عامل، screen reader، DPIهای متعدد، تست انسانی RTL یا update امضاشده را نمی‌گیرد. macOS این دور روی دستگاه/runner بومی اجرا نشده است.
- آزمون‌های dependency بر محیط و زمان پایگاه advisory وابسته‌اند. در lock نهایی چهار هشدار unmaintained برای `proc-macro-error`، `zbus_names`، `zvariant` و `zvariant_derive` و یک هشدار unsound برای `glib 0.18.5` باقی‌اند. خانوادهٔ `unic` با به‌روزرسانی Tauri حذف شد. رفع glib به تغییر زنجیرهٔ GTK یا backport آزموده‌شده نیاز دارد؛ صفر vulnerability به معنی رفع این پنج هشدار نیست و هیچ‌کدام ignore نشده‌اند. سلامت زنجیرهٔ dev شرطی روی Python 3.10 نیز از audit محیط 3.12 نتیجه گرفته نمی‌شود.
- PDF بررسی‌شده می‌تواند فونت embedded، outline، لینک و متن قابل انتخاب داشته باشد؛ ادعای tagged PDF، PDF/UA یا PDF/A بدون validator مستقل مطرح نمی‌شود.

## شرط پایان و انتشار

پایان این دور به اصلاحات ثبت‌شده، قبولی gateهای نهایی و معرفی صادقانهٔ موارد اجرا نشده وابسته است. commitها با author و committer `mragetsars <mragetsars@gmail.com>` و قالب تاریخچهٔ `type(scope): concrete outcome` ثبت می‌شوند. تغییرات نسخهٔ موجود کاربر بدون تفکیک hunkها وارد commit اصلاحی نمی‌شوند.

ریلیز، push و انتشار GitHub در دامنهٔ این بررسی نیستند. تصمیم آمادگی انتشار پس از آزمون شخصی کاربر روی artifact تازه و شواهد سکوهای مورد انتشار گرفته می‌شود.
